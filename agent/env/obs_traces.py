"""Request traces of the Bako backend: where the time of one request goes (database, password check, outside calls, other code).

The backend already sends OpenTelemetry traces. In the cluster a small receiver (Jaeger, in memory) collects them (K8s/tracing.yaml).
This module reads them back and boils them down.

Safety, in one place:
- Read-only: one short-lived pod does ONE web request to the receiver's query API and is deleted afterwards.
- A database span is reduced to a SHAPE: the verb and the table names ("SELECT users"). The text of the query, its values and any
  parameter are never kept. Other span names go through the same "shape" filter as log lines (numbers, ids, quoted text removed).
- Span tags (headers, bodies, user ids) are NOT copied anywhere: only name, kind, start and duration.
Everything returns (data, reason): a problem is a message, never an exception.
"""
import json
import re
import time
from datetime import datetime, timezone

import obs_data
import redact

SERVICE = "bako-backend"
JAEGER = "jaeger"                      # name of the receiver's Service in the namespace
QUERY_PORT = 16686
KEEP_SLOW = 12                         # slowest traces kept with their spans
KEEP_SPANS = 40                        # spans kept per trace
PASSWORD_PREFIX = "password."          # the named spans the app patch adds (password.verify, password.hash)
KINDS = ("database", "password check", "outside calls", "other code")

_ID = re.compile(r"/\d+(?=/|$)")
_TABLE = re.compile(r'\b(?:from|join|into|update)\s+("?[A-Za-z_][\w.]*"?)', re.I)


## ---------------------------------------------------------------
## 1. SHAPES
## ---------------------------------------------------------------
def stmt_shape(sql):
    """'SELECT id, email FROM users WHERE email = %s' -> 'SELECT users'. Never keeps the text itself."""
    s = (sql or "").strip()
    if not s:
        return "query"
    verb = re.split(r"\s+", s, maxsplit=1)[0].upper().strip("(;")[:12] or "QUERY"
    if verb not in ("SELECT", "INSERT", "UPDATE", "DELETE", "BEGIN", "COMMIT", "ROLLBACK", "WITH", "SET", "CREATE", "ALTER", "SHOW"):
        return "query"
    tabs = []
    for t in _TABLE.findall(s):
        t = t.strip('"').split(".")[-1].lower()
        if t not in tabs and re.fullmatch(r"[a-z_][a-z0-9_]*", t):
            tabs.append(t)
    return verb + (" " + ", ".join(tabs[:3]) if tabs else "")


def clean_name(name):
    n = obs_data.shape(str(name or ""))
    return (n or "span")[:60]


def clean_route(route):
    return _ID.sub("/{id}", str(route or "")).split("?")[0][:80]


## ---------------------------------------------------------------
## 2. PARSING (Jaeger query API JSON -> small dicts)
## ---------------------------------------------------------------
def _tags(span):
    out = {}
    for t in span.get("tags") or []:
        out[t.get("key")] = t.get("value")
    return out


def _parent(span):
    for r in span.get("references") or []:
        if r.get("refType") == "CHILD_OF":
            return r.get("spanID")
    return None


def classify(span, tags):
    name = span.get("operationName") or ""
    if name.startswith(PASSWORD_PREFIX):
        return "password check"
    if tags.get("db.system") or tags.get("db.statement") or tags.get("db.query.text"):
        return "database"
    if tags.get("span.kind") == "client" and (tags.get("http.url") or tags.get("url.full") or tags.get("http.method")):
        return "outside calls"
    return "other code"


def parse_trace(tr):
    """One trace -> {id, start_us, total_ms, endpoint, status, spans[], database, password check, outside calls, other code, stmts[]} or None."""
    spans = tr.get("spans") or []
    if not spans:
        return None
    by_id = {s["spanID"]: s for s in spans}
    roots = [s for s in spans if not _parent(s) or _parent(s) not in by_id]
    if not roots:
        return None
    root = min(roots, key=lambda s: s.get("startTime", 0))
    rt = _tags(root)
    method = str(rt.get("http.method") or rt.get("http.request.method") or "").upper()
    route = rt.get("http.route") or rt.get("url.path") or rt.get("http.target") or ""
    if not method or not route:                         # fall back to the span name ("POST /login")
        m = re.match(r"^([A-Z]+)\s+(/\S*)", root.get("operationName") or "")
        if m:
            method, route = m.group(1), m.group(2)
    if not method or not route:
        return None
    route = clean_route(route)
    status = rt.get("http.status_code") or rt.get("http.response.status_code")
    total = (root.get("duration") or 0) / 1000.0
    t0 = root.get("startTime", 0)
    kinds = {k: 0.0 for k in KINDS}
    stmts, slim = [], []
    depth_of = {}

    def depth(s):
        sid = s["spanID"]
        if sid in depth_of:
            return depth_of[sid]
        p = _parent(s)
        d = 0 if (not p or p not in by_id) else depth(by_id[p]) + 1
        depth_of[sid] = min(d, 8)
        return depth_of[sid]

    for s in sorted(spans, key=lambda x: x.get("startTime", 0)):
        if s is root:
            continue
        tg = _tags(s)
        k = classify(s, tg)
        ms = (s.get("duration") or 0) / 1000.0
        if tg.get("asgi.event.type"):                      # the framework's own "send/receive" spans: tiny, not a real step
            continue
        if k == "database":
            sql = tg.get("db.statement") or tg.get("db.query.text") or s.get("operationName") or ""
            name = stmt_shape(sql)
            stmts.append((name, ms))
        elif k == "outside calls":
            host_path = tg.get("http.url") or tg.get("url.full") or ""
            host_path = re.sub(r"^https?://", "", str(host_path))
            name = clean_name((tg.get("http.method") or "") + " " + clean_route(host_path))
        else:
            name = clean_name(s.get("operationName"))
        kinds[k] += ms
        if len(slim) < KEEP_SPANS:
            slim.append({"name": name, "kind": k, "start_ms": round((s.get("startTime", t0) - t0) / 1000.0, 2),
                         "ms": round(ms, 2), "depth": depth(s)})
    named = kinds["database"] + kinds["password check"] + kinds["outside calls"]
    kinds["other code"] = max(0.0, total - named)           # whatever the named steps do not explain
    return {"id": str(tr.get("traceID", ""))[:32], "start_us": t0, "total_ms": round(total, 2),
            "endpoint": f"{method} {route}", "status": status, "spans": slim,
            "kinds": {k: round(v, 2) for k, v in kinds.items()}, "stmts": [(n, round(m, 2)) for n, m in stmts]}


def parse_jaeger(text):
    """-> (list of parsed traces, message)"""
    try:
        data = json.loads(text)
    except ValueError:
        return [], "the receiver did not answer with JSON: " + redact.redact(text.strip())[-160:]
    if data.get("errors"):
        return [], "the receiver said: " + redact.redact(json.dumps(data["errors"]))[:200]
    out = []
    for tr in data.get("data") or []:
        p = parse_trace(tr)
        if p:
            out.append(p)
    return out, ""


## ---------------------------------------------------------------
## 3. SUMMARY
## ---------------------------------------------------------------
def pct(vals, p):
    if not vals:
        return 0.0
    v = sorted(vals)
    return v[min(len(v) - 1, int(round((p / 100.0) * (len(v) - 1))))]


def summarize(traces):
    """-> {n, endpoints{ep: {...}}, queries[], slowest[]}"""
    eps = {}
    qall = {}
    for t in traces:
        e = eps.setdefault(t["endpoint"], {"ms": [], "kinds": {k: 0.0 for k in KINDS}, "errors": 0, "q": {}})
        e["ms"].append(t["total_ms"])
        for k, v in t["kinds"].items():
            e["kinds"][k] += v
        try:
            if int(t.get("status") or 0) >= 500:
                e["errors"] += 1
        except (TypeError, ValueError):
            pass
        for name, ms in t["stmts"]:
            for d in (e["q"], qall):
                x = d.setdefault(name, [0, 0.0, 0.0])        # calls, total ms, slowest single call
                x[0] += 1
                x[1] += ms
                x[2] = max(x[2], ms)

    def qlist(d, top=8):
        rows = [{"stmt": n, "calls": c, "avg_ms": round(tot / c, 2), "total_ms": round(tot, 1), "max_ms": round(mx, 1)}
                for n, (c, tot, mx) in d.items()]
        return sorted(rows, key=lambda r: -r["total_ms"])[:top]

    out = {}
    for ep, e in eps.items():
        n = len(e["ms"])
        out[ep] = {"n": n, "avg_ms": round(sum(e["ms"]) / n, 1), "p50_ms": round(pct(e["ms"], 50), 1), "p95_ms": round(pct(e["ms"], 95), 1),
                   "errors": e["errors"], "kinds": {k: round(v / n, 1) for k, v in e["kinds"].items()}, "queries": qlist(e["q"], 5)}
    slow = sorted(traces, key=lambda t: -t["total_ms"])[:KEEP_SLOW]
    return {"n": len(traces), "endpoints": out, "queries": qlist(qall, 12),
            "slowest": [{k: t[k] for k in ("id", "start_us", "total_ms", "endpoint", "status", "spans", "kinds")} for t in slow]}


def biggest_part(ep_summary):
    """('password check', 94) -> the part of the average request that takes most, with its share in percent."""
    k = ep_summary["kinds"]
    tot = sum(k.values()) or 1.0
    name = max(k, key=lambda x: k[x])
    return name, int(round(100.0 * k[name] / tot))


def match_endpoint(alb_endpoint, trace_endpoint):
    """The load balancer sees 'POST /api/login', the backend sees 'POST /login' (nginx strips /api)."""
    def norm(e):
        m, _, p = (e or "").partition(" ")
        p = re.sub(r"^/api(?=/|$)", "", p) or "/"
        return m.upper() + " " + p
    return norm(alb_endpoint) == norm(trace_endpoint)


def for_endpoint(summary, alb_endpoint):
    if not summary:
        return None
    for ep, v in (summary.get("endpoints") or {}).items():
        if match_endpoint(alb_endpoint, ep):
            return dict(v, endpoint=ep)
    return None


def explain_split(ep_summary):
    """Plain words for one endpoint's average request."""
    if not ep_summary:
        return ""
    k = ep_summary["kinds"]
    tot = sum(k.values()) or 1.0
    name, share = biggest_part(ep_summary)
    parts = ", ".join(f"{n} {k[n]:.0f} ms" for n in KINDS if k[n] >= 1)
    line = f"On average a request to {ep_summary['endpoint']} takes {tot:.0f} ms: {parts}. Most of it ({share}%) is {name}."
    if name == "password check":
        line += " That step is the password hashing, which is slow on purpose."
    return line


## ---------------------------------------------------------------
## 4. LIVE READ (a short-lived pod asks the receiver's query API)
## ---------------------------------------------------------------
NO_RECEIVER = ("The trace receiver is not in the cluster. Copy K8s/tracing.yaml into your Bako repo's K8s folder and merge it; "
               "Argo CD then starts it (about a minute).")
NO_TRACES = ("The receiver is running but holds no traces for the backend yet. Use the app for a minute (log in, open a page) and read again. "
             "If it stays empty, the backend is not sending: run patch_tracing.py, let CI build, and check the OTEL_ variables of the backend.")


def traces_live(kubectl, env, account, minutes=180, limit=150):
    """-> (facts, reason). facts = summarize(...) + {at, minutes}"""
    ok, why = obs_data.cluster_ok(kubectl, env, account)
    if not ok:
        return None, why
    ns = obs_data.NS
    rc, out, err = obs_data._run([kubectl, "-n", ns, "get", "deploy", JAEGER, "-o", "name", "--request-timeout=15s"], env, 30)
    if rc != 0:
        return None, NO_RECEIVER
    end_us = int(time.time() * 1_000_000)
    start_us = end_us - minutes * 60 * 1_000_000
    url = (f"http://{JAEGER}:{QUERY_PORT}/api/traces?service={SERVICE}&start={start_us}&end={end_us}&limit={int(limit)}")
    pod = "bako-traceq"
    obs_data._run([kubectl, "delete", "pod", pod, "-n", ns, "--ignore-not-found", "--wait=true"], env, 60)
    rc, out, err = obs_data._run([kubectl, "run", pod, "-n", ns, "--image=curlimages/curl:8.10.1", "--restart=Never", "--rm", "-i", "--quiet",
                                  "--command", "--", "curl", "-sS", "-m", "25", url], env, 120)
    obs_data._run([kubectl, "delete", "pod", pod, "-n", ns, "--ignore-not-found", "--wait=false"], env, 30)
    text = out[out.find("{"):] if "{" in out else out
    traces, why = parse_jaeger(text)
    if why:
        return None, why + (" " + redact.redact(err.strip())[-120:] if err.strip() and not out.strip() else "")
    if not traces:
        return None, NO_TRACES
    facts = summarize(traces)
    facts["at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    facts["minutes"] = minutes
    return facts, ""


def compact(facts):
    """What the daily file keeps: numbers per endpoint and the top query shapes. No spans, no trace ids."""
    if not facts:
        return None
    return {"n": facts["n"],
            "endpoints": {ep: {"n": v["n"], "avg_ms": v["avg_ms"], "p95_ms": v["p95_ms"], "kinds": v["kinds"], "errors": v["errors"]}
                          for ep, v in facts["endpoints"].items()},
            "queries": [{"stmt": q["stmt"], "calls": q["calls"], "avg_ms": q["avg_ms"], "total_ms": q["total_ms"]} for q in facts["queries"][:8]]}


## ---------------------------------------------------------------
## self test
## ---------------------------------------------------------------
def _fake(trace_id, route, total_ms, db_ms, pw_ms, method="POST", status=200, sql="SELECT id, email, hashed_password FROM users WHERE email = 'a@b.c'"):
    base = 1_700_000_000_000_000
    spans = [{"traceID": trace_id, "spanID": "r", "operationName": f"{method} {route}", "references": [], "startTime": base,
              "duration": int(total_ms * 1000), "tags": [{"key": "http.method", "value": method}, {"key": "http.route", "value": route},
                                                          {"key": "http.status_code", "value": status}]},
             {"traceID": trace_id, "spanID": "d", "operationName": "SELECT", "references": [{"refType": "CHILD_OF", "spanID": "r"}],
              "startTime": base + 3000, "duration": int(db_ms * 1000),
              "tags": [{"key": "db.system", "value": "postgresql"}, {"key": "db.statement", "value": sql}]}]
    if pw_ms:
        spans.append({"traceID": trace_id, "spanID": "p", "operationName": "password.verify", "references": [{"refType": "CHILD_OF", "spanID": "r"}],
                      "startTime": base + 10000, "duration": int(pw_ms * 1000), "tags": []})
    spans.append({"traceID": trace_id, "spanID": "a", "operationName": "POST /login http send", "references": [{"refType": "CHILD_OF", "spanID": "r"}],
                  "startTime": base + 1000, "duration": 200, "tags": [{"key": "asgi.event.type", "value": "http.response.start"}]})
    return {"traceID": trace_id, "spans": spans}


def selftest():
    assert stmt_shape("SELECT id, email FROM users WHERE email = 'x@y.z' AND pw = 'secret'") == "SELECT users"
    assert stmt_shape("insert into transactions (a,b) values (1,2)") == "INSERT transactions"
    assert stmt_shape("SELECT t.id FROM transactions t JOIN categories c ON c.id=t.cid") == "SELECT transactions, categories"
    assert stmt_shape("") == "query" and stmt_shape("weird text here") == "query"
    data = {"data": [_fake("t1", "/login", 616, 6, 590), _fake("t2", "/login", 630, 5, 600), _fake("t3", "/login", 640, 8, 600),
                     _fake("t4", "/expenses/42", 30, 20, 0, method="GET", sql="SELECT * FROM transactions WHERE id = 42 AND note='pizza'")]}
    traces, why = parse_jaeger(json.dumps(data))
    assert not why and len(traces) == 4
    t1 = traces[0]
    assert t1["endpoint"] == "POST /login" and abs(t1["kinds"]["password check"] - 590) < 1 and abs(t1["kinds"]["database"] - 6) < 1
    assert abs(t1["kinds"]["other code"] - 20) < 1, t1["kinds"]
    assert not any(s["name"].startswith("POST /login http") for s in t1["spans"])        # framework spans skipped
    assert traces[3]["endpoint"] == "GET /expenses/{id}"
    s = summarize(traces)
    login = for_endpoint(s, "POST /api/login")
    assert login and login["n"] == 3 and biggest_part(login)[0] == "password check" and biggest_part(login)[1] >= 90
    assert "password hashing" in explain_split(login)
    assert for_endpoint(s, "GET /api/expenses/{id}")["n"] == 1
    assert s["queries"][0]["stmt"] in ("SELECT users", "SELECT transactions")
    blob = json.dumps(compact(s))
    for leak in ("a@b.c", "pizza", "secret", "x@y.z", "trace"):
        assert leak not in blob, leak
    assert "start_us" not in blob
    assert parse_jaeger("not json")[1] and parse_jaeger('{"errors":[{"msg":"x"}]}')[1]
    print("obs_traces selftest: ok")


if __name__ == "__main__":
    selftest()
