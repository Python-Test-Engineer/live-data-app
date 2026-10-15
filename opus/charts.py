"""
Plotly figure builders for the Opus AI-analyst report.

One function per chart id (see OPUS_PLAN.md section 4.6). Every builder takes
plain pandas/numpy data and returns a ``plotly.graph_objects.Figure`` with the
shared theme applied. Titles state the *insight*, not the chart type.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------
STATE_COLORS = {
    "EMPTY": "#d7263d",
    "LOW": "#f49d37",
    "OK": "#3f88c5",
    "HIGH": "#44af69",
    "FULL": "#6c3483",
    "OFFLINE": "#7f8c8d",
}
STATE_ORDER = ["EMPTY", "LOW", "OK", "HIGH", "FULL"]
TYPE_COLORS = {"beryl_bike": "#2e86ab", "bbe": "#f18f01", "scooter": "#a23b72"}
TYPE_LABELS = {"beryl_bike": "Pedal bike", "bbe": "E-bike", "scooter": "E-scooter"}
FONT = "Inter, system-ui, -apple-system, Segoe UI, Roboto, sans-serif"
MAP_CENTER = {"lat": 50.833, "lon": -0.145}
GAP_FILL = "rgba(127,140,141,0.15)"


def theme(fig: go.Figure, title: str, subtitle: str | None = None, height: int = 460) -> go.Figure:
    text = f"<b>{title}</b>"
    if subtitle:
        text += f"<br><span style='font-size:13px;color:#666'>{subtitle}</span>"
    fig.update_layout(
        template="plotly_white",
        title={"text": text, "x": 0.01, "xanchor": "left"},
        font={"family": FONT, "size": 14, "color": "#222"},
        margin={"l": 60, "r": 30, "t": 90, "b": 50},
        height=height,
        hoverlabel={"font": {"family": FONT}},
        legend={"orientation": "h", "y": -0.15},
    )
    return fig


def _map_layout(fig: go.Figure, zoom: float = 11.6) -> None:
    fig.update_layout(
        map={"style": "carto-positron", "center": MAP_CENTER, "zoom": zoom},
        margin={"l": 0, "r": 0, "t": 90, "b": 0},
    )


def _shade_gaps(fig: go.Figure, gaps: list[tuple], row=None, col=None) -> None:
    for start, end in gaps:
        kw = {"row": row, "col": col} if row else {}
        fig.add_vrect(x0=start, x1=end, fillcolor=GAP_FILL, line_width=0,
                      annotation_text="no data", annotation_position="top left",
                      annotation_font_color="#7f8c8d", **kw)


# ---------------------------------------------------------------------------
# Tier A - data forensics
# ---------------------------------------------------------------------------
def residual_hist(resid: pd.Series) -> go.Figure:
    fig = go.Figure(go.Histogram(x=resid, nbinsx=max(10, int(resid.max() - resid.min()) + 1),
                                 marker_color="#3f88c5"))
    fig.add_vline(x=0, line_dash="dash", line_color="#222",
                  annotation_text="bikes + docks = capacity", annotation_position="top")
    fig.update_xaxes(title="bikes + docks − stated capacity")
    fig.update_yaxes(title="observations")
    return theme(fig, f"Stated capacity is soft: bikes+docks misses it by {resid.min():+.0f} to {resid.max():+.0f}",
                 "If capacity were a hard limit every bar would sit on the dashed line")


def docks_heatmap(docks: pd.DataFrame, floor_value: int, share: float) -> go.Figure:
    """docks: rows = station name, cols = time."""
    z = docks.values
    fig = go.Figure(go.Heatmap(
        z=z, x=[t.strftime("%d %b %H:%M") for t in docks.columns], y=list(docks.index),
        colorscale=[[0, "#fdfdfd"], [0.15, "#cfe3f3"], [1, "#08306b"]],
        colorbar={"title": "docks"},
        hovertemplate="%{y}<br>%{x}<br>%{z} docks free<extra></extra>",
    ))
    mask = (z == floor_value).astype(float)
    mask[mask == 0] = np.nan
    fig.add_trace(go.Heatmap(z=mask, x=[t.strftime("%d %b %H:%M") for t in docks.columns], y=list(docks.index),
                             colorscale=[[0, "#d7263d"], [1, "#d7263d"]], showscale=False, opacity=0.55,
                             hoverinfo="skip"))
    fig.update_yaxes(showticklabels=False, title=f"{len(docks)} stations")
    return theme(fig, f"The 'wall of {floor_value}s': {share:.0%} of readings report exactly {floor_value} free docks",
                 f"Red cells = exactly {floor_value}. A real dock count would vary; this is a reporting floor", 560)


def lag_strip(metrics: pd.DataFrame) -> go.Figure:
    m = metrics.sort_values("lag_median_min")
    color = np.where(m["lag_median_min"] > 60, STATE_COLORS["EMPTY"], "#3f88c5")
    fig = go.Figure(go.Scatter(
        x=m["lag_median_min"], y=m["name"], mode="markers",
        marker={"color": color, "size": 8},
        hovertemplate="%{y}<br>last report %{x:.0f} min before snapshot<extra></extra>"))
    fig.add_vline(x=60, line_dash="dot", line_color=STATE_COLORS["EMPTY"], annotation_text="60 min = stale")
    fig.update_xaxes(title="minutes since station last reported (median)", type="log")
    fig.update_yaxes(showticklabels=False, title="stations")
    n = int((metrics["lag_median_min"] > 60).sum())
    return theme(fig, f"{n} stations are reporting stale data (> 1 hour old)", "Each dot is a station", 520)


def sparklines(bikes: pd.DataFrame, names: dict, flagged: set, max_n: int = 120) -> go.Figure:
    """bikes: index = time, columns = station_id."""
    cols = list(bikes.columns)[:max_n]
    ncol = 10
    nrow = int(np.ceil(len(cols) / ncol))
    fig = make_subplots(rows=nrow, cols=ncol, horizontal_spacing=0.01, vertical_spacing=0.02)
    for k, sid in enumerate(cols):
        r, c = k // ncol + 1, k % ncol + 1
        dead = sid in flagged
        fig.add_trace(go.Scatter(
            x=bikes.index, y=bikes[sid], mode="lines", line={"width": 1.5,
                                                             "color": "#c0392b" if dead else "#3f88c5"},
            hovertemplate=f"{names.get(sid, sid)}<br>%{{y}} bikes<extra></extra>", showlegend=False), r, c)
    fig.update_xaxes(visible=False)
    fig.update_yaxes(visible=False)
    return theme(fig, f"{len(flagged)} stations flat-lined or offline (red) — every station's line, at a glance",
                 "Small multiples: one tiny chart per station", 60 * nrow + 120)


# ---------------------------------------------------------------------------
# Tier B - statistics
# ---------------------------------------------------------------------------
def fill_violin(latest: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    for area, g in latest.groupby("area", sort=True):
        fig.add_trace(go.Violin(y=g["fill"], name=area, box_visible=True, meanline_visible=True,
                                points="all", pointpos=0, jitter=0.4, text=g["name"],
                                hovertemplate="%{text}<br>fill %{y:.0%}<extra></extra>"))
    fig.add_hrect(y0=0, y1=0.1, fillcolor=STATE_COLORS["EMPTY"], opacity=0.08, line_width=0,
                  annotation_text="rider can't find a bike", annotation_position="bottom right")
    fig.add_hrect(y0=0.9, y1=1.0, fillcolor=STATE_COLORS["FULL"], opacity=0.08, line_width=0,
                  annotation_text="rider can't park", annotation_position="top right")
    fig.update_yaxes(title="fill ratio (bikes / effective capacity)", tickformat=".0%", range=[-0.05, 1.05])
    fig.update_layout(showlegend=False)
    share = ((latest["fill"] < 0.1) | (latest["fill"] > 0.9)).mean()
    return theme(fig, f"{share:.0%} of stations sit in a danger zone right now",
                 "Fill distribution per area at the latest snapshot")


def lorenz(values: np.ndarray, gini: float, top20: float) -> go.Figure:
    v = np.sort(np.asarray(values, dtype=float))
    cum = np.concatenate([[0], np.cumsum(v) / v.sum()])
    x = np.linspace(0, 1, len(cum))
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x, y=x, mode="lines", line={"dash": "dash", "color": "#999"}, name="perfect equality"))
    fig.add_trace(go.Scatter(x=x, y=cum, mode="lines", fill="tonexty", fillcolor="rgba(215,38,61,0.12)",
                             line={"color": STATE_COLORS["EMPTY"], "width": 3}, name="Brighton stations"))
    fig.add_annotation(x=0.8, y=float(np.interp(0.8, x, cum)), text=f"top 20% hold {top20:.0%} of bikes",
                       showarrow=True, arrowhead=2, ax=-80, ay=-60)
    fig.update_xaxes(title="share of stations (fewest bikes → most)", tickformat=".0%")
    fig.update_yaxes(title="share of docked bikes", tickformat=".0%")
    return theme(fig, f"Bikes are unevenly spread: Gini = {gini:.2f}", "Lorenz curve of docked bikes across stations")


def station_map(m: pd.DataFrame, color: str, title: str, subtitle: str, colorscale="RdBu",
                cmid: float | None = None, size_col: str = "eff_capacity", fmt: str = ".2f",
                cbar_title: str = "") -> go.Figure:
    size = 6 + 18 * (m[size_col] - m[size_col].min()) / max(1e-9, (m[size_col].max() - m[size_col].min()))
    marker = {"size": size, "color": m[color], "colorscale": colorscale, "opacity": 0.85,
              "colorbar": {"title": cbar_title}}
    if cmid is not None:
        span = float(np.nanmax(np.abs(m[color] - cmid))) or 1.0
        marker.update(cmin=cmid - span, cmax=cmid + span)
    fig = go.Figure(go.Scattermap(
        lat=m["lat"], lon=m["lon"], mode="markers", marker=marker, text=m["name"],
        customdata=np.stack([m[color], m["bikes_now"], m["eff_capacity"]], axis=1),
        hovertemplate="<b>%{text}</b><br>" + f"{cbar_title or color}: " + "%{customdata[0]:" + fmt +
                      "}<br>bikes now %{customdata[1]} / %{customdata[2]}<extra></extra>"))
    theme(fig, title, subtitle, 560)
    _map_layout(fig)
    return fig


def fleet_mix(mix: pd.DataFrame) -> go.Figure:
    """mix: index = area, columns = vehicle types (share 0-1)."""
    fig = go.Figure()
    for t in mix.columns:
        fig.add_trace(go.Bar(y=mix.index, x=mix[t], name=TYPE_LABELS.get(t, t), orientation="h",
                             marker_color=TYPE_COLORS.get(t), hovertemplate="%{y}: %{x:.0%}<extra></extra>"))
    fig.update_layout(barmode="stack")
    fig.update_xaxes(tickformat=".0%", title="share of docked vehicles")
    return theme(fig, "Each area has a different fleet mix — the vehicle type matters, not just the count",
                 "Average share of vehicle types docked per area")


def clusters_pca(pc: pd.DataFrame, profile: pd.DataFrame) -> go.Figure:
    fig = make_subplots(rows=1, cols=2, column_widths=[0.55, 0.45], specs=[[{"type": "xy"}, {"type": "polar"}]],
                        subplot_titles=("Stations in behaviour space (PCA)", "Archetype fingerprints"))
    palette = ["#3f88c5", "#d7263d", "#44af69", "#f49d37", "#6c3483", "#2e86ab"]
    for k, (name, g) in enumerate(pc.groupby("archetype", sort=True)):
        fig.add_trace(go.Scatter(x=g["pc1"], y=g["pc2"], mode="markers", name=f"{name} ({len(g)})",
                                 marker={"size": 10, "color": palette[k % 6]}, text=g["name"],
                                 hovertemplate="%{text}<extra></extra>"), 1, 1)
        if name in profile.index:
            r = profile.loc[name]
            fig.add_trace(go.Scatterpolar(r=list(r.values) + [r.values[0]], theta=list(r.index) + [r.index[0]],
                                          fill="toself", name=name, showlegend=False, opacity=0.5,
                                          line_color=palette[k % 6]), 1, 2)
    fig.update_polars(radialaxis={"range": [0, 1], "showticklabels": False})
    return theme(fig, "The AI found distinct station archetypes — each needs a different policy",
                 "K-means on fill, net flow, churn, volatility, e-bike share and capacity", 520)


def capacity_dumbbell(m: pd.DataFrame) -> go.Figure:
    m = m.sort_values("cap_gap")
    fig = go.Figure()
    for _, r in m.iterrows():
        fig.add_trace(go.Scatter(x=[r["capacity"], r["p95_bikes"]], y=[r["name"], r["name"]], mode="lines",
                                 line={"color": "#bbb", "width": 3}, showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=m["capacity"], y=m["name"], mode="markers", name="stated capacity",
                             marker={"size": 11, "color": "#3f88c5"}))
    fig.add_trace(go.Scatter(x=m["p95_bikes"], y=m["name"], mode="markers", name="p95 bikes observed",
                             marker={"size": 11, "color": STATE_COLORS["EMPTY"]}))
    fig.update_xaxes(title="vehicles")
    return theme(fig, "Capacity doesn't match use: bays sit idle in some places and overflow in others",
                 "Most over- and under-provisioned stations", 40 + 26 * len(m) + 120)


def elevation_scatter(m: pd.DataFrame, rho: float, p: float) -> go.Figure:
    fig = go.Figure(go.Scatter(x=m["elevation_m"], y=m["mean_fill"], mode="markers", text=m["name"],
                               marker={"size": 9, "color": m["ebike_share"], "colorscale": "Oranges",
                                       "colorbar": {"title": "e-bike share"}, "line": {"width": 0.5, "color": "#555"}},
                               hovertemplate="%{text}<br>%{x:.0f} m<br>fill %{y:.0%}<extra></extra>"))
    ok = m[["elevation_m", "mean_fill"]].dropna()
    if len(ok) > 3:
        k, c = np.polyfit(ok["elevation_m"], ok["mean_fill"], 1)
        xs = np.linspace(ok["elevation_m"].min(), ok["elevation_m"].max(), 20)
        fig.add_trace(go.Scatter(x=xs, y=k * xs + c, mode="lines", line={"color": "#222", "dash": "dash"},
                                 name="trend", showlegend=False))
    fig.update_xaxes(title="station elevation (m, SRTM)")
    fig.update_yaxes(title="mean fill", tickformat=".0%")
    return theme(fig, f"Brighton's hills shape supply: Spearman ρ = {rho:+.2f} (p = {p:.3f})",
                 "Fill vs elevation; colour = share of e-bikes")


def dockless_map(free: pd.DataFrame, stations: pd.DataFrame, sites: pd.DataFrame, low: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scattermap(lat=stations["lat"], lon=stations["lon"], mode="markers", name="stations",
                                marker={"size": 7, "color": "#3f88c5"}, text=stations["name"],
                                hovertemplate="%{text}<extra>station</extra>"))
    fig.add_trace(go.Scattermap(lat=free["lat"], lon=free["lon"], mode="markers", name="free-floating vehicle",
                                marker={"size": 6, "color": "#f49d37"},
                                hovertemplate="%{customdata}<extra></extra>",
                                customdata=free["vehicle_type_id"].map(TYPE_LABELS).fillna(free["vehicle_type_id"])))
    if len(low):
        fig.add_trace(go.Scattermap(lat=low["lat"], lon=low["lon"], mode="markers", name="low battery (<10 km)",
                                    marker={"size": 9, "color": STATE_COLORS["EMPTY"]},
                                    hovertemplate="%{customdata:.0f} m range<extra>low battery</extra>",
                                    customdata=low["current_range_meters"]))
    if len(sites):
        fig.add_trace(go.Scattermap(lat=sites["lat"], lon=sites["lon"], mode="markers+text", name="candidate new station",
                                    marker={"size": 22, "color": "#6c3483", "opacity": 0.5},
                                    text=sites["n"].astype(str), textposition="middle center",
                                    hovertemplate="%{text} vehicles left here<extra>candidate site</extra>"))
    theme(fig, "Where riders actually leave vehicles — and which ones need a battery swap",
          "Free-floating vehicles far from any station suggest new station sites", 560)
    _map_layout(fig)
    return fig


# ---------------------------------------------------------------------------
# Tier C - time series
# ---------------------------------------------------------------------------
def pulse(tot: pd.DataFrame, gaps: list[tuple]) -> go.Figure:
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Scatter(x=tot.index, y=tot["bikes"], name="docked vehicles", mode="lines+markers",
                             line={"color": "#3f88c5", "width": 3}), secondary_y=False)
    fig.add_trace(go.Scatter(x=tot.index, y=tot["empty"], name="empty stations", mode="lines+markers",
                             line={"color": STATE_COLORS["EMPTY"], "width": 3}), secondary_y=True)
    fig.add_trace(go.Scatter(x=tot.index, y=tot["full"], name="full stations", mode="lines+markers",
                             line={"color": STATE_COLORS["FULL"], "width": 2, "dash": "dot"}), secondary_y=True)
    _shade_gaps(fig, gaps)
    fig.update_yaxes(title="docked vehicles", secondary_y=False)
    fig.update_yaxes(title="stations", secondary_y=True, rangemode="tozero")
    d_empty = int(tot["empty"].iloc[-1] - tot["empty"].iloc[0])
    return theme(fig, f"System pulse: empty stations {int(tot['empty'].iloc[0])} → {int(tot['empty'].iloc[-1])} "
                      f"({d_empty:+d}) over the window",
                 "Collector gaps are shaded, never interpolated")


def netflow_bar(m: pd.DataFrame, n: int = 12) -> go.Figure:
    s = m.dropna(subset=["slope_per_h"]).sort_values("slope_per_h")
    sel = pd.concat([s.head(n), s.tail(n)]).drop_duplicates("station_id")
    color = np.where(sel["slope_per_h"] < 0, STATE_COLORS["EMPTY"], STATE_COLORS["HIGH"])
    fig = go.Figure(go.Bar(x=sel["slope_per_h"], y=sel["name"], orientation="h", marker_color=color,
                           error_x={"type": "data", "array": sel["slope_se"].fillna(0), "color": "#888"},
                           hovertemplate="%{y}<br>%{x:+.1f} bikes/hour<extra></extra>"))
    fig.update_xaxes(title="net flow (bikes per hour, OLS slope ± SE)")
    return theme(fig, "Drains (red) lose bikes, sinks (green) hoard them — that's the rebalancing list",
                 "Top draining and filling stations", 40 + 24 * len(sel) + 120)


def fill_heatmap(fill: pd.DataFrame) -> go.Figure:
    fig = go.Figure(go.Heatmap(
        z=fill.values, x=[t.strftime("%d %b %H:%M") for t in fill.columns], y=list(fill.index),
        colorscale=[[0, STATE_COLORS["EMPTY"]], [0.2, STATE_COLORS["LOW"]], [0.5, "#f7f7f7"],
                    [0.75, STATE_COLORS["HIGH"]], [1, STATE_COLORS["FULL"]]], zmin=0, zmax=1,
        colorbar={"title": "fill", "tickformat": ".0%"},
        hovertemplate="%{y}<br>%{x}<br>fill %{z:.0%}<extra></extra>"))
    fig.update_yaxes(showticklabels=False, title="stations (clustered by behaviour)")
    return theme(fig, "Stations move in groups: clustered fill heatmap",
                 "Rows ordered by hierarchical clustering so similar stations sit together", 600)


def transition(mat: pd.DataFrame, counts: pd.DataFrame) -> go.Figure:
    fig = make_subplots(rows=1, cols=2, column_widths=[0.45, 0.55],
                        specs=[[{"type": "heatmap"}, {"type": "domain"}]],
                        subplot_titles=("P(next state | state)", "State flows between snapshots"))
    fig.add_trace(go.Heatmap(z=mat.values, x=list(mat.columns), y=list(mat.index), colorscale="Blues",
                             text=np.round(mat.values, 2), texttemplate="%{text}", showscale=False,
                             hovertemplate="%{y} → %{x}: %{z:.2f}<extra></extra>"), 1, 1)
    labels = [f"{s} (t)" for s in counts.index] + [f"{s} (t+1)" for s in counts.columns]
    src, tgt, val, col = [], [], [], []
    n = len(counts.index)
    for i, a in enumerate(counts.index):
        for j, b in enumerate(counts.columns):
            v = counts.loc[a, b]
            if v > 0:
                src.append(i); tgt.append(n + j); val.append(float(v))
                col.append("rgba(215,38,61,0.45)" if b == "EMPTY" and a != "EMPTY" else "rgba(150,150,150,0.25)")
    fig.add_trace(go.Sankey(node={"label": labels, "color": [STATE_COLORS[s] for s in counts.index] +
                                  [STATE_COLORS[s] for s in counts.columns], "pad": 12},
                            link={"source": src, "target": tgt, "value": val, "color": col}), 1, 2)
    fig.update_yaxes(autorange="reversed", row=1, col=1)
    return theme(fig, "How stations fail: the state machine of the network",
                 "Red flows = stations tipping into EMPTY", 520)


def time_to_failure(df: pd.DataFrame) -> go.Figure:
    d = df.sort_values("minutes")
    color = np.where(d["kind"] == "empty", STATE_COLORS["EMPTY"], STATE_COLORS["FULL"])
    fig = go.Figure(go.Bar(x=d["minutes"], y=d["name"], orientation="h", marker_color=color,
                           text=[f"{k} in ~{m:.0f} min" for k, m in zip(d["kind"], d["minutes"])],
                           textposition="outside", hovertemplate="%{y}: %{x:.0f} min<extra></extra>"))
    fig.update_xaxes(title="minutes until failure if current trend continues")
    fig.update_yaxes(autorange="reversed")
    return theme(fig, f"{len(d)} stations will run empty or full within 2 hours on current trend",
                 "Linear extrapolation of each station's net flow — the urgency queue for the van",
                 40 + 26 * max(len(d), 3) + 120)


def churn_vs_net(m: pd.DataFrame) -> go.Figure:
    fig = go.Figure(go.Scatter(x=m["slope_per_h"], y=m["churn_per_h"], mode="markers", text=m["name"],
                               marker={"size": 9, "color": m["mean_fill"], "colorscale": "RdYlGn", "cmin": 0,
                                       "cmax": 1, "colorbar": {"title": "mean fill"}},
                               hovertemplate="%{text}<br>net %{x:+.1f}/h · churn %{y:.1f}/h<extra></extra>"))
    fig.add_vline(x=0, line_color="#999", line_dash="dot")
    fig.update_xaxes(title="net flow (bikes/hour)")
    fig.update_yaxes(title="churn (bikes moved in+out per hour)")
    return theme(fig, "Busy ≠ broken: high-churn stations near zero net flow are healthy",
                 "Top-centre = busy & balanced; top-left = busy & draining (act first)")


def before_after(sim: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=sim["minutes"], y=sim["failing_no_plan"], name="do nothing", mode="lines",
                             line={"color": STATE_COLORS["EMPTY"], "width": 3}))
    fig.add_trace(go.Scatter(x=sim["minutes"], y=sim["failing_with_plan"], name="with AI rebalancing plan",
                             mode="lines", line={"color": STATE_COLORS["HIGH"], "width": 3}, fill="tonexty",
                             fillcolor="rgba(68,175,105,0.12)"))
    fig.update_xaxes(title="minutes from now")
    fig.update_yaxes(title="stations empty or full", rangemode="tozero")
    saved = sim["failing_no_plan"].sum() - sim["failing_with_plan"].sum()
    return theme(fig, f"The plan avoids ~{saved * 5 / 60:.0f} station-hours of failure over the next 2 hours",
                 "Simulation: current net flows projected forward with and without the moves")


def route_map(m: pd.DataFrame, stops: pd.DataFrame, depot: tuple, km: float, moved: int) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scattermap(lat=m["lat"], lon=m["lon"], mode="markers", name="stations",
                                marker={"size": 7, "color": [STATE_COLORS.get(s, "#999") for s in m["state_now"]]},
                                text=m["name"], hovertemplate="%{text}<extra></extra>"))
    lat = [depot[0]] + list(stops["lat"])
    lon = [depot[1]] + list(stops["lon"])
    fig.add_trace(go.Scattermap(lat=lat, lon=lon, mode="lines", line={"width": 3, "color": "#222"}, name="van route",
                                hoverinfo="skip"))
    pick = stops[stops["action"] == "pick"]
    drop = stops[stops["action"] == "drop"]
    for d, colr, label in ((pick, STATE_COLORS["HIGH"], "pick up"), (drop, STATE_COLORS["EMPTY"], "drop off")):
        fig.add_trace(go.Scattermap(lat=d["lat"], lon=d["lon"], mode="markers+text", name=label,
                                    marker={"size": 20, "color": colr}, text=d["seq"].astype(str),
                                    textfont={"color": "white", "size": 11},
                                    customdata=np.stack([d["name"], d["qty"]], axis=1),
                                    hovertemplate="#%{text} " + label + " %{customdata[1]} at %{customdata[0]}<extra></extra>"))
    fig.add_trace(go.Scattermap(lat=[depot[0]], lon=[depot[1]], mode="markers", name="depot (start)",
                                marker={"size": 14, "color": "#222"}))
    theme(fig, f"AI rebalancing route: {moved} vehicles moved, {len(stops)} stops, ~{km:.1f} km",
          "Green = pick up surplus, red = drop at starving stations; numbers = stop order", 600)
    _map_layout(fig, 12)
    return fig


def battery_hist(rng: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    for t, g in rng.groupby("vehicle_type_id"):
        fig.add_trace(go.Histogram(x=g["current_range_meters"] / 1000, name=TYPE_LABELS.get(t, t),
                                   marker_color=TYPE_COLORS.get(t), opacity=0.75, nbinsx=25))
    fig.add_vline(x=10, line_dash="dash", line_color=STATE_COLORS["EMPTY"], annotation_text="swap threshold 10 km")
    fig.update_layout(barmode="overlay")
    fig.update_xaxes(title="remaining range (km)")
    n = int((rng["current_range_meters"] < 10000).sum())
    return theme(fig, f"{n} powered vehicles are below 10 km range — battery swap list",
                 "Remaining range of e-bikes and e-scooters")


def hour_profile(prof: pd.DataFrame) -> go.Figure:
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Bar(x=prof.index, y=prof["empty"], name="avg empty stations",
                         marker_color=STATE_COLORS["EMPTY"], opacity=0.6), secondary_y=True)
    fig.add_trace(go.Scatter(x=prof.index, y=prof["bikes"], name="avg docked vehicles", mode="lines+markers",
                             line={"color": "#3f88c5", "width": 3}), secondary_y=False)
    fig.update_xaxes(title="hour of day (Europe/London)", dtick=1)
    worst = int(prof["empty"].idxmax())
    return theme(fig, f"Daily rhythm: failures peak around {worst:02d}:00", "Average by hour of day across all days")


def series_with_points(s: pd.Series, cps: list, title: str, subtitle: str) -> go.Figure:
    fig = go.Figure(go.Scatter(x=s.index, y=s.values, mode="lines", line={"color": "#3f88c5", "width": 2}))
    for c in cps:
        fig.add_vline(x=c, line_color=STATE_COLORS["EMPTY"], line_dash="dash")
    return theme(fig, title, subtitle)


def calibration(prob: np.ndarray, y: np.ndarray, brier: float, brier_base: float) -> go.Figure:
    bins = np.linspace(0, 1, 11)
    idx = np.clip(np.digitize(prob, bins) - 1, 0, 9)
    xs, ys, ns = [], [], []
    for b in range(10):
        sel = idx == b
        if sel.sum() >= 5:
            xs.append(prob[sel].mean()); ys.append(y[sel].mean()); ns.append(int(sel.sum()))
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=[0, 1], y=[0, 1], mode="lines", line={"dash": "dash", "color": "#999"}, name="perfect"))
    fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines+markers", marker={"size": [6 + n ** 0.5 for n in ns]},
                             line={"color": "#6c3483", "width": 3}, name="model"))
    fig.update_xaxes(title="predicted P(empty/full in 30 min)", range=[0, 1])
    fig.update_yaxes(title="observed frequency", range=[0, 1])
    return theme(fig, f"Failure forecast beats persistence: Brier {brier:.3f} vs {brier_base:.3f}",
                 "Calibration of the 30-minute failure classifier on held-out (later) data")
