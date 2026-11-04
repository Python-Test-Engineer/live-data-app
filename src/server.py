#!/usr/bin/env python3
"""Local dashboard server with the chat endpoint.

Run:
    uv run src/server.py
    uv run src/server.py --port 5001 --open

The dashboard is static; this server exists so the chat widget can call the
current model without exposing an API key in the browser.
"""

from __future__ import annotations

import argparse
import threading
import webbrowser
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, request, send_file

try:  # package import
    from .chat import ChatError, ask_model, build_context, resolve_model
except ImportError:  # direct script import
    from chat import ChatError, ask_model, build_context, resolve_model

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DASHBOARD = PROJECT_ROOT / "src" / "output" / "dashboard.html"
DEFAULT_OUTPUT = PROJECT_ROOT / "src" / "output"

app = Flask(__name__)


@app.after_request
def add_cors(response):
    # The dashboard may be opened from file:// or a Live Server preview while
    # the Flask chat endpoint runs on port 5000. Allow that local cross-origin
    # request; there are no cookies or credentials involved.
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Max-Age"] = "600"
    return response


routes: dict[str, Any] = {
    "dashboard": DEFAULT_DASHBOARD,
    "output": DEFAULT_OUTPUT,
}


def _dashboard_path() -> Path:
    return Path(routes["dashboard"])


def _output_path() -> Path:
    return Path(routes["output"])


@app.get("/")
@app.get("/dashboard.html")
def index():
    path = _dashboard_path()
    if not path.exists():
        return (
            "Dashboard not built yet. Run:\n\n"
            "  uv run src/pipeline.py --input data/data_20261104T045733Z.csv\n",
            503,
            {"Content-Type": "text/plain; charset=utf-8"},
        )
    return send_file(path)


@app.get("/api/health")
def health():
    try:
        context = build_context(_output_path())
        stations = len(context.get("stations") or [])
        return jsonify({
            "ok": True,
            "model": resolve_model(),
            "stations": stations,
            "snapshot": context.get("snapshot"),
            "dashboard": str(_dashboard_path()),
        })
    except Exception as exc:  # noqa: BLE001 - health surface
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/chat", methods=["POST", "OPTIONS"])
def chat():
    if request.method == "OPTIONS":
        return "", 204
    body = request.get_json(silent=True) or {}
    question = body.get("question")
    if not isinstance(question, str) or not question.strip():
        return jsonify({"error": "Ask a question about the dashboard."}), 400
    if len(question) > 2000:
        return jsonify({"error": "Question is too long (max 2000 characters)."}), 400

    try:
        context = build_context(_output_path())
        if not context.get("stations"):
            return jsonify({
                "error": "Dashboard data not found. Run `uv run src/pipeline.py` first.",
            }), 503
        answer, model = ask_model(question, body.get("history"), context)
        return jsonify({"answer": answer, "model": model})
    except ChatError as exc:
        return jsonify({"error": str(exc)}), exc.status
    except Exception as exc:  # noqa: BLE001 - keep the browser response clean
        return jsonify({"error": f"Unexpected chat error: {exc}"}), 500


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve the Brighton Bikeshare dashboard with chat")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: localhost only)")
    parser.add_argument("--port", type=int, default=5000, help="Port (default: 5000)")
    parser.add_argument("--dashboard", default=str(DEFAULT_DASHBOARD), help="Dashboard HTML path")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Pipeline output folder used as chat context")
    parser.add_argument("--open", action="store_true", help="Open the dashboard in the default browser")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    routes["dashboard"] = Path(args.dashboard).expanduser().resolve()
    routes["output"] = Path(args.output).expanduser().resolve()

    url = f"http://{args.host}:{args.port}/"
    print(f"Serving {routes['dashboard']}")
    print(f"Chat model: {resolve_model()}")
    print(f"Chat endpoint: {url}api/chat")
    print(f"Open {url}")
    if args.open:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    app.run(host=args.host, port=args.port, debug=False, threaded=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
