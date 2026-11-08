"""Request numbers for Bako (measure-only version).

The load balancer (ALB) writes one log line per request into the permanent S3 bucket.
This file turns one UTC day of those lines into one small JSON file:

    s3://<bucket>/sli-daily/YYYY-MM-DD.json

The file holds COUNTS AND TIMINGS ONLY: how many requests, how many failed or were slow, the 95th percentile time,
and for each request: the time, the method, the address WITHOUT its query string and with ids replaced by {id}
(for example GET /api/goals/{id}), the status, and the three timings the load balancer measured.
Never the address with its query string, never a request body, never an IP address, never anything about expenses.

A "counted" request is one the app really answered or should have answered: it reached a pod, or the load balancer
itself failed it with a 5xx. Redirects from port 80 and bot hits that the load balancer answers on its own (404)
are not counted, because they say nothing about the app and would make the numbers look better than they are.

  good  = status below 500 and answered in under SLOW_MS
  bad   = a 5xx, or slower than SLOW_MS (4xx are good: a typo or a bot is not the app's fault)

Days are UTC days, because that is how the load balancer names its log folders (Cairo is 2 hours ahead).
There is no target and no budget yet: the plan is to measure for about two weeks and then choose the SLO from real data.

Run by hand:
    python agent/env/sli.py rollup            # roll up every missing or unfinished day of the last 7
    python agent/env/sli.py rollup 2026-11-05 # one day
    python agent/env/sli.py selftest          # offline check of the parsing and the maths, no AWS needed
"""
import gzip, io, json, os, re, shutil, subprocess, sys, tempfile
from datetime import datetime, timedelta, timezone

SLOW_MS = 500
KEEP_BAD = 50          # at most this many failed or slow requests are listed per day
KEEP_REQS = 400        # at most this many requests are listed per day (all the bad ones first)
DAILY_PREFIX = "sli-daily"
LOG_PREFIX = "alb-logs"
TOKEN = re.compile(r'"[^"]*"|\S+')


## ---------------------------------------------------------------
## Reading one log line
## ---------------------------------------------------------------
UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
HEX = re.compile(r"^[0-9a-fA-F]{8,}$")
SCHEMA = 2            # 2 = adds hourly numbers, per-endpoint numbers and a list of requests

def norm_path(path):
    ## /api/goals/123 and /api/goals/9f1c... both become /api/goals/{id}, so one endpoint is one line, not thousands.
    out = []
    for seg in path.split("/"):
        if seg and (seg.isdigit() or UUID.match(seg) or HEX.match(seg) or len(seg) > 24):
            seg = "{id}"
        out.append(seg)
    return "/".join(out) or "/"

def endpoint_of(method, path, area):
    ## the name shown on the page: "GET /api/goals/{id}", or a friendly name for the website's own files
    if area == "api":
        return f"{method} {norm_path(path)}"
    last = path.rsplit("/", 1)[-1]
    return f"{method} website files" if path.startswith("/assets/") or "." in last else f"{method} website page"

def _ms(v):
    return None if v < 0 else round(v * 1000)

def parse_line(line):
    ## ALB access log: space separated, some fields in quotes. Field order is fixed by AWS:
    ## 0 type, 1 time, 2 elb, 3 client, 4 target, 5 request_time, 6 target_time, 7 response_time,
    ## 8 elb_status, 9 target_status, 10 received, 11 sent, 12 "request", ..., 24 error_reason
    ## Returns None for a line that does not look like one. Never raises.
    ## Not read at all: client address, user agent, trace id, query string.
    f = TOKEN.findall(line)
    if len(f) < 13:
        return None
    try:
        status = int(f[8])
        times = [float(f[5]), float(f[6]), float(f[7])]
    except ValueError:
        return None
    req = f[12].strip('"').split(" ")
    method = req[0][:8] if req and req[0].isalpha() else "?"
    url = req[1] if len(req) > 1 else ""
    path = re.sub(r"^[a-z]+://[^/]*", "", url).split("?")[0]          # no host, no query string
    total_ms = None if any(t < 0 for t in times) else round(sum(times) * 1000)
    area = "api" if path == "/api" or path.startswith("/api/") else "site"
    reason = f[24].strip('"') if len(f) > 24 else "-"
    return {"time": f[1], "status": status, "target": f[4], "total_ms": total_ms, "area": area,
            "method": method, "endpoint": endpoint_of(method, path, area),
            "target_status": f[9] if f[9] != "-" else None,
            "request_ms": _ms(times[0]), "target_ms": _ms(times[1]), "response_ms": _ms(times[2]),
            "reason": reason if reason not in ("-", "") else None}

def counted(r):
    ## reached a pod, or the load balancer itself failed it
    return r["target"] != "-" or r["status"] >= 500

def is_bad(r):
    return r["status"] >= 500 or (r["total_ms"] is not None and r["total_ms"] >= SLOW_MS)

def percentile(sorted_values, p):
    if not sorted_values:
        return None
    k = max(0, min(len(sorted_values) - 1, int(round(p / 100.0 * len(sorted_values) + 0.5)) - 1))
    return sorted_values[k]

def _stats(times, n, slow, e5, c4=0):
    t = sorted(times)
    return {"n": n, "slow": slow, "e5": e5, "c4": c4, "p50": percentile(t, 50), "p95": percentile(t, 95)}

def summarize_day(day, lines, files=0):
    ## day: "YYYY-MM-DD"; lines: iterable of raw log lines. Pure function, no AWS.
    total = noise = good = slow = e5 = unreadable = 0
    classes = {"2xx": 0, "3xx": 0, "4xx": 0, "5xx": 0}
    areas = {"api": 0, "site": 0}
    times, bad, first, last = [], [], None, None
    hours, eps, reqs = {}, {}, []
    for line in lines:
        if not line.strip():
            continue
        r = parse_line(line)
        if r is None:
            unreadable += 1
            continue
        if not counted(r):
            noise += 1
            continue
        total += 1
        classes[f"{r['status'] // 100}xx"] = classes.get(f"{r['status'] // 100}xx", 0) + 1
        areas[r["area"]] += 1
        first = r["time"] if first is None or r["time"] < first else first
        last = r["time"] if last is None or r["time"] > last else last
        is5, isslow = r["status"] >= 500, (r["status"] < 500 and is_bad(r))
        if r["total_ms"] is not None:
            times.append(r["total_ms"])
        if is5:
            e5 += 1
        elif isslow:
            slow += 1
        if is_bad(r):
            if len(bad) < KEEP_BAD:
                bad.append({"time": r["time"][11:19], "status": r["status"], "area": r["area"], "ms": r["total_ms"]})
        else:
            good += 1
        h = hours.setdefault(r["time"][11:13], {"t": [], "n": 0, "slow": 0, "e5": 0})
        h["n"] += 1; h["slow"] += isslow; h["e5"] += is5
        if r["total_ms"] is not None:
            h["t"].append(r["total_ms"])
        e = eps.setdefault(r["endpoint"], {"t": [], "n": 0, "slow": 0, "e5": 0, "c4": 0})
        e["n"] += 1; e["slow"] += isslow; e["e5"] += is5; e["c4"] += (400 <= r["status"] < 500)
        if r["total_ms"] is not None:
            e["t"].append(r["total_ms"])
        reqs.append({"time": r["time"][11:19], "method": r["method"], "endpoint": r["endpoint"], "area": r["area"],
                     "status": r["status"], "target_status": r["target_status"], "ms": r["total_ms"],
                     "request_ms": r["request_ms"], "target_ms": r["target_ms"], "response_ms": r["response_ms"],
                     "reason": r["reason"], "good": not is_bad(r)})
    times.sort()
    hourly = [dict(_stats(v["t"], v["n"], v["slow"], v["e5"]), h=int(k)) for k, v in sorted(hours.items())]
    ranked = sorted(eps.items(), key=lambda kv: -kv[1]["n"])
    endpoints = {k: _stats(v["t"], v["n"], v["slow"], v["e5"], v["c4"]) for k, v in ranked[:30]}
    if len(ranked) > 30:                                                     # the long tail in one line
        rest = ranked[30:]
        endpoints["other"] = _stats([x for _, v in rest for x in v["t"]], sum(v["n"] for _, v in rest),
                                    sum(v["slow"] for _, v in rest), sum(v["e5"] for _, v in rest), sum(v["c4"] for _, v in rest))
    if len(reqs) > KEEP_REQS:                                                # keep every bad one, then the rest in time order
        badr = [x for x in reqs if not x["good"]][:KEEP_REQS]
        okr = [x for x in reqs if x["good"]][:KEEP_REQS - len(badr)]
        reqs = sorted(badr + okr, key=lambda x: x["time"])
    return {"schema": SCHEMA, "day": day, "total": total, "good": good, "bad": total - good, "status_5xx": e5, "slow": slow,
            "classes": classes, "areas": areas, "noise": noise, "unreadable": unreadable,
            "p50_ms": percentile(times, 50), "p95_ms": percentile(times, 95), "max_ms": times[-1] if times else None,
            "first": first[11:19] if first else None, "last": last[11:19] if last else None,
            "hourly": hourly, "endpoints": endpoints, "requests": reqs, "requests_complete": len(reqs) == total,
            "bad_requests": bad, "log_files": files, "slow_ms": SLOW_MS}


## ---------------------------------------------------------------
## "Why was it slow or failed?" - plain rules, no guessing. Used by the page and by Ask Bako.
## ---------------------------------------------------------------
def explain(r, typical_ms=None):
    ## r: one request dict from a daily file. Returns a list of short sentences. Facts first, then what to check.
    out, st, tms = [], r.get("status", 0), r.get("target_ms")
    if st >= 500:
        if r.get("target_status") is None:
            out.append(f"The load balancer answered {st} itself. The request never reached a pod.")
            out.append("Most likely there was no healthy pod at that moment (starting, restarting, or failing its health check). "
                       "Check: kubectl -n bako get pods, and the pod events around " + str(r.get("time")) + " UTC.")
        elif st == 504:
            out.append("504: a pod was chosen but did not answer before the load balancer's timeout (60 s by default).")
            out.append("Check: the backend log at that time, a slow database query, or a pod that was stuck.")
        else:
            out.append(f"A pod answered {r.get('target_status') or st}. The error came from the application, not from the network.")
            out.append("Check: the backend pod log at " + str(r.get("time")) + " UTC for the stack trace.")
        if r.get("reason"):
            out.append(f"The load balancer's own reason: {r['reason']}.")
    elif not r.get("good", True):
        parts = [("the load balancer waiting to hand the request to a pod", r.get("request_ms")),
                 ("the pod working on it", tms), ("sending the answer back", r.get("response_ms"))]
        parts = [(n, v) for n, v in parts if v is not None]
        if parts:
            name, v = max(parts, key=lambda p: p[1])
            out.append(f"It took {r.get('ms')} ms (limit {SLOW_MS} ms). Most of the time, {v} ms, was {name}.")
            if name == "the pod working on it":
                out.append("So the slowness is inside the app (backend code, database, or a cold pod), not the network.")
            elif name.startswith("the load balancer"):
                out.append("So the pods were busy or just starting. Check pod CPU and the number of replicas.")
            else:
                out.append("So the client was slow to receive the data, or the answer was large.")
        if typical_ms:
            out.append(f"Typical time for this endpoint: {typical_ms} ms.")
    else:
        out.append("This request was good: under the limit and not a 5xx.")
    return out

def _pooled(days, p):
    ## exact percentile over many days, from the saved request lists; None if any day's list is incomplete or missing
    ms = []
    for d in days:
        if d.get("total", 0) and not d.get("requests_complete"):
            return None
        ms += [r["ms"] for r in d.get("requests", []) if r.get("ms") is not None]
    return percentile(sorted(ms), p) if ms else None

def window_summary(days, n=30):
    ## days: list of daily dicts (any order). Totals over the newest n days that have data.
    days = sorted(days, key=lambda d: d["day"], reverse=True)[:n]
    total = sum(d["total"] for d in days)
    bad = sum(d["bad"] for d in days)
    p95s = [d["p95_ms"] for d in days if d.get("p95_ms") is not None]
    return {"days": len(days), "total": total, "bad": bad, "good": total - bad,
            "rate": (100.0 * (total - bad) / total) if total else None,
            "p95_ms_worst_day": max(p95s) if p95s else None,
            "noise": sum(d.get("noise", 0) for d in days),
            "p50_ms": _pooled(days, 50), "p95_ms": _pooled(days, 95)}


## ---------------------------------------------------------------
## S3 (through the AWS CLI, like the snapshots: no extra Python packages)
## ---------------------------------------------------------------
class Store:
    def __init__(self, aws, region, profile="", account="", env=None, bucket=""):
        self.aws, self.region, self.profile, self.env = aws, region, profile, env
        self.account = account
        self.bucket = bucket or os.environ.get("BAKO_OPS_BUCKET") or f"bako-ops-{account}-{region}"

    def _cmd(self, *args):
        cmd = [self.aws, *args, "--region", self.region]
        if self.profile and not os.environ.get("AWS_PROFILE"):
            cmd += ["--profile", self.profile]
        return cmd

    def run(self, *args, timeout=180, stdin=None):
        try:
            p = subprocess.run(self._cmd(*args), capture_output=True, text=True, timeout=timeout,
                               input=stdin, stdin=None if stdin is not None else subprocess.DEVNULL, env=self.env)
            return p.returncode, (p.stdout or "") + (p.stderr or "")
        except subprocess.TimeoutExpired:
            return 124, "timed out"
        except OSError as e:
            return 127, str(e)

    def log_prefix(self, day):
        y, m, d = day.split("-")
        return f"s3://{self.bucket}/{LOG_PREFIX}/AWSLogs/{self.account}/elasticloadbalancing/{self.region}/{y}/{m}/{d}/"

    def read_day_logs(self, day):
        ## returns (lines, number of files) or (None, message) when S3 cannot be read
        tmp = tempfile.mkdtemp(prefix="bako-alb-")
        try:
            rc, out = self.run("s3", "sync", self.log_prefix(day), tmp, "--only-show-errors")
            if rc != 0:
                return None, out.strip()[-300:]
            lines, files = [], 0
            for name in sorted(os.listdir(tmp)):
                if not name.endswith(".log.gz"):
                    continue
                files += 1
                with gzip.open(os.path.join(tmp, name), "rt", encoding="utf-8", errors="replace") as fh:
                    lines.extend(fh.read().splitlines())
            return lines, files
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def write_daily(self, summary):
        key = f"s3://{self.bucket}/{DAILY_PREFIX}/{summary['day']}.json"
        rc, out = self.run("s3", "cp", "-", key, "--only-show-errors", "--sse", "AES256",
                           stdin=json.dumps(summary, separators=(",", ":")))
        return rc == 0, out.strip()[-300:]

    def read_all_daily(self):
        ## every daily file, newest first. Returns (list, message). An empty list is normal before the first run.
        tmp = tempfile.mkdtemp(prefix="bako-sli-")
        try:
            rc, out = self.run("s3", "sync", f"s3://{self.bucket}/{DAILY_PREFIX}/", tmp, "--only-show-errors")
            if rc != 0:
                return [], "Could not read the saved numbers from S3: " + out.strip()[-200:]
            days = []
            for name in os.listdir(tmp):
                if name.endswith(".json"):
                    try:
                        with open(os.path.join(tmp, name), encoding="utf-8") as fh:
                            days.append(json.load(fh))
                    except (OSError, ValueError):
                        pass
            return sorted(days, key=lambda d: d["day"], reverse=True), ""
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


## ---------------------------------------------------------------
## Roll-up: which days, and doing them
## ---------------------------------------------------------------
def utc_today():
    return datetime.now(timezone.utc).date()

def candidate_days(existing, back=7, include_today=False, now=None):
    ## Days to (re)compute: missing, or rolled up before the day was safely over (logs arrive ~5 minutes late).
    now = now or datetime.now(timezone.utc)
    have = {d["day"]: d for d in existing}
    out = []
    for i in range(0 if include_today else 1, back + 1):
        day = (now.date() - timedelta(days=i)).isoformat()
        cur = have.get(day)
        day_end = datetime.fromisoformat(day).replace(tzinfo=timezone.utc) + timedelta(days=1)
        if (cur is None or cur.get("rolled_at", "") < (day_end + timedelta(minutes=30)).isoformat()
                or cur.get("schema", 1) < SCHEMA):                     # older files lack the new numbers: read the logs again
            out.append(day)
    return out

def rollup_day(store, day):
    ## Returns (summary or None, message). A day with no log files is saved as an empty day only if it is already over.
    lines, info = store.read_day_logs(day)
    if lines is None:
        return None, f"{day}: could not read the logs ({info})"
    summary = summarize_day(day, lines, files=info)
    summary["rolled_at"] = datetime.now(timezone.utc).isoformat()
    ok, msg = store.write_daily(summary)
    if not ok:
        return None, f"{day}: could not save the numbers ({msg})"
    return summary, f"{day}: {summary['total']} counted requests, {summary['bad']} failed or slow ({info} log files)"

def rollup_missing(store, back=7, include_today=False):
    ## Used by START and by the dashboard button. Never raises. Returns (ok, lines of text).
    existing, err = store.read_all_daily()
    if err and not existing:
        return False, [err]
    out, ok = [], True
    for day in candidate_days(existing, back, include_today):
        s, msg = rollup_day(store, day)
        out.append(msg)
        ok = ok and s is not None
    return ok, out or ["Nothing to do: every day of the last week is already saved."]


## ---------------------------------------------------------------
## Offline check: python agent/env/sli.py selftest
## ---------------------------------------------------------------
def _line(time, status, target, ms, path="/api/goals", tstatus=None):
    t = ms / 1000.0
    tgt = "10.0.1.5:8000" if target else "-"
    ts = (tstatus if tstatus is not None else status) if target else "-"
    treq = "0.000" if target else "-1"
    return (f'https {time} app/k8s-bako/abc 203.0.113.9:5555 {tgt} {treq if target else "-1"} {t:.3f} 0.000 {status} {ts} 100 200 '
            f'"GET https://bako.awsbako.site:443{path} HTTP/1.1" "UA/1.0" ECDHE-RSA TLSv1.3 arn:tg "Root=1-x" "bako.awsbako.site" '
            f'"arn:cert" 0 {time} "forward" "-" "-" "{tgt}" "{ts}" "-" "-"')

def selftest():
    D = "2026-11-05"
    lines = [
        _line(f"{D}T10:00:01.000000Z", 200, True, 40),                          # good
        _line(f"{D}T10:00:02.000000Z", 200, True, 45, "/"),                      # good, site
        _line(f"{D}T10:00:03.000000Z", 404, True, 30, "/api/nope"),              # 4xx is good
        _line(f"{D}T10:00:04.000000Z", 200, True, 900),                          # slow
        _line(f"{D}T10:00:05.000000Z", 502, False, 0),                           # ALB 5xx, no target: counted, bad
        _line(f"{D}T10:00:06.000000Z", 301, False, 0, "/"),                      # redirect: noise
        _line(f"{D}T10:00:07.000000Z", 404, False, 0, "/wp-login.php"),          # bot: noise
        "not a log line",
        _line(f"{D}T10:00:08.000000Z", 200, True, 60, "/api/x?token=SECRET"),     # query string must not be kept
    ]
    s = summarize_day(D, lines)
    assert s["total"] == 6, s
    assert s["good"] == 4 and s["bad"] == 2, s
    assert s["status_5xx"] == 1 and s["slow"] == 1, s
    assert s["noise"] == 2 and s["unreadable"] == 1, s
    assert s["classes"]["4xx"] == 1 and s["classes"]["5xx"] == 1, s
    assert s["areas"] == {"api": 5, "site": 1}, s
    assert s["first"] == "10:00:01" and s["last"] == "10:00:08", s
    assert "SECRET" not in json.dumps(s) and "203.0.113.9" not in json.dumps(s), "private data leaked"
    assert [b["status"] for b in s["bad_requests"]] == [200, 502], s["bad_requests"]
    w = window_summary([s, dict(s, day="2026-11-04", total=4, bad=0, good=4, p95_ms=50)])
    assert w["total"] == 10 and w["bad"] == 2 and abs(w["rate"] - 80.0) < 1e-9, w
    assert s["schema"] == 2 and s["requests_complete"], s
    eps = s["endpoints"]
    assert "GET /api/goals" in eps and eps["GET /api/goals"]["n"] == 3, eps          # 2 plain + 1 slow... see below
    assert "GET /api/x" in eps and "GET website page" in eps, eps                    # query string dropped
    assert norm_path("/api/goals/123/items/9f1c2d3e-1111-2222-3333-444455556666") == "/api/goals/{id}/items/{id}"
    assert endpoint_of("GET", "/assets/index-ab12cd34.js", "site") == "GET website files"
    assert sum(h["n"] for h in s["hourly"]) == 6 and s["hourly"][0]["h"] == 10, s["hourly"]
    r502 = [x for x in s["requests"] if x["status"] == 502][0]
    assert "no healthy pod" in " ".join(explain(r502)), explain(r502)
    rslow = [x for x in s["requests"] if x["ms"] == 900][0]
    assert "inside the app" in " ".join(explain(rslow)) or "load balancer" in " ".join(explain(rslow)), explain(rslow)
    assert "good" in explain(s["requests"][0])[0]
    assert all(k not in json.dumps(s) for k in ("UA/1.0", "Root=1-x", "token=")), "private data leaked"
    now = datetime(2026, 11, 6, 9, 0, tzinfo=timezone.utc)
    done = {"schema": 2, "day": "2026-11-05", "rolled_at": "2026-11-06T08:00:00+00:00"}
    early = {"schema": 2, "day": "2026-11-04", "rolled_at": "2026-11-04T23:50:00+00:00"}       # rolled before the day was over
    old = {"day": "2026-11-03", "rolled_at": "2026-11-04T08:00:00+00:00"}          # finished day, but schema 1
    assert "2026-11-03" in candidate_days([done, old], back=3, now=now)
    c = candidate_days([done, early], back=3, now=now)
    assert "2026-11-05" not in c and "2026-11-04" in c and "2026-11-03" in c, c
    print("sli selftest: all checks passed")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "selftest":
        selftest()
        raise SystemExit(0)
    aws = shutil.which("aws")
    if not aws:
        raise SystemExit("aws CLI not found")
    region = os.environ.get("AWS_REGION", "eu-north-1")
    account = os.environ.get("BAKO_ACCOUNT", "483272865934")
    st = Store(aws, region, os.environ.get("BAKO_PROFILE", "bakolab"), account)
    if len(sys.argv) > 2 and sys.argv[1] == "rollup":
        s, msg = rollup_day(st, sys.argv[2])
        print(msg)
        raise SystemExit(0 if s else 1)
    ok, msgs = rollup_missing(st)
    print("\n".join(msgs))
    raise SystemExit(0 if ok else 1)
