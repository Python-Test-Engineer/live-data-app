#!/usr/bin/env python3
"""Brighton Bikeshare ETL + analytics pipeline.

Example:
    uv run src/pipeline.py --input data/data_20261104T045733Z.csv

Steps:
    1. ETL the combined GBFS snapshot and record quality checks.
    2. Compute KPI, distribution, zone, station, and outlier analytics.
    3. Write standalone Plotly chart pages.
    4. Write the make-html-dashboard payload and render dashboard.html.

All outputs go to ``src/output/`` unless ``--outdir`` is supplied.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

try:  # package import (uv run python -m src.pipeline)
    from .analytics import analyse, dashboard_payload
    from .build_dashboard import build_dashboard
    from .charts import write_charts
    from .etl import run_etl
    from .utils import write_json
except ImportError:  # direct script import (uv run src/pipeline.py)
    from analytics import analyse, dashboard_payload
    from build_dashboard import build_dashboard
    from charts import write_charts
    from etl import run_etl
    from utils import write_json

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def latest_snapshot() -> Path:
    candidates = sorted((PROJECT_ROOT / "data").glob("data_*.csv"))
    if not candidates:
        raise FileNotFoundError("No data/data_*.csv snapshots found. Run data/fetch_gbfs.py first.")
    return candidates[-1]


def resolve_input(value: str | None) -> Path:
    if not value:
        return latest_snapshot()
    path = Path(value).expanduser()
    if not path.is_absolute() and not path.exists():
        path = PROJECT_ROOT / path
    return path.resolve()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Brighton Bikeshare ETL + analytics dashboard pipeline")
    parser.add_argument("--input", help="Combined snapshot CSV (default: newest data/data_*.csv)")
    parser.add_argument("--outdir", default=str(PROJECT_ROOT / "src" / "output"), help="Output directory")
    parser.add_argument("--no-charts", action="store_true", help="Skip standalone Plotly chart pages")
    parser.add_argument("--no-dashboard", action="store_true", help="Skip the make-html-dashboard render")
    parser.add_argument("--quiet", action="store_true", help="Only print the final paths")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    started = time.perf_counter()
    input_path = resolve_input(args.input)
    output_dir = Path(args.outdir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    log = (lambda *parts: None) if args.quiet else (lambda *parts: print(*parts, flush=True))

    log(f"ETL      {input_path}")
    clean, report = run_etl(input_path)
    clean_path = output_dir / "clean_stations.csv"
    clean.to_csv(clean_path, index=False)
    write_json(output_dir / "etl_report.json", report)
    log(f"         {report['source_rows']} rows in -> {report['clean_rows']} rows out, {len(report['issues'])} issues")

    log("ANALYTICS")
    results = analyse(clean, report)
    write_json(output_dir / "analysis.json", results)
    log(
        f"         {len(results['top_stations'])} top stations, {len(results['zones'])} zones, "
        f"{len(results['utilisation_bands'])} utilisation bands"
    )

    chart_paths: list[Path] = []
    if not args.no_charts:
        log("CHARTS")
        chart_paths = write_charts(clean, results, output_dir / "charts")
        for path in chart_paths:
            log(f"         {path.name}")

    payload = dashboard_payload(clean, report, results)
    dashboard_path = None
    if not args.no_dashboard:
        log("DASHBOARD")
        dashboard_path, payload_path, builder_output = build_dashboard(payload, output_dir)
        log(f"         {builder_output}")
    else:
        payload_path = output_dir / "dashboard-data.json"
        write_json(payload_path, payload)

    elapsed = time.perf_counter() - started
    print("")
    print(f"Input:       {input_path}")
    print(f"Clean data:  {clean_path}")
    print(f"ETL report:  {output_dir / 'etl_report.json'}")
    print(f"Analytics:   {output_dir / 'analysis.json'}")
    print(f"Payload:     {payload_path}")
    if chart_paths:
        print(f"Charts:      {output_dir / 'charts'} ({len(chart_paths)} pages)")
    if dashboard_path:
        print(f"Dashboard:   {dashboard_path}")
        print("Chat:        uv run src/server.py --open")
    print(f"Elapsed:     {elapsed:.2f}s")
    if report["issues"]:
        print("\nQuality issues:")
        for issue in report["issues"]:
            print(f"  - [{issue['status']}] {issue['name']}: {issue['detail']}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # noqa: BLE001 - CLI surface
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
