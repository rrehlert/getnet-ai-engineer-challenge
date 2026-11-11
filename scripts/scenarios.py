"""POST the shared scenario dataset (`evals/scenarios.json`) to a running API.

Usage: uv run python scripts/scenarios.py [BASE_URL]
BASE_URL defaults to $API_BASE_URL, then http://localhost:8000.
Prints intent, agent, answer and Sources per scenario, then routing accuracy (Intent) and
fact accuracy (expected facts in the reply) as separate totals, listing missing facts.
Exits non-zero if either is below 100%.
"""

import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

Fact = list[str]  # accepted alternatives; the fact passes if any appears in the reply


@dataclass(frozen=True)
class Scenario:
    message: str
    user_id: str
    intent: str
    facts: list[Fact] = field(default_factory=list)
    intents_needed: list[str] = field(default_factory=list)  # Mixed question: ≥2 Intents


@dataclass(frozen=True)
class CheckResult:
    routing_ok: bool
    facts_ok: bool | None  # None: the scenario declares no facts
    missing_facts: list[Fact]


def check_reply(body: dict, scenario: Scenario) -> CheckResult:
    answer = (body.get("answer") or "").casefold()
    missing = [fact for fact in scenario.facts if not any(alt.casefold() in answer for alt in fact)]
    return CheckResult(
        routing_ok=body.get("intent") == scenario.intent,
        facts_ok=not missing if scenario.facts else None,
        missing_facts=missing,
    )


def brl(amount: str) -> Fact:
    """Spellings of a BRL amount given as '1817.26': pt-BR and en, with or without thousands separator."""
    units, cents = amount.split(".")
    grouped = f"{int(units):,}"
    return [f"{grouped.replace(',', '.')},{cents}", f"{units},{cents}", f"{grouped}.{cents}", f"{units}.{cents}"]


DATASET = Path(__file__).resolve().parent.parent / "evals" / "scenarios.json"
# Same values as `app.graph.Intent` (a test keeps them in sync); stdlib only so the script runs anywhere.
INTENTS = {"knowledge", "support", "unsupported"}


class DatasetError(ValueError):
    pass


def _fact(raw: object, where: str) -> Fact:
    if isinstance(raw, dict) and set(raw) == {"brl"} and isinstance(raw["brl"], str):
        return brl(raw["brl"])
    if isinstance(raw, list) and raw and all(isinstance(alt, str) and alt for alt in raw):
        return raw
    raise DatasetError(f"{where}: a fact must be a non-empty list of strings or {{\"brl\": \"1.23\"}}, got {raw!r}")


def parse_scenario(raw: dict, where: str) -> Scenario:
    message, user_id, intent = raw.get("message"), raw.get("user_id"), raw.get("intent")
    if not isinstance(message, str) or not message:
        raise DatasetError(f"{where}: missing message")
    where = f"{where} ({message!r})"
    if not isinstance(user_id, str) or not user_id:
        raise DatasetError(f"{where}: missing user_id")
    if intent not in INTENTS:
        raise DatasetError(f"{where}: intent must be one of {sorted(INTENTS)}, got {intent!r}")
    needed = raw.get("intents_needed", [])
    if needed and (len(set(needed)) < 2 or not set(needed) <= INTENTS):
        raise DatasetError(f"{where}: intents_needed must list at least 2 distinct Intents of {sorted(INTENTS)}")
    facts = [_fact(f, where) for f in raw.get("facts", [])]
    return Scenario(message, user_id, intent, facts=facts, intents_needed=list(needed))


def load_scenarios(path: Path = DATASET) -> list[Scenario]:
    """The shared scenario dataset, validated; raises `DatasetError` naming the bad scenario."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [parse_scenario(raw, f"scenario {i}") for i, raw in enumerate(data["scenarios"], 1)]


def post_chat(base_url: str, message: str, user_id: str) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat",
        data=json.dumps({"message": message, "user_id": user_id}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def format_fact(fact: Fact) -> str:
    return " | ".join(fact)


def main() -> int:
    base_url = sys.argv[1] if len(sys.argv) > 1 else os.getenv("API_BASE_URL", "http://localhost:8000")
    routing_passed = facts_passed = facts_total = 0
    missing_by_scenario: list[tuple[int, list[Fact]]] = []
    scenarios = load_scenarios()
    for i, scenario in enumerate(scenarios, 1):
        status, body = post_chat(base_url, scenario.message, scenario.user_id)
        result = check_reply(body, scenario)
        routing_passed += result.routing_ok
        if result.facts_ok is not None:
            facts_total += 1
            facts_passed += result.facts_ok
        if result.missing_facts:
            missing_by_scenario.append((i, result.missing_facts))
        facts_mark = {True: "✓", False: "✗", None: "-"}[result.facts_ok]
        print(f"routing {'✓' if result.routing_ok else '✗'} facts {facts_mark} [{i}] ({scenario.user_id}) {scenario.message}")
        print(f"    HTTP {status} · intent={body.get('intent')} (expected {scenario.intent}) · agent={body.get('agent')}")
        print(f"    steps: {body.get('steps')} · trace_id: {body.get('trace_id')}")
        print(f"    answer: {body.get('answer') or body.get('error')}")
        for source in body.get("sources") or []:
            print(f"    source: {source['title']} <{source['url']}>")
        for fact in result.missing_facts:
            print(f"    missing fact: {format_fact(fact)}")
        print()
    print(f"routing {routing_passed}/{len(scenarios)}")
    print(f"facts {facts_passed}/{facts_total}")
    for i, missing in missing_by_scenario:
        print(f"  [{i}] missing: " + "; ".join(format_fact(fact) for fact in missing))
    ok = routing_passed == len(scenarios) and facts_passed == facts_total
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
