"""Charts for the Bako dashboard (Altair, drawn by Streamlit).

Colour rules, the same everywhere:
  green = good / success       amber = slow, answered but over the limit / a warning       red = failed
Cost and hours charts are not about success or failure, so they use the theme's neutral colours.
Every tooltip names what it shows ("Day", "Requests", "Cost"), never a raw column name.
"""
import altair as alt
import pandas as pd

GREEN, AMBER, RED = "#2E8B57", "#E0A31B", "#C2412D"
KINDS = ["Good", "Slow", "Failed (5xx)"]
KIND_COLORS = [GREEN, AMBER, RED]


def _axes(T):
    x = alt.Axis(labelColor=T["muted"], domain=False, ticks=False, labelAngle=0, labelPadding=6)
    y = alt.Axis(labelColor=T["muted"], gridColor=T["border"], domain=False, ticks=False, tickCount=4)
    return x, y


def _finish(chart, T, height):
    return (chart.properties(height=height)
            .configure_view(strokeWidth=0)
            .configure(background="transparent")
            .configure_legend(labelColor=T["ink"], labelFontSize=12, symbolType="circle", orient="bottom", title=None))


def requests_per_day(days, T, height=230):
    """Stacked bars per day: good (green), slow (amber), failed 5xx (red). days = newest-first daily dicts."""
    rows = []
    for d in reversed(days):
        for i, (kind, key) in enumerate(zip(KINDS, ("good", "slow", "status_5xx"))):
            rows.append({"Day": d["day"][5:], "Type": kind, "Requests": int(d.get(key, 0)), "_o": i})
    df = pd.DataFrame(rows)
    xa, ya = _axes(T)
    chart = alt.Chart(df).mark_bar(size=28, cornerRadius=3).encode(
        x=alt.X("Day:N", title=None, axis=xa, sort=None),
        y=alt.Y("Requests:Q", title=None, axis=ya),
        color=alt.Color("Type:N", scale=alt.Scale(domain=KINDS, range=KIND_COLORS)),
        order=alt.Order("_o:Q", sort="ascending"),
        tooltip=[alt.Tooltip("Day:N", title="Day"), alt.Tooltip("Type:N", title="Type"),
                 alt.Tooltip("Requests:Q", title="Requests")])
    return _finish(chart, T, height)


def cost_per_day(rows, T, height=240):
    """Grouped bars per day: estimated from lab hours next to the real AWS number."""
    data = []
    for r in reversed(rows):
        data.append({"Day": r["date"][5:], "Series": "Estimated", "Cost ($)": round(float(r["est_cost"]), 2)})
        if r["aws_cost"] is not None:
            data.append({"Day": r["date"][5:], "Series": "AWS actual", "Cost ($)": round(float(r["aws_cost"]), 2)})
    df = pd.DataFrame(data)
    xa, ya = _axes(T)
    chart = alt.Chart(df).mark_bar(cornerRadiusTopLeft=6, cornerRadiusTopRight=6).encode(
        x=alt.X("Day:N", title=None, axis=xa, sort=None),
        xOffset=alt.XOffset("Series:N"),
        y=alt.Y("Cost ($):Q", title=None, axis=ya),
        color=alt.Color("Series:N", scale=alt.Scale(domain=["Estimated", "AWS actual"], range=[T["dashB"], T["ink"]])),
        tooltip=[alt.Tooltip("Day:N", title="Day"), alt.Tooltip("Series:N", title="Kind of number"),
                 alt.Tooltip("Cost ($):Q", title="Cost in dollars", format=".2f")])
    return _finish(chart, T, height)


def lab_hours_per_day(rows, T, height=200):
    df = pd.DataFrame([{"Day": r["date"][5:], "Lab ran (hours)": round(r["seconds"] / 3600, 2)} for r in reversed(rows)])
    xa, ya = _axes(T)
    chart = alt.Chart(df).mark_bar(cornerRadiusTopLeft=8, cornerRadiusTopRight=8, color=T["lime"], size=26).encode(
        x=alt.X("Day:N", title=None, axis=xa, sort=None),
        y=alt.Y("Lab ran (hours):Q", title=None, axis=ya),
        tooltip=[alt.Tooltip("Day:N", title="Day"), alt.Tooltip("Lab ran (hours):Q", title="Lab ran, hours", format=".1f")])
    return _finish(chart, T, height)


def month_running_total(rows, budget, T, height=200):
    """Running total of money counted so far (real AWS number when known, else the estimate), with the budget as a line."""
    run, data = 0.0, []
    for r in reversed(rows):
        run += float(r["aws_cost"] if r["aws_cost"] is not None else r["est_cost"])
        data.append({"Day": r["date"][5:], "Running total ($)": round(run, 2)})
    df = pd.DataFrame(data)
    xa, ya = _axes(T)
    line = alt.Chart(df).mark_area(line={"color": T["ink"], "strokeWidth": 2}, color=T["dashB"], opacity=0.45,
                                   interpolate="monotone").encode(
        x=alt.X("Day:N", title=None, axis=xa, sort=None),
        y=alt.Y("Running total ($):Q", title=None, axis=ya),
        tooltip=[alt.Tooltip("Day:N", title="Up to day"), alt.Tooltip("Running total ($):Q", title="Total so far, dollars", format=".2f")])
    layers = [line]
    if budget and budget > 0:
        layers.append(alt.Chart(pd.DataFrame({"y": [budget]})).mark_rule(color=RED, strokeDash=[5, 4]).encode(y="y:Q"))
    return _finish(alt.layer(*layers), T, height)


def donut(value_pct, T, color=GREEN, size=150):
    """One ring: share of good requests. Returns an Altair chart; the number in the middle is added by the caller."""
    v = max(0.0, min(100.0, float(value_pct)))
    df = pd.DataFrame({"Part": ["Good", "Not good"], "Share (%)": [v, 100 - v]})
    ch = alt.Chart(df).mark_arc(innerRadius=size * 0.34, outerRadius=size * 0.5, cornerRadius=6).encode(
        theta=alt.Theta("Share (%):Q", stack=True),
        color=alt.Color("Part:N", scale=alt.Scale(domain=["Good", "Not good"], range=[color, T["soft"]]), legend=None),
        tooltip=[alt.Tooltip("Part:N", title="Requests"), alt.Tooltip("Share (%):Q", title="Share, percent", format=".2f")])
    return ch.properties(width=size, height=size).configure_view(strokeWidth=0).configure(background="transparent")


## ---------------------------------------------------------------
## Observability page: charts that sit on coloured cards (dark ink on pastel, so they read in every theme)
## ---------------------------------------------------------------
INK, SOFT_INK, GRID = "#1F2420", "#4F5A53", "rgba(31,36,32,0.14)"
PASTEL = {"sage": "#CFE6D2", "sun": "#F8E6A6", "rose": "#F4CBD8", "sky": "#CBDCF4", "lilac": "#DCD2F4", "sand": "#EFE9DC"}


def _px():
    x = alt.Axis(labelColor=SOFT_INK, domain=False, ticks=False, labelAngle=0, labelPadding=6, labelFontSize=11)
    y = alt.Axis(labelColor=SOFT_INK, gridColor=GRID, domain=False, ticks=False, tickCount=4, labelFontSize=11)
    return x, y


def _pfinish(chart, height, legend=True):
    c = (chart.properties(height=height).configure_view(strokeWidth=0).configure(background="transparent")
         .configure_legend(labelColor=INK, labelFontSize=12, symbolType="circle", orient="bottom", title=None))
    return c


def spark(values, color=INK, height=54):
    """Tiny line under a big number. No axes, no legend."""
    df = pd.DataFrame({"i": list(range(len(values))), "v": values})
    ch = alt.Chart(df).mark_area(line={"color": color, "strokeWidth": 2}, color=color, opacity=0.18, interpolate="monotone").encode(
        x=alt.X("i:Q", axis=None), y=alt.Y("v:Q", axis=None, scale=alt.Scale(zero=True)), tooltip=alt.value(None))
    return ch.properties(height=height).configure_view(strokeWidth=0).configure(background="transparent")


def timeline(buckets, height=240, unit="Hour"):
    """buckets: [{label, n, slow, e5}] -> stacked bars good / slow / failed."""
    rows = []
    for b in buckets:
        good = max(0, b["n"] - b["slow"] - b["e5"])
        for i, (k, v) in enumerate(zip(KINDS, (good, b["slow"], b["e5"]))):
            rows.append({unit: b["label"], "Type": k, "Requests": int(v), "_o": i})
    df = pd.DataFrame(rows)
    order = [b["label"] for b in buckets]
    xa, ya = _px()
    ch = alt.Chart(df).mark_bar(size=14 if len(order) > 12 else 30, cornerRadius=3).encode(
        x=alt.X(f"{unit}:N", title=None, axis=xa, sort=order),
        y=alt.Y("Requests:Q", title=None, axis=ya),
        color=alt.Color("Type:N", scale=alt.Scale(domain=KINDS, range=KIND_COLORS)),
        order=alt.Order("_o:Q", sort="ascending"),
        tooltip=[alt.Tooltip(f"{unit}:N", title=unit), alt.Tooltip("Type:N", title="Type"), alt.Tooltip("Requests:Q", title="Requests")])
    return _pfinish(ch, height)


def latency_lines(buckets, slow_ms, height=240, unit="Hour"):
    """buckets: [{label, p50, p95}] -> two lines and the limit as a dashed line."""
    rows = []
    for b in buckets:
        for k, key in (("p50 (typical)", "p50"), ("p95 (slow end)", "p95")):
            if b.get(key) is not None:
                rows.append({unit: b["label"], "Line": k, "Milliseconds": int(b[key])})
    if not rows:
        return None
    df = pd.DataFrame(rows)
    order = [b["label"] for b in buckets]
    xa, ya = _px()
    base = alt.Chart(df).encode(x=alt.X(f"{unit}:N", title=None, axis=xa, sort=order),
                                y=alt.Y("Milliseconds:Q", title=None, axis=ya, scale=alt.Scale(domainMin=0)),
                                color=alt.Color("Line:N", scale=alt.Scale(domain=["p50 (typical)", "p95 (slow end)"], range=[INK, "#7B5BD6"])),
                                tooltip=[alt.Tooltip(f"{unit}:N", title=unit), alt.Tooltip("Line:N", title="Line"),
                                         alt.Tooltip("Milliseconds:Q", title="Time, ms")])
    lines = base.mark_line(strokeWidth=2.5, point=alt.OverlayMarkDef(size=60, filled=True), interpolate="monotone")
    limit = alt.Chart(pd.DataFrame({"y": [slow_ms]})).mark_rule(color=AMBER, strokeDash=[5, 4], strokeWidth=2).encode(y="y:Q")
    return _pfinish(alt.layer(lines, limit), height)


def donut_center(good, slow, failed, size=170):
    """Ring split into good / slow / failed, same colours as everywhere. The good share in the middle."""
    tot = max(1, good + slow + failed)
    df = pd.DataFrame({"Type": KINDS, "Requests": [good, slow, failed], "Share (%)": [100.0 * v / tot for v in (good, slow, failed)],
                       "_o": [0, 1, 2]})
    arc = alt.Chart(df).mark_arc(innerRadius=size * 0.30, outerRadius=size * 0.44, padAngle=0.01 if (slow or failed) else 0).encode(
        theta=alt.Theta("Requests:Q", stack=True),
        color=alt.Color("Type:N", scale=alt.Scale(domain=KINDS, range=KIND_COLORS), legend=None),
        order=alt.Order("_o:Q", sort="ascending"),
        tooltip=[alt.Tooltip("Type:N", title="Type"), alt.Tooltip("Requests:Q", title="Requests"),
                 alt.Tooltip("Share (%):Q", title="Share, percent", format=".1f")])
    txt = alt.Chart(pd.DataFrame({"t": [f"{100.0 * good / tot:.1f}%"]})).mark_text(fontSize=22, fontWeight=500, color=INK).encode(text="t:N")
    return (alt.layer(arc, txt).properties(width=size, height=size)
            .configure_view(strokeWidth=0).configure(background="transparent"))


def hbars(rows, height=None):
    """rows: [{name, good, slow, e5}] -> horizontal stacked bars, biggest first (requests per endpoint)."""
    data = []
    for r in rows:
        for i, (k, v) in enumerate(zip(KINDS, (r["good"], r["slow"], r["e5"]))):
            data.append({"Endpoint": r["name"], "Type": k, "Requests": int(v), "_o": i})
    df = pd.DataFrame(data)
    order = [r["name"] for r in rows]
    xa, ya = _px()
    ch = alt.Chart(df).mark_bar(size=16, cornerRadius=3).encode(
        y=alt.Y("Endpoint:N", title=None, sort=order, axis=alt.Axis(labelColor=INK, labelLimit=230, domain=False, ticks=False, labelFontSize=12)),
        x=alt.X("Requests:Q", title=None, axis=ya),
        color=alt.Color("Type:N", scale=alt.Scale(domain=KINDS, range=KIND_COLORS)),
        order=alt.Order("_o:Q", sort="ascending"),
        tooltip=[alt.Tooltip("Endpoint:N", title="Endpoint"), alt.Tooltip("Type:N", title="Type"), alt.Tooltip("Requests:Q", title="Requests")])
    return _pfinish(ch, height or max(80, 34 * len(order) + 16))


def failure_bars(rows, height=None):
    """rows: [{name, n, color}] -> one bar per kind of failure (502, 504, slow...)."""
    df = pd.DataFrame([{"Kind": r["name"], "Requests": int(r["n"]), "_c": r["color"]} for r in rows])
    order = [r["name"] for r in rows]
    xa, ya = _px()
    ch = alt.Chart(df).mark_bar(size=18, cornerRadius=4).encode(
        y=alt.Y("Kind:N", title=None, sort=order, axis=alt.Axis(labelColor=INK, domain=False, ticks=False, labelFontSize=12, labelLimit=150)),
        x=alt.X("Requests:Q", title=None, axis=ya),
        color=alt.Color("_c:N", scale=None),
        tooltip=[alt.Tooltip("Kind:N", title="Kind"), alt.Tooltip("Requests:Q", title="Requests")])
    return _pfinish(ch, height or max(70, 38 * len(order) + 14))


def trouble_timeline(buckets, height=230, unit="Day"):
    """Only the problems: slow (amber) and failed (red) per bucket, so the bad days stand out. Tooltip also gives the share."""
    rows = []
    for b in buckets:
        for i, (k, v) in enumerate((("Slow", b["slow"]), ("Failed (5xx)", b["e5"]))):
            share = round(100.0 * v / b["n"], 1) if b["n"] else 0.0
            rows.append({unit: b["label"], "Type": k, "Requests": int(v), "Share (%)": share,
                         "All requests": int(b["n"]), "_o": i})
    df = pd.DataFrame(rows)
    order = [b["label"] for b in buckets]
    xa, ya = _px()
    ch = alt.Chart(df).mark_bar(size=34 if len(order) <= 12 else 14, cornerRadius=3).encode(
        x=alt.X(f"{unit}:N", title=None, axis=xa, sort=order),
        y=alt.Y("Requests:Q", title=None, axis=ya, scale=alt.Scale(domainMin=0, nice=True)),
        color=alt.Color("Type:N", scale=alt.Scale(domain=["Slow", "Failed (5xx)"], range=[AMBER, RED])),
        order=alt.Order("_o:Q", sort="ascending"),
        tooltip=[alt.Tooltip(f"{unit}:N", title=unit), alt.Tooltip("Type:N", title="Type"),
                 alt.Tooltip("Requests:Q", title="Requests"),
                 alt.Tooltip("Share (%):Q", title="Share of requests, %", format=".1f"),
                 alt.Tooltip("All requests:Q", title="All requests in that bar")])
    return _pfinish(ch, height)


## ---------------------------------------------------------------
## Backend and Database tabs
## ---------------------------------------------------------------
def usage_bars(rows, height=None):
    """rows: [{name, pct, label}] -> horizontal bars of how full a limit is. green under 70, amber under 90, red from 90."""
    df = pd.DataFrame([{"Pod": r["name"], "Used (%)": round(r["pct"], 1), "Detail": r["label"],
                        "_c": GREEN if r["pct"] < 70 else AMBER if r["pct"] < 90 else RED} for r in rows])
    order = [r["name"] for r in rows]
    xa, ya = _px()
    ch = alt.Chart(df).mark_bar(size=16, cornerRadius=4).encode(
        y=alt.Y("Pod:N", title=None, sort=order, axis=alt.Axis(labelColor=INK, labelLimit=200, domain=False, ticks=False, labelFontSize=12)),
        x=alt.X("Used (%):Q", title=None, axis=ya, scale=alt.Scale(domain=[0, 100])),
        color=alt.Color("_c:N", scale=None),
        tooltip=[alt.Tooltip("Pod:N", title="Pod"), alt.Tooltip("Detail:N", title="Used"), alt.Tooltip("Used (%):Q", title="Share of the limit, %")])
    return _pfinish(ch, height or max(70, 34 * len(order) + 14))


def size_bars(tables, height=None):
    """tables: [{name, table_bytes, index_bytes}] -> stacked horizontal bars in MB: the data, and its indexes."""
    data = []
    for t in tables:
        data.append({"Table": t["name"], "Part": "Data", "MB": round(t["table_bytes"] / 1048576, 3)})
        data.append({"Table": t["name"], "Part": "Indexes", "MB": round(t["index_bytes"] / 1048576, 3)})
    df = pd.DataFrame(data)
    order = [t["name"] for t in tables]
    xa, ya = _px()
    ch = alt.Chart(df).mark_bar(size=16, cornerRadius=3).encode(
        y=alt.Y("Table:N", title=None, sort=order, axis=alt.Axis(labelColor=INK, labelLimit=200, domain=False, ticks=False, labelFontSize=12)),
        x=alt.X("MB:Q", title=None, axis=ya),
        color=alt.Color("Part:N", scale=alt.Scale(domain=["Data", "Indexes"], range=["#5B7DB1", "#B7C6E0"])),
        tooltip=[alt.Tooltip("Table:N", title="Table"), alt.Tooltip("Part:N", title="Part"), alt.Tooltip("MB:Q", title="Size, MB", format=".2f")])
    return _pfinish(ch, height or max(80, 34 * len(order) + 30))


def series_lines(rows, xname="Time", yname="Value", colors=None, height=200, zero=True, temporal=False):
    """rows: [{x, y, series}] -> one or more lines with named tooltips."""
    if not rows:
        return None
    df = pd.DataFrame([{xname: r["x"], yname: r["y"], "Line": r.get("series", "")} for r in rows])
    if temporal:
        df[xname] = pd.to_datetime(df[xname])
    order = list(dict.fromkeys(df[xname]))
    series = list(dict.fromkeys(df["Line"]))
    xa, ya = _px()
    xa = alt.Axis(labelColor=SOFT_INK, domain=False, ticks=False, labelAngle=0, labelPadding=6, labelFontSize=11, labelOverlap="greedy")
    if temporal:
        xa = alt.Axis(labelColor=SOFT_INK, domain=False, ticks=False, labelAngle=0, labelFontSize=11, format="%m-%d", tickCount=3)
    enc = dict(x=alt.X(f"{xname}:T", title=None, axis=xa) if temporal else alt.X(f"{xname}:N", title=None, axis=xa, sort=order),
               y=alt.Y(f"{yname}:Q", title=None, axis=ya, scale=alt.Scale(zero=zero)),
               tooltip=[alt.Tooltip(f"{xname}:T", title=xname, format="%m-%d %H:%M") if temporal else alt.Tooltip(f"{xname}:N", title=xname),
                        alt.Tooltip("Line:N", title="Line"), alt.Tooltip(f"{yname}:Q", title=yname, format=",.2f")])
    dots = alt.OverlayMarkDef(size=45, filled=True) if len(df) <= 40 else False
    if len(series) > 1 or series[0]:
        enc["color"] = alt.Color("Line:N", scale=alt.Scale(domain=series, range=(colors or ["#1F2420", "#7B5BD6", "#2E8B57", "#E0A31B"])[:len(series)]))
        line = alt.Chart(df).mark_line(strokeWidth=2.5, point=dots, interpolate="monotone").encode(**enc)
    else:
        line = alt.Chart(df).mark_line(strokeWidth=2.5, color="#1F2420", point=(alt.OverlayMarkDef(size=45, filled=True, color="#1F2420") if dots else False), interpolate="monotone").encode(**enc)
    return _pfinish(line, height)


## ---------------------------------------------------------------
## Traces: where the time of a request goes
## Part colours are NOT the good/slow/failed colours: a part of a request is not good or bad by itself.
## ---------------------------------------------------------------
PART_NAMES = ["database", "password check", "outside calls", "other code"]
PART_COLORS = ["#7B5BD6", "#D0785A", "#3E8FB0", "#B9BFB5"]


def time_split_bars(rows, height=None):
    """rows: [{name, database, password check, outside calls, other code}] (average ms per request) -> stacked horizontal bars, one per endpoint."""
    data = []
    for r in rows:
        for i, k in enumerate(PART_NAMES):
            data.append({"Endpoint": r["name"], "Part": k, "Milliseconds": round(float(r.get(k, 0)), 1), "_o": i})
    df = pd.DataFrame(data)
    order = [r["name"] for r in rows]
    xa, ya = _px()
    ch = alt.Chart(df).mark_bar(size=18, cornerRadius=3).encode(
        y=alt.Y("Endpoint:N", title=None, sort=order, axis=alt.Axis(labelColor=INK, labelLimit=230, domain=False, ticks=False, labelFontSize=12)),
        x=alt.X("Milliseconds:Q", title=None, axis=ya),
        color=alt.Color("Part:N", scale=alt.Scale(domain=PART_NAMES, range=PART_COLORS)),
        order=alt.Order("_o:Q", sort="ascending"),
        tooltip=[alt.Tooltip("Endpoint:N", title="Endpoint"), alt.Tooltip("Part:N", title="Part"), alt.Tooltip("Milliseconds:Q", title="Average ms", format=",.1f")])
    return _pfinish(ch, height or max(90, 38 * len(order) + 20))


def waterfall(spans, total_ms, height=None):
    """spans: [{name, kind, start_ms, ms, depth}] of ONE request -> bars along a time axis, in the order the steps began."""
    rows = [{"Step": f"{'· ' * s.get('depth', 0)}{s['name']}", "Part": s["kind"], "Start (ms)": s["start_ms"], "End (ms)": round(s["start_ms"] + max(s["ms"], 0.3), 2),
             "Took (ms)": s["ms"], "_i": i} for i, s in enumerate(spans)]
    if not rows:
        return None
    df = pd.DataFrame(rows)
    order = list(df["Step"])
    xa, ya = _px()
    ch = alt.Chart(df).mark_bar(size=14, cornerRadius=2).encode(
        y=alt.Y("Step:N", title=None, sort=order, axis=alt.Axis(labelColor=INK, labelLimit=260, domain=False, ticks=False, labelFontSize=11)),
        x=alt.X("Start (ms):Q", title=None, axis=ya, scale=alt.Scale(domain=[0, max(total_ms, 1)])),
        x2="End (ms):Q",
        color=alt.Color("Part:N", scale=alt.Scale(domain=PART_NAMES, range=PART_COLORS)),
        tooltip=[alt.Tooltip("Step:N", title="Step"), alt.Tooltip("Part:N", title="Part"), alt.Tooltip("Start (ms):Q", title="Began at (ms)", format=",.1f"),
                 alt.Tooltip("Took (ms):Q", title="Took (ms)", format=",.1f")])
    return _pfinish(ch, height or max(130, 34 * len(rows) + 40))
