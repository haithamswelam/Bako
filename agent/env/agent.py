## ---------------------------------------------------------------
## 1. IMPORTS AND SETTINGS
## Libraries, run limits, the safety flags, and where bash/terraform live.
## ---------------------------------------------------------------
import json, os, shutil, subprocess, sys, time
from openai import OpenAI
import keyring
MODEL = os.environ.get("AGENT_MODEL", "gpt-5.4-nano")
API_KEY = os.environ.get("OPENAI_API_KEY") or keyring.get_password("bako-agent", "OPENAI_API_KEY")
if not API_KEY:
       raise SystemExit("No OpenAI key found. Run the one-time keyring command.")
client = OpenAI(api_key=API_KEY)
MAX_STEPS = 15                        # max model calls in one run (charter limit)
MAX_SECONDS = 60 * 60                 # max run time: 60 minutes

## Safety flags, set ONLY by our code (never by the model's words):
##   account_ok   = True after the account check passes
##   plan_ok      = True after a clean plan (no deletes) in this run
##   plan_summary = the plan summary shown to the human before apply
STATE = {"account_ok": False, "plan_ok": False, "plan_summary": "", "applied": False, "stop_now": ""}

## MODE decides what the agent may do: "dry" = plan only, "start" = plan + apply (with approval).
MODE = sys.argv[1] if len(sys.argv) > 1 else "dry"
if MODE not in ("dry", "start"):
    raise SystemExit("usage: python agent/env/agent.py dry|start")

## Find bash once and print it, so we never launch the wrong bash (WSL).
BASH = os.environ.get("AGENT_BASH") or shutil.which("bash")
if not BASH:
    raise SystemExit("bash not found")
print(f"using bash: {BASH}")

##old --- client = OpenAI()  # reads OPENAI_API_KEY from the environment

## ---------------------------------------------------------------
## 2. TRACE (the flight recorder)
## One JSON line per event in agent/env/reports/trace-<time>.jsonl.
## This is how we see afterwards what happened, step by step, and what it cost.
## ---------------------------------------------------------------
TRACE_FILE = f"agent/env/reports/trace-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
os.makedirs("agent/env/reports", exist_ok=True)

def trace(**event):
    event["time"] = time.strftime("%H:%M:%S")
    with open(TRACE_FILE, "a") as f:
        f.write(json.dumps(event) + "\n")


## ---------------------------------------------------------------
## 3. TOOL 1: run_checks  (our code, read-only)
## Runs agent/env/checks.sh with one of three allowed words.
## A passing "account" check sets STATE["account_ok"] = True,
## which is what unlocks terraform. The flag comes from the exit code, not the model.
## ---------------------------------------------------------------
def tool_run_checks(kind):
    if kind not in ("account", "ready", "nothing-running"):
        return "ERROR: unknown check"
    proc = subprocess.run(
        [BASH, "agent/env/checks.sh", kind], capture_output=True, text=True
    )
    if kind == "account" and proc.returncode == 0:
        STATE["account_ok"] = True
    return proc.stdout + proc.stderr + f"\nexit code: {proc.returncode}"

## Find terraform once and stop immediately if it is missing.
TERRAFORM = shutil.which("terraform")
if not TERRAFORM:
    raise SystemExit("terraform not found")
TF_DIR = "infra-Bako-eks"          # folder where terraform runs
PLAN_FILE = os.path.abspath("agent/env/reports/last.tfplan")   # saved plan, reused by apply

## ---------------------------------------------------------------
## 4. TOOL 2: terraform_plan  (our code, changes NOTHING)
## a) refuses if the account was not verified (the code gate)
## b) runs terraform plan and saves it to PLAN_FILE
## c) reads the saved plan as JSON and counts create / update / delete
## d) sets STATE["plan_ok"] = True only if the plan deletes nothing
## e) returns ONE short summary, not terraform's long output (saves tokens)
## ---------------------------------------------------------------
def tool_terraform_plan():
    STATE["plan_ok"] = False        # any new plan starts as "not approved for apply"
    if not STATE["account_ok"]:
        return "REFUSED: the account check has not passed in this run. Run run_checks(account) first."
    plan = subprocess.run(
        [TERRAFORM, f"-chdir={TF_DIR}", "plan", "-input=false", "-no-color", f"-out={PLAN_FILE}"],
        capture_output=True, text=True,
    )
    if plan.returncode != 0:
        return "terraform plan FAILED:\n" + (plan.stdout + plan.stderr)[-1500:]
    show = subprocess.run(
        [TERRAFORM, f"-chdir={TF_DIR}", "show", "-json", PLAN_FILE],
        capture_output=True, text=True,
    )
    counts = {"create": 0, "update": 0, "delete": 0}
    types = {}
    for change in json.loads(show.stdout).get("resource_changes", []):
        actions = change["change"]["actions"]
        if actions == ["no-op"]:
            continue
        for a in counts:
            if a in actions:
                counts[a] += 1
        types[change["type"]] = types.get(change["type"], 0) + 1
    summary = (f"plan OK. to create: {counts['create']}, to update: {counts['update']}, "
               f"to delete: {counts['delete']}. Resource types: {types}")
    if counts["delete"] > 0:
        summary += "\nWARNING: this plan deletes or replaces resources."
    STATE["plan_ok"] = counts["delete"] == 0   # clean plan = no deletes
    STATE["plan_summary"] = summary
    return summary

## ---------------------------------------------------------------
## 5. TOOL 3: terraform_apply  (our code, CHANGES AWS, needs human approval)
## a) refuses unless the account check passed AND a clean plan exists in this run
## b) shows the plan summary and waits for the human to type: approved
## c) applies the EXACT saved plan file (nothing new can sneak in)
## d) writes terraform's output to a log file, so we can watch it live
## ---------------------------------------------------------------
def tool_terraform_apply():
    if not STATE["account_ok"]:
        return "REFUSED: the account check has not passed in this run."
    if not STATE["plan_ok"]:
        return "REFUSED: no clean plan in this run (missing, failed, or it deletes resources)."
    print("\n=== APPROVAL NEEDED ===")
    print("Plan to apply: " + STATE["plan_summary"])
    answer = input('Type exactly "approved" to apply (anything else = no): ').strip()
    trace(event="approval", tool="terraform_apply", approved=(answer == "approved"))
    if answer != "approved":
        STATE["stop_now"] = "human did not approve"
        return "REFUSED: the human did not approve. Do nothing more."
    log_path = f"agent/env/reports/apply-{time.strftime('%Y%m%d-%H%M%S')}.log"
    print(f"Apply started. It takes about 15-20 minutes. Watch it with: tail -f {log_path}")
    try:
        with open(log_path, "w") as log:
            proc = subprocess.run(
                [TERRAFORM, f"-chdir={TF_DIR}", "apply", "-input=false", "-no-color", PLAN_FILE],
                stdout=log, stderr=subprocess.STDOUT, text=True, timeout=45 * 60,
            )
    except subprocess.TimeoutExpired:
        STATE["stop_now"] = "apply timed out"
        return f"apply TIMED OUT after 45 minutes. Check state manually. Log: {log_path}"
    tail = open(log_path).read()[-1500:]
    if proc.returncode != 0:
        STATE["stop_now"] = "apply failed"
        return f"apply FAILED (exit {proc.returncode}). Log: {log_path}\n{tail}"
    done = [l for l in tail.splitlines() if l.startswith("Apply complete!")]
    STATE["applied"] = True
    return "apply OK. " + (done[-1] if done else "") + f" Log: {log_path}"

## ---------------------------------------------------------------
## 6. TOOL MENU (what the model is told it may ask for)
## This is only a description sent to the model. The model never runs anything:
## it asks for a tool by name, and OUR code decides whether and how to run it.
## ---------------------------------------------------------------

## Menu item 1: run_checks, with "kind" limited to three allowed words.
TOOLS = [{
    "type": "function",
    "function": {
        "name": "run_checks",
        "description": "Run a read-only check script.",
        "parameters": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["account", "ready", "nothing-running"]}
            },
            "required": ["kind"],
        },
    },
}]

## Lookup table: tool name the model asks for -> our real function.
TOOL_FUNCS = {"run_checks": tool_run_checks}

## Menu item 2: terraform_plan, no inputs. The model cannot pass any arguments to terraform.
TOOLS.append({
    "type": "function",
    "function": {
        "name": "terraform_plan",
        "description": "Run a read-only terraform plan (changes nothing) and return a short summary.",
        "parameters": {"type": "object", "properties": {}},
    },
})
TOOL_FUNCS["terraform_plan"] = tool_terraform_plan

## Menu item 3: terraform_apply. Only offered in "start" mode.
## In "dry" mode the model does not even know this tool exists.
if MODE == "start":
    TOOLS.append({
        "type": "function",
        "function": {
            "name": "terraform_apply",
            "description": "Apply the saved plan. Asks the human for approval first.",
            "parameters": {"type": "object", "properties": {}},
        },
    })
    TOOL_FUNCS["terraform_apply"] = tool_terraform_apply

## ---------------------------------------------------------------
## 7. THE PROMPT
## System message = the charter (the rules). User message = today's task,
## chosen by MODE. Both are sent to the model on every call, so keep them short.
## ---------------------------------------------------------------
charter = open("agent/env/CHARTER.md").read()
TASKS = {
    "dry":   "Task: DRY RUN of START. The AWS account check already passed. Run terraform_plan and report what a START would create. Do nothing else.",
    "start": "Task: START, part 1. The AWS account check already passed. Run terraform_plan. If it is clean, run terraform_apply. Then report. Do nothing else.",
}
messages = [
    {"role": "system", "content": "You are the Environment Agent. Follow this charter exactly.\n\n" + charter},
    {"role": "user", "content": TASKS[MODE]},
]
trace(event="run_start", model=MODEL, mode=MODE, bash=BASH, task=messages[1]["content"])

## ---------------------------------------------------------------
## 8. STEP 0 (before the loop, not counted in the trace's "step" numbers)
## The account check runs in plain code. If it fails we stop here:
## 0 tokens spent, exact message, exit code 1. The model is only called if it passes.
## ---------------------------------------------------------------
check = tool_run_checks("account")
trace(event="tool_result", tool="run_checks", args={"kind": "account"}, result=check[:2000])
print(check)
if not STATE["account_ok"]:
    print("STOP: account check failed. The model was not called.")
    trace(event="stop", reason="account check failed (no model call)")
    raise SystemExit(1)

## ---------------------------------------------------------------
## 9. THE AGENT LOOP
## "step" = one pass of this loop = ONE CALL TO THE MODEL (plus any tool it asked for).
## The trace lines "step": 1, 2, 3 ... come from here, not from the numbered sections.
## Repeat up to MAX_STEPS times:
##   a) stop if the time limit is reached
##   b) send the whole conversation to the model (tools allowed, one tool at a time)
##   c) record the reply and its token cost in the trace
##   d) no tool requested  -> the model gave its final answer: print it and stop
##   e) tool requested     -> run it in OUR code, add the result to the
##                            conversation, and loop again
## ---------------------------------------------------------------
start = time.time()
for step in range(1, MAX_STEPS + 1):
    ## a) Time limit.
    if time.time() - start > MAX_SECONDS:
        print("STOP: time limit reached")
        trace(event="stop", reason="time limit")
        break
    ## b) Ask the model what to do next. parallel_tool_calls=False = one tool per reply.
    reply = client.chat.completions.create(model=MODEL, messages=messages, tools=TOOLS, parallel_tool_calls=False)
    msg = reply.choices[0].message
    ## c) TRACE LINE "model_reply": tokens in/out and which tool (if any) the model asked for.
    trace(step=step, event="model_reply",
          tokens_in=reply.usage.prompt_tokens, tokens_out=reply.usage.completion_tokens,
          tool_calls=[c.function.name for c in (msg.tool_calls or [])])
    print(f"tokens: {reply.usage.prompt_tokens} in / {reply.usage.completion_tokens} out")
    messages.append(msg)
    ## d) No tool requested = final answer.
    if not msg.tool_calls:
        trace(event="final", content=msg.content)
        print("AGENT:", msg.content)
        trace(event="stop", reason="done")
        break
    ## e) Run each requested tool in our code and hand the result back to the model.
    for call in msg.tool_calls:
        args = json.loads(call.function.arguments)
        print(f"step {step}: tool {call.function.name} {args}")
        result = TOOL_FUNCS[call.function.name](**args)
        ## TRACE LINE "tool_result": what OUR code returned for the tool the model asked for.
        ## Always record the result first: every tool_call_id needs a tool message.
        trace(step=step, event="tool_result", tool=call.function.name, args=args, result=result[:2000])
        print(result)
        messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
    ## A tool asked the run to end (declined approval, failed apply): stop now. No model call.
    if STATE["stop_now"]:
        print(f"STOP: {STATE['stop_now']}. The model was not called again.")
        trace(event="stop", reason=STATE["stop_now"] + " (no further model call)")
        break
else:
    ## Runs only if the loop used all MAX_STEPS without hitting a break.
    print("STOP: step limit reached")
    trace(event="stop", reason="step limit")

## ---------------------------------------------------------------
## 10. THE VERDICT (written by CODE, not by the model)
## The model's report is prose. This line is the facts.
## ---------------------------------------------------------------
print("\nRESULT (from code):", "APPLIED" if STATE["applied"] else "NOT APPLIED",
      "| plan clean:", STATE["plan_ok"], "| account ok:", STATE["account_ok"])
trace(event="outcome", applied=STATE["applied"], plan_ok=STATE["plan_ok"])