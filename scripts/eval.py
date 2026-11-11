"""In-process eval runner: every scenario of `evals/scenarios.json`, `EVAL_RUNS` times each.

Usage: uv run python -m scripts.eval
Builds the production graph (needs an LLM key, no server), runs the Judges synchronously
with Evidence, writes `evals/results/<UTC timestamp>.json` and prints a summary.
"""

import hashlib
import json
import logging
import os
import secrets
import subprocess
import sys
import time
import uuid
from collections import defaultdict
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.judge import JUDGES, run_judges
from app.llm import is_provider_error, provider_error_code
from app.observability import LogPrivacy
from scripts.scenarios import DATASET, Scenario, check_reply, load_scenarios

ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "evals" / "results"
DEFAULT_RUNS = 3

MIXED_RATE_THRESHOLD = 0.10
INCOMPLETE_RATE_THRESHOLD = 0.50
BUILD_ROUTER = "build multi-intent Router"
NOT_JUSTIFIED = "not justified"

# A run record (JSON-ready dict): scenario (id), index, run, message, expected_intent,
# intents_needed (dataset label), intent, answer, routing_ok, facts_ok, missing_facts,
# verdicts {Judge Type: verdict dict}, tokens, latency_ms, error (None, or why the graph failed).
Record = dict


def _rate(passed: int, total: int) -> float:
    return passed / total if total else 0


def summarize(records: list[Record]) -> dict:
    """Pass rates, Judge Score mean/min per Judge Type, errors and tokens over some runs.

    A failed run fails routing and (if the scenario declares facts) facts; it has no verdicts.
    `judges_missing` counts runs that answered but lack a Judge Type's verdict (that Judge failed),
    so means over a biased subset don't pass unnoticed.
    """
    answered = [r for r in records if r["error"] is None]
    with_facts = [r["facts_ok"] for r in records if r["facts_ok"] is not None]
    scores: dict[str, list[float]] = defaultdict(list)
    for r in records:
        for judge_type, verdict in r["verdicts"].items():
            scores[judge_type].append(verdict["score"])
    return {
        "runs": len(records),
        "errors": sum(r["error"] is not None for r in records),
        "routing_pass_rate": _rate(sum(r["routing_ok"] for r in records), len(records)),
        "fact_pass_rate": _rate(sum(with_facts), len(with_facts)) if with_facts else None,
        "judges": {
            judge_type: {"mean": sum(values) / len(values), "min": min(values), "n": len(values)}
            for judge_type, values in scores.items()
        },
        "judges_missing": {
            judge_type: sum(judge_type not in r["verdicts"] for r in answered) for judge_type in JUDGES
        },
        "tokens": sum(r["tokens"] for r in records),
    }


def threshold_decision(mixed_rate: float, incomplete_rate: float) -> str:
    """Pre-agreed: ≥10% Mixed questions and ≥50% of those incomplete justify a multi-intent Router."""
    if mixed_rate >= MIXED_RATE_THRESHOLD and incomplete_rate >= INCOMPLETE_RATE_THRESHOLD:
        return BUILD_ROUTER
    return NOT_JUSTIFIED


def _coverage(records: Iterable[Record]) -> list[dict]:
    return [r["verdicts"]["coverage"] for r in records if "coverage" in r["verdicts"]]


def mixed_stats(records: list[Record]) -> dict:
    """Mixed-question and incomplete rates over runs the coverage Judge rated, and the decision."""
    judged = _coverage(records)
    mixed = [c for c in judged if len(set(c["intents_needed"])) > 1]
    incomplete = [c for c in mixed if not c["fully_answered"]]
    mixed_rate = _rate(len(mixed), len(judged))
    incomplete_rate = _rate(len(incomplete), len(mixed))
    return {
        "judged": len(judged),
        "mixed": len(mixed),
        "mixed_rate": mixed_rate,
        "incomplete": len(incomplete),
        "incomplete_rate": incomplete_rate,
        "decision": threshold_decision(mixed_rate, incomplete_rate),
    }


def _labelled_mixed(by_scenario: dict[str, list[Record]]) -> dict:
    """For dataset-labelled Mixed scenarios: did the coverage Judge name the same Intents?"""
    scenarios = {}
    for sid, records in by_scenario.items():
        needed = records[0]["intents_needed"]
        if not needed:
            continue
        judged = _coverage(records)
        agreed = sum(set(c["intents_needed"]) == set(needed) for c in judged)
        scenarios[sid] = {
            "intents_needed": needed,
            "judged": len(judged),
            "agreed": agreed,
            "agreement_rate": _rate(agreed, len(judged)),
        }
    judged = sum(s["judged"] for s in scenarios.values())
    agreed = sum(s["agreed"] for s in scenarios.values())
    return {"scenarios": scenarios, "judged": judged, "agreed": agreed, "agreement_rate": _rate(agreed, judged)}


def _scenario_summary(records: list[Record]) -> dict:
    first = records[0]
    coverage = _coverage(records)
    return {
        "message": first["message"],
        "expected_intent": first["expected_intent"],
        **summarize(records),
        "coverage": {
            "fully_answered_rate": _rate(sum(c["fully_answered"] for c in coverage), len(coverage)),
            "intents_needed": [c["intents_needed"] for c in coverage],
            "missing": [c["missing"] for c in coverage if c["missing"]],
        },
    }


def aggregate(records: list[Record]) -> dict:
    """Per scenario, per expected Intent, overall, Mixed-question stats and labelled-Mixed agreement."""
    by_scenario: dict[str, list[Record]] = defaultdict(list)
    by_intent: dict[str, list[Record]] = defaultdict(list)
    for r in records:
        by_scenario[r["scenario"]].append(r)
        by_intent[r["expected_intent"]].append(r)
    return {
        "per_scenario": {sid: _scenario_summary(rs) for sid, rs in by_scenario.items()},
        "per_intent": {intent: summarize(rs) for intent, rs in by_intent.items()},
        "overall": summarize(records),
        "mixed": mixed_stats(records),
        "labelled_mixed": _labelled_mixed(by_scenario),
    }


# --- Runner ---


def eval_runs(environ: Mapping[str, str] = os.environ) -> int:
    """`EVAL_RUNS` (default 3): runs per scenario."""
    runs = int(environ.get("EVAL_RUNS", DEFAULT_RUNS))
    if runs < 1:
        raise ValueError(f"EVAL_RUNS must be at least 1, got {runs}")
    return runs


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def scenario_id(scenario: Scenario) -> str:
    """Stable across reordering the dataset (baselines join on it): a hash of the Message."""
    return hashlib.sha256(scenario.message.encode()).hexdigest()[:8]


def _run_once(graph: Any, judge_model: Any, privacy: LogPrivacy, index: int, run: int, scenario: Scenario) -> Record:
    record: Record = {
        "scenario": scenario_id(scenario),
        "index": index,
        "run": run,
        "message": scenario.message,
        "expected_intent": scenario.intent,
        "intents_needed": scenario.intents_needed,
        "intent": None,
        "answer": None,
        "verdicts": {},
        "tokens": 0,
        "error": None,
    }
    started = time.perf_counter()
    try:
        # Logged-in scenarios: the Merchant goes straight into graph state, no HTTP.
        result = graph.invoke({"message": scenario.message, "user_id": scenario.user_id})
    except Exception as exc:
        record["error"] = provider_error_code(exc) if is_provider_error(exc) else f"error: {exc!r}"
        result = {}
    record["latency_ms"] = round((time.perf_counter() - started) * 1000)
    check = check_reply(result, scenario)
    record.update(routing_ok=check.routing_ok, facts_ok=check.facts_ok, missing_facts=check.missing_facts)
    if record["error"] is None:
        intent, answer = result["intent"], result.get("answer", "")
        record.update(intent=intent, answer=answer, tokens=result.get("tokens", 0))
        verdicts = run_judges(
            judge_model,
            privacy=privacy,
            trace_id=uuid.uuid4().hex,
            message=scenario.message,
            intent=intent,
            answer=answer,
            sources=result.get("sources", []),
            evidence=result.get("evidence", []),
            user_id=scenario.user_id,
        )
        record["verdicts"] = {judge_type: v.model_dump() for judge_type, v in verdicts.items()}
    return record


def run_eval(
    dataset: Path = DATASET,
    *,
    graph: Any,
    judge_model: Any,
    runs: int,
    out_dir: Path = RESULTS_DIR,
    reply_model: str,
    judge_model_name: str,
    now: datetime | None = None,
) -> Path:
    """Run every scenario `runs` times, Judge each reply, write the results file and return its path.

    `graph` is anything with `.invoke(state) -> state`. A failing run is recorded, not raised.
    """
    now = now or datetime.now(UTC)
    raw = Path(dataset).read_bytes()
    scenarios = load_scenarios(dataset)
    privacy = LogPrivacy(key=secrets.token_bytes(32), messages="none")
    records = []
    for i, scenario in enumerate(scenarios, 1):
        for run in range(1, runs + 1):
            record = _run_once(graph, judge_model, privacy, i, run, scenario)
            records.append(record)
            print(f"[{i:02d}.{run}] {record['intent'] or record['error']}", file=sys.stderr)
    aggregates = aggregate(records)
    results = {
        "metadata": {
            "commit": _git("rev-parse", "HEAD"),
            "dirty": bool(_git("status", "--porcelain")),
            "reply_model": reply_model,
            "judge_model": judge_model_name,
            "eval_runs": runs,
            "date": now.isoformat(),
            "dataset_sha256": hashlib.sha256(raw).hexdigest(),
        },
        **aggregates,
        "tokens": {
            "total": aggregates["overall"]["tokens"],
            "per_intent": {intent: s["tokens"] for intent, s in aggregates["per_intent"].items()},
        },
        "runs": records,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{now.strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


# --- Summary ---


def _pct(rate: float | None) -> str:
    return "-" if rate is None else f"{rate:.0%}"


def _summary_row(name: str, stats: dict) -> str:
    judges = "  ".join(
        f"{judge_type} {j['mean']:.2f}/{j['min']:.2f}" for judge_type, j in sorted(stats["judges"].items())
    )
    return (
        f"{name:<12} runs {stats['runs']:>3}  errors {stats['errors']:>2}  routing {_pct(stats['routing_pass_rate']):>4}"
        f"  facts {_pct(stats['fact_pass_rate']):>4}  {judges}"
    )


def format_summary(results: dict) -> str:
    """Per-Intent table, overall, Mixed/incomplete rates vs threshold, token total."""
    mixed, labelled = results["mixed"], results["labelled_mixed"]
    lines = ["Judge Scores as mean/min", ""]
    lines += [_summary_row(intent, stats) for intent, stats in sorted(results["per_intent"].items())]
    lines.append(_summary_row("overall", results["overall"]))
    missing = {t: n for t, n in results["overall"]["judges_missing"].items() if n}
    if missing:
        lines.append("missing verdicts: " + ", ".join(f"{t} {n}" for t, n in missing.items()))
    lines += [
        "",
        f"Mixed questions {mixed['mixed']}/{mixed['judged']} = {_pct(mixed['mixed_rate'])}"
        f" (threshold ≥{MIXED_RATE_THRESHOLD:.0%})",
        f"incomplete      {mixed['incomplete']}/{mixed['mixed']} = {_pct(mixed['incomplete_rate'])}"
        f" (threshold ≥{INCOMPLETE_RATE_THRESHOLD:.0%})",
        f"multi-intent Router: {mixed['decision']}",
        f"labelled Mixed scenarios: coverage Judge agreed {labelled['agreed']}/{labelled['judged']}",
        "",
        f"tokens {results['tokens']['total']}",
    ]
    return "\n".join(lines)


def main() -> int:
    from app.llm import make_chat_model
    from app.main import build_default_graph, load_default_index
    from app.settings import get_settings, warn_if_judge_not_independent

    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("app.events").setLevel(logging.ERROR)  # Judge lines: the results file has them
    settings = get_settings()
    warn_if_judge_not_independent(settings)
    path = run_eval(
        graph=build_default_graph(load_default_index()),
        judge_model=make_chat_model(settings, settings.judge_model),
        runs=eval_runs(),
        reply_model=settings.llm_model,
        judge_model_name=settings.judge_model,
    )
    print(format_summary(json.loads(path.read_text(encoding="utf-8"))))
    print(f"\nresults: {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
