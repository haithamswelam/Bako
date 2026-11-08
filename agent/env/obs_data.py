"""Facts about the running Bako app: backend pods and the database. Shared by the dashboard (live view) and the agent (daily summary at STOP).

Safety, in one place:
- Database: ONLY the fixed queries below, inside a read-only session (default_transaction_read_only=on, 20 s limit).
  They read structure, sizes and counts. No query ever selects a row's content. The password is read by the pod from the cluster secret.
- Logs: a log line is reduced to its SHAPE (numbers, ids, quoted text, e-mail addresses and addresses removed) before it is stored or shown,
  so a message that happened to contain something a person typed cannot leak.
- Nothing here changes anything in the cluster, except a short-lived pod for the database read (deleted afterwards).
Everything returns (data, reason): a problem is a message, never an exception.
"""
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone

import redact

NS = os.environ.get("BAKO_NAMESPACE", "bako")
DB_SECRET = os.environ.get("BAKO_DB_SECRET", "bako-db-credentials")
DAILY_PREFIX = "obs-daily"
MAX_SHAPES = 12


## ---------------------------------------------------------------
## running kubectl safely
## ---------------------------------------------------------------
def _run(cmd, env, timeout=60):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env, stdin=subprocess.DEVNULL,
                           encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return p.returncode, (p.stdout or ""), (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, "", "timed out"
    except OSError as e:
        return 127, "", str(e)


def cluster_ok(kubectl, env, account):
    """(True, "") when kubectl exists and points at the expected account's cluster and the namespace answers."""
    if not kubectl:
        return False, "kubectl was not found on this computer"
    rc, out, err = _run([kubectl, "config", "current-context"], env, 20)
    if rc != 0 or (account and account not in out):
        return False, "kubectl is not pointed at your Bako cluster (the lab is probably down)"
    rc, out, err = _run([kubectl, "get", "namespace", NS, "-o", "name", "--request-timeout=10s"], env, 25)
    if rc != 0:
        return False, "the cluster does not answer, or the namespace 'bako' is not there yet (the lab is down or still starting)"
    return True, ""


## ---------------------------------------------------------------
## 1. LOG LINES -> SHAPES
## ---------------------------------------------------------------
_RX = [
    (re.compile(r"\b[\w.+-]+@[\w-]+(\.[\w-]+)+\b"), "<email>"),
    (re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"), "<id>"),
    (re.compile(r"\b\d{1,3}(\.\d{1,3}){3}(:\d+)?\b"), "<ip>"),
    (re.compile(r"\beyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]*"), "<token>"),
    (re.compile(r"\b[0-9a-fA-F]{12,}\b"), "<hex>"),
    (re.compile(r"\b[A-Za-z0-9+/_-]{32,}={0,2}"), "<blob>"),
    (re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?Z?"), ""),            # time stamps
    (re.compile(r"\b\d+(\.\d+)?\b"), "N"),
]
SQL = re.compile(r"\b(select|insert\s+into|update|delete\s+from)\b", re.I)
LEVEL = re.compile(r"\b(FATAL|CRITICAL|ERROR|ERR|WARN(?:ING)?|Traceback|Exception|panic)\b", re.I)
HTTP_LINE = re.compile(r'"(?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS) [^"]*" (\d{3})\b')


def _quotes(s):
    """Text between quotes can be something a person typed. A clean pair ("..." once, or '...' once) is replaced; any other use of a
    quote mark (odd, several, nested) cuts the line at the first one, because we cannot tell where the typed text ends."""
    for q in ("'", '"'):
        n = s.count(q)
        if n == 2:
            i = s.index(q); j = s.index(q, i + 1)
            s = s[:i] + q + "…" + q + s[j + 1:]
        elif n != 0:
            s = s[:s.index(q)] + "<cut>"
    return s


def shape(line):
    """One log line reduced to its shape. Never returns more than 140 characters."""
    s = redact.redact(line)
    m = SQL.search(s)
    if m:                                                   # an SQL statement in a log can carry values: keep only what came before it
        s = s[:m.start()] + "<sql statement>"
    s = _quotes(s)
    for rx, rep in _RX:
        s = rx.sub(rep, s)
    return re.sub(r"\s+", " ", s).strip()[:140]


def level_of(line):
    m = LEVEL.search(line)
    if not m:
        return None
    w = m.group(1).upper()
    return "warn" if w.startswith("WARN") else "error"


def scan_logs(lines):
    """-> {lines, errors, warnings, top:[{shape,n,level}], http:{"2xx":n,...}}. Pure."""
    errors = warns = 0
    shapes, http = {}, {}
    for ln in lines:
        m = HTTP_LINE.search(ln)
        if m:
            k = m.group(1)[0] + "xx"
            http[k] = http.get(k, 0) + 1
            if k != "5xx":
                continue                       # a normal access line is not a problem; a 5xx access line is
        lv = level_of(ln) or ("error" if m else None)
        if not lv:
            continue
        errors += lv == "error"
        warns += lv == "warn"
        key = (lv, shape(ln))
        shapes[key] = shapes.get(key, 0) + 1
    top = [{"level": k[0], "shape": k[1], "n": n} for k, n in sorted(shapes.items(), key=lambda kv: -kv[1])[:MAX_SHAPES]]
    return {"lines": len(lines), "errors": errors, "warnings": warns, "top": top, "http": http}


## ---------------------------------------------------------------
## 2. BACKEND PODS (live, kubectl)
## ---------------------------------------------------------------
def _tag(image):
    ## "123.dkr.ecr.eu-north-1.amazonaws.com/bako-backend:abc1234" -> "bako-backend:abc1234"
    return image.rsplit("/", 1)[-1][:60]


def parse_pods(text):
    rows = []
    for p in (json.loads(text).get("items") or []):
        md, spec, stt = p.get("metadata", {}), p.get("spec", {}), p.get("status", {})
        cs = stt.get("containerStatuses") or []
        last = ""
        for c in cs:
            t = (c.get("lastState") or {}).get("terminated") or {}
            if t:
                last = f"{t.get('reason', 'ended')} (exit {t.get('exitCode', '?')})"
        res = {}
        for c in spec.get("containers", []):
            r = c.get("resources") or {}
            res = {"cpu_req": (r.get("requests") or {}).get("cpu"), "mem_req": (r.get("requests") or {}).get("memory"),
                   "cpu_lim": (r.get("limits") or {}).get("cpu"), "mem_lim": (r.get("limits") or {}).get("memory")}
        rows.append({"name": md.get("name", "?"), "app": (md.get("labels") or {}).get("app") or md.get("name", "?").rsplit("-", 2)[0],
                     "phase": stt.get("phase", "?"), "ready": f"{sum(1 for c in cs if c.get('ready'))}/{len(cs) or len(spec.get('containers', []))}",
                     "restarts": sum(int(c.get("restartCount", 0)) for c in cs), "last_end": last,
                     "started": stt.get("startTime", ""), "node": spec.get("nodeName", ""),
                     "image": _tag((spec.get("containers") or [{}])[0].get("image", "")), **res})
    return sorted(rows, key=lambda r: r["name"])


def parse_deployments(text):
    out = []
    for d in (json.loads(text).get("items") or []):
        st_, sp = d.get("status", {}), d.get("spec", {})
        out.append({"name": d["metadata"]["name"], "want": sp.get("replicas", 0), "ready": st_.get("readyReplicas", 0),
                    "updated": st_.get("updatedReplicas", 0),
                    "image": _tag(((sp.get("template") or {}).get("spec", {}).get("containers") or [{}])[0].get("image", ""))})
    return out


def _mem_mi(s):
    if not s:
        return None
    m = re.match(r"^(\d+(?:\.\d+)?)(Ki|Mi|Gi|K|M|G)?$", s)
    if not m:
        return None
    v, u = float(m.group(1)), m.group(2) or ""
    return {"Ki": v / 1024, "Mi": v, "Gi": v * 1024, "K": v / 1049, "M": v * 0.954, "G": v * 954, "": v / 1048576}[u]


def _cpu_m(s):
    if not s:
        return None
    return float(s[:-1]) if s.endswith("m") else float(s) * 1000


def parse_top(text):
    """kubectl top pods --no-headers: 'name  12m  95Mi' -> {name: {cpu_m, mem_mi}}"""
    out = {}
    for ln in text.splitlines():
        f = ln.split()
        if len(f) >= 3 and _cpu_m(f[1]) is not None:
            out[f[0]] = {"cpu_m": _cpu_m(f[1]), "mem_mi": _mem_mi(f[2])}
    return out


def parse_events(text, limit=15):
    ev = []
    for e in (json.loads(text).get("items") or []):
        if e.get("type") != "Warning":
            continue
        ev.append({"when": (e.get("lastTimestamp") or e.get("eventTime") or "")[:19], "reason": e.get("reason", ""),
                   "object": (e.get("involvedObject") or {}).get("name", ""), "n": e.get("count", 1),
                   "message": shape(e.get("message", ""))})
    return sorted(ev, key=lambda x: x["when"], reverse=True)[:limit]


def backend_live(kubectl, env, account, since="1h"):
    """-> (facts, reason). facts = {at, pods, deployments, top, top_why, events, logs:{app: scan}}"""
    ok, why = cluster_ok(kubectl, env, account)
    if not ok:
        return None, why
    f = {"at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), "pods": [], "deployments": [], "top": {}, "top_why": "",
         "events": [], "logs": {}}
    base = [kubectl, "-n", NS, "--request-timeout=20s"]
    rc, out, err = _run(base + ["get", "pods", "-o", "json"], env, 40)
    if rc != 0:
        return None, "could not list the pods: " + redact.redact(err)[-160:]
    try:
        f["pods"] = parse_pods(out)
        rc, out, err = _run(base + ["get", "deployments", "-o", "json"], env, 40)
        f["deployments"] = parse_deployments(out) if rc == 0 else []
        rc, out, err = _run(base + ["get", "events", "-o", "json"], env, 40)
        f["events"] = parse_events(out) if rc == 0 else []
    except (ValueError, KeyError) as e:
        return None, f"unexpected answer from kubectl: {e}"
    rc, out, err = _run(base + ["top", "pods", "--no-headers"], env, 40)
    if rc == 0:
        f["top"] = parse_top(out)
    else:
        f["top_why"] = "CPU and memory are not available: the cluster has no metrics-server (kubectl top does not answer)."
    for d in f["deployments"]:
        rc, out, err = _run(base + ["logs", f"deploy/{d['name']}", f"--since={since}", "--tail=1500", "--all-containers"], env, 60)
        if rc == 0:
            f["logs"][d["name"]] = scan_logs(out.splitlines())
        else:
            f["logs"][d["name"]] = {"lines": 0, "errors": 0, "warnings": 0, "top": [], "http": {}, "why": redact.redact(err)[-120:]}
    return f, ""


## ---------------------------------------------------------------
## 3. DATABASE (live: fixed read-only queries through a short-lived pod; RDS and CloudWatch through the AWS CLI)
## ---------------------------------------------------------------
Q_PUBLIC_TABLES = (
    "select c.relname, coalesce((xpath('/row/c/text()', query_to_xml(format('select count(*) as c from %I.%I', n.nspname, c.relname), false, true, '')))[1]::text::bigint, 0), "
    "pg_total_relation_size(c.oid), pg_relation_size(c.oid), pg_indexes_size(c.oid), coalesce(s.n_dead_tup, 0), "
    "coalesce(to_char(greatest(s.last_autovacuum, s.last_vacuum), 'YYYY-MM-DD HH24:MI'), '') "
    "from pg_class c join pg_namespace n on n.oid = c.relnamespace left join pg_stat_user_tables s on s.relid = c.oid "
    "where c.relkind = 'r' and n.nspname = 'public' order by 3 desc")
DB_QUERIES = [
    ("meta", "select current_setting('server_version'), pg_database_size(current_database()), current_setting('max_connections')"),
    ("tables", Q_PUBLIC_TABLES),
    ("columns", "select table_name, column_name, data_type, is_nullable, coalesce(character_maximum_length::text, '') from information_schema.columns "
                "where table_schema = 'public' order by table_name, ordinal_position"),
    ("indexes", "select s.relname, s.indexrelname, s.idx_scan, pg_relation_size(s.indexrelid), i.indexdef from pg_stat_user_indexes s "
                "join pg_indexes i on i.indexname = s.indexrelname and i.schemaname = s.schemaname order by 1, 2"),
    ("constraints", "select conrelid::regclass::text, conname, contype, pg_get_constraintdef(oid) from pg_constraint "
                    "where connamespace = 'public'::regnamespace order by 1, 2"),
    ("connections", "select coalesce(state, 'background'), count(*) from pg_stat_activity where datname = current_database() group by 1 order by 2 desc"),
    ("statements", "select query, calls, round(mean_exec_time)::bigint, round(total_exec_time)::bigint from pg_stat_statements "
                   "where dbid = (select oid from pg_database where datname = current_database()) order by total_exec_time desc limit 8"),
]


def psql_args():
    args = ["psql", "-X", "-q", "-tA", "-F", "|"]
    for name, sql in DB_QUERIES:
        args += ["-c", f"select '##{name}'", "-c", sql]
    return args


def parse_db(text):
    """Pure. psql output with '##name' marker rows -> structured dict."""
    sec, cur = {}, None
    for ln in text.splitlines():
        if ln.startswith("##") and ln[2:] in dict(DB_QUERIES):
            cur = ln[2:]; sec[cur] = []
        elif cur and ln.strip() and not ln.startswith("ERROR") and not ln.startswith("LINE ") and not ln.startswith("psql:"):
            sec[cur].append(ln)
    out = {"ok": "meta" in sec and bool(sec.get("meta"))}
    if sec.get("meta"):
        v, size, maxc = (sec["meta"][0].split("|") + ["", "0", "0"])[:3]
        out["meta"] = {"version": v, "size_bytes": int(size or 0), "max_connections": int(maxc or 0)}
    out["tables"] = []
    for ln in sec.get("tables", []):
        f = ln.split("|")
        if len(f) >= 7:
            out["tables"].append({"name": f[0], "rows": int(f[1]), "total_bytes": int(f[2]), "table_bytes": int(f[3]),
                                  "index_bytes": int(f[4]), "dead": int(f[5]), "vacuum": f[6]})
    cols = {}
    for ln in sec.get("columns", []):
        f = ln.split("|")
        if len(f) >= 5:
            cols.setdefault(f[0], []).append({"name": f[1], "type": f[2] + (f"({f[4]})" if f[4] else ""), "null": f[3] == "YES"})
    out["columns"] = cols
    idx = {}
    for ln in sec.get("indexes", []):
        f = ln.split("|", 4)
        if len(f) == 5:
            idx.setdefault(f[0], []).append({"name": f[1], "scans": int(f[2]), "bytes": int(f[3]), "def": f[4]})
    out["indexes"] = idx
    con = {}
    for ln in sec.get("constraints", []):
        f = ln.split("|", 3)
        if len(f) == 4:
            con.setdefault(f[0], []).append({"name": f[1], "kind": {"p": "primary key", "f": "foreign key", "u": "unique", "c": "check"}.get(f[2], f[2]), "def": f[3]})
    out["constraints"] = con
    out["connections"] = {}
    for ln in sec.get("connections", []):
        f = ln.split("|")
        if len(f) == 2 and f[1].isdigit():
            out["connections"][f[0]] = int(f[1])
    out["statements"] = []
    for ln in sec.get("statements", []):
        f = ln.rsplit("|", 3)
        if len(f) == 4 and f[1].isdigit():
            out["statements"].append({"query": re.sub(r"\s+", " ", f[0])[:200], "calls": int(f[1]),
                                      "mean_ms": int(f[2]), "total_ms": int(f[3])})
    out["statements_available"] = "statements" in sec and bool(sec.get("statements"))
    return out


def db_live(kubectl, env, account, host, dbname):
    """-> (facts, reason). Read-only session; the pod reads the password from the cluster secret itself."""
    ok, why = cluster_ok(kubectl, env, account)
    if not ok:
        return None, why
    if not host:
        return None, "the database has no address yet"
    rc, out, err = _run([kubectl, "get", "secret", DB_SECRET, "-n", NS, "-o", "name"], env, 30)
    if rc != 0:
        return None, f"secret {DB_SECRET} does not exist yet in namespace {NS}"
    pod = "bako-dbinfo"
    _run([kubectl, "delete", "pod", pod, "-n", NS, "--ignore-not-found", "--wait=true"], env, 60)
    overrides = {"spec": {"containers": [{
        "name": pod, "image": "postgres:16", "command": psql_args(),
        "env": [{"name": "PGHOST", "value": host}, {"name": "PGDATABASE", "value": dbname or "bako"},
                {"name": "PGOPTIONS", "value": "-c default_transaction_read_only=on -c statement_timeout=20000"},
                {"name": "PGUSER", "valueFrom": {"secretKeyRef": {"name": DB_SECRET, "key": "username"}}},
                {"name": "PGPASSWORD", "valueFrom": {"secretKeyRef": {"name": DB_SECRET, "key": "password"}}}]}]}}
    rc, out, err = _run([kubectl, "run", pod, "-n", NS, "--image=postgres:16", "--restart=Never", "--rm", "-i", "--quiet",
                         "--overrides", json.dumps(overrides)], env, 240)
    _run([kubectl, "delete", "pod", pod, "-n", NS, "--ignore-not-found", "--wait=false"], env, 30)
    facts = parse_db(out + "\n" + err)
    if not facts["ok"]:
        return None, "the database did not answer: " + redact.redact((out + err).strip())[-200:]
    facts["at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    return facts, ""


def rds_info(store, db_id):
    """-> (info|None, reason). Instance facts from AWS (no password, no endpoint credentials)."""
    rc, out = store.run("rds", "describe-db-instances", "--db-instance-identifier", db_id, "--output", "json", timeout=60)
    if rc != 0:
        return None, ("the database does not exist right now (the lab is down)" if "DBInstanceNotFound" in out else out.strip()[-200:])
    try:
        i = json.loads(out[out.index("{"):])["DBInstances"][0]
    except (ValueError, KeyError, IndexError):
        return None, "could not read the answer from AWS"
    return {"status": i.get("DBInstanceStatus"), "class": i.get("DBInstanceClass"), "engine": f"{i.get('Engine')} {i.get('EngineVersion')}",
            "storage_gb": i.get("AllocatedStorage"), "storage_type": i.get("StorageType"), "multi_az": i.get("MultiAZ"),
            "host": (i.get("Endpoint") or {}).get("Address", ""), "dbname": i.get("DBName") or "bako",
            "encrypted": i.get("StorageEncrypted"), "backup_days": i.get("BackupRetentionPeriod")}, ""


def rds_snapshots(store, db_id):
    rc, out = store.run("rds", "describe-db-snapshots", "--db-instance-identifier", db_id, "--snapshot-type", "manual", "--output", "json", timeout=90)
    if rc != 0:
        return [], out.strip()[-160:]
    try:
        snaps = json.loads(out[out.index("{"):])["DBSnapshots"]
    except (ValueError, KeyError):
        return [], "could not read the answer from AWS"
    snaps.sort(key=lambda s: str(s.get("SnapshotCreateTime", "")), reverse=True)
    return [{"name": s["DBSnapshotIdentifier"], "at": str(s.get("SnapshotCreateTime", ""))[:16].replace("T", " "),
             "gb": s.get("AllocatedStorage"), "status": s.get("Status")} for s in snaps[:8]], ""


def cloudwatch(store, db_id, hours=72):
    """CloudWatch keeps RDS metrics after the instance is deleted, so this works with the lab down too.
    -> {metric: [(iso_time, value), ...]}, reason"""
    from datetime import timedelta
    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(hours=hours)
    want = {"CPUUtilization": "Average", "DatabaseConnections": "Maximum", "FreeStorageSpace": "Minimum", "FreeableMemory": "Minimum"}
    out, why = {}, ""
    for m, stat in want.items():
        rc, txt = store.run("cloudwatch", "get-metric-statistics", "--namespace", "AWS/RDS", "--metric-name", m,
                            "--dimensions", f"Name=DBInstanceIdentifier,Value={db_id}", "--start-time", start.isoformat(), "--end-time", end.isoformat(),
                            "--period", "3600", "--statistics", stat, "--output", "json", timeout=60)
        if rc != 0:
            why = txt.strip()[-160:]
            continue
        try:
            pts = json.loads(txt[txt.index("{"):])["Datapoints"]
        except (ValueError, KeyError):
            continue
        out[m] = sorted(((p["Timestamp"][:16], p[stat]) for p in pts), key=lambda x: x[0])
    return out, why


## ---------------------------------------------------------------
## 4. DAILY SUMMARY (saved at STOP, because pods and the database are gone the next morning)
## ---------------------------------------------------------------
def make_daily(day, backend, db, traces=None):
    """Small and free of anything a person typed: counts, sizes, restart numbers, log SHAPES, and per-endpoint time splits (obs_traces.compact)."""
    out = {"schema": 1, "day": day, "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if backend:
        top = []
        for app, sc in backend["logs"].items():
            for t in sc["top"][:5]:
                top.append({"app": app, **t})
        out["backend"] = {"pods": [{"name": p["name"], "app": p["app"], "restarts": p["restarts"], "last_end": p["last_end"]} for p in backend["pods"]],
                          "restarts": sum(p["restarts"] for p in backend["pods"]),
                          "errors": sum(s["errors"] for s in backend["logs"].values()),
                          "warnings": sum(s["warnings"] for s in backend["logs"].values()),
                          "top": top[:10], "events": len(backend["events"])}
    if db:
        out["db"] = {"size_bytes": db["meta"]["size_bytes"], "connections": sum(db["connections"].values()),
                     "tables": [{"name": t["name"], "rows": t["rows"], "bytes": t["total_bytes"]} for t in db["tables"]]}
    if traces:
        out["traces"] = traces
    return out


def save_daily(store, summary):
    key = f"s3://{store.bucket}/{DAILY_PREFIX}/{summary['day']}.json"
    rc, out = store.run("s3", "cp", "-", key, "--only-show-errors", "--sse", "AES256", stdin=json.dumps(summary, separators=(",", ":")))
    return rc == 0, out.strip()[-200:]


def read_daily(store):
    """-> (list newest first, message)"""
    tmp = tempfile.mkdtemp(prefix="bako-obs-")
    try:
        rc, out = store.run("s3", "sync", f"s3://{store.bucket}/{DAILY_PREFIX}/", tmp, "--only-show-errors")
        if rc != 0:
            return [], "Could not read the saved facts from S3: " + out.strip()[-160:]
        days = []
        for n in os.listdir(tmp):
            if n.endswith(".json"):
                try:
                    with open(os.path.join(tmp, n), encoding="utf-8") as fh:
                        days.append(json.load(fh))
                except (OSError, ValueError):
                    pass
        return sorted(days, key=lambda d: d["day"], reverse=True), ""
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def human_bytes(n):
    n = float(n or 0)
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024


## ---------------------------------------------------------------
## selftest: python obs_data.py selftest
## ---------------------------------------------------------------
def selftest():
    s = shape('2026-11-08T10:00:01.123Z ERROR user a.b@x.com saved "Coffee 45.50" for id 9f1c2d3e-1111-2222-3333-444455556666 from 10.0.1.5:5432 count=17')
    assert "a.b@x.com" not in s and "Coffee" not in s and "9f1c" not in s and "10.0.1" not in s and "17" not in s, s
    assert "ERROR" in s and "<email>" in s and "<id>" in s and "<ip>" in s, s
    s2 = shape("WARNING slow query 812 ms for 'select * from transactions where note = 'Coffee 45.50''")
    assert "Coffee" not in s2 and "45" not in s2, s2
    s3 = shape("ERROR could not parse value 'Tea 'house' 12' in field")
    assert "Tea" not in s3 and "house" not in s3, s3
    lines = ['INFO: 10.0.0.1:5 - "GET /api/goals HTTP/1.1" 200 OK', 'INFO: 10.0.0.1:5 - "POST /api/transactions HTTP/1.1" 500 Internal',
             "ERROR db timeout after 30 s on query 4411", "ERROR db timeout after 31 s on query 4412", "WARNING slow request 812 ms", "plain info line"]
    sc = scan_logs(lines)
    assert sc["errors"] == 3 and sc["warnings"] == 1 and sc["http"] == {"2xx": 1, "5xx": 1}, sc
    assert sc["top"][0]["n"] == 2 and "N" in sc["top"][0]["shape"], sc["top"]
    pods = json.dumps({"items": [{"metadata": {"name": "backend-6d9f-abc", "labels": {"app": "backend"}},
        "spec": {"nodeName": "ip-1", "containers": [{"image": "1.dkr.ecr.eu-north-1.amazonaws.com/bako-backend:abc1234",
                 "resources": {"requests": {"cpu": "100m", "memory": "128Mi"}, "limits": {"memory": "256Mi"}}}]},
        "status": {"phase": "Running", "startTime": "2026-11-08T08:00:00Z", "containerStatuses": [
            {"ready": True, "restartCount": 2, "lastState": {"terminated": {"reason": "OOMKilled", "exitCode": 137}}}]}}]})
    p = parse_pods(pods)[0]
    assert p["restarts"] == 2 and "OOMKilled" in p["last_end"] and p["image"] == "bako-backend:abc1234" and p["ready"] == "1/1", p
    assert parse_top("backend-6d9f-abc 12m 95Mi\n")["backend-6d9f-abc"] == {"cpu_m": 12.0, "mem_mi": 95.0}
    txt = "##meta\n16.4|9437184|87\n##tables\ntransactions|463|1048576|524288|524288|3|2026-11-08 02:10\nusers|4|65536|8192|57344|0|\n" \
          "##columns\ntransactions|id|uuid|NO|\ntransactions|note|character varying|YES|120\n##indexes\ntransactions|transactions_pkey|52|16384|CREATE UNIQUE INDEX transactions_pkey ON public.transactions USING btree (id)\n" \
          "##constraints\ntransactions|transactions_user_fk|f|FOREIGN KEY (user_id) REFERENCES users(id)\n##connections\nactive|1\nidle|4\n" \
          "##statements\nERROR:  relation \"pg_stat_statements\" does not exist\n"
    d = parse_db(txt)
    assert d["ok"] and d["meta"]["size_bytes"] == 9437184 and d["tables"][0]["rows"] == 463 and d["columns"]["transactions"][1]["type"] == "character varying(120)", d
    assert d["indexes"]["transactions"][0]["scans"] == 52 and d["constraints"]["transactions"][0]["kind"] == "foreign key", d
    assert d["connections"] == {"active": 1, "idle": 4} and d["statements_available"] is False, d
    day = make_daily("2026-11-08", {"pods": parse_pods(pods), "events": [], "logs": {"backend": sc}}, d)
    j = json.dumps(day)
    assert "Coffee" not in j and day["db"]["tables"][0]["name"] == "transactions" and day["backend"]["restarts"] == 2, day
    sql_all = " ".join(q for _, q in DB_QUERIES).lower()
    for bad in ("insert ", "update ", "delete ", "drop ", "alter ", "create ", "truncate", "grant "):
        assert bad not in sql_all, bad
    print("obs_data selftest: all checks passed")


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["selftest"]:
        selftest()
