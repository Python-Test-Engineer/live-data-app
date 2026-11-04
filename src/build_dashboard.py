"""Write the dashboard payload and invoke the make-html-dashboard skill."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

try:
    from .utils import write_json
except ImportError:  # direct script import
    from utils import write_json

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BUILDER = PROJECT_ROOT / "skills" / "make-html-dashboard" / "scripts" / "build_dashboard.mjs"


def build_dashboard(
    payload: dict[str, Any],
    outdir: str | Path,
    *,
    builder: str | Path | None = None,
) -> tuple[Path, Path, str]:
    """Save the payload JSON, then render it through the skill's Node builder."""
    output_dir = Path(outdir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    payload_path = output_dir / "dashboard-data.json"
    write_json(payload_path, payload)

    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node.js is required to render the dashboard (make-html-dashboard skill).")

    builder_path = Path(builder or os.environ.get("DASHBOARD_BUILDER", DEFAULT_BUILDER)).expanduser().resolve()
    if not builder_path.exists():
        raise FileNotFoundError(f"Dashboard builder not found: {builder_path}")

    dashboard_path = output_dir / "dashboard.html"
    command = [node, str(builder_path), "--data", str(payload_path), "--out", str(dashboard_path)]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            "Dashboard build failed.\n"
            f"Command: {' '.join(command)}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    return dashboard_path, payload_path, (result.stdout or "").strip()


def load_dashboard_payload(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
