## ---------------------------------------------------------------
## BAKO CHAT WINDOW (v2) - a thin shell around agent.py and bako_chat.py
## It contains NO agent logic. It starts "python agent.py <mode>" as a
## separate process, shows what it prints, and forwards what YOU type to it.
## The real approval check stays inside agent.py (it compares what you typed).
##
## Run (from the Bako folder, venv active):
##   streamlit run agent/env/ui.py --server.address 127.0.0.1 --browser.gatherUsageStats false
## ---------------------------------------------------------------
import os, queue, shutil, subprocess, sys, threading, time
import streamlit as st
import keyring
from openai import OpenAI
import bako_chat

## ---------------------------------------------------------------
## 1. SETTINGS
## REPO = the Bako folder (agent.py uses paths relative to it).
## LOGO = optional picture shown at the top. Put bako-logo.png next to this file.
## ---------------------------------------------------------------
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
LOGO = os.path.join(os.path.dirname(__file__), "bako-logo.png")
BASH = os.environ.get("AGENT_BASH") or shutil.which("bash")

MODEL = os.environ.get("AGENT_MODEL", "gpt-5.4-nano")

## One OpenAI client for the whole window. The key comes from the Windows
## Credential Manager (same place agent.py reads it). None = chat falls back to keywords.
@st.cache_resource
def get_client():
    try:
        key = os.environ.get("OPENAI_API_KEY") or keyring.get_password("bako-agent", "OPENAI_API_KEY")
    except Exception:
        key = None
    return OpenAI(api_key=key) if key else None

st.set_page_config(page_title="Bako", page_icon="🤖")

## ---------------------------------------------------------------
## 2. MEMORY OF THIS BROWSER SESSION
## Streamlit re-runs this whole file on every click or keystroke, so anything
## that must survive (the chat, the running process) lives in session_state.
## ---------------------------------------------------------------
ss = st.session_state
ss.setdefault("chat", [])        # the conversation: list of (role, text)
ss.setdefault("log", [])         # raw lines printed by the running agent
ss.setdefault("proc", None)      # the running agent process
ss.setdefault("q", None)         # lines from the process arrive in this queue
ss.setdefault("awaiting", None)  # the approval word the agent is waiting for
ss.setdefault("logfile", None)   # terraform log path, once apply/destroy starts
ss.setdefault("hist", [])        # text-only history sent to the model
ss.setdefault("pending", None)   # a proposed commit+push waiting for "push bako"
ss.setdefault("tokens", 0)       # model tokens used in this window

## ---------------------------------------------------------------
## 3. HEADER
## ---------------------------------------------------------------
if os.path.exists(LOGO):
    st.image(LOGO, width=110)
st.title("Bako")
st.caption("Talk to me about the Bako lab: status, errors, the repo, start, stop, push.")

## ---------------------------------------------------------------
## 4. TALKING TO THE AGENT PROCESS
## ---------------------------------------------------------------

## A background thread that copies each line the agent prints into a queue.
## (A thread is needed because reading a pipe blocks until a line arrives.)
def reader(proc, q):
    for line in proc.stdout:
        q.put(line.rstrip("\r\n"))
    q.put(None)          # None = the process has ended

## Start "python -u agent/env/agent.py <mode>" in the Bako folder.
## -u = unbuffered, so lines show up immediately instead of at the end.
def launch(mode):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    proc = subprocess.Popen(
        [sys.executable, "-u", os.path.join("agent", "env", "agent.py"), mode],
        cwd=REPO, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace", bufsize=1,
    )
    ss.proc, ss.q = proc, queue.Queue()
    ss.log, ss.awaiting, ss.logfile = [], None, None
    threading.Thread(target=reader, args=(proc, ss.q), daemon=True).start()

## Move new lines from the queue into the log. Also notice two special lines:
##   "APPROVAL NEEDED"  -> remember which word the agent wants typed
##   "tail -f <path>"   -> remember the terraform log file, so we can show it live
## Returns True once the process has ended.
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

## ---------------------------------------------------------------
## 5. UNDERSTANDING WHAT YOU TYPE (v1: plain keywords, no model, 0 tokens)
## Even if a keyword fires by mistake, nothing is destroyed or applied:
## the agent still waits for the typed approval word.
## ---------------------------------------------------------------
def say(text):
    ss.chat.append(("assistant", text))

def handle_keywords(text):
    t = text.lower()
    words = set(t.replace(",", " ").replace("!", " ").replace("?", " ").split())
    if any(w in t for w in ("stop", "destroy", "shut down", "tear down")):
        say("Starting STOP. I will plan the destroy and show it to you. "
            "Nothing is deleted until you type the approval word.")
        launch("stop")
    elif any(w in t for w in ("start", "bring up")):
        say("Starting START. I will plan first, then ask you to approve the apply. "
            "For now it covers plan and apply only; build, bootstrap and the PR merge are still manual.")
        launch("start")
    elif "status" in t or "ready" in t:
        if not BASH:
            say("I can't find bash on this computer.")
        else:
            out = subprocess.run([BASH, "agent/env/checks.sh", "ready"], cwd=REPO,
                                 capture_output=True, text=True)
            say("```\n" + (out.stdout + out.stderr).strip() + "\n```")
    elif words & {"hi", "hello", "hey"}:
        say("Hi Haitham! I can **start** the lab, **stop** it, or show its **status**. What would you like?")
    else:
        say("I only know three things for now: **start**, **stop** and **status**.")

## v2 router: the model understands the sentence and may use read-only tools.
## It can only PROPOSE actions. Starting, stopping and pushing still wait for your typed word.
def handle(text):
    client = get_client()
    if client is None:
        say("No OpenAI key found, so I use the simple keyword mode. Say: start, stop or status.")
        return handle_keywords(text)
    try:
        with st.spinner("Bako is thinking..."):
            reply, action, used = bako_chat.run_turn(client, MODEL, ss.hist, text, REPO)
    except Exception as e:
        say(f"The model is not reachable ({type(e).__name__}). Keyword mode: say start, stop or status.")
        return handle_keywords(text)
    ss.tokens += used
    say(reply or "(no reply)")
    if action:
        apply_action(action)

## Turn a proposal into the matching flow. Nothing here skips the typed approval.
def apply_action(action):
    if action["type"] == "start":
        say("Opening the START flow. I will plan first, then ask you to approve.")
        launch("start")
    elif action["type"] == "stop":
        say("Opening the STOP flow. I will plan the destroy first, then ask you to approve.")
        launch("stop")
    elif action["type"] == "commit_push":
        ss.pending = action

## ---------------------------------------------------------------
## 6. DRAWING THE SCREEN
## ---------------------------------------------------------------

## The conversation so far.
for role, text in ss.chat:
    with st.chat_message(role):
        st.markdown(text)

## While a run is active: show its output, and the live terraform log if there is one.
finished = False
if ss.proc is not None:
    finished = drain()
    with st.chat_message("assistant"):
        st.code("\n".join(ss.log[-60:]) or "starting...", language=None)
        if ss.logfile:
            path = os.path.join(REPO, ss.logfile)
            if os.path.exists(path):
                with open(path, encoding="utf-8", errors="replace") as f:
                    tail = f.read().splitlines()[-12:]
                st.caption("Live terraform log (last lines)")
                st.code("\n".join(tail), language=None)

## When the run ends: keep its output in the chat, and show the verdict line
## that agent.py prints ("RESULT (from code): ...") in bold.
if finished:
    code = ss.proc.wait()
    ss.chat.append(("assistant", "```\n" + "\n".join(ss.log) + "\n```"))
    results = [l for l in ss.log if l.startswith("RESULT (from code)")]
    say("**" + results[-1] + "**" if results else f"The run ended (exit code {code}).")
    ss.proc, ss.log, ss.awaiting, ss.logfile = None, [], None, None
    st.rerun()

## A proposed commit + push waits here until you type "push bako".
if ss.pending:
    a = ss.pending
    st.warning(f'Bako proposes to commit to the NEW branch "{a["branch"]}" and push it.\n\n'
               f'Message: {a["message"]}\n\nFiles: ' + ", ".join(a["files"]) +
               '\n\nType exactly "push bako" to do it. Anything else cancels.')

## If the agent is waiting for approval, say so clearly.
if ss.awaiting and ss.proc is not None:
    st.warning(f'The agent is waiting for your approval. Type exactly "{ss.awaiting}" '
               f'in the box below. Anything else means no.')

## ---------------------------------------------------------------
## 7. THE CHAT BOX
## While the agent is waiting for approval, whatever you type is sent to it
## EXACTLY as typed. agent.py decides if it is the approval word.
## ---------------------------------------------------------------
prompt = st.chat_input("Talk to Bako...")
if prompt:
    ss.chat.append(("user", prompt))
    if ss.pending:
        action, ss.pending = ss.pending, None
        if prompt.strip() == "push bako":
            say("```\n" + bako_chat.do_commit_push(REPO, action) + "\n```")
        else:
            say("Cancelled. Nothing was committed or pushed.")
    elif ss.proc is not None and ss.awaiting:
        try:
            ss.proc.stdin.write(prompt.strip() + "\n")
            ss.proc.stdin.flush()
            say("Sent to the agent. It decides whether that is the approval.")
        except OSError:
            say("The agent is no longer listening.")
        ss.awaiting = None
    elif ss.proc is not None:
        say("I am in the middle of a run. Please wait until it finishes.")
    else:
        handle(prompt)
    st.rerun()

st.caption(f"Model tokens used in this window: {ss.tokens}")

## While a run is active, look again every second.
if ss.proc is not None:
    time.sleep(1)
    st.rerun()