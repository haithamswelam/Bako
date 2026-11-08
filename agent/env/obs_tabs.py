"""Observability tabs that look INSIDE the app: Backend pod, Database, Traces, SLO and budget.

Live facts come from obs_data (kubectl, a read-only database pod, AWS). They are read only when you press the button, never while you
look at another tab, and the last answer is kept in a file so a refresh does not lose it. History comes from the daily summaries
saved at STOP, because the pods and the database are gone every morning.
"""
import html
import json
import os
import time
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

import charts
import obs_data
import obs_traces
import sli
import sre


def _esc(x):
    return html.escape(str(x))


def _title(t, s=""):
    st.markdown(f"<div class='obs-t'>{_esc(t)}</div>" + (f"<div class='obs-s'>{_esc(s)}</div>" if s else ""), unsafe_allow_html=True)


def _kpi(key, label, value, note):
    with st.container(key=key):
        small = " style='font-size:" + ("21px" if len(str(value)) > 12 else "26px") + ";word-break:normal'" if len(str(value)) > 8 else ""
        st.markdown(f"<div class='kc'><div class='l'>{_esc(label)}</div><div class='v'{small}>{_esc(value)}</div><div class='n'>{_esc(note)}</div></div>",
                    unsafe_allow_html=True)


def _table(head, rows, right=()):
    h = "".join(f"<th{' class=n' if i in right else ''}>{_esc(c)}</th>" for i, c in enumerate(head))
    b = "".join("<tr style='white-space:nowrap'>" + "".join(f"<td{' class=n' if i in right else ''}>{c if isinstance(c, _Raw) else _esc(c)}</td>"
                                                           for i, c in enumerate(r)) + "</tr>" for r in rows)
    st.markdown(f"<div style='overflow-x:auto'><table class='rtable'>{h and '<tr>' + h + '</tr>'}{b}</table></div>", unsafe_allow_html=True)


class _Raw(str):
    pass


def _note(text):
    st.markdown(f"<div class='obs-s' style='margin:0 0 10px'>{_esc(text)}</div>", unsafe_allow_html=True)


def _last_path(ctx, name):
    return os.path.join(ctx["reports"], f"obs-{name}-last.json")


def _load_last(ctx, name):
    try:
        with open(_last_path(ctx, name), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _save_last(ctx, name, data):
    try:
        os.makedirs(ctx["reports"], exist_ok=True)
        with open(_last_path(ctx, name), "w", encoding="utf-8") as fh:
            json.dump(data, fh, separators=(",", ":"))
    except OSError:
        pass


def _age(at):
    try:
        t = datetime.strptime(at, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        m = int((datetime.now(timezone.utc) - t).total_seconds() // 60)
        return "just now" if m < 1 else f"{m} min ago" if m < 120 else f"{m // 60} h ago"
    except (ValueError, TypeError):
        return ""


def _history(ctx):
    ss = ctx["ss"]
    if "obs_hist" not in ss:
        ss.obs_hist = obs_data.read_daily(ctx["store"]) if ctx["aws_ok"] else ([], "The AWS command line was not found.")
    return ss.obs_hist[0]


## ---------------------------------------------------------------
## BACKEND POD
## ---------------------------------------------------------------
def backend_tab(ctx):
    ss = ctx["ss"]
    ctx["page_note"]("what the backend and frontend pods are doing: are they up, restarting, running out of memory, logging errors. Live facts exist only while the lab is up; history comes from the facts saved at every STOP.")
    c1, c2 = st.columns([1.2, 3], vertical_alignment="center")
    with c1:
        pressed = st.button("Read the pods now", key="obs_read_backend", use_container_width=True, type="primary")
    if pressed:
        with st.spinner("Asking the cluster..."):
            f, why = obs_data.backend_live(ctx["kubectl"], ctx["env"], ctx["account"])
        ss.obs_backend_why = why
        if f:
            ss.obs_backend = f
            _save_last(ctx, "backend", f)
    f = ss.get("obs_backend") or _load_last(ctx, "backend")
    with c2:
        if ss.get("obs_backend_why"):
            st.caption(ss.obs_backend_why + (" Showing the last reading below." if f else ""))
        elif f:
            st.caption(f"Read {_age(f['at'])} ({f['at']} UTC). Press the button to read again.")
        else:
            st.caption("Not read yet in this installation. Start the lab, then press the button.")

    if f:
        pods, tops = f["pods"], f.get("top", {})
        total_restarts = sum(p["restarts"] for p in pods)
        ready = sum(1 for p in pods if p["phase"] == "Running" and p["ready"].split("/")[0] == p["ready"].split("/")[1])
        errs = sum(s["errors"] for s in f["logs"].values()); warns = sum(s["warnings"] for s in f["logs"].values())
        lasts = [p["last_end"] for p in pods if p["last_end"]]
        k = st.columns(4, gap="small")
        with k[0]:
            _kpi("kcs_b1", "Pods ready", f"{ready}/{len(pods)}", "running and passing their checks")
        with k[1]:
            _kpi("kcr_b2", "Restarts", str(total_restarts), ("last end: " + lasts[0]) if lasts else "no pod has been restarted")
        with k[2]:
            _kpi("kcy_b3", "Errors, last hour", str(errs), f"{warns} warnings in the logs")
        mem = sum(v["mem_mi"] or 0 for v in tops.values()) if tops else None
        with k[3]:
            _kpi("kcb_b4", "Memory in use", f"{mem:.0f} MB" if mem is not None else "-", "all pods together" if tops else "no metrics-server")
        st.write("")

        with st.container(key="otc_b_pods"):
            _title("Pods", "one row per pod. Restarts and 'last ended' show crashes; memory is compared with the pod's limit.")
            rows, bars = [], []
            for p in pods:
                t_ = tops.get(p["name"], {})
                lim = obs_data._mem_mi(p.get("mem_lim"))
                mem_txt = "-" if not t_ else (f"{t_['mem_mi']:.0f} / {lim:.0f} MB" if lim else f"{t_['mem_mi']:.0f} MB (no limit)")
                if t_ and lim:
                    bars.append({"name": p["name"], "pct": 100 * t_["mem_mi"] / lim, "label": mem_txt})
                rows.append([p["name"], p["ready"], p["restarts"], p["last_end"] or "-", f"{t_['cpu_m']:.0f} m" if t_ else "-", mem_txt])
            _table(["Pod", "Ready", "Restarts", "Last ended", "CPU", "Memory"], rows, right=(1, 2))
            if bars:
                _note("Memory as a share of each pod's limit (green under 70, amber under 90, red from 90):")
                st.altair_chart(charts.usage_bars(bars), use_container_width=True, theme=None)
            elif f.get("top_why"):
                st.caption(f["top_why"])
        st.write("")

        with st.container(key="otc_b_dep"):
            _title("Deployments", "how many copies should run, and how many do")
            _table(["Deployment", "Ready", "Wanted", "Updated", "Image"], [[d["name"], d["ready"], d["want"], d["updated"], d["image"]] for d in f["deployments"]], right=(1, 2, 3))
        st.write("")

        with st.container(key="otc_b_log"):
            _title("Problems in the logs", "last hour. Each message is reduced to its shape (numbers, ids, text in quotes and addresses removed), so nothing a person typed shows here.")
            shown = []
            for app, sc in f["logs"].items():
                http = ", ".join(f"{n} {k}" for k, n in sorted(sc["http"].items())) or "no access lines"
                _note(f"{app}: {sc['lines']} lines read, {sc['errors']} errors, {sc['warnings']} warnings. The backend's own count of answers: {http}." + (f" ({sc['why']})" if sc.get("why") else ""))
                for t in sc["top"]:
                    shown.append([app, t["level"], t["n"], t["shape"]])
            if shown:
                _table(["App", "Level", "Times", "What it said (shape)"], shown, right=(2,))
                if st.button("Ask Bako what the top problem means", key="obs_ask_logs"):
                    top = shown[0]
                    ss.obs_asked = f"{top[0]} log: {top[3][:60]}"
                    ctx["ask"](f"Troubleshoot a problem in the Bako {top[0]} logs. It appeared {top[2]} times in the last hour. Shape of the log line (numbers, ids and text were removed): {top[3]}\n"
                               "What does it most likely mean, and which exact command or file should I look at first?",
                               f"Troubleshoot: {top[0]} log, {top[2]} times: {top[3][:80]}")
            else:
                st.markdown("<div style='padding:20px 0;text-align:center;opacity:.75'>No errors or warnings in the last hour.</div>", unsafe_allow_html=True)
        st.write("")
        if ctx.get("answer_card"):
            ctx["answer_card"]("obs_c11")
            st.write("")

        if f["events"]:
            with st.container(key="otc_b_ev"):
                _title("Warnings from the cluster", "Kubernetes events: things like failed health checks, pods that could not start, out-of-memory kills")
                _table(["When (UTC)", "Reason", "Object", "Times", "Message (shape)"], [[e["when"].replace("T", " "), e["reason"], e["object"], e["n"], e["message"]] for e in f["events"]], right=(3,))
            st.write("")

    hist = _history(ctx)
    with st.container(key="otc_b_hist"):
        _title("History, one point per day", "saved at every STOP, so it survives the nightly teardown")
        rows = [d for d in hist if d.get("backend")]
        if not rows:
            st.markdown("<div style='padding:24px 0;text-align:center;opacity:.75'>Nothing saved yet. The first point appears after the next STOP.</div>", unsafe_allow_html=True)
        else:
            rows = list(reversed(rows[:30]))
            ch = charts.series_lines([{"x": d["day"][5:], "y": d["backend"]["errors"], "series": "Errors in the logs"} for d in rows]
                                     + [{"x": d["day"][5:], "y": d["backend"]["restarts"], "series": "Pod restarts"} for d in rows],
                                     xname="Day", yname="Count", colors=[charts.RED, "#7B5BD6"], height=210)
            st.altair_chart(ch, use_container_width=True, theme=None)


## ---------------------------------------------------------------
## DATABASE
## ---------------------------------------------------------------
def db_tab(ctx):
    ss = ctx["ss"]
    store, db_id = ctx["store"], ctx["db_id"]
    ctx["page_note"]("everything about the database: size, tables, structure, activity, AWS numbers and saved copies. Read-only: only structure, sizes and counts are read, never the content of a row.")
    c1, c2 = st.columns([1.2, 3], vertical_alignment="center")
    with c1:
        pressed = st.button("Read the database now", key="obs_read_db", use_container_width=True, type="primary")
    if pressed:
        with st.spinner("Reading AWS numbers, then the database through a short-lived pod (about 30 seconds)..."):
            info, why_i = obs_data.rds_info(store, db_id) if ctx["aws_ok"] else (None, "The AWS command line was not found.")
            snaps, why_s = obs_data.rds_snapshots(store, db_id) if ctx["aws_ok"] else ([], "")
            cw, why_c = obs_data.cloudwatch(store, db_id) if ctx["aws_ok"] else ({}, "")
            live, why_l = (obs_data.db_live(ctx["kubectl"], ctx["env"], ctx["account"], info["host"], info["dbname"]) if info else (None, why_i))
        data = {"at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), "info": info, "info_why": why_i, "snaps": snaps, "cw": cw, "live": live, "live_why": why_l}
        ss.obs_db = data
        if live or snaps or cw:
            _save_last(ctx, "db", data)
    d = ss.get("obs_db") or _load_last(ctx, "db")
    with c2:
        if d:
            st.caption(f"Read {_age(d['at'])} ({d['at']} UTC)." + (f" Live database: {d['live_why']}" if not d.get("live") and d.get("live_why") else " Press the button to read again."))
        else:
            st.caption("Not read yet. The AWS numbers and saved copies can be read any time; the tables need the lab to be up.")
    live = (d or {}).get("live")

    if d:
        info = d.get("info") or {}
        k = st.columns(4, gap="small")
        with k[0]:
            _kpi("kcs_d1", "Database size", obs_data.human_bytes(live["meta"]["size_bytes"]) if live else "-", f"{len(live['tables'])} tables" if live else "needs the lab up")
        with k[1]:
            rows = sum(t["rows"] for t in live["tables"]) if live else None
            _kpi("kcy_d2", "Rows in total", f"{rows:,}" if rows is not None else "-", "all tables together")
        with k[2]:
            if live:
                n = sum(live["connections"].values())
                _kpi("kcr_d3", "Connections", f"{n} / {live['meta']['max_connections']}", ", ".join(f"{v} {k_}" for k_, v in live["connections"].items()) or "none open")
            else:
                _kpi("kcr_d3", "Connections", "-", "needs the lab up")
        with k[3]:
            _kpi("kcb_d4", "Server", (info.get("class") or "-").replace("db.", ""), f"{info.get('engine', 'not running now')} · {info.get('storage_gb', '?')} GB" if info else "not running now")
        st.write("")

    if live:
        with st.container(key="otc_d_tables"):
            _title("Tables", "how big each table is (data and indexes) and how many rows it holds")
            st.altair_chart(charts.size_bars(live["tables"]), use_container_width=True, theme=None)
            _table(["Table", "Rows", "Total size", "Data", "Indexes", "Dead rows", "Last vacuum"],
                   [[t["name"], f"{t['rows']:,}", obs_data.human_bytes(t["total_bytes"]), obs_data.human_bytes(t["table_bytes"]),
                     obs_data.human_bytes(t["index_bytes"]), t["dead"], t["vacuum"] or "-"] for t in live["tables"]], right=(1, 2, 3, 4, 5))
            _note("Dead rows are old versions of rows that PostgreSQL has not cleaned up yet. A large, growing number means vacuum is falling behind.")
        st.write("")

        with st.container(key="otc_d_struct"):
            _title("Structure", "columns, indexes and rules of each table. 'Scans' = how often an index was used since the database started.")
            for t in live["tables"]:
                with st.expander(f"{t['name']} · {t['rows']:,} rows · {obs_data.human_bytes(t['total_bytes'])}"):
                    _table(["Column", "Type", "Can be empty"], [[c["name"], c["type"], "yes" if c["null"] else "no"] for c in live["columns"].get(t["name"], [])])
                    ix = live["indexes"].get(t["name"], [])
                    if ix:
                        _table(["Index", "Scans", "Size", "Definition"], [[i["name"], i["scans"], obs_data.human_bytes(i["bytes"]), i["def"].split(" USING ")[-1]] for i in ix], right=(1, 2))
                    cs = live["constraints"].get(t["name"], [])
                    if cs:
                        _table(["Rule", "Kind", "Definition"], [[c["name"], c["kind"], c["def"]] for c in cs])
        st.write("")

        with st.container(key="otc_d_stmts"):
            _title("Slowest queries", "from pg_stat_statements: the shape of each query, how often it ran and how long it took")
            if live["statements"]:
                _table(["Query (values replaced by $1, $2)", "Calls", "Average ms", "Total ms"], [[s["query"], s["calls"], s["mean_ms"], s["total_ms"]] for s in live["statements"]], right=(1, 2, 3))
            else:
                st.markdown("<div style='padding:14px 0;opacity:.8'>Per-query timing is not available: the pg_stat_statements extension is not switched on in this database. "
                            "Turning it on is a small change (a parameter group setting and one CREATE EXTENSION). We can add it later through Terraform if you want this view.</div>", unsafe_allow_html=True)
        st.write("")

    cw = (d or {}).get("cw") or {}
    if cw:
        with st.container(key="otc_d_cw"):
            _title("AWS numbers, last 72 hours", "from CloudWatch. These stay available after the nightly teardown. Hover for the exact hour.")
            lc = st.columns(3, gap="medium")
            specs = [("CPUUtilization", "CPU, %", 1), ("DatabaseConnections", "Connections (highest in the hour)", 1), ("FreeStorageSpace", "Free disk, GB", 1 / 1073741824)]
            for col, (m, label, mult) in zip(lc, specs):
                with col:
                    st.markdown(f"<div class='obs-s'>{label}</div>", unsafe_allow_html=True)
                    pts = cw.get(m) or []
                    ch = charts.series_lines([{"x": t_, "y": v * mult, "series": ""} for t_, v in pts], xname="Time (UTC)", yname=label, height=170, temporal=True)
                    if ch is None:
                        st.caption("No data points.")
                    else:
                        st.altair_chart(ch, use_container_width=True, theme=None)
        st.write("")

    if d and d.get("snaps"):
        with st.container(key="otc_d_snaps"):
            _title("Saved copies (snapshots)", "made at every STOP. The newest 3 are kept.")
            _table(["Snapshot", "Taken (UTC)", "Allocated", "State"], [[s["name"], s["at"], f"{s['gb']} GB", s["status"]] for s in d["snaps"]], right=(2,))
        st.write("")

    hist = _history(ctx)
    with st.container(key="otc_d_hist"):
        _title("Growth, one point per day", "saved at every STOP")
        rows = [x for x in hist if x.get("db")]
        if not rows:
            st.markdown("<div style='padding:24px 0;text-align:center;opacity:.75'>Nothing saved yet. The first point appears after the next STOP.</div>", unsafe_allow_html=True)
        else:
            rows = list(reversed(rows[:30]))
            g1, g2 = st.columns(2, gap="medium")
            with g1:
                st.markdown("<div class='obs-s'>Database size, MB</div>", unsafe_allow_html=True)
                st.altair_chart(charts.series_lines([{"x": x["day"][5:], "y": x["db"]["size_bytes"] / 1048576, "series": ""} for x in rows], xname="Day", yname="Size, MB", height=180),
                                use_container_width=True, theme=None)
            with g2:
                st.markdown("<div class='obs-s'>Rows per table</div>", unsafe_allow_html=True)
                pts = [{"x": x["day"][5:], "y": t["rows"], "series": t["name"]} for x in rows for t in x["db"]["tables"][:4]]
                st.altair_chart(charts.series_lines(pts, xname="Day", yname="Rows", height=180), use_container_width=True, theme=None)


## ---------------------------------------------------------------
## TRACES (not built yet: say exactly why, and what comes next)
## ---------------------------------------------------------------
def traces_tab(ctx):
    ss = ctx["ss"]
    ctx["page_note"]("a trace follows ONE request inside the app and shows how long each step took: the database, the password check, calls to other services, and everything else. "
                     "This is the part the load balancer cannot see.")
    c1, c2 = st.columns([1.2, 3], vertical_alignment="center")
    with c1:
        pressed = st.button("Read the traces now", key="obs_read_traces", use_container_width=True, type="primary")
    if pressed:
        with st.spinner("Asking the trace receiver in the cluster..."):
            f, why = obs_traces.traces_live(ctx["kubectl"], ctx["env"], ctx["account"])
        ss.obs_traces_why = why
        if f:
            ss.obs_traces = f
            _save_last(ctx, "traces", f)
    f = ss.get("obs_traces") or _load_last(ctx, "traces")
    with c2:
        if ss.get("obs_traces_why"):
            st.caption(ss.obs_traces_why + (" Showing the last reading below." if f else ""))
        elif f:
            st.caption(f"{f['n']} traces from the last {f.get('minutes', '?')} minutes, read {_age(f['at'])} ({f['at']} UTC). Press the button to read again.")
        else:
            st.caption("Not read yet. Start the lab, use the app for a minute, then press the button.")

    with st.expander("How tracing gets switched on (one time)", expanded=not f):
        st.markdown(
            "<ol class='why'>"
            "<li>Copy <b>K8s/tracing.yaml</b> into your Bako repo's K8s folder. It starts a small receiver (Jaeger, traces kept in memory, no AWS cost).</li>"
            "<li>Run <b>python patch_tracing.py</b> in the repo root. It adds four OTEL_ settings to the backend deployment and wraps the password check in a named step, "
            "so it shows up on its own instead of hiding inside 'other code'.</li>"
            "<li>Commit and push. CI builds the image, the bot opens the pull request, you merge it. Argo CD starts the receiver and the new backend.</li>"
            "<li>Use the app (log in, add something), then press <b>Read the traces now</b>.</li></ol>"
            "<div class='obs-s'>Only the backend can reach the receiver. A database step is stored as its shape only (for example <i>SELECT users</i>): never the query text or its values.</div>",
            unsafe_allow_html=True)
    st.write("")

    if f:
        eps = f["endpoints"]
        rows = []
        for ep, v in eps.items():
            k = v["kinds"]
            rows.append({"name": ep, "total": sum(k.values()), "n": v["n"], **k})
        rows.sort(key=lambda r: -r["total"])
        slowest = rows[0]
        tot_n = sum(r["n"] for r in rows) or 1
        all_parts = {p: sum(r[p] * r["n"] for r in rows) / tot_n for p in obs_traces.KINDS}
        big_p = max(all_parts, key=all_parts.get)
        share = 100.0 * all_parts[big_p] / (sum(all_parts.values()) or 1)
        topq = f["queries"][0] if f["queries"] else None
        k = st.columns(4, gap="small")
        with k[0]:
            _kpi("kcs_t1", "Traces read", str(f["n"]), f"{len(eps)} endpoints, last {f.get('minutes', '?')} min")
        with k[1]:
            _kpi("kcy_t2", "Slowest endpoint", f"{slowest['total']:.0f} ms", f"{slowest['name']} on average")
        with k[2]:
            _kpi("kcb_t3", "Biggest part of the time", big_p, f"{share:.0f}% of all request time")
        with k[3]:
            _kpi("kcr_t4", "Most time in one query", topq["stmt"] if topq else "-", f"{topq['calls']} calls, {topq['avg_ms']} ms each" if topq else "no database steps in these traces")
        st.write("")

        with st.container(key="otc_t_split"):
            _title("Where the time goes", "average milliseconds of one request, split into its parts. This is what fills the 'Database: not measured yet' box on the Overview.")
            st.altair_chart(charts.time_split_bars(rows[:10]), use_container_width=True, theme=None)
            top_ep = dict(eps[slowest["name"]], endpoint=slowest["name"])
            _note(obs_traces.explain_split(top_ep))
            _note("Other code = whatever the named steps do not explain: the app's own Python, waiting for a worker, sending the answer.")
        st.write("")

        with st.container(key="otc_t_q"):
            _title("Queries, by total time", "each database call is stored as its shape: the verb and the tables, never the text or the values. This answers 'which query takes the time'.")
            if f["queries"]:
                _table(["Query shape", "Calls", "Average ms", "Slowest ms", "Total ms"],
                       [[q["stmt"], q["calls"], q["avg_ms"], q["max_ms"], q["total_ms"]] for q in f["queries"]], right=(1, 2, 3, 4))
            else:
                st.caption("No database steps in these traces.")
        st.write("")

        with st.container(key="otc_t_one"):
            _title("One request, step by step", "the slowest requests of this reading. Each bar is one step, placed where it began.")
            sl = f["slowest"]
            def lab(i):
                t = sl[i]
                try:
                    clock = datetime.fromtimestamp(t["start_us"] / 1e6, tz=timezone.utc).strftime("%H:%M:%S")
                except (OSError, ValueError, OverflowError, TypeError):
                    clock = "?"
                return f"{t['endpoint']} · {t['total_ms']:.0f} ms · {t.get('status', '-')} · {clock} UTC"
            i = st.selectbox("Trace", range(len(sl)), format_func=lab, key="obs_trace_pick", label_visibility="collapsed")
            t = sl[i]
            ch = charts.waterfall(t["spans"], t["total_ms"])
            if ch is not None:
                st.altair_chart(ch, use_container_width=True, theme=None)
            parts = ", ".join(f"{n} {v:.0f} ms" for n, v in t["kinds"].items() if v >= 1)
            _note(f"Total {t['total_ms']:.0f} ms: {parts}.")
            if st.button("Ask Bako why this one took that long", key="obs_ask_trace"):
                label = f"{t['endpoint']} · {t['total_ms']:.0f} ms trace"
                ss.obs_asked = label
                ctx["ask"](sre.trace_question(t), "Troubleshoot: " + label)
        st.write("")
        if ctx.get("answer_card"):
            ctx["answer_card"]("obs_c10")
            st.write("")

    hist = [d for d in _history(ctx) if d.get("traces")]
    with st.container(key="otc_t_hist"):
        _title("History, one point per day", "average milliseconds per part for the busiest endpoint, saved at every STOP")
        if not hist:
            st.markdown("<div style='padding:24px 0;text-align:center;opacity:.75'>Nothing saved yet. The first point appears after the next STOP, if traces were running.</div>", unsafe_allow_html=True)
        else:
            counts = {}
            for d in hist:
                for ep, v in d["traces"]["endpoints"].items():
                    counts[ep] = counts.get(ep, 0) + v["n"]
            ep = max(counts, key=counts.get)
            days = list(reversed(hist[:30]))
            lines = []
            for d in days:
                v = d["traces"]["endpoints"].get(ep)
                if v:
                    for p in obs_traces.KINDS:
                        lines.append({"x": d["day"][5:], "y": v["kinds"].get(p, 0), "series": p})
            _note(f"Endpoint: {ep}")
            st.altair_chart(charts.series_lines(lines, xname="Day", yname="Average ms", colors=charts.PART_COLORS, height=210), use_container_width=True, theme=None)


## ---------------------------------------------------------------
## SLO AND BUDGET (a placeholder that is already useful: how far the measuring is, and what each candidate target would mean)
## ---------------------------------------------------------------
def slo_tab(ctx):
    ss = ctx["ss"]
    days = [d for d in ss.get("slo_days", []) if d.get("total", 0) > 0]
    ctx["page_note"]("the target (SLO) is chosen from real numbers, after about two weeks of measuring. Until then this tab shows how far the measuring is and what each candidate target would mean.")
    n = len(days)
    first = days[-1]["day"] if days else "-"
    with st.container(key="otc_s_prog"):
        _title("Measuring progress", "the target is not set yet")
        st.progress(min(1.0, n / 14), text=f"{n} day(s) with traffic of about 14 · first day {first}")
    if not days:
        return
    st.write("")
    w = sli.window_summary(days)
    total, bad = w["total"], w["bad"]
    per_day = total / n
    with st.container(key="otc_s_what"):
        _title("What each candidate target would mean", f"for your traffic of about {per_day:.0f} requests a day ({total} counted so far, {bad} not good)")
        rows = []
        for t in (99.0, 99.5, 99.9):
            allowed30 = (1 - t / 100) * per_day * 30
            rows.append([f"{t}%", f"{allowed30:.1f}", f"{(1 - t / 100) * 3000:.0f}", "yes" if 100 * (total - bad) / total >= t else "no"])
        _table(["Target", "Bad requests allowed in 30 days", "Allowed per 3,000 requests", "Met so far?"], rows, right=(1, 2))
        _note("Bad = a 5xx, or over 500 ms. 'Allowed' is the error budget. With only about 100 requests a day, one bad request is a large share of a day, so a very high target would trip on a single slow request. We choose after more days.")
