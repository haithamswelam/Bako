## ---------------------------------------------------------------
## tabs.py - the Repo, Cluster and AWS resources tabs of the Bako window.
## Everything here is READ-ONLY, except two buttons that only PREPARE a proposal:
##   - "Prepare commit and push"  -> the same approval card as the chat (you still type push bako)
##   - "Review and merge"         -> the same pull request card (you still type merge bako)
## No model is used on these tabs, so they cost no tokens.
##
## Loading: git, GitHub and kubectl can take several seconds. Each tab loads in a background thread
## and keeps showing the last result while it refreshes, so the page never freezes.
## The threads only run commands; they never touch the screen.
## ---------------------------------------------------------------
import datetime, html, json, re, subprocess, threading, time

import streamlit as st

import bako_chat
import redact
import usage

## ---------------------------------------------------------------
## 1. RUN COMMANDS, READ THE ANSWER
## ---------------------------------------------------------------
def _run(cmd, cwd, env=None, timeout=60):
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env, stdin=subprocess.DEVNULL,
                           encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return p.returncode, p.stdout or "", p.stderr or ""
    except Exception as e:
        return 1, "", f"{type(e).__name__}: {e}"

def _json(out):
    try:
        return json.loads(out)
    except ValueError:
        return None

def _when(iso):
    try:
        return datetime.datetime.strptime(str(iso)[:19], "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None

def _ago(iso):
    w = _when(iso)
    return bako_chat.ago(w) if w else "?"

## ---------------------------------------------------------------
## 2. THE FACTS (each returns a plain dict; safe to run in a background thread)
## ---------------------------------------------------------------
def fetch_repo(repo, gh, env):
    d = {"at": time.strftime("%H:%M:%S"), "gh_error": None}
    git = bako_chat.GIT
    if git:
        rc, out, _ = _run([git, "branch", "--show-current"], repo, env)
        d["branch"] = out.strip() or "(detached)"
        d["changes"] = [{"path": p, "status": s, "blocked": bako_chat.is_blocked(p)} for p, s in bako_chat._changed_files(repo).items()]
        rc, out, _ = _run([git, "rev-list", "--left-right", "--count", "origin/main...HEAD"], repo, env)
        try:
            behind, ahead = (int(x) for x in out.split())
        except ValueError:
            behind = ahead = None
        d["behind"], d["ahead"] = behind, ahead
        rc, out, _ = _run([git, "log", "-1", "--format=%h %s (%cr)"], repo, env)
        d["head"] = out.strip()
    else:
        d["branch"], d["changes"], d["head"] = "?", [], ""
        d["behind"] = d["ahead"] = None
    d["prs"], d["runs"], d["failed"], d["triggers"] = [], [], None, {}
    if not gh:
        d["gh_error"] = "The gh program was not found on this computer, so pull requests and CI runs cannot be shown."
        return d
    rc, out, err = _run([gh, "pr", "list", "--state", "all", "--limit", "10", "--json",
                         "number,title,state,headRefName,createdAt,mergedAt,url"], repo, env, 90)
    prs = _json(out) if rc == 0 else None
    if prs is None:
        d["gh_error"] = ("GitHub did not answer: " + (err or out).strip()[:200]) if rc != 0 else "unexpected answer from gh"
    else:
        d["prs"] = prs
    rc, out, err = _run([gh, "run", "list", "--limit", "10", "--json",
                         "databaseId,conclusion,status,displayTitle,workflowName,headBranch,event,createdAt,url"], repo, env, 90)
    runs = _json(out) if rc == 0 else None
    if runs is not None:
        d["runs"] = runs
        for r in runs:
            d["triggers"][r.get("event", "?")] = d["triggers"].get(r.get("event", "?"), 0) + 1
        bad = next((r for r in runs if r.get("conclusion") == "failure"), None)
        if bad:
            d["failed"] = {"run": bad, "text": redact.redact(bako_chat._gh_failed_lean(repo, bad["databaseId"]))[:1800]}
    elif not d["gh_error"]:
        d["gh_error"] = "Could not read CI runs: " + (err or out).strip()[:200]
    return d

def _pod_row(p):
    s, spec = p.get("status", {}), p.get("spec", {})
    cs = s.get("containerStatuses", [])
    total = len(spec.get("containers", [])) or len(cs)
    ready = sum(1 for c in cs if c.get("ready"))
    reason = s.get("phase", "?")
    for c in cs:
        w = (c.get("state") or {}).get("waiting")
        t = (c.get("state") or {}).get("terminated")
        if w:
            reason = w.get("reason", reason)
        elif t and t.get("reason") != "Completed":
            reason = t.get("reason", reason)
    if p.get("metadata", {}).get("deletionTimestamp"):
        reason = "Terminating"
    tags = []
    for c in spec.get("containers", []):
        img = c.get("image", "")
        tags.append(img.rsplit(":", 1)[-1][:10] if ":" in img.split("/")[-1] else "latest")
    return {"ns": p["metadata"].get("namespace", ""), "name": p["metadata"]["name"], "ready": f"{ready}/{total}", "status": reason,
            "restarts": sum(c.get("restartCount", 0) for c in cs), "age": _ago(p["metadata"].get("creationTimestamp")),
            "tags": ", ".join(tags), "node": spec.get("nodeName", ""), "ok": reason == "Running" and ready == total and total > 0}

def fetch_cluster(kubectl, repo, env):
    d = {"at": time.strftime("%H:%M:%S"), "error": None, "pods": [], "nodes": [], "events": [], "argo": None}
    base = [kubectl, "--request-timeout=10s"]
    rc, out, err = _run(base + ["get", "pods", "-A", "-o", "json"], repo, env, 40)
    j = _json(out) if rc == 0 else None
    if j is None:
        d["error"] = redact.redact((err or out).strip())[:300] or "kubectl gave no answer"
        return d
    d["pods"] = [_pod_row(p) for p in j.get("items", [])]
    rc, out, _ = _run(base + ["-n", "argocd", "get", "application", "bako", "-o", "json"], repo, env, 40)
    a = _json(out) if rc == 0 else None
    if a:
        d["argo"] = {"sync": a.get("status", {}).get("sync", {}).get("status", "?"),
                     "health": a.get("status", {}).get("health", {}).get("status", "?"),
                     "revision": str(a.get("status", {}).get("sync", {}).get("revision", ""))[:7]}
    rc, out, _ = _run(base + ["get", "nodes", "-o", "json"], repo, env, 40)
    n = _json(out) if rc == 0 else None
    for x in (n or {}).get("items", []):
        ready = next((c.get("status") for c in x.get("status", {}).get("conditions", []) if c.get("type") == "Ready"), "?")
        d["nodes"].append({"name": x["metadata"]["name"], "ready": ready == "True",
                           "version": x.get("status", {}).get("nodeInfo", {}).get("kubeletVersion", ""),
                           "age": _ago(x["metadata"].get("creationTimestamp"))})
    rc, out, _ = _run(base + ["get", "events", "-A", "--field-selector", "type=Warning", "-o", "json"], repo, env, 40)
    ev = _json(out) if rc == 0 else None
    items = sorted((ev or {}).get("items", []), key=lambda e: e.get("lastTimestamp") or e.get("eventTime") or "", reverse=True)[:8]
    d["events"] = [{"ns": e.get("involvedObject", {}).get("namespace") or e.get("metadata", {}).get("namespace", ""), "reason": e.get("reason", ""), "object": e.get("involvedObject", {}).get("name", ""),
                    "message": redact.redact(e.get("message", ""))[:160], "count": e.get("count", 1),
                    "age": _ago(e.get("lastTimestamp") or e.get("eventTime"))} for e in items]
    return d

def fetch_aws(bash, repo, env):
    rc, out, err = _run([bash, "agent/env/checks.sh", "nothing-running"], repo, env, 150)
    rows = []
    for line in out.splitlines():
        m = re.match(r"^(PASS|FAIL)\s+(.*)$", line.strip())
        if m:
            rows.append({"running": m.group(1) == "FAIL", "text": m.group(2)})
    return {"at": time.strftime("%H:%M:%S"), "rows": rows, "rc": rc, "error": None if rows else (err or out).strip()[:300]}

## ---------------------------------------------------------------
## 3. BACKGROUND LOADING (stale-while-refreshing)
## ---------------------------------------------------------------
def bg(key, fn, ttl=60, force=False, auto=True):
    """Returns the entry {data, job, at, error}. Starts a thread when the data is missing or older than ttl seconds
    (only if auto, or when force is True). Call it again to pick up a finished result."""
    store = st.session_state.setdefault("_bg", {})
    e = store.setdefault(key, {"data": None, "job": None, "holder": None, "at": None, "error": None})
    if e["job"] is not None and not e["job"].is_alive():
        h = e["holder"] or {}
        e["data"] = h.get("data", e["data"])
        e["error"] = h.get("error")
        e["at"], e["job"] = time.time(), None
    stale = e["at"] is None or (time.time() - e["at"] > ttl)
    if e["job"] is None and (force or (auto and stale)):
        holder = {}
        def work():
            try:
                holder["data"] = fn()
            except Exception as ex:                       # a failed load must never hang the page
                holder["error"] = f"{type(ex).__name__}: {ex}"
        t = threading.Thread(target=work, daemon=True)
        t.start()
        e["job"], e["holder"] = t, holder
    return e

## ---------------------------------------------------------------
## 4. SMALL DRAWING HELPERS
## ---------------------------------------------------------------
def _pill(text, kind, T=None):
    cls = {"ok": "ok", "bad": "bad"}.get(kind, "")
    extra = "" if cls else " style='background:rgba(127,127,127,.18)'"
    return f"<span class='pill {cls}'{extra}>{html.escape(str(text))}</span>"

def _link(url, text):
    url = str(url or "")
    if url.startswith("https://github.com/"):
        return f"<a href='{html.escape(url)}' target='_blank' style='color:inherit'>{html.escape(str(text))}</a>"
    return html.escape(str(text))

def _kpis(items):
    for col, (l, v, n) in zip(st.columns(len(items), gap="small"), items):
        col.markdown(f"<div class='kpi'><div class='l'>{html.escape(l)}</div><div class='v'>{html.escape(str(v))}</div>"
                     f"<div class='n'>{html.escape(n)}</div></div>", unsafe_allow_html=True)

def _table(head, rows):
    th = "".join(f"<th>{html.escape(h)}</th>" for h in head)
    return f"<div class='card' style='overflow-x:auto;padding:8px 14px'><table class='rtable'><tr>{th}</tr>{''.join(rows)}</table></div>"

def _ask(text):
    st.session_state.flow_prompt = redact.redact(text)

## ---------------------------------------------------------------
## 5. CLICKABLE TABLES AND THE DETAIL PANEL (under the chat, on the right)
## Click a row in a table below and the panel under the chat shows everything about it:
## for a CI run the failed step and the log, for a pull request the runs it started, for a pod its events and log.
## ---------------------------------------------------------------
import pandas as pd

def _pick(key, rows, ids, kind, height):
    """Draws a clickable table. rows = list of dicts (what you see), ids = what identifies each row.
    A click on a row opens it in the detail panel."""
    ss = st.session_state
    if not rows:
        return
    ev = st.dataframe(pd.DataFrame(rows), key=f"tbl_{key}", on_select="rerun", selection_mode="single-row",
                      hide_index=True, use_container_width=True, height=height)
    sel = tuple(ev.selection.rows)
    if sel != ss.get(f"_sel_{key}", ()):               # only react when the click changed
        ss[f"_sel_{key}"] = sel
        if sel and sel[0] < len(ids):
            ss["detail"] = {"kind": kind, "id": ids[sel[0]]}
            st.rerun()

def _res(r):
    x = r.get("conclusion") or r.get("status") or "?"
    return {"success": "✓ success", "failure": "✗ failure", "cancelled": "– cancelled"}.get(x, "… " + x)

def _height(n, row=35, cap=330):
    return min(cap, 38 + row * max(n, 1))

def fetch_run(gh, repo, env, run_id):
    rc, out, _ = _run([gh, "run", "view", str(run_id), "--json", "conclusion,status,url,jobs,displayTitle,event,headBranch,createdAt"], repo, env, 90)
    j = _json(out) or {}
    failed = []
    for job in j.get("jobs", []):
        for s in job.get("steps", []):
            if (s.get("conclusion") or "") not in ("success", "skipped", ""):
                failed.append(f"{job.get('name')}  →  {s.get('name')}  ({s.get('conclusion')})")
    lines = []
    if j.get("conclusion") == "failure" or not j:
        rc, out, _ = _run([gh, "run", "view", str(run_id), "--log-failed"], repo, env, 90)
        for l in out.splitlines():
            parts = l.split("\t", 2)
            l = parts[2] if len(parts) == 3 else l
            l = re.sub(r"^\S+Z\s", "", l)                      # drop the timestamp in front of each line
            lines.append(redact.redact(l.rstrip()))
    key = [l for l in lines if re.search(r"error|fail|denied|not authorized|exception|not found|invalid", l, re.I)
           and not l.lstrip().startswith(("##[group]", "##[endgroup]"))]
    return {"failed": failed, "key": key[:8], "tail": lines[-25:], "n": len(lines), "url": j.get("url", ""), "conclusion": j.get("conclusion")}

def fetch_podlog(kubectl, repo, env, ns, name):
    rc, out, err = _run([kubectl, "--request-timeout=15s", "-n", ns, "logs", name, "--all-containers", "--tail=30"], repo, env, 40)
    return redact.redact((out or err).strip())[-3000:] or "(no log lines)"

def _pending_entry(d, sel):
    """Starts the background load the selected row needs and returns its entry (None when it needs none)."""
    ss = st.session_state
    if not sel:
        return None
    if sel["kind"] == "run":
        repo_data = (ss.get("_bg", {}).get("repo") or {}).get("data")
        r = _find(repo_data, "runs", sel["id"])
        if r and (r.get("conclusion") or r.get("status")) != "success":
            return bg(f"run_{sel['id']}", lambda: fetch_run(d["gh"], d["repo"], d["env"], sel["id"]), ttl=120)
    if sel["kind"] == "pod":
        ns, name = sel["id"]
        key = f"podlog_{ns}_{name}"
        if ss.get(f"want_{key}"):
            return bg(key, lambda: fetch_podlog(d["kubectl"], d["repo"], d["env"], ns, name), ttl=30)
    return None

def detail_panel(d):
    """d: dict(repo, env, gh, kubectl). Drawn in the right column under the chat.
    While a log is still loading, the panel redraws itself every 2 seconds, then the page redraws once."""
    e = _pending_entry(d, st.session_state.get("detail"))
    loading = e is not None and e["job"] is not None
    st.session_state["_detail_loading"] = loading
    st.fragment(_detail_body, run_every=2 if loading else None)(d)

def _find(data, key, val, field="databaseId"):
    return next((x for x in (data or {}).get(key, []) if x.get(field) == val), None)

def _detail_body(d):
    ss = st.session_state
    sel = ss.get("detail")
    with st.container(key="detail"):
        if not sel:
            st.markdown("<div class='ctitle'>Details</div><div class='sub'>Click a row in a table (a CI run, a pull request or a pod) "
                        "and everything about it opens here.</div>", unsafe_allow_html=True)
            return
        c1, c2 = st.columns([2, 1])
        c1.markdown(f"<div class='ctitle'>{ {'run': 'CI run', 'pr': 'Pull request', 'pod': 'Pod'}[sel['kind']] }</div>", unsafe_allow_html=True)
        if c2.button("Close", key="detail_close", use_container_width=True):
            ss["detail"] = None
            st.rerun()
        repo_data = (ss.get("_bg", {}).get("repo") or {}).get("data")
        if sel["kind"] == "run":
            _detail_run(d, repo_data, sel["id"])
        elif sel["kind"] == "pr":
            _detail_pr(d, repo_data, sel["id"])
        else:
            _detail_pod(d, (ss.get("_bg", {}).get("cluster") or {}).get("data"), sel["id"])

def _detail_run(d, data, rid):
    r = _find(data, "runs", rid)
    if not r:
        st.markdown("<div class='sub'>This run is no longer in the list. Press Refresh on the Repo tab.</div>", unsafe_allow_html=True)
        return
    res = r.get("conclusion") or r.get("status") or "?"
    st.markdown(f"**{html.escape(r.get('displayTitle', ''))}**  \n"
                f"{_pill(res, 'ok' if res == 'success' else 'bad' if res == 'failure' else 'soft')}  "
                f"<span class='sub'>run {rid} · {html.escape(r.get('workflowName', ''))} · started by <b>{html.escape(r.get('event', ''))}</b> "
                f"on <b>{html.escape(r.get('headBranch', ''))}</b> · {html.escape(_ago(r.get('createdAt')))}</span>", unsafe_allow_html=True)
    if str(r.get("url", "")).startswith("https://github.com/"):
        st.markdown(f"[Open on GitHub]({r['url']})")
    if res == "success":
        st.markdown("<div class='sub'>This run succeeded. There is no failed step.</div>", unsafe_allow_html=True)
        return
    if res == "action_required":
        st.markdown("<div class='sub'><b>GitHub is holding this run until someone approves it.</b> No job has started, so there is no log and no failed step. "
                    "A person with write access approves it on GitHub (open the run while signed in; the Approve button is on the run page). "
                    "If nobody approves in time, the run expires and GitHub marks it as failed. "
                    "Pull requests opened by the github-actions bot work like this.</div>", unsafe_allow_html=True)
        return
    e = bg(f"run_{rid}", lambda: fetch_run(d["gh"], d["repo"], d["env"], rid), ttl=120)
    x = e["data"]
    if x is None:
        if e["job"] is not None:
            st.caption("Loading the failed step and its log...")
        else:
            st.caption("Could not load: " + str(e["error"]))
            if st.session_state.pop("_detail_loading", False):
                st.rerun()
        return
    if st.session_state.pop("_detail_loading", False):
        st.rerun()                                          # the load finished: redraw the page once so the polling stops
    if x["failed"]:
        st.markdown("**Failed step**")
        st.code("\n".join(x["failed"]), language=None, wrap_lines=True)
    if x["key"]:
        st.markdown("**Lines that matter**")
        st.code("\n".join(x["key"]), language=None, wrap_lines=True)
    elif not x["failed"]:
        st.caption("GitHub gave no failed step and no log for this run.")
    if x["tail"]:
        with st.expander(f"Last {len(x['tail'])} of {x['n']} log lines"):
            st.code("\n".join(x["tail"]), language=None, wrap_lines=True)
    if st.button("Ask Bako to explain this", key=f"ask_run_{rid}", use_container_width=True):
        _ask(f"Explain why CI run {rid} ({r.get('displayTitle', '')}, started by {r.get('event')} on {r.get('headBranch')}) failed. Evidence:\n\n```\n"
             + "\n".join((x["failed"] + x["key"])[:8])[:700] + "\n```")
        st.rerun()

def _detail_pr(d, data, n):
    p = _find(data, "prs", n, "number")
    if not p:
        st.markdown("<div class='sub'>This pull request is no longer in the list.</div>", unsafe_allow_html=True)
        return
    state = p.get("state", "?")
    st.markdown(f"**#{n} {html.escape(p.get('title', ''))}**  \n{_pill(state, {'MERGED': 'ok', 'CLOSED': 'bad'}.get(state, 'soft'))}  "
                f"<span class='sub'>branch <b>{html.escape(p.get('headRefName', ''))}</b> · opened {html.escape(_ago(p.get('createdAt')))}"
                + (f" · merged {html.escape(_ago(p['mergedAt']))}" if p.get("mergedAt") else "") + "</span>", unsafe_allow_html=True)
    if str(p.get("url", "")).startswith("https://github.com/"):
        st.markdown(f"[Open on GitHub]({p['url']})")
    runs = (data or {}).get("runs", [])
    branch = p.get("headRefName")
    mine = [r for r in runs if r.get("headBranch") == branch]
    after = [r for r in runs if p.get("mergedAt") and (_when(r["createdAt"]) or datetime.datetime.min) >= (_when(p["mergedAt"]) or datetime.datetime.max)
             and r not in mine]
    for title, group in (("CI runs on its branch", mine), ("CI runs that started after the merge", after)):
        if group:
            st.markdown(f"**{title}**")
            for r in group[:5]:
                if st.button(f"{_res(r)} · {r.get('event')} · {_ago(r['createdAt'])}", key=f"pr{n}_run_{r['databaseId']}", use_container_width=True):
                    st.session_state["detail"] = {"kind": "run", "id": r["databaseId"]}
                    st.rerun()
    if state == "MERGED" and not after:
        st.markdown("<div class='sub'>No CI run started after the merge.</div>", unsafe_allow_html=True)
    if state == "OPEN" and str(branch).startswith("bako/update-"):
        if st.button(f"Review and merge #{n}", key=f"rm_{n}", use_container_width=True):
            st.session_state.code_pr = {"branch": branch, "message": p.get("title", ""), "files": [], "n": n, "url": p.get("url")}
            st.rerun()

def _detail_pod(d, data, pid):
    ns, name = pid
    p = next((x for x in (data or {}).get("pods", []) if x["ns"] == ns and x["name"] == name), None)
    if not p:
        st.markdown("<div class='sub'>This pod is gone or the cluster is down.</div>", unsafe_allow_html=True)
        return
    st.markdown(f"**{html.escape(name)}**  \n{_pill(p['status'], 'ok' if p['ok'] else 'bad')}  "
                f"<span class='sub'>namespace <b>{html.escape(ns)}</b> · ready {p['ready']} · {p['restarts']} restarts · "
                f"age {html.escape(p['age'])} · image tag {html.escape(p['tags'])} · node {html.escape(p['node'])}</span>", unsafe_allow_html=True)
    ev = [x for x in data.get("events", []) if x["object"] == name and x["ns"] == ns]
    st.markdown("**Warnings for this pod**")
    st.code("\n".join(f"{x['reason']} (x{x['count']}, {x['age']}): {x['message']}" for x in ev) or "none", language=None, wrap_lines=True)
    key = f"podlog_{ns}_{name}"
    want = st.session_state.get(f"want_{key}", False)
    if not want:
        if st.button("Show the last 30 log lines", key=f"btn_{key}", use_container_width=True):
            st.session_state[f"want_{key}"] = True
            st.rerun()
    else:
        e = bg(key, lambda: fetch_podlog(d["kubectl"], d["repo"], d["env"], ns, name), ttl=30)
        if e["data"] is not None:
            st.code(e["data"], language=None, wrap_lines=True)
            if st.session_state.pop("_detail_loading", False):
                st.rerun()
        else:
            st.caption("Loading the log...")
    if not p["ok"] and st.button(f"Ask Bako about {name}", key=f"ask_{key}", use_container_width=True):
        _ask(f"Pod {name} in namespace {ns} is {p['status']} (ready {p['ready']}, {p['restarts']} restarts, image tag {p['tags']}). Warning events:\n\n```\n"
             + "\n".join(f"{x['reason']}: {x['message']}" for x in ev[:3]) + "\n```")
        st.rerun()

## ---------------------------------------------------------------
## 6. THE REPO TAB
## ---------------------------------------------------------------
def repo_tab(d):
    """d: dict(repo, env, gh, T)."""
    fn = lambda: fetch_repo(d["repo"], d["gh"], d["env"])
    e = bg("repo", fn, ttl=90)
    st.fragment(_repo_body, run_every=2 if e["job"] is not None else None)(d)

def _repo_body(d):
    fn = lambda: fetch_repo(d["repo"], d["gh"], d["env"])
    e = bg("repo", fn, ttl=90)
    c1, c2 = st.columns([4, 1])
    if c2.button("Refresh", key="refresh_repo", use_container_width=True, disabled=e["job"] is not None):
        bg("repo", fn, force=True)
        st.rerun(scope="fragment")
    data = e["data"]
    c1.markdown(f"<div class='sub'>Click a row to see its details on the right. "
                f"{'Loaded at ' + data['at'] + '. ' if data else ''}{'Loading from git and GitHub...' if e['job'] is not None else ''}</div>",
                unsafe_allow_html=True)
    if e["error"] and not data:
        st.error("Could not load: " + e["error"])
    if not data:
        return
    if data.get("gh_error"):
        st.warning(data["gh_error"])
    runs, prs = data["runs"], data["prs"]
    last = runs[0] if runs else None
    sync = ""
    if data.get("ahead") is not None:
        sync = f"{data['ahead']} ahead, {data['behind']} behind origin/main (as of your last fetch)"
    _kpis([("Branch", data["branch"], sync or data["head"][:40]),
           ("Your changes", f"{len(data['changes'])} file(s)", "not committed yet" if data["changes"] else "folder is clean"),
           ("Open pull requests", sum(1 for p in prs if p.get("state") == "OPEN"), f"{len(prs)} recent"),
           ("Latest CI run", (last.get("conclusion") or last.get("status") or "?") if last else "-",
            f"{_ago(last['createdAt'])} · {last.get('displayTitle', '')[:30]}" if last else "no runs found")])
    st.write("")

    ## --- what the last merge did (the question "did anything run after my merge?") ---
    merged = next((p for p in prs if p.get("state") == "MERGED"), None)
    if merged:
        after = [r for r in runs if (_when(r["createdAt"]) or datetime.datetime.min) >= (_when(merged.get("mergedAt")) or datetime.datetime.max)]
        line = f"Pull request #{merged['number']} \"{merged['title'][:60]}\" was merged {_ago(merged.get('mergedAt'))}. "
        if after:
            line += f"{len(after)} CI run(s) started after that: " + ", ".join(
                f"{(r.get('conclusion') or r.get('status'))} ({r.get('event')} on {r.get('headBranch')})" for r in after[:4]) + "."
        else:
            line += "No CI run started after it."
        with st.container(key="repo_after"):
            st.markdown("<div class='ctitle'>After the last merge</div>", unsafe_allow_html=True)
            st.markdown(f"<div class='sub' style='font-size:15px'>{html.escape(line)}</div>", unsafe_allow_html=True)
            if after and st.button(f"Open the newest of them (run {after[0]['databaseId']})", key="repo_open_after"):
                st.session_state["detail"] = {"kind": "run", "id": after[0]["databaseId"]}
                st.rerun()
        st.write("")

    st.markdown("<div class='ctitle'>CI runs (GitHub Actions)</div>", unsafe_allow_html=True)
    _pick("runs", [{"Result": _res(r), "Title": r.get("displayTitle", "")[:60], "Branch": r.get("headRefName", r.get("headBranch", ""))[:34],
                    "Started by": r.get("event", ""), "When": _ago(r.get("createdAt"))} for r in runs],
          [r["databaseId"] for r in runs], "run", _height(len(runs)))
    if not runs:
        st.markdown("<div class='sub'>No runs found.</div>", unsafe_allow_html=True)

    st.markdown("<div class='ctitle' style='margin-top:14px'>Pull requests</div>", unsafe_allow_html=True)
    _pick("prs", [{"PR": f"#{p['number']}", "Title": p.get("title", "")[:56], "Branch": p.get("headRefName", "")[:34],
                   "State": p.get("state", "?"), "When": _ago(p.get("mergedAt") or p.get("createdAt"))} for p in prs],
          [p["number"] for p in prs], "pr", _height(len(prs)))
    if not prs:
        st.markdown("<div class='sub'>None found.</div>", unsafe_allow_html=True)

    st.markdown("<div class='ctitle' style='margin-top:14px'>Your changes</div>", unsafe_allow_html=True)
    if not data["changes"]:
        st.markdown("<div class='sub'>Nothing to commit. Everything in your folder is already committed.</div>", unsafe_allow_html=True)
    else:
        st.dataframe(pd.DataFrame([{"File": c["path"], "Change": "skipped: secret-looking" if c["blocked"] else c["status"]} for c in data["changes"]]),
                     hide_index=True, use_container_width=True, height=_height(len(data["changes"]), cap=250))
        msg = st.text_input("Commit message", value="Update Bako files", key="repo_commit_msg")
        if st.button("Prepare commit and push", key="repo_prepare", use_container_width=True):
            ctx = {}
            res = bako_chat.t_propose_commit_push(d["repo"], ctx, message=msg)
            if ctx.get("action"):
                st.session_state.pending = ctx["action"]          # the same approval card as the chat: you type push bako
                st.rerun()
            else:
                st.info(res)
        st.caption("This only prepares the proposal. Nothing is committed until you type push bako in the chat.")

## ---------------------------------------------------------------
## 7. THE CLUSTER TAB
## ---------------------------------------------------------------
def cluster_tab(d):
    """d: dict(repo, env, kubectl, state, T). state is the lab state from the Lab tab (DOWN, READY, ...)."""
    if d["state"] == "DOWN":
        st.markdown("<div class='card'><div class='ctitle'>The lab is down</div>There is no cluster to look at. Nothing is billing. "
                    "Press <b>Start lab</b> and this tab fills with the pods, the Argo CD app and the nodes.</div>", unsafe_allow_html=True)
        return
    if not d.get("kubectl"):
        st.warning("kubectl was not found on this computer.")
        return
    fn = lambda: fetch_cluster(d["kubectl"], d["repo"], d["env"])
    e = bg("cluster", fn, ttl=30)
    st.fragment(_cluster_body, run_every=2 if e["job"] is not None else None)(d)

def _cluster_body(d):
    fn = lambda: fetch_cluster(d["kubectl"], d["repo"], d["env"])
    e = bg("cluster", fn, ttl=30)
    c1, c2 = st.columns([4, 1])
    if c2.button("Refresh", key="refresh_cluster", use_container_width=True, disabled=e["job"] is not None):
        bg("cluster", fn, force=True)
        st.rerun(scope="fragment")
    data = e["data"]
    c1.markdown(f"<div class='sub'>Click a pod to see its details on the right. {'Loaded at ' + data['at'] + '. ' if data else ''}"
                f"{'Asking the cluster...' if e['job'] is not None else ''}</div>", unsafe_allow_html=True)
    if not data:
        if e["error"]:
            st.error("Could not load: " + e["error"])
        return
    if data["error"]:
        st.error("The cluster did not answer: " + data["error"] + "  \nIf the lab was just started, wait a minute and press Refresh.")
        return
    allpods, argo = data["pods"], data["argo"]
    ok = sum(1 for p in allpods if p["ok"])
    spaces = sorted({p["ns"] for p in allpods})
    _kpis([("Pods ready", f"{ok} / {len(allpods)}", f"{sum(p['restarts'] for p in allpods)} restarts · {len(spaces)} namespaces"),
           ("Argo CD app", (argo or {}).get("sync", "unknown"), f"health: {(argo or {}).get('health', 'unknown')} · commit {(argo or {}).get('revision', '-')}"),
           ("Nodes", f"{sum(1 for n in data['nodes'] if n['ready'])} / {len(data['nodes'])}", "ready"),
           ("Warnings", len(data["events"]), "recent, all namespaces")])
    st.write("")
    pick = st.selectbox("Namespace", ["All namespaces"] + spaces, key="cluster_ns", label_visibility="collapsed")
    pods = sorted((p for p in allpods if pick in ("All namespaces", p["ns"])), key=lambda p: (p["ok"], p["ns"], p["name"]))   # problems first
    st.markdown(f"<div class='ctitle'>Pods ({'all namespaces' if pick == 'All namespaces' else pick}): {len(pods)}</div>", unsafe_allow_html=True)
    _pick("pods", [{"Namespace": p["ns"], "Pod": p["name"][:44], "Ready": p["ready"], "Status": ("✓ " if p["ok"] else "✗ ") + p["status"],
                    "Restarts": p["restarts"], "Age": p["age"], "Image tag": p["tags"]} for p in pods],
          [(p["ns"], p["name"]) for p in pods], "pod", _height(len(pods), cap=380))
    if not pods:
        st.markdown("<div class='sub'>No pods here.</div>", unsafe_allow_html=True)
    st.markdown("<div class='ctitle' style='margin-top:14px'>Nodes</div>", unsafe_allow_html=True)
    st.dataframe(pd.DataFrame([{"Node": n["name"][-30:], "State": "✓ Ready" if n["ready"] else "✗ NotReady", "Version": n["version"], "Age": n["age"]}
                               for n in data["nodes"]]), hide_index=True, use_container_width=True, height=_height(len(data["nodes"])))
    st.markdown("<div class='ctitle' style='margin-top:14px'>Recent warnings</div>", unsafe_allow_html=True)
    if data["events"]:
        st.dataframe(pd.DataFrame([{"Namespace": x["ns"], "Reason": x["reason"], "On": x["object"][:28], "Message": x["message"], "When": x["age"]}
                                   for x in data["events"]]), hide_index=True, use_container_width=True, height=_height(len(data["events"])))
    else:
        st.markdown("<div class='sub'>No warnings. Good.</div>", unsafe_allow_html=True)

## ---------------------------------------------------------------
## 7. THE AWS RESOURCES TAB (what could still be billing; the money itself is on the Reports page)
## ---------------------------------------------------------------
def aws_tab(d):
    """d: dict(repo, env, bash, T, hourly, up_now)."""
    T = d["T"]
    fn = lambda: fetch_aws(d["bash"], d["repo"], d["env"])
    e = bg("aws", fn, ttl=10**9, auto=False)
    if e["job"] is not None:
        st.fragment(_aws_wait, run_every=2)(d)
    c1, c2 = st.columns([4, 1])
    ms = usage.month_summary(d["repo"], d["hourly"], d["up_now"])
    c1.markdown(f"<div class='sub'>What could still be billing in AWS. Money: <b>${ms['spent']:.2f}</b> so far this month "
                f"(details and budget on the Reports page).</div>", unsafe_allow_html=True)
    if c2.button("Reports", key="aws_to_reports", use_container_width=True):
        st.session_state.page = "reports"
        st.rerun()
    if st.button("Check what is running in AWS now", key="aws_check", use_container_width=True, disabled=e["job"] is not None,
                 help="Runs the same checks as Stop does. Takes 10 to 30 seconds."):
        bg("aws", fn, force=True, auto=False)
        st.rerun()
    data = e["data"]
    if e["job"] is not None:
        st.caption("Asking AWS... this takes 10 to 30 seconds.")
    elif not data:
        st.markdown("<div class='sub'>Not checked yet. The check counts clusters, nodes, NAT gateways, Elastic IPs, databases and load balancers.</div>",
                    unsafe_allow_html=True)
    else:
        if data["error"]:
            st.error("The check could not run: " + data["error"])
        running = [r for r in data["rows"] if r["running"]]
        rows = [f"<tr><td>{html.escape(r['text'])}</td><td>{_pill('running: billing' if r['running'] else 'none', 'bad' if r['running'] else 'ok', T)}</td></tr>"
                for r in data["rows"]]
        st.markdown(f"<div class='sub'>Checked at {html.escape(data['at'])}: "
                    + ("<b>nothing is running, nothing is billing.</b>" if data["rows"] and not running else f"<b>{len(running)} item(s) are running and billing.</b>")
                    + "</div>", unsafe_allow_html=True)
        if rows:
            st.markdown(_table(["Resource", "State"], rows), unsafe_allow_html=True)

def _aws_wait(d):
    ## re-checks the background thread every 2 seconds; when it is done, the whole page redraws once with the result
    e = bg("aws", lambda: None, ttl=10**9, auto=False)
    if e["job"] is None:
        st.rerun()