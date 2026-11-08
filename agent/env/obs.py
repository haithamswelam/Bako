"""The Observability view: how the Bako application is doing, seen from the outside (load balancer logs).

Everything here reads the small daily files made by sli.py. No target and no error budget yet: measure first.
Only counts, timings, method and address WITHOUT query string are shown. Nothing a person typed is ever stored.
"""
import html
import json
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

import charts
import obs_tabs
import obs_traces
import sli
import sre

CSS = """
<style>
.st-key-kc_req, .st-key-kc_bad, .st-key-kc_p50, .st-key-kc_p95, .st-key-obs_donut { border-radius: 24px; padding: 16px 20px 18px; min-height: 148px; color: #1F2420; }
.st-key-kc_req { background: #CFE6D2; } .st-key-kc_bad { background: #F4CBD8; }
.st-key-kc_p50 { background: #F8E6A6; } .st-key-kc_p95 { background: #CBDCF4; }
.st-key-obs_donut { background: #DCD2F4; }
.st-key-kc_req *, .st-key-kc_bad *, .st-key-kc_p50 *, .st-key-kc_p95 *, .st-key-obs_donut * { color: #1F2420 !important; }
.kc .l { font-size: 13px; opacity: .75; } .kc .v { font-size: 32px; line-height: 1.15; font-weight: 500; } .kc .n { font-size: 13px; opacity: .75; }
.st-key-obs_c1, .st-key-obs_c2, .st-key-obs_c3, .st-key-obs_c4, .st-key-obs_c5, .st-key-obs_c6, .st-key-obs_c7, .st-key-obs_c8, .st-key-obs_c10, .st-key-obs_c11, .st-key-obs_detail, .st-key-obs_sli
  { border-radius: 24px; padding: 18px 22px 18px; background: var(--obs-card, #F6F3EA); color: #1F2420; }
.st-key-obs_c1 *, .st-key-obs_c2 *, .st-key-obs_c3 *, .st-key-obs_c4 *, .st-key-obs_c5 *, .st-key-obs_c6 *, .st-key-obs_c7 *, .st-key-obs_c8 *, .st-key-obs_c10 *, .st-key-obs_c11 *, .st-key-obs_detail *, .st-key-obs_sli * { color: #1F2420; }
.st-key-obs_sli { background: #EFE9DC; }
[class*="st-key-otc_"] { border-radius: 24px; padding: 18px 22px 18px; background: #F6F3EA; color: #1F2420; }
[class*="st-key-otc_"] * { color: #1F2420; }
[class*="st-key-kcs_"], [class*="st-key-kcy_"], [class*="st-key-kcr_"], [class*="st-key-kcb_"] { border-radius: 24px; padding: 16px 20px 18px; min-height: 148px; color: #1F2420; }
[class*="st-key-kcs_"] { background: #CFE6D2; } [class*="st-key-kcy_"] { background: #F8E6A6; }
[class*="st-key-kcr_"] { background: #F4CBD8; } [class*="st-key-kcb_"] { background: #CBDCF4; }
[class*="st-key-kcs_"] *, [class*="st-key-kcy_"] *, [class*="st-key-kcr_"] *, [class*="st-key-kcb_"] * { color: #1F2420 !important; }
.obs-t { font-size: 18px; font-weight: 500; margin-bottom: 2px; } .obs-s { font-size: 13px; opacity: .7; margin-bottom: 8px; }
.leg { display: flex; align-items: center; justify-content: space-between; padding: 7px 0; border-bottom: 1px solid rgba(31,36,32,.12); font-size: 14px; }
.leg:last-child { border-bottom: 0; } .leg i { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 8px; }
.sli3 { display: flex; gap: 12px; flex-wrap: wrap; margin-top: 6px; }
.sli3 > div { flex: 1 1 140px; background: rgba(255,255,255,.65); border-radius: 18px; padding: 10px 14px; }
.sli3 b { font-size: 24px; font-weight: 500; display: block; } .sli3 span { font-size: 12.5px; opacity: .75; }
.flow { display: flex; align-items: stretch; gap: 0; flex-wrap: nowrap; margin: 6px 0 4px; }
.fbox { border-radius: 16px; padding: 10px 14px; background: rgba(255,255,255,.75); border: 2px solid transparent; min-width: 110px; flex: 0 0 auto; text-align: center; font-size: 12.5px; }
.fbox small { display: block; opacity: .7; font-size: 11.5px; }
.fbox.ok { border-color: #2E8B57; } .fbox.slow { border-color: #E0A31B; background: #FCF1CE; } .fbox.bad { border-color: #C2412D; background: #F7D9D3; }
.fbox.off { border: 2px dashed rgba(31,36,32,.35); background: transparent; opacity: .8; }
.farrow { flex: 1 1 40px; min-width: 40px; text-align: center; font-size: 12px; align-self: center; line-height: 1.2; }
.farrow:after { content: ""; display: block; height: 2px; background: rgba(31,36,32,.45); margin: 3px 6px 0; }
.farrow.slow { color: #8A5E00; font-weight: 600; } .farrow.slow:after { background: #E0A31B; height: 3px; }
.farrow.bad { color: #A12D1B; font-weight: 600; } .farrow.bad:after { background: #C2412D; height: 3px; }
.fnote { font-size: 12.5px; opacity: .75; margin-top: 6px; }
.why li { margin-bottom: 4px; font-size: 14px; }
@media (max-width: 1000px) {
  .st-key-slo_refresh button { min-width: 92px; }
  [data-testid="stHorizontalBlock"]:has(.st-key-slo_refresh) { flex-wrap: wrap !important; }
  [data-testid="stHorizontalBlock"]:has(.st-key-slo_refresh) > [data-testid="stColumn"]:last-child { flex: 1 1 100% !important; }
  [data-testid="stHorizontalBlock"]:has(.kc) { flex-wrap: wrap !important; }
  [data-testid="stHorizontalBlock"]:has(.kc) > [data-testid="stColumn"] { flex: 1 1 calc(50% - 8px) !important; min-width: calc(50% - 8px) !important; }
}
@media (max-width: 640px) {
  [data-testid="stHorizontalBlock"]:has(.kc) > [data-testid="stColumn"] { flex: 1 1 100% !important; min-width: 100% !important; }
}
</style>
"""


def _esc(x):
    return html.escape(str(x))


def _rate(a, b):
    return 100.0 * a / b if b else None


## ---------------------------------------------------------------
## Picking the data for the chosen day (or all days)
## ---------------------------------------------------------------
def pick(days, choice):
    """days: newest first. choice: 'All days' or a YYYY-MM-DD string. Returns the daily dicts in scope (oldest first)."""
    if choice == "All days":
        return list(reversed(days[:30]))
    return [d for d in days if d["day"] == choice]


def buckets_for(scope, choice):
    """A list of {label,n,slow,e5,p50,p95}: 24 hours for one day, one bar per day for all days."""
    if choice != "All days" and scope and scope[0].get("hourly") is not None and scope[0].get("schema", 1) >= 2:
        have = {h["h"]: h for h in scope[0]["hourly"]}
        return [dict(label=f"{h:02d}", n=have.get(h, {}).get("n", 0), slow=have.get(h, {}).get("slow", 0),
                     e5=have.get(h, {}).get("e5", 0), p50=have.get(h, {}).get("p50"), p95=have.get(h, {}).get("p95"))
                for h in range(24)], "Hour"
    return [dict(label=d["day"][5:], n=d["total"], slow=d["slow"], e5=d["status_5xx"], p50=d.get("p50_ms"), p95=d.get("p95_ms"))
            for d in scope], "Day"


def all_requests(scope):
    out = []
    for d in scope:
        for r in d.get("requests", []):
            out.append(dict(r, day=d["day"]))
    return out


def merged_endpoints(scope):
    ep = {}
    for d in scope:
        for k, v in (d.get("endpoints") or {}).items():
            m = ep.setdefault(k, {"n": 0, "slow": 0, "e5": 0, "c4": 0, "p50w": 0.0, "p95": 0})
            m["n"] += v["n"]; m["slow"] += v["slow"]; m["e5"] += v["e5"]; m["c4"] += v.get("c4", 0)
            m["p50w"] += (v.get("p50") or 0) * v["n"]; m["p95"] = max(m["p95"], v.get("p95") or 0)
    rows = [dict(name=k, n=v["n"], slow=v["slow"], e5=v["e5"], good=v["n"] - v["slow"] - v["e5"],
                 p50=round(v["p50w"] / v["n"]) if v["n"] else None, p95=v["p95"] or None) for k, v in ep.items()]
    return sorted(rows, key=lambda r: -r["n"])


def failure_rows(scope):
    reqs = [r for r in all_requests(scope) if not r.get("good", True)]
    complete = all(d.get("requests_complete") for d in scope if d.get("total"))
    if not complete:                                               # old files: only the two totals are known
        e5, slow = sum(d["status_5xx"] for d in scope), sum(d["slow"] for d in scope)
        return [r for r in (dict(name="Failed (5xx)", n=e5, color=charts.RED), dict(name="Slow (over limit)", n=slow, color=charts.AMBER)) if r["n"]]
    kinds = {}
    for r in reqs:
        if r["status"] >= 500:
            name = f"{r['status']} · no pod answered" if r.get("target_status") is None else f"{r['status']} · app error"
            col = charts.RED
        else:
            name, col = f"Slow · over {sli.SLOW_MS} ms", charts.AMBER
        kinds.setdefault(name, [0, col])[0] += 1
    return [dict(name=k, n=v[0], color=v[1]) for k, v in sorted(kinds.items(), key=lambda kv: -kv[1][0])]


## ---------------------------------------------------------------
## Pieces of the page
## ---------------------------------------------------------------
def kpi_card(key, label, value, note):
    with st.container(key=key):
        st.markdown(f"<div class='kc'><div class='l'>{_esc(label)}</div><div class='v'>{_esc(value)}</div>"
                    f"<div class='n'>{_esc(note)}</div></div>", unsafe_allow_html=True)


def card_title(t, s=""):
    st.markdown(f"<div class='obs-t'>{_esc(t)}</div>" + (f"<div class='obs-s'>{_esc(s)}</div>" if s else ""), unsafe_allow_html=True)


def flow_html(r, split=None):
    """Phone -> load balancer -> pod, with the three measured times. The inner hops need tracing and are shown as not measured."""
    st_, rq, tg, rs = r.get("status", 0), r.get("request_ms"), r.get("target_ms"), r.get("response_ms")
    no_pod = st_ >= 500 and r.get("target_status") is None
    api = r.get("area") == "api"
    seg = [("Phone or browser", "sends the request", "ok"), ("Load balancer", "ALB", "ok"),
           ("Backend pod" if api else "Frontend pod", "the API" if api else "the website files", "ok")]
    big = None
    if not r.get("good", True) and st_ < 500:
        vals = [("req", rq), ("tgt", tg), ("res", rs)]
        vals = [(k, v) for k, v in vals if v is not None]
        big = max(vals, key=lambda p: p[1])[0] if vals else None
    cls = lambda k: "slow" if big == k else ("bad" if (no_pod and k == "tgt") else "")
    def arrow(k, label):
        txt = f"{label}<br>{'-' if {'req': rq, 'tgt': tg, 'res': rs}[k] is None else str({'req': rq, 'tgt': tg, 'res': rs}[k]) + ' ms'}"
        return f"<div class='farrow {cls(k)}'>{txt}</div>"
    b = [dict(t=x, s=y, c=z) for x, y, z in seg]
    if no_pod:
        b[1]["c"], b[2]["c"], b[2]["s"] = "bad", "never reached", "off"
    elif st_ >= 500:
        b[2]["c"] = "bad"
    elif big == "tgt":
        b[2]["c"] = "slow"
    elif big == "req":
        b[1]["c"] = "slow"
    box = lambda x: f"<div class='fbox {x['c']}'>{_esc(x['t'])}<small>{_esc(x['s'])}</small></div>"
    row = box(b[0]) + arrow("req", "waited for a pod") + box(b[1]) + arrow("tgt", "pod worked") + box(b[2]) + arrow("res", "answer sent back")
    if api and split:
        k = split["kinds"]
        tot = sum(k.values()) or 1.0
        inner = ("<div class='flow' style='margin-top:10px'><div class='fbox'>Backend pod<small>measured above</small></div>"
                 f"<div class='farrow'>asks</div><div class='fbox{' slow' if k['database'] / tot > .5 else ''}'>Database<small>about {k['database']:.0f} ms of a typical request</small></div></div>"
                 f"<div class='fnote'>{_esc(obs_traces.explain_split(split))} (from {split['n']} traces: an average for this endpoint, not this exact request.)</div>")
    elif api:
        inner = ("<div class='flow' style='margin-top:10px'><div class='fbox'>Backend pod<small>measured above</small></div>"
                 "<div class='farrow'>asks</div><div class='fbox off'>Database<small>not measured yet</small></div></div>"
                 "<div class='fnote'>An API request ends in the database. How long the database part took is hidden inside the backend's time. "
                 "Open the Traces tab and read the traces while the lab is up: it splits the time into database, password check and the rest.</div>")
    else:
        inner = "<div class='fnote'>The website files are served by the frontend pod alone. Nothing else is called for this request.</div>"
    return (f"<div class='flow'>{row}</div>"
            f"<div class='fnote'>Measured by the load balancer: total {_esc(r.get('ms') if r.get('ms') is not None else '-')} ms, status {_esc(st_)}.</div>"
            f"{inner}")


def ask_text(r, why):
    """Plain facts only: no query string, no body, no address of the client. The dashboard also redacts it."""
    facts = {k: r.get(k) for k in ("day", "time", "method", "endpoint", "status", "target_status", "ms", "request_ms", "target_ms",
                                   "response_ms", "reason") if r.get(k) is not None}
    return ("Troubleshoot this request from the Bako application. Facts from the load balancer log (UTC):\n"
            + json.dumps(facts, indent=2) + "\nWhat my rules say:\n- " + "\n- ".join(why)
            + f"\nWhy was it {'failed' if r.get('status', 0) >= 500 else 'slow'}, what is the most likely cause in my Bako cluster, "
              "and which exact command or log should I look at first?")


## ---------------------------------------------------------------
## The page
## ---------------------------------------------------------------
def overview(ctx):
    ss, store, ask, aws_ok = ctx["ss"], ctx["store"], ctx["ask"], ctx["aws_ok"]
    ctx["page_note"]("how the Bako application is doing for the people using it: requests, failures, speed. Numbers come from the load balancer logs in S3, so they stay here while the lab is off.")

    if "slo_days" not in ss:
        ss.slo_days, ss.slo_msg = store.read_all_daily() if aws_ok else ([], "The AWS command line was not found on this computer.")
    # files made by the first version lack the hourly and per-endpoint numbers: read those days again, once
    if aws_ok and not ss.get("slo_upgraded") and any(d.get("schema", 1) < sli.SCHEMA for d in ss.slo_days):
        ss.slo_upgraded = True
        with st.spinner("Reading older days again to get the richer numbers (one time)..."):
            sli.rollup_missing(store, include_today=True)
            ss.slo_days, ss.slo_msg = store.read_all_daily()

    days = [d for d in ss.slo_days if d.get("total", 0) > 0]
    c1, c2, c3 = st.columns([1.6, 1.3, 3], vertical_alignment="center")
    options = ["All days"] + [d["day"] for d in days]
    with c1:
        choice = st.selectbox("Period", options, key="obs_day", label_visibility="collapsed") if days else None
    with c2:
        if st.button("Refresh", key="slo_refresh", use_container_width=True,
                     help="Reads today's load balancer logs and any missing day from S3. Logs arrive about 5 minutes late."):
            with st.spinner("Reading the load balancer logs from S3..."):
                ok, msgs = sli.rollup_missing(store, include_today=True) if aws_ok else (False, ["The AWS command line was not found."])
                ss.slo_days, err = store.read_all_daily()
                ss.slo_msg = err or ("; ".join(msgs[-2:]))
            st.rerun()
    with c3:
        st.caption(ss.get("slo_msg") or "Days are UTC days (Cairo is 2 hours ahead). Only counts and timings are kept, never what you typed.")

    if not days:
        st.markdown("<div class='card'><div class='ctitle'>No request numbers yet</div><div class='sub'>Turn on the load balancer access logs "
                    "(one line in K8s/ingress.yaml), start the lab, use the app for a few minutes, wait about 10 minutes, then press Refresh.</div></div>",
                    unsafe_allow_html=True)
        return

    scope = pick(days, choice or "All days")
    if not scope:
        st.info("No data for that day.")
        return
    total = sum(d["total"] for d in scope); slow = sum(d["slow"] for d in scope); e5 = sum(d["status_5xx"] for d in scope)
    good = total - slow - e5
    p50, p95 = sli._pooled(scope, 50), sli._pooled(scope, 95)
    if p95 is None:
        p95s = [d["p95_ms"] for d in scope if d.get("p95_ms") is not None]
        p95 = max(p95s) if p95s else None
        p50s = [(d["p50_ms"], d["total"]) for d in scope if d.get("p50_ms") is not None]
        p50 = round(sum(a * b for a, b in p50s) / sum(b for _, b in p50s)) if p50s else None
    buckets, unit = buckets_for(scope, choice or "All days")
    rate = _rate(good, total)
    span = "last 30 days" if (choice or "All days") == "All days" else choice

    ## --- 1. four coloured number cards, each with a small trend line ---
    k = st.columns(4, gap="small")
    with k[0]:
        kpi_card("kc_req", "Requests", f"{total:,}", f"{span} · {len(scope)} {'day' if len(scope) == 1 else 'days'}")
    with k[1]:
        kpi_card("kc_bad", "Failed or slow", f"{slow + e5:,}", f"{e5} failed (5xx) · {slow} slow (over {sli.SLOW_MS} ms)")
    with k[2]:
        kpi_card("kc_p50", "Typical time (p50)", f"{p50} ms" if p50 is not None else "-", "half of the requests were faster")
    with k[3]:
        kpi_card("kc_p95", "Slow end (p95)", f"{p95} ms" if p95 is not None else "-", "95 in 100 requests were faster")
    st.write("")

    ## --- 2. the SLI, named ---
    avail = _rate(total - e5, total)
    lat = _rate((total - e5) - slow, total - e5)
    with st.container(key="obs_sli"):
        card_title("Where the SLI is", "An SLI is a measured number. An SLO is the target we put on it. We are only measuring now.")
        st.markdown(
            "<div class='sli3'>"
            f"<div><b>{avail:.2f}%</b><span>Availability SLI · requests that did not fail with a 5xx</span></div>"
            f"<div><b>{lat:.2f}%</b><span>Latency SLI · answered requests under {sli.SLOW_MS} ms</span></div>"
            f"<div><b>{rate:.2f}%</b><span>Overall good · both at once (the number the donut shows)</span></div>"
            "<div><b>not set yet</b><span>SLO target · chosen after about two weeks of real numbers</span></div></div>", unsafe_allow_html=True)
    st.write("")

    ## --- 3. requests over time + success ratio ---
    left, right = st.columns([1.7, 1], gap="medium")
    with left:
        with st.container(key="obs_c1"):
            card_title("Requests over time" if unit == "Hour" else "Requests per day",
                       "by hour, UTC" if unit == "Hour" else "green good · amber slow · red failed")
            st.altair_chart(charts.timeline(buckets, 250, unit), use_container_width=True, theme=None)
    with right:
        with st.container(key="obs_donut"):
            card_title("Success ratio", "good out of all counted")
            st.altair_chart(charts.donut_center(good, slow, e5), use_container_width=False, theme=None)
            leg = [("Good", good, charts.GREEN), ("Slow", slow, charts.AMBER), ("Failed (5xx)", e5, charts.RED)]
            st.markdown("".join(f"<div class='leg'><span><i style='background:{c}'></i>{_esc(n)}</span><b>{v:,} · {_rate(v, total):.1f}%</b></div>"
                                for n, v, c in leg), unsafe_allow_html=True)
    st.write("")

    ## --- 4. latency + kinds of problems ---
    l2, r2 = st.columns([1.7, 1], gap="medium")
    with l2:
        with st.container(key="obs_c2"):
            card_title("Latency", f"p50 and p95 per {unit.lower()}, dashed line = the {sli.SLOW_MS} ms limit")
            ch = charts.latency_lines(buckets, sli.SLOW_MS, 240, unit)
            if ch is None:
                st.caption("No timings yet.")
            else:
                st.altair_chart(ch, use_container_width=True, theme=None)
    rows = failure_rows(scope)
    with r2:
        with st.container(key="obs_c3"):
            card_title("Kinds of problems", "failed or slow, in this period")
            if rows:
                st.markdown("".join(f"<div class='leg'><span><i style='background:{r['color']}'></i>{_esc(r['name'])}</span><b>{r['n']}</b></div>" for r in rows),
                            unsafe_allow_html=True)
            else:
                st.markdown("<div style='padding:40px 0;text-align:center;opacity:.75'>Nothing failed and nothing was slow.</div>", unsafe_allow_html=True)
    st.write("")
    with st.container(key="obs_c8"):
        card_title("What went wrong, per day" if unit == "Day" else "What went wrong, per hour",
                   "only the problems: amber = slow, red = failed. Hover a bar for the share of that day's requests." if unit == "Day"
                   else "only the problems, by hour (UTC). Pick 'All days' to compare days.")
        if sum(b["slow"] + b["e5"] for b in buckets):
            st.altair_chart(charts.trouble_timeline(buckets, 230, unit), use_container_width=True, theme=None)
        else:
            st.markdown("<div style='padding:30px 0;text-align:center;opacity:.75'>No problems in this period.</div>", unsafe_allow_html=True)
    st.write("")

    ## --- 5. endpoints ---
    eps = merged_endpoints(scope)
    with st.container(key="obs_c4"):
        card_title("Requests by endpoint", "what the requests were for: the method and the address, ids replaced by {id}")
        if eps:
            st.altair_chart(charts.hbars([dict(name=e["name"], good=e["good"], slow=e["slow"], e5=e["e5"]) for e in eps[:12]]),
                            use_container_width=True, theme=None)
            head = "<tr><th>Endpoint</th><th class='n'>Requests</th><th class='n'>Failed or slow</th><th class='n'>p50 ms</th><th class='n'>p95 ms</th></tr>"
            body = "".join(f"<tr style='white-space:nowrap'><td>{_esc(e['name'])}</td><td class='n'>{e['n']}</td>"
                           f"<td class='n'{' style=color:#C2412D' if e['slow'] + e['e5'] else ''}>{e['slow'] + e['e5']}</td>"
                           f"<td class='n'>{e['p50'] if e['p50'] is not None else '-'}</td><td class='n'>{e['p95'] if e['p95'] is not None else '-'}</td></tr>"
                           for e in eps[:15])
            st.markdown(f"<table class='rtable'>{head}{body}</table>", unsafe_allow_html=True)
        else:
            st.caption("The per-endpoint numbers appear after the next Refresh (older days were saved without them).")
    st.caption("Counted = reached a pod, or the load balancer failed it. Not counted = port 80 redirects and bot hits the load balancer answers itself "
               f"({sum(d.get('noise', 0) for d in scope)} in this period). 4xx answers count as good.")
    st.write("")

    ## --- 6. one request: JSON, flow, why, ask Bako ---
    reqs = all_requests(scope)
    if not reqs and any(d.get("bad_requests") for d in scope):
        reqs = [dict(r, day=d["day"], good=False, method="?", endpoint="(older file)") for d in scope for r in d.get("bad_requests", [])]
    card_title("Look at one request", "pick a request to see it as data, how it travelled, and why it was slow or failed")
    only_bad = st.toggle("Only failed or slow", value=True, key="obs_only_bad")
    shown = [r for r in reqs if not r.get("good", True)] if only_bad else reqs
    if not shown:
        st.caption("No failed or slow requests in this period." if only_bad else "No requests listed.")
        return
    shown = sorted(shown, key=lambda r: (r["day"], r["time"]), reverse=True)[:200]
    labels = [f"{r['day'][5:]} {r['time']} · {r['status']} · {r.get('endpoint', r.get('area', ''))} · {r['ms'] if r.get('ms') is not None else '-'} ms" for r in shown]
    pick_i = st.selectbox("Request", range(len(shown)), format_func=lambda i: labels[i], key="obs_req", label_visibility="collapsed")
    r = shown[pick_i]
    typical = next((e["p50"] for e in eps if e["name"] == r.get("endpoint")), None)
    why = sli.explain(r, typical)
    req_key = f"{r['day']} {r['time']} {r.get('endpoint')}"
    traces = ss.get("obs_traces") or obs_tabs._load_last(ctx, "traces")             # the last trace reading (live or from disk)
    trace_split = obs_traces.for_endpoint(traces, r.get("endpoint", "")) if traces else None
    with st.container(key="obs_c5"):
        card_title("How it travelled", "from the phone to the pod and back")
        st.markdown(flow_html(r, trace_split), unsafe_allow_html=True)
    st.write("")
    a, b = st.columns([1, 1], gap="medium")
    with a:
        with st.container(key="obs_detail"):
            card_title("The request as data", "exactly what is stored: no query string, no client address, no body")
            shown_fields = {k: v for k, v in r.items() if k not in ("good",) and v is not None}
            st.code(json.dumps(shown_fields, indent=2), language="json", wrap_lines=True)
    with b:
        with st.container(key="obs_c6"):
            card_title("Why it " + ("failed" if r["status"] >= 500 else "was slow" if not r.get("good", True) else "was fine"))
            st.markdown("<ul class='why'>" + "".join(f"<li>{_esc(x)}</li>" for x in why) + "</ul>", unsafe_allow_html=True)
            if not r.get("good", True):
                if st.button("Ask Bako to troubleshoot this", key="obs_ask", type="primary"):
                    label = f"{r.get('endpoint', '')} · {r['status']} · {str(r['ms']) + ' ms' if r.get('ms') is not None else 'no timing'} · {r['time']} UTC ({r['day']})"
                    ss.obs_asked = label
                    ep_row = next((e for e in eps if e["name"] == r.get("endpoint")), None)
                    day_reqs = [x for x in reqs if x["day"] == r["day"]]
                    text, items = sre.build_pack(r, why, ep_row, day_reqs, traces=traces,
                                                 backend=obs_tabs._load_last(ctx, "backend"), db=(obs_tabs._load_last(ctx, "db") or {}).get("live"))
                    ask(sre.question(r, text, "failed" if r["status"] >= 500 else "slow"), "Troubleshoot: " + label, items)

    st.write("")
    answer_card(ctx, "obs_c7")


def answer_card(ctx, key):
    ss = ctx["ss"]
    if not ss.get("obs_asked"):
        return
    with st.container(key=key):
        card_title("Bako's answer", "for " + str(ss.obs_asked) + " · also in the Ask Bako chat; the full record (tools, tokens, cost) is on the Bako & AI page")
        state, text = ctx["answer"]()
        if state == "thinking":
            st.markdown("Bako is thinking. You can switch pages: the answer is kept and will show here and in the chat.")
        elif state == "done":
            st.markdown(text)
            case_view(ctx)
        else:
            st.caption("No answer yet.")


def case_view(ctx):
    """Not blind: what Bako was given, what it called, and what it cost. Read from the real record of the turn."""
    ss = ctx["ss"]
    case = ss.get("obs_case") or {}
    items = case.get("items") or []
    ct = ss.get("chat_trace") or {}
    tr = ct.get("trace") or {}
    with st.expander("How Bako got to this answer", expanded=False):
        if items:
            miss = sum(1 for x in items if not x["measured"])
            st.markdown(f"**1. The evidence it was given** ({len(items)} items" + (f", {miss} not measured" if miss else "") + ")")
            for i, x in enumerate(items, 1):
                st.markdown(f"{'✓' if x['measured'] else '✕'} **[{i}] {_esc(x['title'])}:** {_esc(x['text'])}")
        else:
            st.caption("This question carried no evidence pack (it was asked from a tab that sends only the facts it shows).")
        calls = tr.get("calls") or []
        st.markdown(f"**2. Tools it called** ({len(calls)})")
        if not calls:
            st.caption("None. It answered from the evidence alone.")
        for c in calls:
            st.markdown(f"{'✓' if c['ok'] else '✕'} **{_esc(c['name'])}** {_esc(c['arguments'])} · {c['ms']:,} ms · {c['result_chars']:,} characters")
            st.code(str(c["result"])[:900], language=None, wrap_lines=True)
        cost = ct.get("cost") or {}
        st.markdown("**3. Model and cost:** " + f"{_esc(ct.get('model', '?'))}, mode {_esc(tr.get('mode', '?'))}, {ct.get('tokens', 0):,} tokens"
                    + (f", ${cost['dollars']:.4f}" if cost.get("dollars") is not None else "") + (f", stopped by {tr['stopped_by']}" if tr.get("stopped_by") else "") + ".")
        st.caption("The same record, with the raw requests and replies, is on the Bako & AI page.")
    past = sre.load_cases(ctx["reports"], 8)
    if past:
        with st.expander(f"Past cases ({len(past)} saved)"):
            for c in past:
                st.markdown(f"**{_esc(c.get('time', '')[:16])}** · {_esc(c.get('label', ''))}: {_esc((c.get('reply') or '')[:160])}")


def show(ctx):
    """The Observability view: one tab per question. Each tab is a page of its own."""
    st.markdown(CSS, unsafe_allow_html=True)
    ctx = dict(ctx, answer_card=lambda key: answer_card(ctx, key))
    t = st.tabs([":material/insights: Overview", ":material/dns: Backend pod", ":material/database: Database",
                 ":material/route: Traces", ":material/flag: SLO and budget"])
    with t[0]:
        overview(ctx)
    with t[1]:
        obs_tabs.backend_tab(ctx)
    with t[2]:
        obs_tabs.db_tab(ctx)
    with t[3]:
        obs_tabs.traces_tab(ctx)
    with t[4]:
        obs_tabs.slo_tab(ctx)
