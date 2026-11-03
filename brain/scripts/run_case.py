"""Replay one actual registered scenario without network or API keys."""

import argparse
import asyncio
import json
from pathlib import Path

from civis_mock_peers.peers import FixtureGuardian, FixturePlanProvider, FixtureTwin

from civis_brain.contracts import ReadingsBatch
from civis_brain.integration.runtime import build_runtime

DOMAINS = {
    "S01": "traffic",
    "S02": "water",
    "S03": "power",
    "S04": "air_quality",
    "S05": "emergency",
}


async def replay(scenario: str, variant: str):
    root = Path(__file__).resolve().parents[1]
    path = root / "mocks" / "cases" / DOMAINS[scenario] / f"{variant}_case.json"
    if not path.exists():
        raise SystemExit(f"{scenario}: its owner has not delivered {variant}_case.json")
    case = json.loads(path.read_text(encoding="utf-8"))
    if case["scenario_id"] != scenario:
        raise SystemExit("Fixture scenario ID mismatch")
    twin, guardian, provider = FixtureTwin(case), FixtureGuardian(case), FixturePlanProvider(case)
    directory = root / ".artifacts" / f"{scenario}-{variant}"
    directory.mkdir(parents=True, exist_ok=True)
    trace = directory / "trace.jsonl"
    trace.unlink(missing_ok=True)
    runtime = build_runtime(
        twin=twin,
        guardian=guardian,
        provider=provider,
        policies={scenario: case["policy"]},
        features={
            "enabled_scenario_ids": [scenario],
            "guardian_score_tool": "fixture_score",
            "guardian_token_tool": "fixture_approve",
            "preview_tool": "fixture_preview",
            "commit_tool": "fixture_commit",
        },
        artifact_dir=directory,
    )
    results = []
    for raw in case["batches"]:
        batch = ReadingsBatch.model_validate(raw)
        twin.advance(batch)
        results.append(await runtime.evaluate_tick(batch))
    expected = case["expected"]
    actual_statuses = [row.status for row in results[-1].decisions]
    if actual_statuses != expected["final_statuses"]:
        raise SystemExit(f"FAIL: expected {expected['final_statuses']}; got {actual_statuses}")
    checks = {
        "effects": len(twin.effects),
        "provider_calls": len(provider.calls),
        "actuate_calls": sum(row["name"] == "actuate" for row in twin.calls),
    }
    for key, value in checks.items():
        if key in expected and expected[key] != value:
            raise SystemExit(f"FAIL: {key}: expected {expected[key]}, got {value}")
    if expected.get("reason_contains") and not any(
        expected["reason_contains"] in row.reason for row in results[-1].decisions
    ):
        raise SystemExit("FAIL: expected uncertainty reason is absent")
    print(
        json.dumps(
            {
                "scenario": scenario,
                "case": variant,
                "fixture_only": True,
                "statuses": actual_statuses,
                **checks,
                "trace": str(trace),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=DOMAINS, required=True)
    parser.add_argument("--case", choices=["base", "refusal"], default="base")
    args = parser.parse_args()
    asyncio.run(replay(args.scenario, args.case))
