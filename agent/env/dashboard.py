## ---------------------------------------------------------------
## BAKO DASHBOARD (phase 1) - one window for the lab.
## Header with Start / Stop, live Lab tab, chat on the right.
## Like ui.py, it contains NO agent logic: it starts "python agent.py <mode>" as a
## separate process and forwards what YOU type. The agent compares the typed word.
##
## Run (from the Bako folder, venv active):
##   streamlit run agent/env/dashboard.py --server.address 127.0.0.1 --browser.gatherUsageStats false
## ---------------------------------------------------------------
import webbrowser, glob, html, json, os, queue, re, shutil, subprocess, sys, threading, time
from datetime import datetime, timezone
import streamlit as st
import keyring
from openai import OpenAI
import bako_chat
import redact
import shellenv
import prmerge
import usage
import flow_tab
import importlib
## Streamlit keeps imported files in memory until the server restarts. Reloading the small helper files
## on every full page run means a copied-in new version is used straight away.
for _m in (redact, shellenv, prmerge, usage, flow_tab):
    importlib.reload(_m)

## ---------------------------------------------------------------
## 1. SETTINGS
## ---------------------------------------------------------------
NAME = "Haitham"
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
LOGO = os.path.join(os.path.dirname(__file__), "bako-logo.png")
BASH = os.environ.get("AGENT_BASH") or shutil.which("bash")
UENV = shellenv.unix_env(BASH)      # lets bash find grep, awk, base64 when started from here
MODEL = os.environ.get("AGENT_MODEL", "gpt-5.4-nano")
HOURLY = float(os.environ.get("BAKO_HOURLY", "0.27"))     # rough lab cost per hour
CLUSTER = os.environ.get("BAKO_CLUSTER", "bako-eks")

## AWS profile and region: read from checks.sh so they are set in ONE place.
## Understands PROFILE=name, PROFILE="name" and PROFILE="${AWS_PROFILE:-name}".
def read_setting(name, fallback):
    try:
        with open(os.path.join(REPO, "agent", "env", "checks.sh"), encoding="utf-8") as f:
            for line in f:
                m = re.match(r"^\s*" + name + r"=(.*)$", line.strip())
                if m:
                    value = m.group(1).split("#")[0].strip().strip("\"'")
                    d = re.search(r":-([^}]*)\}", value)
                    value = d.group(1) if d else value
                    if value and "$" not in value:
                        return value
    except OSError:
        pass
    return fallback

REGION = read_setting("REGION", "eu-north-1")
PROFILE = read_setting("PROFILE", "")
AWS = shutil.which("aws")
KUBECTL = shutil.which("kubectl")
GHCLI = shutil.which("gh")

st.set_page_config(page_title="Bako", page_icon="🤖", layout="wide")

@st.cache_resource
def get_client():
    try:
        key = os.environ.get("OPENAI_API_KEY") or keyring.get_password("bako-agent", "OPENAI_API_KEY")
    except Exception:
        key = None
    return OpenAI(api_key=key) if key else None

## ---------------------------------------------------------------
## 2. THE LOOK (colours from the approved mockup: Warm grey, or Dark with the sidebar switch)
## The palette lives in flow_tab.THEMES so the Flow tab and the rest of the page always agree.
## ---------------------------------------------------------------
ss = st.session_state
THEME_FILE = os.path.join(os.path.expanduser("~"), ".bako_theme")
def load_theme():
    try:
        with open(THEME_FILE, encoding="utf-8") as f:
            name = f.read().strip()
        return name if name in flow_tab.THEMES else "warm"
    except OSError:
        return "warm"
def save_theme(name):
    try:
        with open(THEME_FILE, "w", encoding="utf-8") as f:
            f.write(name)
    except OSError:
        pass
if "theme" not in ss:
    ss.theme = load_theme()
T = flow_tab.THEMES[ss.theme]

CSS = """
@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600&display=swap');
html, body, [class*="css"], .stApp, button, input, textarea { font-family: 'Outfit', system-ui, sans-serif !important; }
.stApp { background: @bg@; color: @ink@; }
.stApp p, .stApp label, .stApp li, .stApp h1, .stApp h2, .stApp h3, .stApp [data-testid="stMarkdownContainer"] { color: @ink@; }
.stApp [data-testid="stCaptionContainer"], .stApp [data-testid="stCaptionContainer"] p { color: @muted@; }
header[data-testid="stHeader"] { background: transparent; }
.block-container { padding-top: 1.6rem; max-width: 1560px; }
section[data-testid="stSidebar"] { background: @card@; }
section[data-testid="stSidebar"] p, section[data-testid="stSidebar"] h3 { color: @ink@; }
.st-key-hdr { background: linear-gradient(135deg, @soft@ 0%, @light@ 70%); border-radius: 28px; padding: 26px 30px; }
.st-key-chat, .st-key-checks { background: @card@; border-radius: 24px; padding: 20px 22px; }
.st-key-today { background: @panel@; border-radius: 24px; padding: 20px 22px; }
.st-key-today, .st-key-today div, .st-key-today span, .st-key-today p { color: @onPanel@; }
.st-key-approve { background: @notice@; border: 2px solid @ink@; border-radius: 22px; padding: 18px 22px; margin-top: 14px; }
.st-key-runbox { background: @card@; border-radius: 22px; padding: 14px 16px; margin-top: 14px; }
.st-key-runbox pre, .st-key-runbox code { font-size: 12px !important; white-space: pre-wrap !important; word-break: break-word; }
.stApp pre, .stApp code, [data-testid="stCode"], [data-testid="stCode"] pre { background: @inset@ !important; color: @ink@ !important; }
.kpi { background: @card@; border-radius: 22px; padding: 16px 20px; min-height: 118px; }
.kpi .l { font-size: 13px; color: @muted@; } .kpi .v { font-size: 30px; line-height: 1.15; }
.kpi .n { font-size: 13px; color: @muted@; }
.ctitle { font-size: 18px; font-weight: 500; margin-bottom: 6px; }
.row { display: flex; justify-content: space-between; align-items: center; gap: 10px;
       padding: 10px 0; border-top: 1px solid @border@; font-size: 15px; }
.pill { font-size: 12px; font-weight: 600; padding: 3px 10px; border-radius: 999px; }
.ok { background: @okBg@; color: @okFg@; } .bad { background: @badBg@; color: @badFg@; }
.tl { display: flex; gap: 12px; padding: 5px 0; font-size: 15px; line-height: 1.4; }
.st-key-today button { background: transparent !important; border: 1px solid @panelAccent@ !important; margin-top: 8px; }
.st-key-today button p { color: @onPanel@ !important; }
.st-key-budgetcard, .st-key-budgetform { background: @card@; border-radius: 22px; padding: 18px 22px; }
button[data-variant="segmented_control"] { background: @card@ !important; border-color: @border@ !important; }
button[data-variant="segmented_control"][aria-checked="true"] { background: @accent@ !important; border-color: @accent@ !important; }
button[data-variant="segmented_control"] p, button[data-variant="segmented_control"] span { color: @ink@ !important; }
button[data-variant="segmented_control"][aria-checked="true"] p, button[data-variant="segmented_control"][aria-checked="true"] span { color: @onAccent@ !important; }
.rtable { width: 100%; border-collapse: collapse; font-size: 14px; }
.rtable th { text-align: left; font-weight: 500; color: @muted@; padding: 8px 10px; border-bottom: 1px solid @border@; font-size: 13px; }
.rtable td { padding: 11px 10px; border-bottom: 1px solid @border@; color: @ink@; }
.rtable .n { text-align: right; font-variant-numeric: tabular-nums; }
.rtable tr:last-child td { border-bottom: 0; }
.bar { background: @inset@; border-radius: 99px; height: 12px; overflow: hidden; margin: 8px 0 6px; }
.bar > div { height: 100%; border-radius: 99px; }
.rep { padding: 8px 0; border-top: 1px solid @border@; }
.rep:first-of-type { border-top: 0; }
.rep .rh { font-size: 13px; font-weight: 600; color: @ink@; }
.rep .rl { font-size: 12.5px; color: @muted@; line-height: 1.5; }
.rep b { color: @ink@; font-weight: 600; }
.st-key-today .tl .t { color: @panelAccent@; flex: 0 0 48px; font-size: 13px; padding-top: 2px; }
.dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 8px; }
.hello { font-size: 40px; font-weight: 400; line-height: 1.1; margin: 4px 0 8px; }
.sub { font-size: 14px; color: @muted@; }
.card { background: @card@; border-radius: 22px; padding: 18px 22px; }
.stAppDeployButton, [data-testid="stAppDeployButton"], [data-testid="stToolbar"] { display: none; }
.stButton button, [data-testid="stFormSubmitButton"] button { white-space: nowrap; border-radius: 999px; min-height: 46px; padding: 0 22px;
                   border: 2px solid @ink@; background: transparent; color: @ink@; font-weight: 500; font-size: 16px; }
.stButton button p, [data-testid="stFormSubmitButton"] button p { color: @ink@; }
.stButton button[kind="primary"], .stButton button[data-testid="stBaseButton-primary"] { background: @deep@; color: @light@; }
.stButton button[kind="primary"] p, .stButton button[data-testid="stBaseButton-primary"] p { color: @light@; }
.stButton button:disabled { opacity: 0.4; cursor: not-allowed; }
.stTabs [role="tablist"], .stTabs [data-baseweb="tab-list"] { gap: 8px; }
.stTabs [role="tab"], .stTabs [data-baseweb="tab"] { border-radius: 999px !important; padding: 8px 20px !important; height: auto !important;
    background: @inset@ !important; color: @ink@ !important; border-bottom: none !important; box-shadow: none !important; }
.stTabs [role="tab"] p, .stTabs [data-baseweb="tab"] p { color: @ink@ !important; }
.stTabs [role="tab"][aria-selected="true"], .stTabs [data-baseweb="tab"][aria-selected="true"] { background: @deep@ !important; }
.stTabs [role="tab"][aria-selected="true"] p, .stTabs [data-baseweb="tab"][aria-selected="true"] p { color: @light@ !important; }
.stTabs [data-baseweb="tab-highlight"], .stTabs [data-baseweb="tab-border"], .stTabs .react-aria-SelectionIndicator { display: none !important; background: transparent !important; }
[data-testid="stChatInput"], [data-testid="stChatInput"] > div { background: @card@; border-color: @ink@; }
[data-testid="stChatInput"] textarea { color: @ink@; background: transparent; }
[data-testid="stChatInput"] textarea::placeholder { color: @muted@ !important; opacity: 1 !important; }
[data-testid="stChatInput"] button { background: @deep@ !important; }
[data-testid="stChatInput"] button svg { fill: @light@ !important; color: @light@ !important; }
[data-testid="stChatMessage"] { background: transparent; }
[data-baseweb="input"], [data-baseweb="base-input"], .stTextInput input { background: @card@ !important; color: @ink@ !important; }
[data-testid="stAlert"] { background: @notice@; color: @ink@; }
[data-testid="stAlert"] p { color: @ink@; }
"""
for _k, _v in T.items():
    CSS = CSS.replace("@" + _k + "@", _v)
st.markdown("<style>" + CSS + "</style>", unsafe_allow_html=True)

## ---------------------------------------------------------------
## 3. MEMORY OF THIS BROWSER SESSION (Streamlit re-runs the file on every click)
## ---------------------------------------------------------------
ss = st.session_state
for key, default in (("chat", []), ("log", []), ("proc", None), ("q", None), ("awaiting", None),
                     ("logfile", None), ("hist", []), ("pending", None), ("tokens", 0), ("refresh", 0),
                     ("lastmode", None), ("snap", None), ("job", None), ("need_refresh", False)):
    ss.setdefault(key, default)

def say(text):
    ss.chat.append(("assistant", text))

## ---------------------------------------------------------------
## 4. READING THE LAB (read-only; results are cached for 45 seconds)
## ---------------------------------------------------------------
def sh(cmd, timeout=90):
    try:
        p = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, timeout=timeout, env=UENV,
                           encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return p.returncode, p.stdout + p.stderr
    except Exception as e:
        return 1, str(e)

def parse_lines(out):
    rows = []
    for line in out.splitlines():
        m = re.match(r"^(PASS|FAIL)\s+(.*)$", line.strip())
        if m:
            rows.append((m.group(1), m.group(2)))
    return rows

## State: DOWN = nothing-running passes. READY = ready passes. Anything else = NOT READY.
def get_status():
    if not BASH:
        return {"state": "UNKNOWN", "rows": [], "at": time.strftime("%H:%M:%S")}
    rc, out = sh([BASH, "agent/env/checks.sh", "nothing-running"], 120)
    if rc == 0:
        return {"state": "DOWN", "rows": parse_lines(out), "at": time.strftime("%H:%M:%S")}
    rc, out = sh([BASH, "agent/env/checks.sh", "ready"], 120)
    return {"state": "READY" if rc == 0 else "NOT READY", "rows": parse_lines(out),
            "at": time.strftime("%H:%M:%S")}

## Cluster creation time = when the lab came up (good enough for uptime and cost).
def get_uptime_hours():
    if not AWS:
        return None
    cmd = [AWS, "eks", "describe-cluster", "--name", CLUSTER, "--query", "cluster.createdAt",
           "--output", "text", "--region", REGION]
    if PROFILE:
        cmd += ["--profile", PROFILE]
    rc, out = sh(cmd, 30)
    out = out.strip()
    if rc != 0 or not out:
        return None
    try:
        started = datetime.fromtimestamp(float(out), tz=timezone.utc)
    except ValueError:
        try:
            started = datetime.fromisoformat(out.replace("Z", "+00:00"))
        except ValueError:
            return None
    return max(0.0, (datetime.now(timezone.utc) - started).total_seconds() / 3600)

def get_pods():
    if not KUBECTL:
        return None
    rc, out = sh([KUBECTL, "-n", "bako", "get", "pods", "--request-timeout=10s", "-o", "json"], 30)
    try:
        items = json.loads(out)["items"]
    except Exception:
        return None
    ready = restarts = 0
    for p in items:
        cs = p.get("status", {}).get("containerStatuses", [])
        if p.get("status", {}).get("phase") == "Running" and cs and all(c.get("ready") for c in cs):
            ready += 1
        restarts += sum(c.get("restartCount", 0) for c in cs)
    return {"ready": ready, "total": len(items), "restarts": restarts}

## Today's results, read from the agent's trace files.
STAGE_LABELS = {"apply": "Terraform apply finished", "boot": "Cluster set up (bootstrap)", "trig": "Build requested on GitHub",
                "build": "Images built", "push": "Images pushed to ECR", "bot": "Bot pull request opened",
                "merge": "Pull request merged", "argo": "Argo CD synced", "ready": "READY checks all pass"}

def todays_events():
    events = []
    for path in glob.glob(os.path.join(REPO, "agent", "env", "reports", time.strftime("trace-%Y%m%d-*.jsonl"))):
        try:
            with open(path, encoding="utf-8") as f:
                for line in f:
                    ev = json.loads(line)
                    t = ev.get("time", "")[:5]
                    if ev.get("event") == "stage":
                        label = STAGE_LABELS.get(ev.get("id"))
                        if label and ev.get("status") == "done":
                            events.append((t, label))
                        elif ev.get("status") == "failed":
                            events.append((t, f"FAILED at {label or ev.get('id')}"))
                    if ev.get("event") == "outcome":
                        if "ready" in ev:
                            events.append((t, "START finished: " + ("READY" if ev["ready"] else
                                           "stopped at " + (ev.get("stopped_at") or "an early step"))))
                        elif "applied" in ev:
                            events.append((t, "START finished: " + ("applied" if ev["applied"] else "not applied")))
                        elif "destroyed" in ev:
                            events.append((t, "STOP finished: " +
                                           ("destroyed, nothing running" if ev["destroyed"] and ev.get("nothing_running")
                                            else "destroy not confirmed")))
        except (OSError, ValueError):
            continue
    return sorted(events)

def fmt_hours(h):
    return f"{int(h)}h {int((h % 1) * 60):02d}m"

## ---------------------------------------------------------------
## 4a. THE REPORTS PAGE (opened from the sidebar; replaces the main area)
## ---------------------------------------------------------------
def money(x):
    return f"${x:,.2f}"

def reports_page():
    top1, top2 = st.columns([1, 5])
    if top1.button("Back to the lab", key="rep_back", use_container_width=True):
        ss.page = "lab"; st.rerun()
    st.markdown(f"<div class='hello'>Reports</div><div class='sub'>What the lab ran, what it cost and what is left of the budget. "
                f"Estimates use ${HOURLY:.2f} per hour.</div>", unsafe_allow_html=True)
    span = st.segmented_control("Period", ["7 days", "14 days", "30 days"], default="14 days",
                                key="rep_span", label_visibility="collapsed") or "14 days"
    n = int(span.split()[0])
    rows = usage.report(REPO, HOURLY, up_now, n_days=n)
    ms = usage.month_summary(REPO, HOURLY, up_now)

    ## --- tiles for the chosen period ---
    tot_s = sum(r["seconds"] for r in rows)
    est = sum(r["est_cost"] for r in rows)
    known = [r for r in rows if r["aws_cost"] is not None]
    actual = sum(r["aws_cost"] for r in known)
    tokens = sum(r["tokens"] for r in rows)
    tiles = [(f"Lab ran, last {n} days", usage.fmt_duration(tot_s), f"{sum(r['starts'] for r in rows)} starts, {sum(r['stops'] for r in rows)} stops"),
             ("Estimated cost", money(est), f"{tot_s/3600:.1f} hours x ${HOURLY:.2f}"),
             ("AWS actual", money(actual) if known else "not checked", f"{len(known)} of {n} days checked"),
             ("Tokens", usage.fmt_tokens(tokens), "chat with Bako")]
    for col, (l, v, note) in zip(st.columns(4, gap="small"), tiles):
        col.markdown(f"<div class='kpi'><div class='l'>{html.escape(l)}</div><div class='v'>{html.escape(v)}</div>"
                     f"<div class='n'>{html.escape(note)}</div></div>", unsafe_allow_html=True)

    ## --- this month and the budget ---
    st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
    left, right = st.columns([1.6, 1], gap="medium")
    with left:
        with st.container(key="budgetcard"):
            month = time.strftime("%B %Y")
            st.markdown(f"<div class='ctitle'>This month · {month}</div>", unsafe_allow_html=True)
            if ms["budget"]:
                pct = ms["spent"] / ms["budget"]
                color = T["badFg"] if pct >= 1 else T["ink"]
                st.markdown(f"<div style='font-size:15px'><b>{money(ms['spent'])}</b> of {money(ms['budget'])} budget "
                            f"({pct*100:.0f}%)</div><div class='bar'><div style='width:{min(100, pct*100):.0f}%;background:{color}'></div></div>",
                            unsafe_allow_html=True)
                over = ms["forecast"] > ms["budget"]
                st.markdown(f"<div class='sub'>Left: <b>{money(ms['left'])}</b> · at this pace the month ends near "
                            f"<b>{money(ms['forecast'])}</b>{' - over the budget' if over else ''}.</div>", unsafe_allow_html=True)
            else:
                st.markdown(f"<div style='font-size:15px'><b>{money(ms['spent'])}</b> so far. No budget set yet.</div>",
                            unsafe_allow_html=True)
            st.markdown(f"<div class='sub'>Counts the real AWS number for {ms['real_days']} of {ms['days']} days and the estimate for the rest. "
                        f"Lab hours this month: {ms['hours']:.1f}.</div>", unsafe_allow_html=True)
    with right:
        with st.container(key="budgetform"):
            st.markdown("<div class='ctitle'>Budget and real cost</div>", unsafe_allow_html=True)
            with st.form("budget_form", clear_on_submit=False):
                value = st.number_input("Monthly budget (USD)", min_value=0.0, step=5.0, value=float(usage.get_budget(REPO)))
                if st.form_submit_button("Save budget", use_container_width=True):
                    usage.set_budget(REPO, value); st.rerun()
            if st.button("Check real AWS cost (31 days)", key="aws_cost_btn", use_container_width=True,
                         help="Asks AWS Cost Explorer. Each request costs about $0.01."):
                ok, msg = usage.fetch_aws_costs(AWS, PROFILE, REPO, n_days=31)
                ss.cost_msg = msg; st.rerun()
            if ss.get("cost_msg"):
                st.caption(ss.cost_msg)

    ## --- chart: estimate next to the real number ---
    import pandas as pd
    df = pd.DataFrame({"Estimated": [r["est_cost"] for r in reversed(rows)],
                       "AWS actual": [r["aws_cost"] for r in reversed(rows)]},
                      index=[r["date"][5:] for r in reversed(rows)])
    st.markdown("<div style='height:6px'></div><div class='ctitle'>Cost per day</div>", unsafe_allow_html=True)
    st.bar_chart(df, color=[T["muted"], T["ink"]], height=240, stack=False)

    ## --- the table ---
    head = ("<tr><th>Day</th><th class='n'>Lab ran</th><th class='n'>Starts / stops</th><th class='n'>Estimated</th>"
            "<th class='n'>AWS actual</th><th class='n'>Gap</th><th class='n'>Tokens</th><th class='n'>Chat cost</th></tr>")
    chat_costs = usage.chat_cost_by_day(REPO)
    body = ""
    quiet = st.checkbox("Show days with no activity", value=False, key="rep_quiet")
    for r in rows:
        if not quiet and r["label"] not in ("Today", "Yesterday") and not (r["seconds"] or r["tokens"] or r["aws_cost"]):
            continue
        aws = money(r["aws_cost"]) if r["aws_cost"] is not None else "-"
        gap = f"{r['aws_cost'] - r['est_cost']:+.2f}" if r["aws_cost"] is not None else "-"
        body += (f"<tr><td>{html.escape(r['label'] if r['label'] in ('Today', 'Yesterday') else r['date'])}"
                 f"</td>"
                 f"<td class='n'>{usage.fmt_duration(r['seconds'])}</td><td class='n'>{r['starts']} / {r['stops']}</td>"
                 f"<td class='n'>{money(r['est_cost'])}</td><td class='n'>{aws}</td><td class='n'>{gap}</td>"
                 f"<td class='n'>{usage.fmt_tokens(r['tokens'])}</td>"
                 f"<td class='n'>{cents(chat_costs[r['date']]) if chat_costs.get(r['date']) else '-'}</td></tr>")
    st.markdown(f"<div class='card'><table class='rtable'>{head}{body}</table></div>", unsafe_allow_html=True)
    st.caption("Gap = AWS actual minus estimate (a positive gap means AWS charged more than the hours predict). "
               "Today's AWS number is partial: AWS fills it in up to a day later.")
    questions_section()

def cents(x):
    return f"${x:.4f}" if x < 0.1 else f"${x:.2f}"

def questions_section():
    prices = usage.get_prices(REPO)
    qrows = usage.questions(REPO, prices)
    ref = usage.reference(qrows)
    st.markdown("<div style='height:18px'></div><div class='ctitle'>What questions to Bako cost</div>", unsafe_allow_html=True)
    if not qrows:
        st.markdown("<div class='sub'>No question recorded yet. Ask Bako something and every message appears here with its cost "
                    "(they are saved in agent/env/reports/chat-traces.jsonl).</div>", unsafe_allow_html=True)
    else:
        today, month = time.strftime("%Y-%m-%d"), time.strftime("%Y-%m")
        tr_ = [r for r in qrows if r["day"] == today]
        mr_ = [r for r in qrows if r["day"].startswith(month)]
        top = max(qrows, key=lambda r: r["cost"])
        tiles = [("Today", cents(sum(r["cost"] for r in tr_)), f"{len(tr_)} question(s)"),
                 ("This month", cents(sum(r["cost"] for r in mr_)), f"{len(mr_)} question(s)"),
                 ("Average per question", cents(sum(r["cost"] for r in mr_) / len(mr_)) if mr_ else "-", "this month"),
                 ("Most expensive", cents(top["cost"]), top["question"][:34] + ("..." if len(top["question"]) > 34 else ""))]
        for col, (l, v, note) in zip(st.columns(4, gap="small"), tiles):
            col.markdown(f"<div class='kpi'><div class='l'>{html.escape(l)}</div><div class='v'>{html.escape(v)}</div>"
                         f"<div class='n'>{html.escape(note)}</div></div>", unsafe_allow_html=True)
        st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)
        head = ("<tr><th>When</th><th>Question</th><th>Tools used</th><th class='n'>Tokens</th><th class='n'>Cost</th>"
                "<th class='n'>Fixed part</th><th class='n'>Compared with normal</th></tr>")
        body = ""
        for r in qrows[:25]:
            j = usage.judge(r, ref)
            when = r["time"].strftime("%H:%M" if r["day"] == today else "%d %b %H:%M") if r["time"] else "?"
            color = {"very high": T["badFg"], "high": T["ink"], "normal": T["muted"]}[j["flag"]]
            weight = "600" if j["flag"] != "normal" else "400"
            tools = f"{r['calls']}: " + ", ".join(dict.fromkeys(r["tools"])) if r["calls"] else "none"
            fixed_pct = f"{round(100 * j['fixed'] / r['total'])}%" if r["total"] else "-"
            body += (f"<tr><td>{html.escape(when)}</td><td>{html.escape(r['question'][:70])}</td><td>{html.escape(tools)}</td>"
                     f"<td class='n'>{r['total']:,}</td><td class='n'>{cents(r['cost'])}</td><td class='n'>{fixed_pct}</td>"
                     f"<td class='n' style='color:{color};font-weight:{weight}'>{j['ratio']:.1f}x · {j['flag']}</td></tr>")
        st.markdown(f"<div class='card'><table class='rtable'>{head}{body}</table></div>", unsafe_allow_html=True)
        typ = ", ".join(f"{'2+' if k == 2 else k} tool call(s): {v:,} tokens" for k, v in sorted(ref["typical"].items())) or "not enough messages yet (needs 5 with the same number of tool calls)"
        st.caption(f"How to read this. Every message pays a fixed part again on each model call: about {ref['floor']:,} tokens "
                   f"(the rules, the tool menu and your question; measured from your own messages). A message with 2 tool calls makes 3 model calls, "
                   f"so it pays that part 3 times. 'Fixed part' is the share of the message that was only this overhead; the rest is tool results, "
                   f"earlier messages and the answer. Normal = your own median for the same number of tool calls ({typ}). "
                   f"High = 2x that or more (1.5x of the fixed part while there is little history). Very high = 3x or more, or the message hit the token budget. "
                   f"A very high message with a low fixed part means a big tool result: look at its Telemetry in the Flow tab.")
    with st.expander("Prices used for these dollars"):
        with st.form("price_form", clear_on_submit=False):
            c1, c2, c3 = st.columns(3)
            pin = c1.number_input("Input, $ per 1M tokens", min_value=0.0, step=0.01, format="%.4f", value=float(prices["in"]))
            pca = c2.number_input("Cached input, $ per 1M", min_value=0.0, step=0.01, format="%.4f", value=float(prices["cached"]))
            pout = c3.number_input("Output, $ per 1M", min_value=0.0, step=0.01, format="%.4f", value=float(prices["out"]))
            if st.form_submit_button("Save prices"):
                usage.set_prices(REPO, pin, pca, pout)
                st.rerun()
        st.caption("Defaults are the gpt-5.4-nano prices listed on OpenAI's page (developers.openai.com/api/docs/models/gpt-5.4-nano), "
                   "read on 2026-10-24. Change them if the model or the price changes. Reasoning tokens, if the model uses them, are counted inside the output tokens.")

## ---------------------------------------------------------------
## 4b. BACKGROUND REFRESH
## The checks take 10-30 seconds (many AWS calls). They run in a background thread so the
## page never freezes: it keeps showing the last known result and says "Checking AWS...".
## The thread must not touch st.* or session_state; it only fills a plain dict.
## ---------------------------------------------------------------
def compute_snapshot():
    snap = {"status": get_status(), "hours": None, "pods": None, "at": time.strftime("%H:%M:%S")}
    if snap["status"]["state"] != "DOWN":
        snap["hours"] = get_uptime_hours()
        snap["pods"] = get_pods()
    return snap

def start_job():
    holder = {}
    def work():
        try:
            holder["snap"] = compute_snapshot()
        except Exception as e:                       # never leave the page waiting forever
            holder["error"] = str(e)
    t = threading.Thread(target=work, daemon=True)
    t.start()
    ss.job = (t, holder, time.time())

## ---------------------------------------------------------------
## 5. TALKING TO THE AGENT PROCESS (same mechanism as ui.py)
## ---------------------------------------------------------------
def reader(proc, q):
    for line in proc.stdout:
        q.put(line.rstrip("\r\n"))
    q.put(None)

def launch(mode, frm=""):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    proc = subprocess.Popen(
        [sys.executable, "-u", os.path.join("agent", "env", "agent.py"), mode] + (["--from", frm] if frm else []),
        cwd=REPO, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", bufsize=1)
    ss.proc, ss.q = proc, queue.Queue()
    ss.log, ss.awaiting, ss.logfile, ss.lastmode = [], None, None, mode
    ss.pr_review, ss.merge_msg = None, None
    threading.Thread(target=reader, args=(proc, ss.q), daemon=True).start()

def drain():
    while True:
        try:
            line = ss.q.get_nowait()
        except queue.Empty:
            return False
        if line is None:
            return True
        ss.log.append(line)
        if "APPROVAL NEEDED" in line:
            ss.awaiting = "destroy bako" if "DESTROY" in line else "approved"
        if "tail -f " in line:
            ss.logfile = line.split("tail -f ", 1)[1].strip()

def send_to_agent(text):
    try:
        ss.proc.stdin.write(text.strip() + "\n")
        ss.proc.stdin.flush()
    except OSError:
        say("The agent is no longer listening.")
    ss.awaiting = None

## ---------------------------------------------------------------
## 6. THE CHAT (model-driven; it can only PROPOSE actions)
## ---------------------------------------------------------------
def handle_keywords(text):
    t = text.lower()
    if any(w in t for w in ("stop", "destroy", "shut down", "tear down")):
        say("Starting STOP. I will plan the destroy first.")
        launch("stop")
    elif any(w in t for w in ("start", "bring up")):
        say("Starting START. I will plan first.")
        launch("start")
    else:
        say("Keyword mode: say start or stop.")

def apply_action(action):
    if action["type"] == "start":
        say("Opening the START flow. I will plan first, then ask you to approve.")
        launch("start")
    elif action["type"] == "stop":
        say("Opening the STOP flow. I will plan the destroy first, then ask you to approve.")
        launch("stop")
    elif action["type"] == "commit_push":
        ss.pending = action

def handle(text):
    client = get_client()
    if client is None:
        say("No OpenAI key found, so I use keyword mode.")
        return handle_keywords(text)
    try:
        with st.spinner("Bako is thinking..."):
            reply, action, used = bako_chat.run_turn(client, MODEL, ss.hist, text, REPO)
    except Exception as e:
        ss.chat_trace = {"question": text, "tools": [], "tokens": 0, "model": MODEL, "proposal": None,
                         "trace": getattr(bako_chat, "LAST_TRACE", None), "error": f"{type(e).__name__}: {e}"[:300]}
        say(f"The model is not reachable ({type(e).__name__}). Keyword mode: say start or stop.")
        return handle_keywords(text)
    ss.tokens += used
    usage.add_chat_tokens(REPO, used)           # kept for the daily report
    ## what the Flow tab shows for "Bako and OpenAI" (tool details need bako_chat.LAST_TOOLS)
    ss.chat_trace = {"question": text, "tools": getattr(bako_chat, "LAST_TOOLS", None),
                     "tokens": used, "model": MODEL, "proposal": (action or {}).get("type"),
                     "trace": getattr(bako_chat, "LAST_TRACE", None)}
    try:                                       # what this message cost, and whether that is normal for you
        qr = usage.questions(REPO)
        if qr:
            ss.chat_trace["cost"] = dict(usage.judge(qr[0], usage.reference(qr[1:])), dollars=qr[0]["cost"])
    except Exception:
        pass
    say(reply or "(no reply)")
    if action:
        apply_action(action)

## ---------------------------------------------------------------
## 7. THE LIVE PART OF THE PAGE (a "fragment")
## While an agent run (or a background check) is active, only this small block refreshes,
## once per second, and the rest of the page stays still. (Re-running the WHOLE page every
## second sometimes left old copies of panels on screen.) When something finishes, the
## fragment asks for ONE full re-run so every panel shows the new state.
## ---------------------------------------------------------------

## Collect the agent's output. Returns True once the run has ended (and tidies up after it).
def finish_run_if_done():
    if not drain():
        return False
    code = ss.proc.wait()
    ss.chat.append(("assistant", "```\n" + "\n".join(ss.log) + "\n```"))
    results = [l for l in ss.log if l.startswith("RESULT (from code)")]
    say("**" + results[-1] + "**" if results else f"The run ended (exit code {code}).")
    ss.proc, ss.log, ss.awaiting, ss.logfile = None, [], None, None
    ss.need_refresh = True                    # the lab changed: read it again
    return True

def live_panel():
    if ss.proc is not None:
        if finish_run_if_done():
            st.rerun()                        # full page re-run, once
        ## typed approval, shown while the agent waits
        if ss.awaiting:
            with st.container(key="approve"):
                st.markdown(f"**Approval needed.** Type exactly `{ss.awaiting}` to continue. "
                            f"Anything else means no. The agent itself compares what you type.")
                with st.form("approve_form", clear_on_submit=True):
                    word = st.text_input("Your answer", label_visibility="collapsed", placeholder=ss.awaiting)
                    c1, c2 = st.columns(2)
                    yes = c1.form_submit_button("Send", use_container_width=True)
                    no = c2.form_submit_button("Cancel", use_container_width=True)
                if yes:
                    send_to_agent(word); st.rerun(scope="fragment")
                if no:
                    send_to_agent("no"); st.rerun(scope="fragment")
        ## the merge gate: the agent is waiting for YOU to merge the bot pull request on GitHub
        merge_line = next((l for l in reversed(ss.log) if "Merge pull request #" in l), None)
        merge_done = any("[merge] DONE" in l or "[merge] SKIPPED" in l or "[merge] FAILED" in l for l in ss.log)
        if merge_line and not merge_done:
            m = re.search(r"Merge pull request #(\d+): (\S+)", merge_line)
            if m:
                with st.container(key="approve"):
                    st.markdown(f"**Your turn.** Merge pull request #{m.group(1)} on GitHub. "
                                "Bako waits and continues by itself once it is merged.")
                    if st.button("Open the pull request", key="open_pr", use_container_width=True):
                        webbrowser.open(m.group(2))
                    n = int(m.group(1))
                    if GHCLI and st.button("Review and merge here", key="review_pr", use_container_width=True):
                        ss.pr_review = dict(prmerge.review(GHCLI, n, REPO), n=n)
                    rv = ss.get("pr_review")
                    if rv and rv.get("n") == n:
                        if rv["problems"]:
                            st.error("Cannot merge from here: " + " ".join(rv["problems"]))
                        else:
                            st.markdown(f"**{html.escape(rv['title'])}**  \n+{rv['additions']} / -{rv['deletions']} in "
                                        f"{rv['changedFiles']} files. This is exactly what will change:")
                            st.code("\n".join(rv["diff"].splitlines()[:40]), language="diff")
                            st.markdown("Type exactly `merge bako` to merge it. Anything else means no. "
                                        "Bako compares the word itself.")
                            with st.form("merge_form", clear_on_submit=True):
                                word = st.text_input("Your answer", label_visibility="collapsed", placeholder="merge bako")
                                c1, c2 = st.columns(2)
                                yes = c1.form_submit_button("Merge", use_container_width=True)
                                no = c2.form_submit_button("Cancel", use_container_width=True)
                            if yes:
                                if word.strip() == "merge bako":
                                    _, text = prmerge.merge(GHCLI, n, REPO)
                                else:
                                    text = "Not merged. You must type exactly: merge bako"
                                ss.pr_review = None
                                ss.merge_msg = text
                                st.rerun(scope="fragment")
                            if no:
                                ss.pr_review = None
                                st.rerun(scope="fragment")
                    if ss.get("merge_msg"):
                        st.info(ss.merge_msg)
        ## live output of the running agent
        with st.container(key="runbox"):
            st.code("\n".join(ss.log[-40:]) or "starting...", language=None)
            if ss.logfile:
                path = os.path.join(REPO, ss.logfile)
                if os.path.exists(path):
                    with open(path, encoding="utf-8", errors="replace") as f:
                        tail = f.read().splitlines()[-12:]
                    st.caption("Live terraform log (last lines)")
                    st.code("\n".join(tail), language=None)
    elif ss.job is not None and not ss.job[0].is_alive():
        st.rerun()                            # the background check finished: show its result

running = ss.proc is not None
if running and finish_run_if_done():
    st.rerun()
running = ss.proc is not None

## ---------------------------------------------------------------
## 8. SIDEBAR
## ---------------------------------------------------------------
## Pick up a finished background check, and start a new one when needed.
if ss.job is not None:
    t, holder, started = ss.job
    if not t.is_alive():
        if "snap" in holder:
            ss.snap = holder["snap"]
        ss.job = None
    elif time.time() - started > 150:                # a stuck check: give up on it
        ss.job = None
if not running and ss.job is None and (ss.snap is None or ss.need_refresh):
    ss.need_refresh = False
    start_job()
checking = ss.job is not None
snap = ss.snap
status = None if running or snap is None else snap["status"]
account = ss.get("account", "")
if status:
    for _, text in status["rows"]:
        m = re.search(r"\b(\d{12})\b", text)
        if m:
            account = ss.account = m.group(1)
            break
with st.sidebar:
    if os.path.exists(LOGO):
        st.image(LOGO, width=90)
    st.markdown(f"<div class='card'><div class='sub'>AWS account</div>"
                f"<div style='font-size:16px;font-weight:500'>{'••••' + account[-4:] if account else '—'}</div>"
                f"<div class='sub'>{html.escape(REGION)} · {html.escape(CLUSTER)}</div></div>",
                unsafe_allow_html=True)
    st.caption(f"Model: {MODEL}")
    st.caption(f"Tokens used in this window: {ss.tokens}")
    ## --- the daily report (short): the full one is on the Reports page ---
    up_now = bool(running or (status and status["state"] in ("READY", "NOT READY")))
    rows = usage.report(REPO, HOURLY, up_now, n_days=2)
    body = ""
    for r in rows:
        aws = f"${r['aws_cost']:.2f}" if r["aws_cost"] is not None else "not checked"
        body += (f"<div class='rep'><div class='rh'>{html.escape(r['label'])}</div>"
                 f"<div class='rl'>Lab ran <b>{usage.fmt_duration(r['seconds'])}</b> · est. ${r['est_cost']:.2f}</div>"
                 f"<div class='rl'>Tokens <b>{usage.fmt_tokens(r['tokens'])}</b> · AWS actual <b>{aws}</b></div></div>")
    st.markdown(f"<div class='card'><div class='ctitle' style='font-size:15px'>Daily report</div>{body}</div>",
                unsafe_allow_html=True)
    if st.button("Reports" if ss.get("page") != "reports" else "Back to the lab", key="open_reports", use_container_width=True):
        ss.page = "reports" if ss.get("page") != "reports" else "lab"
        st.rerun()
    st.caption("Appearance")
    ta, tb = st.columns(2)
    if ta.button("Warm grey", key="theme_warm", use_container_width=True, type="primary" if ss.theme == "warm" else "secondary"):
        ss.theme = "warm"; save_theme("warm"); st.rerun()
    if tb.button("Dark", key="theme_dark", use_container_width=True, type="primary" if ss.theme == "dark" else "secondary"):
        ss.theme = "dark"; save_theme("dark"); st.rerun()

if ss.get("page") == "reports":
    reports_page()
    st.stop()

## ---------------------------------------------------------------
## 9. THE PAGE: main column on the left, chat on the right
## ---------------------------------------------------------------
main, side = st.columns([2.5, 1.5], gap="medium")

with main:
    ## --- header: greeting, state, Start / Stop ---
    hour = int(time.strftime("%H"))
    greet = "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening"
    if running:
        state, color = "RUNNING " + (ss.lastmode or "").upper(), "#3B6FD4"
        hours = None
    else:
        state = status["state"] if status else "CHECKING"
        color = {"READY": "#2E8B57", "DOWN": "#8A8575", "NOT READY": "#D98A1F"}.get(state, "#8A8575")
        hours = snap["hours"] if snap else None
    label = {"READY": "The lab is UP and READY", "DOWN": "The lab is DOWN, nothing is running",
             "NOT READY": "Some resources exist, but the lab is NOT READY",
             "CHECKING": "Checking AWS, this takes about 30 seconds..."}.get(state, f"Bako is running: {state}")
    with st.container(key="hdr"):
        st.markdown(f"<div class='sub'>{time.strftime('%a %d %b %Y')}</div>"
                    f"<div class='hello'>{greet}, {html.escape(NAME)}</div>"
                    f"<div style='font-size:16px;font-weight:500'><span class='dot' style='background:{color}'></span>"
                    f"{html.escape(label)}"
                    f"{' <span class=sub>· running ' + fmt_hours(hours) + '</span>' if hours is not None else ''}</div>",
                    unsafe_allow_html=True)
        b1, b2, _ = st.columns([1.6, 1.6, 3])
        if b1.button("Start lab", disabled=running):
            say("Starting the lab. I will plan first, then ask you to approve."); launch("start"); st.rerun()
        if b2.button("Stop lab", type="primary", disabled=running):
            say("Stopping the lab. I will plan the destroy first, then ask you to approve."); launch("stop"); st.rerun()

    ## --- a proposed commit + push waits for "push bako" ---
    if ss.pending:
        a = ss.pending
        st.warning(f'Bako proposes to commit to the NEW branch "{a["branch"]}" and push it. '
                   f'Message: {a["message"]}. Files: ' + ", ".join(a["files"]) +
                   '. Type exactly "push bako" in the chat to do it. Anything else cancels.')

    ## --- tabs ---
    t_lab, t_flow, t_infra, t_cluster, t_repo = st.tabs(["Lab", "Flow", "Infra and cost", "Cluster", "Repo"])

    with t_lab:
        pods = None if running or not snap else snap["pods"]
        cost = f"${hours * HOURLY:.2f}" if hours is not None else ("$0.00" if state == "DOWN" else "—")
        kpis = [
            ("Lab", state if not running else "BUSY", {"READY": "all checks pass", "DOWN": "nothing billing"}.get(state, "see checks below")),
            ("Running for", fmt_hours(hours) if hours is not None else "—", "since the cluster was created"),
            ("Estimated cost", cost, f"about ${HOURLY:.2f} per hour"),
            ("Pods", f"{pods['ready']} / {pods['total']}" if pods else "—", f"{pods['restarts']} restarts" if pods else "not running"),
        ]
        for col, (l, v, n) in zip(st.columns(4, gap="small"), kpis):
            col.markdown(f"<div class='kpi'><div class='l'>{html.escape(l)}</div>"
                         f"<div class='v'>{html.escape(str(v))}</div><div class='n'>{html.escape(n)}</div></div>",
                         unsafe_allow_html=True)
        st.write("")
        left, right = st.columns([1.15, 1], gap="medium")
        with left:
            with st.container(key="checks"):
                h1, h2 = st.columns([2, 1.3])
                title = "Checks right now" if state != "READY" else "READY checks"
                h1.markdown(f"<div class='ctitle'>{title}</div>", unsafe_allow_html=True)
                if h2.button("Refresh", disabled=running or checking):
                    ss.need_refresh = True; st.rerun()
                rows = status["rows"] if status else []
                body = "".join(
                    f"<div class='row'><span>{html.escape(t)}</span>"
                    f"<span class='pill {'ok' if r == 'PASS' else 'bad'}'>{r}</span></div>" for r, t in rows)
                st.markdown(body or ("<div class='sub'>Checks are paused while a run is active.</div>" if running
                                     else "<div class='sub'>No results yet.</div>"), unsafe_allow_html=True)
                if checking:
                    st.caption("Checking AWS in the background… the numbers above update when it finishes.")
                elif snap:
                    st.caption(f"Checked at {snap['at']}. Press Refresh to check again.")
        with right:
            with st.container(key="today"):
                events = todays_events()
                shown = events if ss.get("today_all") else events[-6:]
                lines = "".join(f"<div class='tl'><span class='t'>{t}</span><span>{html.escape(x)}</span></div>"
                                for t, x in shown) or "<div class='tl'><span>Nothing recorded yet today.</span></div>"
                more = f" · last {len(shown)} of {len(events)}" if len(shown) < len(events) else ""
                st.markdown(f"<div class='ctitle'>Today{more}</div>{lines}", unsafe_allow_html=True)
                if len(events) > 6 and st.button("Show less" if ss.get("today_all") else f"Show all {len(events)} events",
                                                 key="today_toggle", use_container_width=True):
                    ss.today_all = not ss.get("today_all")
                    st.rerun()

    with t_flow:
        def ask_bako(text):
            ss.flow_prompt = redact.redact(text)      # secrets hidden; picked up by the chat box after the next full re-run
        def rerun_from(stage_id):
            if not running:                           # one run at a time
                say(f"Re-running START from '{stage_id}'. Plan and apply are not repeated; finished steps are skipped.")
                launch("start", stage_id)
        flow_tab.show(REPO, running=running, on_ask=ask_bako, theme=ss.theme, chat_trace=ss.get("chat_trace"),
                      on_rerun=rerun_from)

    with t_infra:
        st.markdown("<div class='card'><div class='ctitle'>Infra and cost</div>Coming in phase 2: counts of what is "
                    "running in AWS, the estimate since START, and the real month-to-date cost on a button.</div>",
                    unsafe_allow_html=True)
    with t_cluster:
        st.markdown("<div class='card'><div class='ctitle'>Cluster</div>Coming in phase 2: pods, the Argo CD app "
                    "and the image tags running in the cluster.</div>", unsafe_allow_html=True)
    with t_repo:
        st.markdown("<div class='card'><div class='ctitle'>Repo</div>Coming in phase 3: branch, changes, pull requests "
                    "and CI runs, with commit and merge buttons. For now, ask Bako in the chat.</div>",
                    unsafe_allow_html=True)

with side:
    with st.container(key="chat"):
        st.markdown("<div class='ctitle'>Ask Bako</div>", unsafe_allow_html=True)
        box = st.container(height=470, border=False)
        with box:
            if not ss.chat:
                st.caption("Try: what is the status of the lab? · what changed in my last commit? · why did CI fail?")
            for role, text in ss.chat:
                with st.chat_message(role):
                    st.markdown(text)
        prompt = st.chat_input("Ask about the lab, the repo, an error…")
        prompt = ss.pop("flow_prompt", None) or prompt          # a "troubleshoot this step" click from the Flow tab
        if prompt:
            ss.chat.append(("user", prompt))
            if ss.pending:
                action, ss.pending = ss.pending, None
                if prompt.strip() == "push bako":
                    say("```\n" + bako_chat.do_commit_push(REPO, action) + "\n```")
                else:
                    say("Cancelled. Nothing was committed or pushed.")
            elif running and ss.awaiting:
                send_to_agent(prompt)
                say("Sent to the agent. It decides whether that is the approval.")
            elif running:
                say("I am in the middle of a run. Please wait until it finishes.")
            else:
                handle(prompt)
            st.rerun()

    ## --- live area: approval box and run output, under the chat (refreshes by itself) ---
    busy = ss.proc is not None or ss.job is not None
    st.fragment(live_panel, run_every=1 if busy else None)()