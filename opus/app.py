"""
Opus AI-analyst app - entry point.

All analysis lives in ``analysis`` (charts in ``charts``); this file only wires
it to the CLI and HTTP.

CLI (run from the repo root):
    uv run opus/app.py --analyse            run the full analysis, write opus/reports/<stamp>/
    uv run opus/app.py --analyse --history  also fold in data/history.csv (longer, sparser series)
    uv run opus/app.py --analyse --llm      add an LLM-narrated briefing (needs OPENROUTER_API_KEY)
    uv run opus/app.py --analyse --offline  skip the one-off elevation lookup (uses cache if present)
    uv run opus/app.py --analyse --quiet    no console output (exit code 0/1 for schedulers)
    uv run opus/app.py                      web UI on http://127.0.0.1:5001

Web UI:
    GET  /                 latest report (insight cards + interactive charts + re-run button)
    POST /analyse          run the analysis in-process, return {ok, returncode, output}
    GET  /reports/<path>   raw report files (CSV, Markdown, standalone chart HTML)
"""

import json
import sys
from os.path import join

from flask import Flask, abort, jsonify, send_from_directory

import analysis

app = Flask(__name__)
PORT = 5001          # 5000 is the main live-data dashboard


@app.route("/")
def index():
    d = analysis.latest_report_dir()
    if d is None:
        code, _, d = analysis.run_analysis(quiet=True)
        if code != 0 or d is None:
            abort(500, "analysis failed - run `uv run opus/app.py --analyse` to see why")
    with open(join(d, "insights.json"), encoding="utf-8") as f:
        payload = json.load(f)
    figs = {}
    import glob
    import os
    for p in glob.glob(join(d, "charts", "*.json")):
        with open(p, encoding="utf-8") as f:
            figs[os.path.basename(p)[:-5]] = f.read()
    import pandas as pd
    route_csv = join(d, "rebalancing_plan.csv")
    route = pd.read_csv(route_csv) if os.path.exists(route_csv) else pd.DataFrame()
    ctx = payload["context"]
    ctx["skipped"] = ctx.get("skipped") or {}
    stamp = os.path.basename(d)
    return analysis.render_report(payload["insights"], ctx, figs, route,
                                  f"/reports/{stamp}/plotly.min.js", None, analyse_button=True)


@app.route("/analyse", methods=["POST"])
def analyse():
    code, output, _ = analysis.run_analysis(quiet=True)
    analysis.clean_reports(keep=5)
    return jsonify(ok=code == 0, returncode=code, output=output), (200 if code == 0 else 500)


@app.route("/reports/<path:p>")
def reports(p):
    return send_from_directory(analysis.REPORTS_DIR, p)


def main() -> int:
    argv = sys.argv[1:]
    if "--analyse" in argv or "--analyze" in argv:
        code, _, _ = analysis.run_analysis(include_history="--history" in argv, llm="--llm" in argv,
                                           offline="--offline" in argv, quiet="--quiet" in argv)
        return code
    print(f"Starting Opus AI-analyst on http://127.0.0.1:{PORT}")
    app.run(debug=False, host="127.0.0.1", port=PORT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
