## ---------------------------------------------------------------
## usage.py - the daily report: how long the lab ran, estimated cost, tokens, real AWS cost.
## Everything is read from files that already exist (the agent's trace files) plus one small
## file, agent/env/reports/usage.json, where the dashboard saves chat tokens and AWS costs it fetched.
## The lab "ran" from a successful terraform apply until the destroy finished.
## ---------------------------------------------------------------
import calendar, glob, json, os, re, subprocess
from datetime import datetime, timedelta

def _usage_path(repo):
    return os.path.join(repo, "agent", "env", "reports", "usage.json")

def load(repo):
    try:
        with open(_usage_path(repo), encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}

def save(repo, data):
    try:
        os.makedirs(os.path.dirname(_usage_path(repo)), exist_ok=True)
        with open(_usage_path(repo), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1)
    except OSError:
        pass

def add_chat_tokens(repo, n, when=None):
    day = (when or datetime.now()).strftime("%Y-%m-%d")
    data = load(repo)
    tokens = data.setdefault("chat_tokens", {})
    tokens[day] = tokens.get(day, 0) + int(n)
    save(repo, data)

## ---- reading the traces ----
def _events(repo, since_day):
    """Yield (datetime, event) from every trace file dated since_day (a date), oldest first."""
    rows = []
    for path in glob.glob(os.path.join(repo, "agent", "env", "reports", "trace-*.jsonl")):
        m = re.search(r"trace-(\d{8})-(\d{6})", os.path.basename(path))
        if not m:
            continue
        day = datetime.strptime(m.group(1), "%Y%m%d")
        if day.date() < since_day:
            continue
        last_t = None
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    try:
                        ev = json.loads(line)
                        h, mi, s = (int(x) for x in ev.get("time", "00:00:00").split(":"))
                    except (ValueError, TypeError):
                        continue
                    if last_t is not None and (h, mi, s) < last_t:
                        day += timedelta(days=1)             # the run went past midnight
                    last_t = (h, mi, s)
                    rows.append((day.replace(hour=h, minute=mi, second=s), ev))
        except OSError:
            continue
    rows.sort(key=lambda r: r[0])
    return rows

def _is_up_event(ev):
    if ev.get("event") == "stage" and ev.get("id") == "apply" and ev.get("status") == "done":
        return True
    return ev.get("event") in ("tool_result", "step_result") and \
        (ev.get("tool") == "terraform_apply" or ev.get("step") == "terraform_apply") and \
        str(ev.get("result", "")).startswith("apply OK")

def _is_down_event(ev):
    if ev.get("event") == "outcome" and ev.get("destroyed") is True:
        return True
    return ev.get("event") == "step_result" and ev.get("step") == "terraform_destroy" and \
        str(ev.get("result", "")).startswith("destroy OK")

def _split_by_day(start, end, out):
    cur = start
    while cur < end:
        midnight = (cur + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        stop = min(end, midnight)
        key = cur.strftime("%Y-%m-%d")
        out[key] = out.get(key, 0) + (stop - cur).total_seconds()
        cur = stop

def lab_seconds(repo, now, up_now, days_back=4):
    """{ 'YYYY-MM-DD': seconds the lab was up }. An interval that never closed ends now if the lab is up
    (up_now), otherwise at the last event we have."""
    since = (now - timedelta(days=days_back)).date()
    rows = _events(repo, since)
    out, up_since, last_ts = {}, None, None
    for ts, ev in rows:
        last_ts = ts
        if _is_up_event(ev) and up_since is None:
            up_since = ts
        elif _is_down_event(ev) and up_since is not None:
            _split_by_day(up_since, ts, out)
            up_since = None
    if up_since is not None:
        _split_by_day(up_since, now if up_now else (last_ts or up_since), out)
    return out

def agent_tokens(repo, days_back=4, now=None):
    now = now or datetime.now()
    since = (now - timedelta(days=days_back)).date()
    out = {}
    for ts, ev in _events(repo, since):
        if ev.get("event") == "model_reply":
            key = ts.strftime("%Y-%m-%d")
            out[key] = out.get(key, 0) + int(ev.get("tokens_in", 0) or 0) + int(ev.get("tokens_out", 0) or 0)
    return out

def day_counts(repo, now, days_back):
    """{ 'YYYY-MM-DD': {'starts': n, 'stops': n, 'ready': n} } from the trace files."""
    since = (now - timedelta(days=days_back)).date()
    out = {}
    for ts, ev in _events(repo, since):
        c = out.setdefault(ts.strftime("%Y-%m-%d"), {"starts": 0, "stops": 0, "ready": 0})
        if _is_up_event(ev):
            c["starts"] += 1
        if _is_down_event(ev):
            c["stops"] += 1
        if ev.get("event") == "outcome" and ev.get("ready") is True:
            c["ready"] += 1
    return out

def get_budget(repo):
    try:
        return float(load(repo).get("budget", 0) or 0)
    except (TypeError, ValueError):
        return 0.0

def set_budget(repo, value):
    data = load(repo)
    data["budget"] = max(0.0, float(value))
    save(repo, data)

def report(repo, hourly, up_now, now=None, n_days=3):
    """A list of rows, newest first: date, label, seconds, est_cost, tokens, aws_cost (or None), starts, stops, ready."""
    now = now or datetime.now()
    back = n_days + 2                       # a little more history, so an interval that began earlier is still counted
    secs = lab_seconds(repo, now, up_now, days_back=back)
    ag = agent_tokens(repo, days_back=back, now=now)
    counts = day_counts(repo, now, back)
    data = load(repo)
    chat = data.get("chat_tokens", {})
    aws = data.get("aws_cost", {})
    rows = []
    for i in range(n_days):
        d = (now - timedelta(days=i)).strftime("%Y-%m-%d")
        s = secs.get(d, 0)
        c = counts.get(d, {})
        rows.append({"date": d, "label": "Today" if i == 0 else "Yesterday" if i == 1 else d,
                     "starts": c.get("starts", 0), "stops": c.get("stops", 0), "ready": c.get("ready", 0),
                     "seconds": s, "est_cost": s / 3600 * hourly,
                     "tokens": int(chat.get(d, 0)) + int(ag.get(d, 0)),
                     "aws_cost": (aws.get(d) or {}).get("amount")})
    return rows

def fmt_duration(sec):
    sec = int(round(sec))
    if sec < 60:
        return "0m" if sec == 0 else "<1m"
    h, m = divmod(sec // 60, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"

def fmt_tokens(n):
    return f"{n/1000:.1f}k" if n >= 1000 else str(n)

## ---- the real AWS cost (Cost Explorer: each request costs about $0.01) ----
def fetch_aws_costs(aws, profile, repo, now=None, n_days=3):
    """Asks Cost Explorer for the last n_days and saves them. Returns (ok, message)."""
    if not aws:
        return False, "the aws tool was not found"
    now = now or datetime.now()
    start = (now - timedelta(days=n_days - 1)).strftime("%Y-%m-%d")
    end = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    cmd = [aws, "ce", "get-cost-and-usage", "--time-period", f"Start={start},End={end}",
           "--granularity", "DAILY", "--metrics", "UnblendedCost", "--region", "us-east-1", "--output", "json"]
    if profile and not os.environ.get("AWS_PROFILE"):
        cmd += ["--profile", profile]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL,
                           encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except Exception as e:
        return False, str(e)
    if p.returncode != 0:
        msg = (p.stderr or p.stdout).strip()
        if "AccessDenied" in msg or "not authorized" in msg:
            return False, "your AWS login is not allowed to read costs (needs ce:GetCostAndUsage)."
        return False, msg[:300]
    try:
        results = json.loads(p.stdout)["ResultsByTime"]
    except (ValueError, KeyError):
        return False, "unexpected answer from AWS"
    data = load(repo)
    store = data.setdefault("aws_cost", {})
    for r in results:
        day = r["TimePeriod"]["Start"]
        amt = float(r["Total"]["UnblendedCost"]["Amount"])
        store[day] = {"amount": round(amt, 2), "fetched": now.strftime("%Y-%m-%d %H:%M")}
    save(repo, data)
    return True, "Real AWS cost updated. Today's number can still be incomplete: AWS fills it in up to a day later."

def month_summary(repo, hourly, up_now, now=None):
    """Spent so far this month (the real AWS number where we have it, else the estimate), the budget and a forecast."""
    now = now or datetime.now()
    rows = report(repo, hourly, up_now, now, n_days=now.day)
    spent = sum(r["aws_cost"] if r["aws_cost"] is not None else r["est_cost"] for r in rows)
    real_days = sum(1 for r in rows if r["aws_cost"] is not None)
    days_in_month = calendar.monthrange(now.year, now.month)[1]
    forecast = spent / now.day * days_in_month if now.day else 0.0
    budget = get_budget(repo)
    return {"spent": spent, "real_days": real_days, "days": now.day, "days_in_month": days_in_month,
            "forecast": forecast, "budget": budget, "left": budget - spent if budget else None,
            "hours": sum(r["seconds"] for r in rows) / 3600}


## ---------------------------------------------------------------
## CHAT COST (what each question to Bako costs in dollars) and the REFERENCE for "too expensive"
## Source of the facts: agent/env/reports/chat-traces.jsonl (one line per message, written by bako_chat.py).
## Prices are per 1 million tokens. The defaults are from OpenAI's page for gpt-5.4-nano
## (developers.openai.com/api/docs/models/gpt-5.4-nano, read 2026-10-24). They are editable in Reports.
## ---------------------------------------------------------------
DEFAULT_PRICES = {"in": 0.20, "cached": 0.02, "out": 1.25}

def get_prices(repo):
    p = load(repo).get("prices") or {}
    out = dict(DEFAULT_PRICES)
    for k in out:
        try:
            if p.get(k) is not None:
                out[k] = float(p[k])
        except (TypeError, ValueError):
            pass
    return out

def set_prices(repo, pin, pcached, pout):
    data = load(repo)
    data["prices"] = {"in": max(0.0, float(pin)), "cached": max(0.0, float(pcached)), "out": max(0.0, float(pout))}
    save(repo, data)

def turn_cost(tokens_in, cached, tokens_out, prices):
    """Dollars. Cached input tokens are billed at the lower cached price; the rest of the input at the normal price."""
    cached = min(cached, tokens_in)
    return ((tokens_in - cached) * prices["in"] + cached * prices["cached"] + tokens_out * prices["out"]) / 1_000_000

def _median(xs):
    xs = sorted(xs)
    n = len(xs)
    return 0 if not n else (xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2)

def questions(repo, prices=None, limit=300):
    """Every recorded message, newest first: tokens, cost, how many tool calls, what part was fixed overhead."""
    prices = prices or get_prices(repo)
    path = os.path.join(repo, "agent", "env", "reports", "chat-traces.jsonl")
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return []
    rows = []
    for line in lines[-limit:]:
        try:
            t = json.loads(line)
        except ValueError:
            continue
        rounds = t.get("rounds", [])
        use = [r.get("usage") or {} for r in rounds]
        tin = sum(u.get("prompt_tokens", 0) for u in use)
        cached = sum(u.get("cached_tokens", 0) for u in use)
        tout = sum(u.get("completion_tokens", 0) for u in use)
        first = use[0].get("prompt_tokens", 0) if use else 0
        try:
            when = datetime.strptime(str(t.get("time", ""))[:19], "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            when = None
        rows.append({"time": when, "day": when.strftime("%Y-%m-%d") if when else "?", "question": t.get("question", ""),
                     "tools": [c.get("name") for c in t.get("calls", [])], "calls": len(t.get("calls", [])),
                     "rounds": len(rounds), "in": tin, "cached": cached, "out": tout, "total": tin + tout,
                     "cost": turn_cost(tin, cached, tout, prices), "first_in": first,
                     "stopped_by": t.get("stopped_by"), "mode": t.get("mode", "old"), "error": t.get("error")})
    rows.reverse()
    return rows

def reference(rows):
    """What 'normal' looks like, from your own history.
    floor = the input of the FIRST model call of each message (rules + tool menu + your question): the smallest a message can cost.
    Every extra round sends that floor again, plus the tool results so far.
    typical[k] = median tokens of messages that made k tool calls (0, 1, 2+), once there are 5 of them."""
    firsts = [r["first_in"] for r in rows if r["first_in"]]
    floor = int(_median(firsts)) if firsts else 0
    groups = {}
    for r in rows:
        if r["total"]:
            groups.setdefault(min(r["calls"], 2), []).append(r["total"])
    typical = {k: int(_median(v)) for k, v in groups.items() if len(v) >= 5}
    return {"floor": floor, "typical": typical, "counts": {k: len(v) for k, v in groups.items()}}

def judge(row, ref):
    """-> dict(expected, ratio, flag, fixed, variable, basis). flag: normal / high / very high."""
    k = min(row["calls"], 2)
    fixed = ref["floor"] * row["rounds"] if ref["floor"] else 0
    if k in ref["typical"]:
        expected, basis = ref["typical"][k], f"median of your {ref['counts'][k]} messages with {'2+' if k == 2 else k} tool call(s)"
    else:
        expected, basis = fixed, "the fixed part only (not enough history yet: needs 5 messages with the same number of tool calls)"
    ratio = (row["total"] / expected) if expected else 0
    high, very = (2.0, 3.0) if k in ref["typical"] else (1.5, 3.0)
    flag = "very high" if ratio >= very else "high" if ratio >= high else "normal"
    cut = {"cost_budget": "cut by the cost budget", "token_budget": "cut by the token budget",
           "tool_limit": "cut by the 6-call limit"}.get(row["stopped_by"], "")
    return {"expected": int(expected), "ratio": ratio, "flag": flag, "cut": cut, "fixed": min(fixed, row["total"]),
            "variable": max(0, row["total"] - fixed), "basis": basis}

def chat_cost_by_day(repo, prices=None):
    out = {}
    for r in questions(repo, prices, limit=5000):
        out[r["day"]] = out.get(r["day"], 0.0) + r["cost"]
    return out