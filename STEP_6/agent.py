#!/usr/bin/env python
"""STEP 6 — Hand it to the room: extend, then close

Run the deterministic demo:
    uv run python STEP_6/agent.py

Ask a question through the model (needs OPENROUTER_API_KEY in .env):
    uv run python STEP_6/agent.py --llm -q "Which stations are at risk?"

Use a different data folder:
    uv run python STEP_6/agent.py --data path/to/snapshots
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from harness import Harness, LLMClient, LLMError, have_api_key, run_llm
from tools import DEFAULT_DATA, SPECS, TOOLS

STAGE = "STEP 6 — Hand it to the room: extend, then close"
REPORTS = Path(__file__).resolve().parent / "reports"

SYSTEM = """You are a data intelligence agent analysing Brighton Bikeshare (Beryl) snapshots.

Hard rules:
1. Use the tools. Never calculate a number yourself and never invent one.
2. Every claim must cite at least one evidence_id returned by a tool.
3. State the window, the gaps and the limits behind each claim.
4. Prefer a refusal over a forecast the data cannot support.
5. End with an action: owner, what, where, when, expected impact, confidence and a falsifier.
"""

ROUTES = [
    (("audit", "quality", "duplicate", "missing", "null", "metric", "docks"), "audit_snapshots", {}),
    (("timeline", "panel", "gap", "cadence", "when"), "build_panel", {}),
    (("flow", "drain", "sink", "change", "moving"), "net_flow", {}),
    (("transition", "state"), "state_transitions", {}),
    (("risk", "empty", "fail", "urgent", "soon", "lock"), "failure_risk", {}),
    (("move", "rebalance", "surplus", "deficit", "route"), "rebalance_plan", {}),
    (("action", "should", "recommend", "priority", "fix"), "rank_actions", {}),
    (("forecast", "predict", "next hour", "tomorrow"), "forecast_gate", {}),
    (("fleet", "e-bike", "ebike", "scooter", "vehicle", "mix", "type"), "fleet_mix", {}),
]


def build_harness(args: argparse.Namespace) -> Harness:
    if args.data:
        os.environ["BIKESHARE_DATA"] = str(Path(args.data).resolve())
    return Harness(TOOLS, SPECS, max_steps=args.max_steps, verbose=not args.quiet)


def route(harness: Harness, question: str) -> dict:
    text = question.lower()
    for keywords, tool, payload in ROUTES:
        if tool in TOOLS and any(word in text for word in keywords):
            return harness.call(tool, payload)
    fallback = "audit_snapshots" if "audit_snapshots" in TOOLS else next(iter(TOOLS))
    return harness.call(fallback, {})


def ask(harness: Harness, args: argparse.Namespace) -> None:
    print(f"\n=== {STAGE} ===")
    print(f"Q: {args.question}\n")
    if args.llm:
        if not have_api_key():
            print("No OPENROUTER_API_KEY / OPENROUTER_KEY found; falling back to the deterministic demo.")
            demo(harness, args)
            return
        try:
            client = LLMClient(model=args.model)
            answer, _messages = run_llm(harness, SYSTEM, args.question, client, args.max_steps)
        except LLMError as exc:
            print(f"Model unavailable: {exc}")
            print("Falling back to the deterministic demo.\n")
            demo(harness, args)
            return
        print("\n--- model answer ---\n")
        print(answer)
        print("\nEvidence ledger:")
        for row in harness.ledger.summaries():
            print(f"  {row['evidence_id']}  {row['tool']:<18} {row['summary']}")
        return

    result = route(harness, args.question)
    print("\n--- result ---")
    print(json.dumps(result["data"], indent=2, default=str)[:5000])
    print("\n(Deterministic router. Use --llm for model-driven tool choice.)")


def demo(harness: Harness, args: argparse.Namespace) -> None:
    print(f"\n=== {STAGE} ===")
    print("Question: are e-bikes pooling in the north, and what would you do about it?\n")
    fleet = harness.call("fleet_mix")
    audit = harness.call("audit_snapshots")
    flow = harness.call("net_flow")
    risk = harness.call("failure_risk")
    plan = harness.call("rebalance_plan")
    gate = harness.call("forecast_gate", {"horizon_min": 60})

    f = fleet["data"]
    shares = f["overall_shares"]
    by_band = {row["band"]: row["share"] for row in f["by_lat_band"]}
    south = by_band.get("south", {})
    north = by_band.get("north", {})
    last_left = f["last_one_left"]
    a = audit["data"]["metrics"]
    p = plan["data"]

    print("\n--- Fleet mix ---")
    for key, count in sorted(f["overall_counts"].items(), key=lambda kv: kv[1], reverse=True):
        print(f"  {key:<12} {count:>5} vehicles  {shares[key]:.1%}")
    print("\nE-bike share by latitude band:")
    for row in f["by_lat_band"]:
        print(f"  {row['band']:<6} e-bike {row['share'].get('bbe', 0):.1%}  scooter {row['share'].get('scooter', 0):.1%}")
    print("\nLast vehicle left at one-bike stations:")
    for key, count in sorted(last_left.items(), key=lambda kv: kv[1], reverse=True):
        print(f"  {key:<12} {count}")
    print("\nTop e-bike stations (min 5 observations):")
    for row in f["top_ebike_share"][:5]:
        print(f"  {row['ebb_share']:.0%}  {row['name']}")

    claims = [
        {
            "text": (
                f"E-bikes are {shares.get('bbe', 0):.1%} of the docked fleet and scooters are "
                f"{shares.get('scooter', 0):.1%}."
            ),
            "evidence_ids": [fleet["evidence_id"]],
            "action": {"owner": "fleet planning", "what": "treat the three vehicle types as separate products", "when": "now"},
            "impact": "avoids averaging incompatible demand",
            "confidence": "high",
            "limits": ["counts are docked vehicles only; free-floating bikes are a separate feed"],
            "falsifier": "a snapshot where the shares reverse",
        },
        {
            "text": (
                f"E-bike share rises from {south.get('bbe', 0):.0%} in the southern third to "
                f"{north.get('bbe', 0):.0%} in the northern third."
            ),
            "evidence_ids": [fleet["evidence_id"]],
            "action": {"owner": "operations", "what": "test type-specific moves up the hill rather than generic bike moves", "when": "next rebalance trial"},
            "impact": "may reduce the hill-top drain without adding vehicles",
            "confidence": "medium",
            "limits": ["latitude is a proxy for elevation, not a measurement"],
            "falsifier": "e-bike share at hill-top stations does not predict a slower drain",
        },
        {
            "text": (
                f"Beryl bikes are the last vehicle at {last_left.get('beryl_bike', 0)} of "
                f"{f['one_bike_observations']} one-bike observations."
            ),
            "evidence_ids": [fleet["evidence_id"]],
            "action": {"owner": "rider product", "what": "show vehicle type, not just 'bike available'", "when": "next sprint"},
            "impact": "fewer surprises for riders who need a specific type",
            "confidence": "medium",
            "limits": ["85 observations, one morning"],
            "falsifier": "the last-vehicle mix matches the overall fleet mix",
        },
        {
            "text": (
                f"The last snapshot has {a['last_empty']} empty and {a['last_full']} full stations, "
                f"while {a['last_bikes']} of {a['last_capacity']} reported bays are occupied."
            ),
            "evidence_ids": [audit["evidence_id"]],
            "action": {"owner": "operations", "what": "fix distribution, not total fleet size", "when": "this week"},
            "impact": "the network has stock; it is in the wrong places",
            "confidence": "high",
            "limits": ["capacity is soft; occupancy uses observed bays"],
            "falsifier": "empty stations remain empty after a full rebalance cycle",
        },
        {
            "text": (
                f"Moving {p['total_bikes']} bikes in {len(p['moves'])} moves restores at least one bike "
                f"to {p['deficits_helped']} stations."
            ),
            "evidence_ids": [plan["evidence_id"]],
            "action": {"owner": "operations", "what": "run the nearest-source plan", "when": "before the next weekday peak"},
            "impact": f"{p['deficits_helped']} stations helped over {p['total_km']} km",
            "confidence": "medium",
            "limits": ["greedy matching", "no van capacity or traffic"],
            "falsifier": "helped stations are still empty two hours later",
        },
        {
            "text": (
                f"The forecast gate refuses a {gate['data']['horizon_min']}-minute forecast because there are "
                f"only {gate['data']['data_sufficiency']['duration_hours']} hours and "
                f"{gate['data']['data_sufficiency']['n_snapshots']} snapshots."
            ),
            "evidence_ids": [gate["evidence_id"]],
            "action": {"owner": "data engineering", "what": "keep the 5-minute collector running for at least 7 days", "when": "from today"},
            "impact": "unlocks a forecast that can be validated",
            "confidence": "high",
            "limits": ["the refusal is the correct output today"],
            "falsifier": "a longer series still fails to beat persistence",
        },
    ]

    print("\n--- Validated report ---")
    report = harness.call(
        "write_report",
        {
            "title": "Brighton Bikeshare — full agent report",
            "claims": claims,
            "filename": "FULL_REPORT.md",
        },
    )
    for row in harness.ledger.summaries():
        print(f"  {row['evidence_id']}  {row['tool']:<18} {row['summary']}")
    print(f"\nReport: {report['data']['path']}  ({report['data']['written']} claims, {len(report['data']['rejected'])} rejected)")

    print("\n--- What the room can ask next ---")
    print("  uv run python STEP_6/agent.py --llm -q \"Which stations need maintenance vs rebalancing?\"")
    print("  Try adding one tool (weather, events, free-floating bikes) and re-run the same loop.")
    print("\nTakeaway: the model is the easy part. The intelligence is in the tools, the time handling,")
    print("the evidence trail, and the willingness to say 'not yet'.")
    if args.json:
        print(json.dumps(report, indent=2, default=str))

def main() -> None:
    parser = argparse.ArgumentParser(description=STAGE)
    parser.add_argument("-q", "--question", help="question to ask; omit for the stage demo")
    parser.add_argument("--llm", action="store_true", help="let the model choose tools (needs an API key)")
    parser.add_argument("--model", help="OpenRouter model override")
    parser.add_argument("--data", help=f"snapshot folder (default: {DEFAULT_DATA})")
    parser.add_argument("--max-steps", type=int, default=8, help="tool-call loop limit")
    parser.add_argument("--json", action="store_true", help="also print the structured result")
    parser.add_argument("--quiet", action="store_true", help="do not print every tool call")
    args = parser.parse_args()

    REPORTS.mkdir(exist_ok=True)
    harness = build_harness(args)
    if args.question:
        ask(harness, args)
    else:
        demo(harness, args)


if __name__ == "__main__":
    main()
