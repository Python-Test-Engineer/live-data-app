"""Plotly chart pages generated from the ETL/analytics output.

These are the standalone "charts and plots" artefacts. The dashboard itself is
rendered by the ``make-html-dashboard`` skill with inline SVG, so it stays a
single file; these Plotly pages are for exploration and can be opened directly.

``include_plotlyjs="directory"`` writes one shared ``plotly.min.js`` into the
output folder instead of embedding ~5 MB in every chart.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

PAPER = "#f0eee6"
SURFACE = "#fbfaf7"
INK = "#1f1e1d"
MUTED = "#55524c"
GRID = "#e9e4d8"
ACCENT = "#d97757"
GREEN = "#6f9a6a"
AMBER = "#b9862f"
STONE = "#8c877c"
COLORS = [ACCENT, GREEN, AMBER, STONE, "#c9633f", "#5f8f8a", "#a06a9a"]


def _style(fig: go.Figure, title: str, subtitle: str = "") -> go.Figure:
    full_title = title if not subtitle else f"{title}<br><sup>{subtitle}</sup>"
    fig.update_layout(
        title=dict(text=full_title, x=0.01, xanchor="left", font=dict(size=18, color=INK)),
        paper_bgcolor=PAPER,
        plot_bgcolor=SURFACE,
        font=dict(family="Segoe UI, Inter, Helvetica, Arial, sans-serif", color=MUTED, size=12),
        margin=dict(l=60, r=32, t=78, b=52),
        colorway=COLORS,
        hoverlabel=dict(bgcolor=SURFACE, font=dict(color=INK)),
    )
    fig.update_xaxes(gridcolor=GRID, zerolinecolor=GRID, linecolor=GRID)
    fig.update_yaxes(gridcolor=GRID, zerolinecolor=GRID, linecolor=GRID)
    return fig


def _write(fig: go.Figure, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(path, include_plotlyjs="directory", full_html=True, auto_open=False)
    return path


def write_charts(df: pd.DataFrame, analytics: dict[str, Any], outdir: Path) -> list[Path]:
    """Write all standalone chart HTML pages and return their paths."""
    outdir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    # 1. Utilisation distribution
    bins = pd.DataFrame(analytics["utilisation_bands"])
    fig = go.Figure(go.Bar(
        x=bins["label"],
        y=bins["count"],
        marker_color=ACCENT,
        text=bins["count"],
        textposition="outside",
        hovertemplate="%{x} utilisation<br>%{y} stations<extra></extra>",
    ))
    _style(fig, "Utilisation distribution", "station count by utilisation band")
    fig.update_layout(xaxis_title="Utilisation band", yaxis_title="Stations", showlegend=False)
    paths.append(_write(fig, outdir / "utilisation_histogram.html"))

    # 2. Bikes by zone
    zones = pd.DataFrame(analytics["zones"])
    fig = go.Figure(go.Bar(
        x=zones["bikes"],
        y=zones["label"],
        orientation="h",
        marker_color=zones["color"] if "color" in zones else ACCENT,
        text=zones["bikes"],
        textposition="outside",
        customdata=zones[["stations", "utilisation_pct", "empty"]],
        hovertemplate=(
            "<b>%{y}</b><br>%{x} bikes<br>"
            "%{customdata[0]} stations · %{customdata[1]}% utilised · "
            "%{customdata[2]} empty<extra></extra>"
        ),
    ))
    _style(fig, "Bikes by zone", "supply concentration across geofences")
    fig.update_layout(xaxis_title="Bikes available", yaxis_title="", showlegend=False)
    fig.update_yaxes(autorange="reversed")
    paths.append(_write(fig, outdir / "zone_availability.html"))

    # 3. Top stations by bikes
    top = pd.DataFrame(analytics["top_stations"])
    fig = go.Figure(go.Bar(
        x=top["bikes"],
        y=top["name"],
        orientation="h",
        marker=dict(
            color=top["utilisation_pct"],
            colorscale=[[0, GREEN], [0.5, AMBER], [1, ACCENT]],
            colorbar=dict(title="Utilisation %"),
        ),
        text=top["bikes"],
        textposition="outside",
        customdata=top[["docks", "capacity", "zone"]],
        hovertemplate=(
            "<b>%{y}</b><br>%{x} bikes · %{customdata[0]} free docks<br>"
            "capacity %{customdata[1]} · %{customdata[2]}<extra></extra>"
        ),
    ))
    _style(fig, "Top stations by bikes", "colour shows utilisation; hover for free docks")
    fig.update_layout(xaxis_title="Bikes available", yaxis_title="", showlegend=False)
    fig.update_yaxes(autorange="reversed")
    paths.append(_write(fig, outdir / "top_stations.html"))

    # 4. Capacity vs bikes scatter
    scatter_df = df.copy()
    scatter_df["zone_name"] = scatter_df["zone_name"].fillna("Unzoned")
    fig = px.scatter(
        scatter_df,
        x="capacity",
        y="num_bikes_available",
        color="zone_name",
        size="capacity",
        hover_name="station_name",
        labels={"capacity": "Capacity", "num_bikes_available": "Bikes available", "zone_name": "Zone"},
        color_discrete_sequence=COLORS,
    )
    _style(fig, "Capacity vs bikes", "each point is a station; size repeats capacity")
    fig.update_layout(xaxis_title="Capacity", yaxis_title="Bikes available", legend_title_text="Zone")
    fig.add_shape(
        type="line", x0=0, y0=0, x1=float(df["capacity"].max()), y1=float(df["capacity"].max()),
        line=dict(color=ACCENT, width=1.5, dash="dot"),
    )
    fig.add_annotation(
        x=float(df["capacity"].max()), y=float(df["capacity"].max()),
        text="100% utilisation", showarrow=False, yshift=12,
        font=dict(color=ACCENT, size=11),
    )
    paths.append(_write(fig, outdir / "capacity_vs_bikes.html"))

    # 5. Vehicle mix
    mix = pd.DataFrame(analytics["vehicle_mix"])
    fig = go.Figure(go.Pie(
        labels=mix["label"],
        values=mix["value"],
        hole=0.55,
        marker=dict(colors=mix["color"]),
        textinfo="label+percent",
        hovertemplate="<b>%{label}</b><br>%{value} bikes · %{percent}<extra></extra>",
    ))
    _style(fig, "Vehicle mix", f"{int(mix['value'].sum())} bikes in the snapshot")
    fig.update_layout(showlegend=True, legend=dict(orientation="h", yanchor="bottom", y=-0.15))
    paths.append(_write(fig, outdir / "vehicle_mix.html"))

    # 6. Station status
    status = pd.DataFrame(analytics["status_counts"])
    status_colors = {
        "balanced": GREEN,
        "low": AMBER,
        "busy": ACCENT,
        "empty": "#c9633f",
        "full": "#a06a9a",
        "offline": STONE,
        "unknown": STONE,
    }
    fig = go.Figure(go.Bar(
        x=status["label"],
        y=status["count"],
        marker_color=[status_colors.get(label, STONE) for label in status["label"]],
        text=status["count"],
        textposition="outside",
        hovertemplate="%{x}<br>%{y} stations<extra></extra>",
    ))
    _style(fig, "Station status", "classification from bikes, docks and availability flags")
    fig.update_layout(xaxis_title="Status", yaxis_title="Stations", showlegend=False)
    paths.append(_write(fig, outdir / "station_status.html"))

    return paths
