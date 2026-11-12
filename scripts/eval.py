"""In-process eval runner: every scenario of `evals/scenarios.json`, `EVAL_RUNS` times each.

Usage: uv run python -m scripts.eval [--save-baseline | --retrieval-only]
Builds the production graph (needs an LLM key, no server), runs the Judges synchronously
with Evidence, measures retrieval recall@4 on `evals/retrieval.json`, writes
`evals/results/<UTC timestamp>.json`, prints a summary and the deltas vs `evals/baseline.json`.
`--save-baseline` then copies this run's results over the baseline.
`--retrieval-only` measures just recall@4 against the Corpus index (no LLM key needed).
"""

import argparse
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

from app.graph import agent_for
from app.judge import JUDGES, run_judges
from app.llm import is_provider_error, provider_error_code
from app.observability import LogPrivacy
from app.rag import CORPUS_DIR, Index
from scripts.retrieval import (
    RETRIEVAL_SET,
    format_retrieval,
    load_retrieval,
    recall_at_k,
)
from scripts.scenarios import DATASET, Scenario, check_reply, load_scenarios

ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = ROOT / "evals" / "results"
BASELINE = ROOT / "evals" / "baseline.json"
# Metadata that must match the baseline's for deltas to be like-for-like.
LIKE_FOR_LIKE_FIELDS = ("reply_model", "judge_model", "dataset_sha256")
DEFAULT_RUNS = 3

MIXED_RATE_THRESHOLD = 0.10
INCOMPLETE_RATE_THRESHOLD = 0.50
BUILD_ROUTER = "build multi-intent Router"
NOT_JUSTIFIED = "not justified"

# A run record (JSON-ready dict): scenario (id), index, run, message, expected_intent,
# intents_needed (dataset label), intent, agent, answer, routing_ok, facts_ok, missing_facts,
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
        "agent": None,
        "answer": None,
        "verdicts": {},
        "tokens": 0,
        "error": None,
    }
    started = time.perf_counter()
    try:
        # The Merchant (None: anonymous visitor) goes straight into graph state, no HTTP or token.
        result = graph.invoke({"message": scenario.message, "user_id": scenario.user_id})
    except Exception as exc:
        record["error"] = provider_error_code(exc) if is_provider_error(exc) else f"error: {exc!r}"
        result = {}
    record["latency_ms"] = round((time.perf_counter() - started) * 1000)
    if record["error"] is None:
        # As `/chat` reports it: the Escalator for an escalated Turn, the Router for refusals/login.
        result["agent"] = agent_for(
            result["intent"], anonymous=scenario.user_id is None, escalated=result.get("handoff") is not None
        )
    check = check_reply(result, scenario)
    record.update(routing_ok=check.routing_ok, facts_ok=check.facts_ok, missing_facts=check.missing_facts)
    if record["error"] is None:
        intent, answer = result["intent"], result.get("answer", "")
        record.update(intent=intent, agent=result["agent"], answer=answer, tokens=result.get("tokens", 0))
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
            handoff=result.get("handoff"),
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
    index: Index | None = None,
    retrieval_set: Path = RETRIEVAL_SET,
    corpus_dir: Path = CORPUS_DIR,
) -> Path:
    """Run every scenario `runs` times, Judge each reply, write the results file and return its path.

    `graph` is anything with `.invoke(state) -> state`. A failing run is recorded, not raised.
    With an `index`, the results also carry recall@4 on `retrieval_set`.
    """
    now = now or datetime.now(UTC)
    raw = Path(dataset).read_bytes()
    scenarios = load_scenarios(dataset)
    # Before the graph runs: no model, and a bad retrieval set fails fast.
    retrieval = recall_at_k(load_retrieval(retrieval_set, corpus_dir), index) if index is not None else None
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
            **_run_metadata(now),
            "reply_model": reply_model,
            "judge_model": judge_model_name,
            "eval_runs": runs,
            "dataset_sha256": hashlib.sha256(raw).hexdigest(),
            **({"retrieval_sha256": _sha256(retrieval_set)} if index is not None else {}),
        },
        **aggregates,
        "tokens": {
            "total": aggregates["overall"]["tokens"],
            "per_intent": {intent: s["tokens"] for intent, s in aggregates["per_intent"].items()},
        },
    }
    if retrieval is not None:
        results["retrieval"] = retrieval
    results["runs"] = records
    return _write_results(results, out_dir, now)


def run_retrieval(
    index: Index,
    retrieval_set: Path = RETRIEVAL_SET,
    *,
    corpus_dir: Path = CORPUS_DIR,
    out_dir: Path = RESULTS_DIR,
    now: datetime | None = None,
) -> Path:
    """recall@4 only (no model): writes a results file with metadata and the `retrieval` section."""
    now = now or datetime.now(UTC)
    results = {
        "metadata": {**_run_metadata(now), "retrieval_only": True, "retrieval_sha256": _sha256(retrieval_set)},
        "retrieval": recall_at_k(load_retrieval(retrieval_set, corpus_dir), index),
    }
    return _write_results(results, out_dir, now)


def _sha256(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _run_metadata(now: datetime) -> dict:
    return {"commit": _git("rev-parse", "HEAD"), "dirty": bool(_git("status", "--porcelain")), "date": now.isoformat()}


def _write_results(results: dict, out_dir: Path, now: datetime) -> Path:
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
    if "retrieval" in results:
        lines += ["", format_retrieval(results["retrieval"])]
    return "\n".join(lines)


# --- Baseline comparison ---

def _delta(current: float | None, baseline: float | None) -> float | None:
    return None if current is None or baseline is None else current - baseline


def _stats_delta(current: dict, baseline: dict) -> dict:
    """Run minus baseline; None where either side lacks the value (no facts, Judge Type absent)."""
    judge_types = current["judges"].keys() | baseline["judges"].keys()
    return {
        "routing_pass_rate": _delta(current["routing_pass_rate"], baseline["routing_pass_rate"]),
        "fact_pass_rate": _delta(current["fact_pass_rate"], baseline["fact_pass_rate"]),
        "judges": {
            judge_type: _delta(
                current["judges"].get(judge_type, {}).get("mean"), baseline["judges"].get(judge_type, {}).get("mean")
            )
            for judge_type in judge_types
        },
    }


def _mixed_rates(mixed: dict) -> dict:
    """Rates with None where undefined: no coverage verdicts, or no Mixed questions to be incomplete."""
    return {
        "mixed_rate": mixed["mixed_rate"] if mixed["judged"] else None,
        "incomplete_rate": mixed["incomplete_rate"] if mixed["mixed"] else None,
    }


def _tokens_per_run(results: dict) -> float:
    return _rate(results["tokens"]["total"], results["overall"]["runs"])


def compare(results: dict, baseline: dict) -> dict:
    """Deltas (run minus baseline) per expected Intent, overall, Mixed/incomplete rates and tokens per run.

    An Intent on one side only is marked `{"only_in": "run" | "baseline"}`.
    """
    per_intent: dict[str, dict] = {}
    for intent in results["per_intent"].keys() | baseline["per_intent"].keys():
        current, base = results["per_intent"].get(intent), baseline["per_intent"].get(intent)
        if current is None or base is None:
            per_intent[intent] = {"only_in": "run" if base is None else "baseline"}
        else:
            per_intent[intent] = _stats_delta(current, base)
    current_mixed, base_mixed = _mixed_rates(results["mixed"]), _mixed_rates(baseline["mixed"])
    return {
        "per_intent": per_intent,
        "overall": _stats_delta(results["overall"], baseline["overall"]),
        "mixed": {rate: _delta(current_mixed[rate], base_mixed[rate]) for rate in current_mixed},
        # Per run: totals scale with EVAL_RUNS, which may differ from the baseline's.
        "tokens_per_run": _tokens_per_run(results) - _tokens_per_run(baseline),
    }


def baseline_warnings(results: dict, baseline: dict) -> list[str]:
    """One line per like-for-like metadata field that differs from the baseline."""
    run, base = results["metadata"], baseline["metadata"]
    return [
        f"WARNING: {field} differs (run {run.get(field)}, baseline {base.get(field)}): deltas are not like-for-like"
        for field in LIKE_FOR_LIKE_FIELDS
        if run.get(field) != base.get(field)
    ]


def _signed(delta: float | None, fmt: str) -> str:
    return "-" if delta is None else format(delta, fmt)


def _points(delta: float | None) -> str:
    """A rate delta in percentage points."""
    return "-" if delta is None else f"{delta * 100:+.0f}pp"


def _delta_row(name: str, delta: dict) -> str:
    if "only_in" in delta:
        return f"{name:<12} only in {delta['only_in']}"
    judges = "  ".join(f"{judge_type} {_signed(d, '+.2f')}" for judge_type, d in sorted(delta["judges"].items()))
    return (
        f"{name:<12} routing {_points(delta['routing_pass_rate'])}  facts {_points(delta['fact_pass_rate'])}  {judges}"
    )


def format_comparison(results: dict, baseline: dict | None) -> str:
    """Deltas vs baseline (Judge Score deltas on means), with warnings when not like-for-like."""
    if baseline is None:
        return "no baseline (evals/baseline.json): run with --save-baseline to create one"
    deltas = compare(results, baseline)
    base = baseline["metadata"]
    lines = [f"vs baseline {base.get('date', '?')} ({str(base.get('commit', ''))[:7] or '?'})"]
    lines += baseline_warnings(results, baseline)
    lines.append("")
    lines += [_delta_row(intent, d) for intent, d in sorted(deltas["per_intent"].items())]
    lines += [
        _delta_row("overall", deltas["overall"]),
        "",
        f"Mixed questions {_points(deltas['mixed']['mixed_rate'])}"
        f"  incomplete {_points(deltas['mixed']['incomplete_rate'])}",
        f"tokens/run {_signed(deltas['tokens_per_run'], '+.0f')}",
    ]
    return "\n".join(lines)


def report(results_path: Path, *, baseline_path: Path = BASELINE, save_baseline: bool = False) -> str:
    """Summary plus comparison against the baseline file; then optionally make this run the baseline."""
    raw = results_path.read_text(encoding="utf-8")
    results = json.loads(raw)
    baseline = json.loads(baseline_path.read_text(encoding="utf-8")) if baseline_path.exists() else None
    text = format_summary(results) + "\n\n" + format_comparison(results, baseline)
    if save_baseline:
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(raw, encoding="utf-8")
        text += f"\n\nbaseline saved: {_display(baseline_path)}"
    return text


def _display(path: Path) -> Path:
    return path.relative_to(ROOT) if path.is_relative_to(ROOT) else path


def main(argv: list[str] | None = None) -> int:
    from app.llm import make_chat_model
    from app.main import build_default_graph, load_default_index
    from app.settings import get_settings, warn_if_judge_not_independent

    parser = argparse.ArgumentParser(description="In-process eval runner")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--save-baseline", action="store_true", help=f"copy this run's results to {_display(BASELINE)}")
    modes.add_argument("--retrieval-only", action="store_true", help="only recall@4 on the Corpus index (no LLM key)")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING)
    index = load_default_index()
    if args.retrieval_only:
        path = run_retrieval(index)
        print(format_retrieval(json.loads(path.read_text(encoding="utf-8"))["retrieval"]))
        print(f"\nresults: {_display(path)}")
        return 0

    logging.getLogger("app.events").setLevel(logging.ERROR)  # Judge lines: the results file has them
    settings = get_settings()
    warn_if_judge_not_independent(settings)
    path = run_eval(
        graph=build_default_graph(index),
        judge_model=make_chat_model(settings, settings.judge_model),
        runs=eval_runs(),
        reply_model=settings.llm_model,
        judge_model_name=settings.judge_model,
        index=index,
    )
    print(report(path, save_baseline=args.save_baseline))
    print(f"\nresults: {_display(path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
