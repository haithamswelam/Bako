## ---------------------------------------------------------------
## FLOW TAB for the Bako dashboard  (agent/env/flow_tab.py)
## Draws three flows as clickable boxes and colours them from FACTS:
##   - Start Lab flow and Stop Lab flow: from the newest agent trace file
##     (agent/env/reports/trace-*.jsonl). Each START step writes a
##     {"event": "stage", "id": ..., "status": ...} line; STOP is read from
##     its existing events.
##   - Bako and OpenAI flow: from the last chat message's trace
##     (a dict the chat code leaves in session_state["chat_trace"]).
## Click a box: what it does, what it found (evidence), likely cause if it failed,
## and a button that sends the step to Bako in the chat to troubleshoot.
## This file only READS. Nothing here changes AWS, git or any file.
## ---------------------------------------------------------------
import glob, json, os, re, webbrowser
import streamlit as st

## ---- colours (same palette as the approved mockup; "warm" is the default) ----
THEMES = {
    "warm": dict(bg="#EFEDEA", card="#FDFCFB", inset="#F5F3F0", soft="#E5E1DB", accent="#C4B8A8", border="#E6E2DC",
                 ink="#3B3834", muted="#635E57", ink2="#49453F", light="#F9F8F6", deep="#3B3834", onAccent="#3B3834",
                 panel="#3B3834", onPanel="#F9F8F6", panelAccent="#C4B8A8", dashA="#A9A49D", dashB="#CFCBC6",
                 okBg="#D9F0E1", okFg="#17613A", okLine="#2E8B57", badBg="#F8D9D4", badFg="#8A2A1B", badLine="#B3382A", notice="#EEEBE6"),
    "dark": dict(bg="#1E1C1A", card="#292623", inset="#322E2A", soft="#413B34", accent="#C9BBA6", border="#3A3631",
                 ink="#ECE7DE", muted="#B3ABA0", ink2="#D8D2C7", light="#1E1C1A", deep="#ECE7DE", onAccent="#1E1C1A",
                 panel="#3A3631", onPanel="#ECE7DE", panelAccent="#D2C3A9", dashA="#7E776D", dashB="#5C564E",
                 okBg="#22382A", okFg="#8FD6A8", okLine="#4E9A68", badBg="#4A2B27", badFg="#F4AFA3", badLine="#D9695A", notice="#3A342B"),
}

## ---- the flows: lanes of steps. id = the stage id the agent writes ----
def N(id, label, sub, what, ifFails, url=None):
    return dict(id=id, label=label, sub=sub, what=what, ifFails=ifFails, url=url)

FLOWS = {
    "start": dict(title="Start Lab flow", lanes=[
        dict(label="On your computer · the agent", then="then GitHub builds the images", nodes=[
            N("acct", "Account check", "expected AWS account", "Runs checks.sh account. Everything stops if the AWS account is not the expected one.",
              "Wrong AWS profile or an expired login. Sign in again, then retry. Nothing was changed."),
            N("plan", "Terraform plan", "what will be created", "Saves an exact plan file. It counts as clean only when it deletes nothing.",
              "A plan with deletes or errors usually means state drift or a missing variable. Read the plan output first."),
            N("appr", "Your approval", "you type approved", "The agent itself compares the word you typed. No other word counts.",
              "Any other word means no. The run stops and nothing is applied."),
            N("apply", "Terraform apply", "creates the lab", "Applies the exact saved plan file, nothing more.",
              "A half-finished apply: do not rerun blindly. Make a new plan and compare it with the old one."),
            N("boot", "Bootstrap cluster", "kubectl + script", "Points kubectl at the new cluster (and refuses a wrong one), then installs Argo CD, External Secrets and the app. Runs BEFORE the build, so a broken cluster stops the run early.",
              "A command was not found (for example base64 or helm), or kubectl cannot reach the cluster, or the context is the wrong account. The log names the exact line. Fix it, then press Start again: finished steps are skipped.")]),
        dict(label="On GitHub · CI workflow (ci.yml)", then="then the bot opens a pull request", nodes=[
            N("trig", "Trigger build", "ci.yml on main", "Starts ci.yml on main, only after the cluster is up. Skipped when the images for this commit already exist.",
              "GitHub login missing on this computer (gh auth status), or the workflow file has an error.", url="run"),
            N("test", "Tests and lint", "backend, frontend", "Runs the backend and frontend checks before anything is built.",
              "A test failed. The log names the test. Fix it on a branch, merge, then START again.", url="run"),
            N("build", "Build images", "tag = commit id", "Builds bako-backend and bako-frontend, tagged with the commit id.",
              "Usually a Dockerfile or dependency error. The failed log shows the exact line.", url="run"),
            N("push", "Push to ECR", "needs the AWS role", "Signs in to AWS with the OIDC role and pushes both images to ECR.",
              "The AWS role was not found or does not trust this run. A role created minutes ago can take about a minute to work; Bako retries once by itself.", url="run")]),
        dict(label="Pull request · Argo CD and you", then="", nodes=[
            N("bot", "Bot pull request", "image tags bumped", "After a good build, CI opens a pull request that changes the image tags in K8s/.",
              "No pull request after 10 minutes means the build did not finish. Check the CI run.", url="pr"),
            N("merge", "Your merge", "you click Merge", "You merge the bot pull request on GitHub. Bako never merges it for you.",
              "Red checks on the pull request: open it and read the failing check.", url="pr"),
            N("argo", "Argo CD sync", "deploys K8s/", "Argo CD deploys whatever is in K8s/ after your merge. Bako waits until it is Synced and Healthy at that commit.",
              "OutOfSync or Degraded. Look at the pod events: often ImagePullBackOff because the tag is not in ECR."),
            N("ready", "READY checks", "checks.sh ready", "Argo Healthy, pods Running with 0 restarts, running image tags exist in ECR.",
              "The failing row names the problem. Fix it, then run the checks again.")])]),
    "stop": dict(title="Stop Lab flow", lanes=[
        dict(label="On your computer · the agent", then="", nodes=[
            N("s1", "Account check", "expected account", "Same check as START: stops if the AWS account is not the expected one.",
              "Wrong profile or expired login. Nothing is deleted."),
            N("s2", "Destroy plan", "only deletes", "Saves a plan that must delete resources and create or change none.",
              "A destroy plan with creates or changes means something is off. Read it before going on."),
            N("s3", "Your approval", "you type destroy bako", "The agent itself compares the word you typed.",
              "Any other word means no. Nothing is deleted."),
            N("s4", "Terraform destroy", "deletes the lab", "Runs the exact saved destroy plan.",
              "A resource that will not delete (often a load balancer or network interface). Delete it, then run again."),
            N("s5", "Nothing-running checks", "billing stopped?", "Checks that no cluster, node, NAT gateway, Elastic IP, database or load balancer is left billing.",
              "Any row that is not 0 is still costing money. The row names it.")])]),
    "chat": dict(title="Bako and OpenAI", lanes=[
        dict(label="On your computer · bako_chat.py", then="the request goes out", nodes=[
            N("c1", "You ask", "your message", "Your message, plus the last 20 text messages of the conversation.", "An empty or very long message. Shorten it."),
            N("c2", "Build the request", "rules + history", "Adds the charter (the rules) and the first 6,000 characters of CHARTER.md. The model remembers nothing, so everything is sent again each time.",
              "If CHARTER.md is missing, the built-in rules are used."),
            N("c3", "Send to OpenAI", "model call", "Sends the request to the model over the internet with your key.",
              "A 401 means the key is missing from the keyring (service bako-agent). A timeout means the network: try again.")]),
        dict(label="At OpenAI · the model", then="it asks our code for facts", nodes=[
            N("m1", "Reads the request", "text only", "The model sees text only. It cannot touch your files, GitHub or AWS.",
              "Nothing runs here that you can fix. A bad answer usually means the tools gave it too little."),
            N("m2", "Wants a tool?", "up to 6 times", "If it needs a fact, it asks for a tool. Our code runs it and sends the result back. At most 6 per message, and the same call twice is refused.",
              "When the 6 calls are used up, Bako is forced to answer with what it has."),
            N("m3", "Writes the answer", "reply + tokens", "Writes the reply you see in the chat. Facts about the lab come from code, not from its wording.",
              "If it states a fact that checks do not show, trust the checks.")]),
        dict(label="Tools · run by our code, read only", then="to change anything, Bako can only propose", noarrows=True, nodes=[
            N("t1", "lab_check", "READY or DOWN", "Runs the same checks as the Lab tab.", "Needs AWS login and kubectl access."),
            N("t2", "git", "status, log, show", "Reads git history and changes. Never writes.", "Not a git repository, or a revision name that does not exist."),
            N("t3", "github", "runs, PRs, logs", "Reads CI runs, failed logs and pull requests through the gh program.", "The gh program has no GitHub login on this computer (gh auth login)."),
            N("t4", "read_file / search", "repo files only", "Reads files inside the repo. Secrets, state files, .env and .git are blocked in code.", "A blocked or missing path."),
            N("t5", "agent_logs", "newest run log", "Reads the newest agent log or trace file.", "No log yet today.")]),
        dict(label="Proposals · need your typed word", then="", noarrows=True, nodes=[
            N("p1", "Propose start", "approved", "Bako can only suggest a START. The agent runs it after you type approved.", "Nothing runs without the typed word."),
            N("p2", "Propose stop", "destroy bako", "Bako can only suggest a STOP. The agent runs it after you type destroy bako.", "Nothing runs without the typed word."),
            N("p3", "Propose commit and push", "push bako", "Bako can suggest a commit and push to a new branch, never to main. It happens after you type push bako.", "Nothing runs without the typed word.")])]),
}
CHAT_TOOL_NODE = {"lab_check": "t1", "git": "t2", "github": "t3", "read_file": "t4", "list_dir": "t4", "search_repo": "t4",
                  "agent_logs": "t5", "propose_start": "p1", "propose_stop": "p2", "propose_commit_push": "p3"}

STATUS_TEXT = {"done": "✓ Done", "running": "● Running", "failed": "✕ Failed", "waiting": "○ Waiting",
               "skipped": "– Skipped", "unused": "– Not used"}

## ---------------------------------------------------------------
## 1. READ THE FACTS
## ---------------------------------------------------------------
def read_events(path):
    events = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    events.append(json.loads(line))
                except ValueError:
                    continue
    except OSError:
        pass
    return events

def newest_run(repo, mode):
    ## The newest trace file whose run_start says this mode (start or stop).
    files = sorted(glob.glob(os.path.join(repo, "agent", "env", "reports", "trace-*.jsonl")), reverse=True)
    for path in files[:40]:
        events = read_events(path)
        if any(e.get("event") == "run_start" and e.get("mode") == mode for e in events):
            return path, events
    return None, []

def newest_log(repo, prefix):
    files = sorted(glob.glob(os.path.join(repo, "agent", "env", "reports", prefix + "-*.log")))
    return files[-1] if files else None

def tail(path, n=1200):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()[-n:]
    except OSError:
        return ""

def derive_start(events, running):
    stages = {}
    for e in events:
        if e.get("event") == "stage":
            stages[e["id"]] = dict(status=e.get("status", "waiting"), detail=e.get("detail", ""), time=e.get("time", ""))
    finished = any(e.get("event") == "stop" for e in events)
    out = {}
    for sid, s in stages.items():
        status = s["status"]
        if status == "running" and finished and not running:
            status = "waiting"                      # the run ended while this was running
        out[sid] = dict(s, status=status)
    return out

def derive_stop(events, running):
    st = {}
    def put(sid, status, detail=""):
        st[sid] = dict(status=status, detail=detail, time="")
    for e in events:
        ev = e.get("event")
        if ev == "tool_result" and e.get("tool") == "run_checks" and (e.get("args") or {}).get("kind") == "account":
            put("s1", "done" if "exit code: 0" in e.get("result", "") else "failed", e.get("result", "")[-300:])
        if ev == "step_result" and e.get("step") == "terraform_plan_destroy":
            r = e.get("result", "")
            bad = re.search(r"FAILED|REFUSED|WARNING|not clean", r, re.I)
            put("s2", "failed" if bad else "done", r[:300])
        if ev == "approval" and e.get("tool") == "terraform_destroy":
            put("s3", "done" if e.get("approved") else "failed", "typed word matched" if e.get("approved") else "you did not type destroy bako")
        if ev == "step_result" and e.get("step") == "terraform_destroy":
            r = e.get("result", "")
            put("s4", "done" if r.startswith("destroy OK") else "failed", r[:300])
        if ev == "outcome" and "nothing_running" in e:
            put("s5", "done" if e.get("nothing_running") else "failed",
                "NOTHING RUNNING" if e.get("nothing_running") else "something is still running or the destroy was not confirmed")
    finished = any(e.get("event") == "stop" for e in events)
    order = ["s1", "s2", "s3", "s4", "s5"]
    if running and not finished:
        for sid in order:
            if sid not in st:
                put(sid, "running", "")
                break
    return st

def derive_chat(trace):
    ## trace = {"question","tools":[{"name","ok","detail"}],"tokens","model","proposal"} left by the chat code.
    if not trace:
        return {}, "No message yet in this session. Ask Bako something and this flow lights up."
    if trace.get("error"):
        st = {"c1": dict(status="done", detail='"' + str(trace.get("question", ""))[:200] + '"', time=""),
              "c2": dict(status="done", detail="", time=""),
              "c3": dict(status="failed", detail=str(trace["error"]), time="")}
        return st, f'Last message: "{str(trace.get("question",""))[:70]}" · the model could not be reached: {str(trace["error"])[:120]}'
    st = {k: dict(status="done", detail="", time="") for k in ("c1", "c2", "c3", "m1", "m3")}
    st["c1"]["detail"] = '"' + str(trace.get("question", ""))[:200] + '"'
    st["c3"]["detail"] = "model: " + str(trace.get("model", "?"))
    st["m3"]["detail"] = f"{trace.get('tokens', 0):,} tokens in total"
    tr = trace.get("trace") or {}
    if tr.get("rounds"):
        r1 = tr["rounds"][0]
        st["c2"]["detail"] = f"{r1['request']['message_count']} messages · rules {tr.get('system_chars', 0):,} characters · {tr.get('history_count', 0)} earlier messages"
        st["m1"]["detail"] = f"{(r1.get('usage') or {}).get('prompt_tokens', 0):,} input tokens in call 1"
    tools = trace.get("tools")
    known = tools is not None
    tools = tools or []
    st["m2"] = dict(status="done", time="", detail="\n".join(
        f"call {i}: {t['name']}" + ("" if t.get("ok", True) else "  (failed)") for i, t in enumerate(tools, 1))
        or ("no tool needed" if known else "(the chat code does not record which tools it called yet)"))
    for t in tools:
        nid = CHAT_TOOL_NODE.get(t["name"])
        if nid:
            prev = st.get(nid)
            bad = not t.get("ok", True)
            st[nid] = dict(status="failed" if (bad or (prev and prev["status"] == "failed")) else "done", time="",
                           detail=((prev["detail"] + "\n") if prev and prev["detail"] else "") + str(t.get("detail", ""))[:400])
    used = sum(1 for t in tools if t.get("ok", True))
    bad = sum(1 for t in tools if not t.get("ok", True))
    tool_part = (f" · {used} tool(s) worked" if known else "")
    summary = (f'Last message: "{str(trace.get("question",""))[:70]}"' + tool_part
               + (f", {bad} failed" if bad else "") + f" · {trace.get('tokens', 0):,} tokens." + (" Dashed boxes were not used this time." if known else " Tool details are not recorded yet."))
    return st, summary


## ---------------------------------------------------------------
## 1b. "WHAT HAPPENED THIS TIME" for the Bako and OpenAI boxes, built from the real trace
## (the same box would otherwise say the same thing for every message)
## Returns dict(what, fails, tele) where tele = [(title, text_or_object, language)]
## ---------------------------------------------------------------
TOOL_BOX = {"t1": ("lab_check",), "t2": ("git",), "t3": ("github",), "t4": ("read_file", "list_dir", "search_repo"),
            "t5": ("agent_logs",), "p1": ("propose_start",), "p2": ("propose_stop",), "p3": ("propose_commit_push",)}

def _j(obj):
    return json.dumps(obj, indent=2, ensure_ascii=False)

def _secs(ms):
    return f"{(ms or 0) / 1000:.1f} s"

def _args_short(a):
    try:
        d = json.loads(a or "{}")
        return ", ".join(f"{k}={v}" for k, v in d.items()) or "no arguments"
    except ValueError:
        return str(a)[:80]

def chat_detail(node, trace):
    tr = (trace or {}).get("trace")
    if not tr:
        return None
    nid = node["id"]
    rounds, calls = tr.get("rounds", []), tr.get("calls", [])
    r1 = rounds[0] if rounds else {}
    usage_in = sum((r.get("usage") or {}).get("prompt_tokens", 0) for r in rounds)
    usage_out = sum((r.get("usage") or {}).get("completion_tokens", 0) for r in rounds)
    total_ms = sum(r.get("ms") or 0 for r in rounds)
    names = [t["function"]["name"] for t in tr.get("tools", [])]
    out = dict(what=node["what"], fails=node["ifFails"], tele=[])

    if nid == "c1":
        q = tr.get("question", "")
        out["what"] = (f"You typed {len(q):,} characters. Bako also attached the last {tr.get('history_count', 0)} earlier text messages "
                       f"of this conversation (the limit is 20; tool results from earlier messages are not kept).")
        out["fails"] = "Nothing can fail here. A very long message just costs more tokens, because everything is sent to the model."
        out["tele"] = [("Your message as the model received it", {"role": "user", "content": q}, "json")]
    elif nid == "c2":
        m = r1.get("request", {}).get("message_count", "?")
        notes = tr.get("notes_chars", 0)
        out["what"] = (f"Built the first request: {m} messages = the rules ({tr.get('system_chars', 0):,} characters: "
                       f"{tr.get('builtin_rules_chars', 0):,} built in + {notes:,} from CHARTER.md), {tr.get('history_count', 0)} earlier messages, and your new one. "
                       f"It also lists {len(names)} tools the model may ask for. The model remembers nothing, so this is sent in full every time.")
        out["fails"] = ("CHARTER.md was not found or is empty, so only the built-in rules were sent." if not notes
                        else f"Nothing failed. CHARTER.md was read ({notes:,} characters; only the first 6,000 are used).")
        an = tr.get("anatomy")
        real1 = (r1.get("usage") or {}).get("prompt_tokens", 0)
        if an and real1 and sum(an.values()):
            k_ = real1 / sum(an.values())              # the characters/4 guess is scaled to the number OpenAI really counted
            an = {k: round(v * k_) for k, v in an.items()}
        if an:
            tot = sum(an.values()) or 1
            big = max(an, key=an.get)
            out["what"] += ("\n\nWhere call 1's " + (f"{real1:,} real input tokens" if real1 else "input") + " go (a split estimated from the text sizes): "
                            + ", ".join(f"{k.replace('_', ' ')} ~{v:,}" for k, v in an.items())
                            + f". The biggest part is {big.replace('_', ' ')} ({round(100 * an[big] / tot)}%). All of this is paid again on every call.")
        out["tele"] = [("Request 1: exactly what was sent (the rules are shortened here, the model got all of them)", r1.get("request", {}), "json"),
                       ("Where the first call's input goes (estimated tokens = characters / 4)", an or "not recorded by this version", "json"),
                       (f"The {len(names)} tool definitions sent with every request (how the model learns what it may ask for)", tr.get("tools", []), "json")]
    elif nid == "c3":
        per = ", ".join(f"call {r['n']}: {_secs(r.get('ms'))}" for r in rounds)
        cached = sum((r.get("usage") or {}).get("cached_tokens", 0) for r in rounds)
        unique = (rounds[-1].get("usage") or {}).get("prompt_tokens", 0) if rounds else 0
        resent = f" The last call alone was {unique:,}, so {usage_in - unique:,} ({round(100 * (usage_in - unique) / max(usage_in, 1))}%) of the input was text sent again." if len(rounds) > 1 else ""
        out["what"] = (f"Called {tr.get('model', '?')} {len(rounds)} time(s) over the internet ({per}; {_secs(total_ms)} in total, mode: {tr.get('mode', 'old')}). "
                       f"Tokens: {usage_in:,} in, {usage_out:,} out.{resent} {cached:,} input tokens came from OpenAI's cache (billed at a lower rate). "
                       "OpenAI counted these and sent the numbers back inside the reply; our laptop cannot know them before sending.")
        c = (trace or {}).get("cost")
        if c:
            cents_ = f"${c['dollars']:.4f}" if c["dollars"] < 0.1 else f"${c['dollars']:.2f}"
            out["what"] += (f"\n\n**Cost of this message: {cents_}**, {c['ratio']:.1f}x normal ({c['flag']}). "
                            f"{c['fixed']:,} tokens were the fixed part sent again on every call (rules, tool menu, your question); "
                            f"{c['variable']:,} were tool results, earlier messages and the answer. Compared with: {c['basis']}.")
        err = tr.get("error")
        out["fails"] = (f"It failed this time: {err}. A 401 means the key is missing or wrong in the keyring (service bako-agent); a timeout means the network."
                        if err else "All calls returned. A 401 would mean the key is missing from the keyring (service bako-agent); a timeout means the network.")
        out["tele"] = [("Timing and tokens per call", [dict(call=r["n"], ms=r.get("ms"), finish_reason=(r.get("response") or {}).get("finish_reason"),
                                                          **(r.get("usage") or {}), error=r.get("error")) for r in rounds], "json"),
                       ("Settings sent with the request", {k: r1.get("request", {}).get(k) for k in ("model", "tool_choice", "parallel_tool_calls")}, "json")]
    elif nid == "m1":
        msgs = r1.get("request", {}).get("messages", [])
        roles = {}
        for mm in msgs:
            roles[mm["role"]] = roles.get(mm["role"], 0) + 1
        pt = (rounds[0].get("usage") or {}).get("prompt_tokens", 0) if rounds else 0
        out["what"] = (f"The model read {len(msgs)} messages ({', '.join(f'{v} {k}' for k, v in roles.items())}), "
                       f"which the provider counted as {pt:,} input tokens in call 1. It sees only this text: no files, no GitHub, no AWS.")
        out["fails"] = ("Nothing here for you to fix. If the answer was weak, look at the tool results below: "
                        "the model can only use what the tools gave it.")
        out["tele"] = [("Call 1: the messages the model read (role and size)",
                        [dict(role=mm["role"], chars=len(mm.get("content") or "") if mm["role"] != "system" else mm.get("content_total_chars"),
                              starts=(mm.get("content") or "")[:90]) for mm in msgs], "json")]
    elif nid == "m2":
        tool_rounds = [r for r in rounds if (r.get("response") or {}).get("tool_calls")]
        dups = sum(1 for c in calls if c.get("duplicate"))
        if not calls:
            out["what"] = "The model decided it did not need any tool and answered from the conversation alone (finish reason: stop)."
        else:
            steps = "; ".join(f"{c['n']}) {c['name']}({_args_short(c['arguments'])})" for c in calls)
            out["what"] = f"The model asked for {len(calls)} tool call(s) of the {tr.get('max_tool_calls', 6)} allowed: {steps}. Our code ran each one and sent the result back."
        stop = tr.get("stopped_by")
        if stop == "token_budget":
            out["fails"] = f"This message hit the token budget ({tr.get('token_budget'):,}). Code stopped the tool use and forced an answer."
        elif dups:
            out["fails"] = f"{dups} repeated call(s) were refused by code this time and the model was told to use the earlier result."
        elif len(calls) >= tr.get("max_tool_calls", 6):
            out["fails"] = "The budget was used up this time, so Bako was forced to answer with what it had."
        else:
            out["fails"] = (f"Nothing went wrong: {len(calls)} of {tr.get('max_tool_calls', 6)} calls used. "
                            "If the model had reached 6, or repeated a call, our code would have cut it off.")
        out["tele"] = [(f"Call {r['n']}: the model's reply asking for a tool", r.get("response"), "json") for r in tool_rounds] or \
                      [("No tool was requested: the model's whole reply (this is the answer you saw)", rounds[-1].get("response") if rounds else None, "json")]
    elif nid == "m3":
        last = rounds[-1] if rounds else {}
        rep = tr.get("reply", "")
        out["what"] = (f"Wrote the {len(rep):,}-character reply you saw, as the model's call {last.get('n', '?')} "
                       f"(finish reason: {(last.get('response') or {}).get('finish_reason')}). Whole message: {usage_in + usage_out:,} tokens "
                       f"({usage_in:,} read, {usage_out:,} written).")
        out["fails"] = "If the reply states a fact that no tool result above shows, do not trust it. Ask Bako to check with a tool."
        out["tele"] = [("The model's final reply (raw response)", last.get("response"), "json")]
    elif nid in TOOL_BOX:
        mine = [c for c in calls if c["name"] in TOOL_BOX[nid]]
        if not mine:
            out["what"] = "Not used for this message. The model did not need it. For reference: " + node["what"]
            out["fails"] = node["ifFails"]
        else:
            lines = [f"{c['name']}({_args_short(c['arguments'])}): {'worked' if c['ok'] else 'FAILED'} in {c['ms']:,} ms, "
                     f"{c['result_chars']:,} characters returned" + (" (repeat, refused by code)" if c.get("duplicate") else "") for c in mine]
            out["what"] = "Our code ran: " + "; ".join(lines) + ". This is real code on your computer; the model only asked for it."
            bad = [c for c in mine if not c["ok"]]
            out["fails"] = ("It failed this time: " + bad[0]["result"][:220] + "\n\nCommon causes: " + node["ifFails"]) if bad else node["ifFails"]
            for c in mine:
                out["tele"].append((f"Call {c['n']}: what the model asked for", {"tool": c["name"], "arguments": json.loads(c["arguments"]) if c["arguments"].startswith("{") and "more characters" not in c["arguments"] else c["arguments"]}, "json"))
                out["tele"].append((f"Call {c['n']}: what our code sent back to the model ({c['result_chars']:,} characters)", c["result"], None))
    return out

## ---------------------------------------------------------------
## 2. STYLE (one CSS block, built from the theme; one rule per box colour)
## ---------------------------------------------------------------
def node_css(key, status, selected, t):
    look = {"done": (t["okBg"], f"2px solid {t['okLine']}"), "running": (t["soft"], f"2px solid {t['ink']}"),
            "failed": (t["badBg"], f"2px solid {t['badLine']}"), "waiting": (t["card"], f"2px dashed {t['dashA']}"),
            "skipped": (t["inset"], f"2px dashed {t['dashB']}"), "unused": (t["inset"], f"2px dashed {t['dashB']}")}[status]
    fg = {"done": t["okFg"], "failed": t["badFg"]}.get(status, t["muted"])
    ring = f"box-shadow:0 0 0 3px {t['ink']};" if selected else ""
    return (f".st-key-{key} button{{background:{look[0]} !important;border:{look[1]} !important;{ring}}}"
            f".st-key-{key} button p{{color:{t['ink']} !important;}}"
            f".st-key-{key} button p:first-child{{color:{fg} !important;font-weight:600;font-size:12px;}}")

BASE_CSS = """
[class*="st-key-fn_"] button{width:100% !important;min-height:96px !important;height:100% !important;border-radius:16px !important;
  justify-content:flex-start !important;align-items:flex-start !important;text-align:left !important;padding:10px 12px !important;
  white-space:normal !important;}
[class*="st-key-fn_"] button > div,[class*="st-key-fn_"] button [data-testid="stMarkdownContainer"]{
  display:block !important;width:100%;text-align:left !important;}
[class*="st-key-fn_"] button p{display:block !important;white-space:normal !important;overflow:visible !important;
  text-overflow:clip !important;margin:0 0 3px 0 !important;line-height:1.25;text-align:left !important;font-size:14px;}
[class*="st-key-flowview_"] button,.st-key-flowdetail button{border-radius:999px !important;min-height:40px !important;padding:0 10px !important;font-size:14px !important;white-space:normal !important;}
.fl-arrow{display:flex;align-items:center;justify-content:center;height:96px;font-size:20px;}
.fl-lane{font-size:13px;font-weight:600;margin:6px 0 4px 2px;}
.fl-then{display:flex;justify-content:center;gap:8px;font-size:12px;margin:2px 0 0 0;}
.fl-pill{font-size:12px;font-weight:600;padding:3px 10px;border-radius:999px;margin-left:10px;vertical-align:middle;}
"""

def theme_css(t):
    return (BASE_CSS + f".fl-arrow,.fl-then,.fl-lane{{color:{t['muted']};}}"
            f".st-key-flowdetail button{{background:transparent !important;border:2px solid {t['ink']} !important;}}"
            f".st-key-flowdetail button p{{color:{t['ink']} !important;white-space:normal !important;overflow:visible !important;text-overflow:clip !important;}}"
            f".st-key-flowdetail h3,.st-key-flowdetail p,.st-key-flowdetail li{{color:{t['ink']};}}"
            f".st-key-flowdetail [data-testid=stCaptionContainer]{{color:{t['muted']};}}"
            f".st-key-flowdetail{{background:{t['card']};border-radius:22px;padding:18px 22px;border:2px solid {t['border']};}}")

## ---------------------------------------------------------------
## 3. DRAW
## ---------------------------------------------------------------
def pick_url(node, stages):
    ## A real link for this box, if the facts contain one.
    kind = node.get("url")
    pool = stages.get("trig", {}).get("detail", "") if kind == "run" else stages.get("bot", {}).get("detail", "") if kind == "pr" else ""
    m = re.search(r"https://\S+", pool)
    return m.group(0) if m else None

def evidence_for(node, s, repo, view):
    text = (s or {}).get("detail", "").strip()
    if not s:
        return "Nothing yet. This step has not run."
    extra = ""
    if s["status"] == "failed":
        prefix = {"apply": "apply", "boot": "bootstrap", "s4": "destroy"}.get(node["id"])
        log = newest_log(repo, prefix) if prefix else None
        if log:
            extra = f"\n--- end of {os.path.basename(log)} ---\n" + tail(log, 900)
    return (text or "(no detail recorded)") + extra

RERUNNABLE = {"boot", "trig", "test", "build", "push", "bot", "merge", "argo", "ready"}   # steps after terraform apply

def render_flow(repo, running=False, on_ask=None, theme="warm", chat_trace=None, on_rerun=None):
    t = THEMES.get(theme, THEMES["warm"])
    ss = st.session_state
    ss.setdefault("flow_view", "start")
    ss.setdefault("flow_sel", {})
    view = ss.flow_view
    st.markdown(f"<style>{theme_css(t)}</style>", unsafe_allow_html=True)

    ## view switch
    with st.container(key="flowbox"):
        vcss = []
        c1, c2, c3 = st.columns(3)
        for col, vid, label in ((c1, "start", "Start Lab flow"), (c2, "stop", "Stop Lab flow"), (c3, "chat", "Bako and OpenAI")):
            if col.button(label, key=f"flowview_{vid}", use_container_width=True, type="primary" if view == vid else "secondary"):
                ss.flow_view = vid
                st.rerun(scope="fragment")
            vcss.append(f".st-key-flowview_{vid} button{{background:{t['deep'] if view == vid else 'transparent'} !important;"
                        f"border:2px solid {t['ink']} !important;}}.st-key-flowview_{vid} button p{{color:{t['light'] if view == vid else t['ink']} !important;}}")

        st.markdown("<style>" + "".join(vcss) + "</style>", unsafe_allow_html=True)

        ## facts
        stages, summary, run_file = {}, "", None
        if view in ("start", "stop"):
            run_file, events = newest_run(repo, view)
            stages = derive_start(events, running) if view == "start" else derive_stop(events, running)
            if not events:
                summary = "No " + view.upper() + " run recorded yet. After you run it, every box here is coloured from what happened."
            else:
                total = sum(len(l["nodes"]) for l in FLOWS[view]["lanes"])
                done = sum(1 for s in stages.values() if s["status"] in ("done", "skipped"))
                bad = [s for s in stages if stages[s]["status"] == "failed"]
                first = next((e.get("time", "") for e in events if e.get("event") == "run_start"), "")
                label = {n["id"]: n["label"] for l in FLOWS[view]["lanes"] for n in l["nodes"]}
                summary = (f"{view.upper()} at {first[:5]} · {done} of {total} steps done"
                           + (f" · stopped at \"{label.get(bad[0], bad[0])}\"" if bad else (" · running now" if running else "")) + ". Click any box.")
            pre = stages.get("pre")
            if pre and pre["status"] == "failed":
                st.error("START could not begin, and nothing was changed: " + pre["detail"])
        else:
            stages, summary = derive_chat(chat_trace)
        st.caption(summary)

        ## the diagram
        sel_id = ss.flow_sel.get(view)
        all_nodes = [n for l in FLOWS[view]["lanes"] for n in l["nodes"]]
        bad_first = next((n["id"] for n in all_nodes if stages.get(n["id"], {}).get("status") == "failed"), None)
        if sel_id not in {n["id"] for n in all_nodes}:
            sel_id = bad_first or all_nodes[0]["id"]
        css = []
        for li, lane in enumerate(FLOWS[view]["lanes"]):
            st.markdown(f"<div class='fl-lane'>{lane['label']}</div>", unsafe_allow_html=True)
            n = len(lane["nodes"])
            arrows = not lane.get("noarrows")
            spec = []
            for i in range(n):
                spec.append(1)
                if arrows and i < n - 1:
                    spec.append(0.18)
            cols = st.columns(spec)
            ci = 0
            for i, node in enumerate(lane["nodes"]):
                s = stages.get(node["id"])
                status = s["status"] if s else ("unused" if view == "chat" else "waiting")
                key = f"fn_{view}_{node['id']}"
                css.append(node_css(key, status, node["id"] == sel_id, t))
                label = f"{STATUS_TEXT[status]}\n\n**{node['label']}**\n\n{node['sub']}"
                if cols[ci].button(label, key=key, use_container_width=True):
                    ss.flow_sel[view] = node["id"]
                    sel_id = node["id"]
                    st.rerun(scope="fragment")
                ci += 1
                if arrows and i < n - 1:
                    cols[ci].markdown("<div class='fl-arrow'>→</div>", unsafe_allow_html=True)
                    ci += 1
            if lane.get("then"):
                st.markdown(f"<div class='fl-then'>↓ {lane['then']}</div>", unsafe_allow_html=True)
        st.markdown("<style>" + "".join(css) + "</style>", unsafe_allow_html=True)

    ## the detail panel
    node = next(n for n in all_nodes if n["id"] == sel_id)
    s = stages.get(node["id"])
    status = s["status"] if s else ("unused" if view == "chat" else "waiting")
    pill_bg = {"done": t["okBg"], "failed": t["badBg"], "running": t["soft"]}.get(status, t["inset"])
    pill_fg = {"done": t["okFg"], "failed": t["badFg"]}.get(status, t["ink2"])
    with st.container(key="flowdetail"):
        st.markdown(f"<h3 style='margin:0;color:{t['ink']};font-weight:500'>{node['label']}"
                    f"<span class='fl-pill' style='background:{pill_bg};color:{pill_fg}'>{STATUS_TEXT[status]}</span></h3>",
                    unsafe_allow_html=True)
        cd = chat_detail(node, chat_trace) if view == "chat" else None
        a, b = st.columns(2)
        a.markdown(("**What happened this time**" if cd else "**What this step does**") + "\n\n" + (cd["what"] if cd else node["what"]))
        b.markdown(("**Likely cause**" if status == "failed" else ("**What went wrong, or could**" if cd else "**If this step fails**")) + "\n\n" + (cd["fails"] if cd else node["ifFails"]))
        st.markdown("**Evidence**")
        st.code(evidence_for(node, s, repo, view), language=None)
        if cd and cd["tele"]:
            st.markdown("**Telemetry** · the real request and response, secrets hidden")
            for i, (title, body, lang) in enumerate(cd["tele"]):
                with st.expander(title, expanded=False):
                    st.code(body if isinstance(body, str) else _j(body), language=lang)
        elif view == "chat" and chat_trace and not chat_trace.get("trace"):
            st.caption("Telemetry needs the newer bako_chat.py. Copy it in and restart Bako.")
        can_rerun = bool(on_rerun) and view == "start" and node["id"] in RERUNNABLE and status == "failed" and not running
        bc0, bc1, bc2 = st.columns([1.5, 2.0, 1.4]) if can_rerun else (None, *st.columns([2.0, 1.4])[:2])
        if can_rerun and bc0.button("Re-run from here", key=f"flowrerun_{view}_{node['id']}", use_container_width=True):
            on_rerun(node["id"])
            st.rerun()                               # full page: the Lab tab must see the new run
        if on_ask and bc1.button("Ask Bako to troubleshoot this", key=f"flowask_{view}_{node['id']}", use_container_width=True):
            ev = evidence_for(node, s, repo, view)[:700]
            fence = "```"
            while fence in ev:
                fence += "`"                         # the evidence goes in a code block, so lines like ---- cannot turn into huge headings
            on_ask(f"Troubleshoot the \"{node['label']}\" step of the {FLOWS[view]['title']}. Status: "
                   f"{STATUS_TEXT[status][2:]}. Evidence:\n\n{fence}\n{ev}\n{fence}")
            st.rerun()                               # full page: the chat must pick the question up
        url = pick_url(node, stages)
        if url and bc2.button("Open on GitHub", key=f"flowurl_{view}_{node['id']}", use_container_width=True):
            webbrowser.open(url)
        st.caption("This panel only shows information. If Bako suggests a fix, it arrives as a proposal in the chat and still needs your typed word.")
    if view == "chat" and chat_trace and chat_trace.get("trace"):
        tr = {k: v for k, v in chat_trace["trace"].items() if k != "tools"}
        with st.expander("Everything for this message (full record, JSON)", expanded=False):
            st.code(_j(tr), language="json")
            st.caption("Every message is also saved, one line each, in agent/env/reports/chat-traces.jsonl. Passwords and keys are hidden in this record.")


def show(repo, running=False, on_ask=None, theme="warm", chat_trace=None, on_rerun=None):
    ## Call this inside the Flow tab. It refreshes itself every 3 seconds while a run is active.
    st.fragment(render_flow, run_every=3 if running else None)(repo, running, on_ask, theme, chat_trace, on_rerun)