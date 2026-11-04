"""Brighton Bikeshare ETL + analytics package.

Run the whole pipeline with:

    uv run src/pipeline.py --input data/data_20261104T045733Z.csv

Outputs land in ``src/output/``: cleaned data, ETL report, analytics JSON,
Plotly chart pages, dashboard payload, and the final dashboard HTML.
"""

from .etl import run_etl
from .analytics import analyse
from .charts import write_charts
from .build_dashboard import build_dashboard

__all__ = ["run_etl", "analyse", "write_charts", "build_dashboard"]
