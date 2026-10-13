"""
Brighton Bikeshare Dashboard - main entry point.

The single app file. All fetching, ETL, analysis and history logic lives in
``utils``; this module only wires it to HTTP and the CLI.

CLI modes:
    uv run app.py                    -> start the web dashboard
                                        (http://127.0.0.1:5000)
    uv run app.py --collect          -> run one ETL snapshot and append it to
                                        history.csv (exit 0 on success, 1 on
                                        failure; for cron / Task Scheduler).
    uv run app.py --collect --quiet  -> same, without the summary line.

Web UI:
    * GET  /       run the live ETL and render KPIs, charts, and the table.
    * POST /run    trigger utils.run_full_pipeline() (re-pull every feed,
                   write per-feed CSVs + a timestamped DEMO snapshot) and
                   return its console output for the "Run data.py" button.
"""

import sys

from flask import Flask, jsonify, render_template

import utils

app = Flask(__name__)


@app.route("/")
def index():
    df, snapshot_time, error = utils.run_etl()

    context = {
        "snapshot_time": snapshot_time,
        "error": error,
        "history_snapshots": utils.count_snapshots(),
        "time_series": utils.read_time_series(),
    }
    if df is not None:
        context["analysis"] = utils.analyse(df)
    return render_template("index.html", **context)


@app.route("/run", methods=["POST"])
def run_data_pipeline():
    """Run the full data pipeline in-process and return its console output."""
    try:
        output = utils.run_full_pipeline()
        return jsonify(ok=True, returncode=0, output=output)
    except Exception as e:  # noqa: BLE001 - surface run failures to the UI
        return jsonify(ok=False, returncode=-1, output=str(e)), 500


@app.route("/snapshot", methods=["POST"])
def snapshot():
    """Fetch current live data and write a fresh DEMO_DATA_<stamp>.csv."""
    try:
        output = utils.snapshot_current_data()
        return jsonify(ok=True, returncode=0, output=output)
    except Exception as e:  # noqa: BLE001 - surface run failures to the UI
        return jsonify(ok=False, returncode=-1, output=str(e)), 500


def main() -> int:
    if "--collect" in sys.argv:
        quiet = "--quiet" in sys.argv
        sys.exit(utils.run_snapshot(quiet))
    print("Starting Brighton Bikeshare dashboard on http://127.0.0.1:5000")
    app.run(debug=False, host="127.0.0.1", port=5000)
    return 0


if __name__ == "__main__":
    main()