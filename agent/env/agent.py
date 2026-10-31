## ---------------------------------------------------------------
## 1. IMPORTS AND SETTINGS
## Libraries, run limits, the safety flags, and where bash/terraform live.
## ---------------------------------------------------------------
import json, os, shutil, subprocess, sys, time
from openai import OpenAI
import keyring
import redact                         # hides secrets before they reach the trace or the model
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
STATE = {"account_ok": False, "plan_ok": False, "plan_summary": "", "applied": False, "stop_now": "",
         "destroy_plan_ok": False, "destroy_summary": "", "destroyed": False, "nothing_running": False,
         "ready": False, "stopped_at": "", "plan_counts": {}}

MODE = sys.argv[1] if len(sys.argv) > 1 else "dry"
if MODE not in ("dry", "start", "stop"):
    raise SystemExit("usage: python agent/env/agent.py dry|start|stop")

## Find bash once and print it, so we never launch the wrong bash (WSL).
BASH = os.environ.get("AGENT_BASH") or shutil.which("bash")
if not BASH:
    raise SystemExit("bash not found")
print(f"using bash: {BASH}")
import shellenv                      # lets bash find grep, awk, base64 (Git's usr/bin) when started from Python
UNIX_ENV = shellenv.unix_env(BASH, {k: v for k, v in os.environ.items() if k != "KUBECONFIG"})

## "start --from <step>" re-runs START from one step after terraform apply (the lab must already exist).
ORDER = ["boot", "trig", "bot", "merge", "argo", "ready"]
ALIAS = {"test": "trig", "build": "trig", "push": "trig"}
FROM = ""
if "--from" in sys.argv:
    i = sys.argv.index("--from")
    FROM = ALIAS.get(sys.argv[i + 1], sys.argv[i + 1]) if i + 1 < len(sys.argv) else ""
    if MODE != "start" or FROM not in ORDER:
        raise SystemExit("usage: python agent/env/agent.py start --from " + "|".join(ORDER))


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
## 10. THE VERDICT (written by CODE, not by the model)
## The model's report is prose. This line is the facts.
## ---------------------------------------------------------------
def print_verdict():
    if MODE == "dry":
        print("\nRESULT (from code):", "APPLIED" if STATE["applied"] else "NOT APPLIED",
              "| plan clean:", STATE["plan_ok"], "| account ok:", STATE["account_ok"])
        trace(event="outcome", applied=STATE["applied"], plan_ok=STATE["plan_ok"])
    if MODE == "start":
        where = STATE["stopped_at"] or "unknown"
        if STATE["ready"]:
            word = "READY"
        elif STATE["applied"]:
            word = "APPLIED, NOT READY | stopped at: " + where
        else:
            word = "NOT APPLIED | stopped at: " + where
        print("\nRESULT (from code):", word, "| account ok:", STATE["account_ok"])
        trace(event="outcome", applied=STATE["applied"], ready=STATE["ready"], stopped_at=STATE["stopped_at"])
    if MODE == "stop":
        print("\nRESULT (from code):", "NOTHING RUNNING" if STATE["nothing_running"] else "NOT CLEAN or NOT DESTROYED",
              "| destroyed:", STATE["destroyed"])
        trace(event="outcome", destroyed=STATE["destroyed"], nothing_running=STATE["nothing_running"])


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
        [BASH, "agent/env/checks.sh", kind], capture_output=True, text=True, env=UNIX_ENV
    )
    if kind == "account" and proc.returncode == 0:
        STATE["account_ok"] = True
    if kind == "nothing-running":
        STATE["nothing_running"] = (proc.returncode == 0)
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
    STATE["plan_counts"] = dict(counts)
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

DESTROY_PLAN_FILE = os.path.abspath("agent/env/reports/last-destroy.tfplan")

## ---------------------------------------------------------------
## TOOL 4: terraform_plan_destroy  (our code, changes NOTHING)
## Plans a FULL destroy, saves it, and summarizes it. The plan counts as
## clean only if it deletes something and creates/updates nothing.
## ---------------------------------------------------------------
def tool_terraform_plan_destroy():
    STATE["destroy_plan_ok"] = False
    if not STATE["account_ok"]:
        return "REFUSED: the account check has not passed in this run."
    plan = subprocess.run(
        [TERRAFORM, f"-chdir={TF_DIR}", "plan", "-destroy", "-input=false", "-no-color", f"-out={DESTROY_PLAN_FILE}"],
        capture_output=True, text=True,
    )
    if plan.returncode != 0:
        return "terraform plan -destroy FAILED:\n" + (plan.stdout + plan.stderr)[-1500:]
    show = subprocess.run(
        [TERRAFORM, f"-chdir={TF_DIR}", "show", "-json", DESTROY_PLAN_FILE],
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
        if "delete" in actions:
            types[change["type"]] = types.get(change["type"], 0) + 1
    summary = (f"destroy plan OK. to delete: {counts['delete']}, to create: {counts['create']}, "
               f"to update: {counts['update']}. Resource types: {types}")
    STATE["destroy_plan_ok"] = counts["delete"] > 0 and counts["create"] == 0 and counts["update"] == 0
    STATE["destroy_summary"] = summary
    return summary

## ---------------------------------------------------------------
## release_load_balancer  (our code, runs inside the destroy tool, AFTER you typed "destroy bako")
## The ALB is not in terraform: the AWS Load Balancer Controller builds it from K8s/ingress.yaml. If the cluster is
## destroyed first, nobody is left to delete it: it keeps billing every hour and blocks the VPC from being deleted.
## agent/env/pre-destroy-alb.sh removes the Ingress (so the controller removes the ALB), then waits until AWS shows
## no load balancer or controller security group for this cluster. Exit 0 is the ONLY result that lets the destroy go on.
## It is fail-closed: a missing script, a timeout or an AWS error all mean "do not destroy".
## ---------------------------------------------------------------
RELEASE_SCRIPT = "agent/env/pre-destroy-alb.sh"

def release_load_balancer():
    if not os.path.exists(RELEASE_SCRIPT):
        return False, f"{RELEASE_SCRIPT} is missing. Copy it next to agent.py. The destroy is refused without it."
    code, out = run_cmd([BASH, RELEASE_SCRIPT], timeout=12 * 60, env=UNIX_ENV)
    out = redact.redact(out)
    return code == 0, f"pre-destroy-alb.sh exit {code}\n{out[-1500:]}"

## ---------------------------------------------------------------
## TOOL 5: terraform_destroy  (our code, DELETES everything, needs typed approval)
## a) refuses unless the account check passed AND a clean destroy plan exists
## b) shows the plan and waits for the human to type: destroy bako
## c) applies the EXACT saved destroy plan, output goes to a log file
## d) then the CODE runs the nothing-running check (no model involved)
## ---------------------------------------------------------------
def tool_terraform_destroy():
    if not STATE["account_ok"]:
        return "REFUSED: the account check has not passed in this run."
    if not STATE["destroy_plan_ok"]:
        return "REFUSED: no clean destroy plan in this run (missing, failed, or not delete-only)."
    print("\n=== DESTROY APPROVAL NEEDED ===")
    print("Plan to apply: " + STATE["destroy_summary"])
    answer = input('Type exactly "destroy bako" to destroy (anything else = no): ').strip()
    trace(event="approval", tool="terraform_destroy", approved=(answer == "destroy bako"))
    if answer != "destroy bako":
        STATE["stop_now"] = "human did not approve"
        return "REFUSED: the human did not approve. Do nothing more."
    ## Step before the destroy: take the load balancer away while the cluster still exists. Refuse if it is still there.
    print("Releasing the load balancer first (pre-destroy-alb.sh)...")
    released, note = release_load_balancer()
    trace(event="step_result", step="release_load_balancer", result=note[-1500:])
    if not released:
        STATE["stop_now"] = "load balancer still exists"
        return ("REFUSED: the load balancer is not released, so destroying the cluster now would leave it running and billing. "
                "Nothing was destroyed.\n" + note)
    print("Load balancer released.")
    log_path = f"agent/env/reports/destroy-{time.strftime('%Y%m%d-%H%M%S')}.log"
    print(f"Destroy started. It takes about 10-15 minutes. Watch it with: tail -f {log_path}")
    try:
        with open(log_path, "w") as log:
            proc = subprocess.run(
                [TERRAFORM, f"-chdir={TF_DIR}", "apply", "-input=false", "-no-color", DESTROY_PLAN_FILE],
                stdout=log, stderr=subprocess.STDOUT, text=True, timeout=30 * 60,
            )
    except subprocess.TimeoutExpired:
        STATE["stop_now"] = "destroy timed out"
        return f"destroy TIMED OUT after 30 minutes. Check state manually. Log: {log_path}"
    tail = open(log_path).read()[-1500:]
    if proc.returncode != 0:
        STATE["stop_now"] = "destroy failed"
        return f"destroy FAILED (exit {proc.returncode}). Log: {log_path}\n{tail}"
    STATE["destroyed"] = True
    checks = tool_run_checks("nothing-running")      # plain code, sets STATE["nothing_running"]
    STATE["stop_now"] = "destroy finished"
    return f"destroy OK. Log: {log_path}\n{checks}"

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

if MODE == "stop":
    for name, desc, fn in [
        ("terraform_plan_destroy", "Plan a full destroy (changes nothing) and return a short summary.", tool_terraform_plan_destroy),
        ("terraform_destroy", "Destroy everything in the saved destroy plan. Asks the human for approval first.", tool_terraform_destroy),
    ]:
        TOOLS.append({"type": "function", "function": {"name": name, "description": desc,
                      "parameters": {"type": "object", "properties": {}}}})
        TOOL_FUNCS[name] = fn

## ---------------------------------------------------------------
## 7. THE PROMPT
## System message = the charter (the rules). User message = today's task,
## chosen by MODE. Both are sent to the model on every call, so keep them short.
## ---------------------------------------------------------------
charter = open("agent/env/CHARTER.md").read()
TASKS = {
    "dry":   "Task: DRY RUN of START. The AWS account check already passed. Run terraform_plan and report what a START would create. Do nothing else.",
    "start": "Task: START, part 1. The AWS account check already passed. Run terraform_plan. If it is clean, run terraform_apply. Then report. Do nothing else.",
    "stop":  "Task: STOP. The AWS account check already passed. Run terraform_plan_destroy. If it is clean, run terraform_destroy. Do nothing else.",
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
## 8b. FIXED SEQUENCES FOR START AND STOP (plain code, the model is not called)
## The order is always the same, so code runs it. Your typed approval is
## still the gate inside terraform_apply / terraform_destroy.
## ---------------------------------------------------------------
def show(name, result):
    trace(event="step_result", step=name, result=result[:2000])
    print(result)

## ---------------------------------------------------------------
## 8b-START. THE FULL START SEQUENCE (plain code, the model is not called)
## One fixed order. Each step reports a "stage" line in the trace, so the
## dashboard's Flow tab can colour its boxes from facts, not from prose:
##   acct -> plan -> appr -> apply -> boot (kubeconfig + bootstrap script; the cluster must be up first)
##   trig -> test -> build -> push (GitHub CI) -> bot (pull request)
##   -> merge (YOU click it on GitHub) -> argo -> ready
## Humans decide twice: the typed word "approved" before apply, and the
## merge of the bot pull request. Code never merges for you.
## ---------------------------------------------------------------
import re
from datetime import datetime, timezone

def read_setting(name, fallback):
    ## Reads NAME=value from checks.sh, so these settings live in one place.
    try:
        with open("agent/env/checks.sh", encoding="utf-8") as f:
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
EXPECTED_ACCOUNT = read_setting("EXPECTED_ACCOUNT", "483272865934")
CLUSTER = os.environ.get("BAKO_CLUSTER", "bako-eks")
ARGO_APP = os.environ.get("BAKO_ARGO_APP", "bako")
ECR_REPOS = ["bako-backend", "bako-frontend"]
POLL = float(os.environ.get("AGENT_POLL_SECONDS", "15"))        # seconds between checks
## kubectl and aws must not see a stray KUBECONFIG (it overrides ~/.kube/config)
CLEAN_ENV = {k: v for k, v in os.environ.items() if k != "KUBECONFIG"}

GH = shutil.which("gh")
AWSCLI = shutil.which("aws")
KUBECTL = shutil.which("kubectl")

def run_cmd(cmd, timeout=120, env=None, stdout_only=False):
    ## Never raises: returns (exit code, output). Never waits for keyboard input.
    ## stdout_only=True is for commands whose output we parse as JSON: a warning on stderr must not break it.
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           stdin=subprocess.DEVNULL, env=env)
        return p.returncode, (p.stdout or "") + ("" if stdout_only else (p.stderr or ""))
    except subprocess.TimeoutExpired:
        return 124, f"TIMED OUT after {timeout}s: {' '.join(cmd[:3])}"
    except OSError as e:
        return 127, f"cannot run {cmd[0]}: {e}"

def aws_cmd(*args):
    cmd = [AWSCLI, *args, "--region", REGION]
    if PROFILE and not os.environ.get("AWS_PROFILE"):
        cmd += ["--profile", PROFILE]
    return cmd

def stage(sid, status, detail=""):
    ## status: running | done | failed | waiting | skipped
    detail = redact.redact(detail)
    trace(event="stage", id=sid, status=status, detail=detail[:1500])
    print(f"[{sid}] {status.upper()}" + (f": {detail}" if detail else ""))

def fail(sid, detail):
    stage(sid, "failed", detail)
    STATE["stopped_at"] = sid
    return False

def wait_for(fn, timeout_s, label=""):
    ## Calls fn() every POLL seconds until it returns something other than None, or time runs out.
    t0 = time.time()
    while True:
        value = fn()
        if value is not None:
            return value
        if time.time() - t0 > timeout_s:
            return None
        time.sleep(POLL)

def preflight_start():
    ## Cheap checks BEFORE any money is spent: everything later steps need must exist.
    problems = []
    for name, path in (("gh", GH), ("aws", AWSCLI), ("kubectl", KUBECTL)):
        if not path:
            problems.append(f"{name} was not found on this computer")
    if not os.path.exists("bootstrap-cluster.sh"):
        problems.append("bootstrap-cluster.sh was not found in the repo root")
    if not os.path.exists(".github/workflows/ci.yml"):
        problems.append(".github/workflows/ci.yml was not found")
    if GH:
        rc, out = run_cmd([GH, "auth", "status"], 30)
        if rc != 0:
            problems.append("gh is not signed in. Run: gh auth login")
    ## the shell that will run bootstrap-cluster.sh must find every tool the script uses
    rc, out = run_cmd([BASH, "-c", "for t in grep awk base64 helm aws kubectl; do command -v $t >/dev/null 2>&1 || echo $t; done"],
                      30, UNIX_ENV)
    missing = out.split()
    if rc != 0 or missing:
        problems.append("the shell that runs bootstrap-cluster.sh cannot find: " + (", ".join(missing) or out.strip()[:200]))
    return problems

def main_sha():
    rc, out = run_cmd([GH, "api", "repos/:owner/:repo/commits/main", "--jq", ".sha"], 30, stdout_only=True)
    sha = out.strip()
    return sha if rc == 0 and re.fullmatch(r"[0-9a-f]{40}", sha) else ""

def ecr_has(repo, tag):
    rc, _ = run_cmd(aws_cmd("ecr", "describe-images", "--repository-name", repo,
                            "--image-ids", f"imageTag={tag}"), 60, CLEAN_ENV)
    return rc == 0

def images_exist(tag):
    return all(ecr_has(repo, tag) for repo in ECR_REPOS)

def deployed_tags():
    ## The image tags that the manifests in K8s/ on main point at: {"bako-backend": tag, ...}.
    ## Empty when we cannot tell for sure (then START simply builds, which is always safe).
    rc, out = run_cmd([GH, "api", "repos/:owner/:repo/git/trees/main?recursive=1", "--jq", ".tree[].path"],
                      60, stdout_only=True)
    if rc != 0:
        return {}
    files = [p for p in out.splitlines() if p.lower().startswith("k8s/") and p.lower().endswith((".yaml", ".yml"))]
    found = {repo: set() for repo in ECR_REPOS}
    for path in files[:80]:
        rc, body = run_cmd([GH, "api", f"repos/:owner/:repo/contents/{path}?ref=main",
                            "-H", "Accept: application/vnd.github.raw"], 60, stdout_only=True)
        if rc != 0:
            continue
        for repo in ECR_REPOS:
            for m in re.finditer(re.escape(repo) + r":([A-Za-z0-9_.-]+)", body):
                found[repo].add(m.group(1))
    if all(len(tags) == 1 for tags in found.values()):
        return {repo: next(iter(tags)) for repo, tags in found.items()}
    return {}

def step_cluster_access():
    ## Point kubectl at the new cluster, and refuse to go on if it is the wrong one.
    rc, out = run_cmd(aws_cmd("eks", "update-kubeconfig", "--name", CLUSTER), 120, CLEAN_ENV)
    if rc != 0:
        return fail("boot", "aws eks update-kubeconfig failed:\n" + out[-800:])
    rc, ctx = run_cmd([KUBECTL, "config", "current-context"], 30, CLEAN_ENV)
    ctx = ctx.strip()
    if rc != 0 or not ctx.endswith(f"{EXPECTED_ACCOUNT}:cluster/{CLUSTER}"):
        return fail("boot", f"kubectl context is '{ctx}', expected one ending in {EXPECTED_ACCOUNT}:cluster/{CLUSTER}. Nothing was changed in the cluster.")
    return True

def step_bootstrap():
    log_path = f"agent/env/reports/bootstrap-{time.strftime('%Y%m%d-%H%M%S')}.log"
    print(f"Bootstrap started (Argo CD, External Secrets, the app). Log: {log_path}")
    try:
        with open(log_path, "w") as log:
            p = subprocess.run([BASH, "bootstrap-cluster.sh"], stdout=log, stderr=subprocess.STDOUT,
                               text=True, timeout=25 * 60, stdin=subprocess.DEVNULL, env=UNIX_ENV)
    except subprocess.TimeoutExpired:
        return fail("boot", f"bootstrap-cluster.sh timed out after 25 minutes. Log: {log_path}")
    if p.returncode != 0:
        tail = open(log_path, errors="replace").read()[-1200:]
        return fail("boot", f"bootstrap-cluster.sh failed (exit {p.returncode}). Log: {log_path}\n{tail}")
    return True

def group_status(items):
    ## items: list of (status, conclusion). Returns done | running | failed | waiting.
    if not items:
        return "waiting"
    if any(c in ("failure", "cancelled", "timed_out", "startup_failure") for _, c in items):
        return "failed"
    if any(s in ("in_progress", "queued", "waiting", "pending") and c in (None, "") for s, c in items):
        return "running" if any(s == "in_progress" for s, _ in items) else "waiting"
    if all(c in ("success", "skipped", "neutral") for _, c in items):
        return "done"
    return "waiting"

def ci_stages(run_json):
    ## Turns a GitHub run into the Flow boxes: test, build, push.
    ## Jobs whose name has "build" or "push" feed build/push (by step name);
    ## every other job is a test job.
    tests, build, push, whole = [], [], [], []
    for job in run_json.get("jobs", []):
        name = job.get("name", "").lower()
        item = (job.get("status"), job.get("conclusion"))
        if "build" in name or "push" in name:
            whole.append(item)
            for st in job.get("steps", []):
                sname = st.get("name", "").lower()
                sitem = (st.get("status"), st.get("conclusion"))
                if re.search(r"credential|login|push|ecr", sname):
                    push.append(sitem)
                elif re.search(r"build|docker|image", sname):
                    build.append(sitem)
        elif job.get("conclusion") != "skipped":
            tests.append(item)
    if whole and not build and not push:
        build, push = whole, whole
    return {"test": group_status(tests), "build": group_status(build), "push": group_status(push)}

def wait_for_ci(run_id):
    ## Polls the run until it finishes. Returns (finished, conclusion, run_json).
    last = {}
    def poll():
        rc, out = run_cmd([GH, "run", "view", str(run_id), "--json", "status,conclusion,jobs,headSha,url"], 60, stdout_only=True)
        if rc != 0:
            return None
        try:
            data = json.loads(out)
        except ValueError:
            return None
        for sid, st in ci_stages(data).items():
            if st == "waiting" and data.get("status") == "completed" and data.get("conclusion") == "success":
                st = "skipped"                  # this workflow has no job for that box
            if last.get(sid) != st:
                last[sid] = st
                stage(sid, st)
        return data if data.get("status") == "completed" else None
    data = wait_for(poll, 25 * 60)
    if data is None:
        return False, "timeout", {}
    return True, data.get("conclusion"), data

def failed_ci_report(run_id, data):
    bad = []
    for job in data.get("jobs", []):
        for st in job.get("steps", []):
            if st.get("conclusion") == "failure":
                bad.append(f"{job.get('name')} / {st.get('name')}")
    rc, log = run_cmd([GH, "run", "view", str(run_id), "--log-failed"], 60)
    return ("Failed step: " + "; ".join(bad) if bad else "Failed") + f"\nRun: {data.get('url', '')}\n" + log[-1200:]

def step_build():
    ## Trigger ci.yml on main (or skip when this commit's images already exist), then follow it.
    ## 1. Do the manifests on main already point at images that exist? Then there is nothing to build or merge.
    tags = deployed_tags()
    if tags and all(ecr_has(repo, tag) for repo, tag in tags.items()):
        for sid in ("trig", "test", "build", "push"):
            stage(sid, "skipped", "the images the cluster needs already exist in ECR (" + next(iter(tags.values()))[:7] + ")")
        STATE["reuse"] = True
        return True
    ## 2. Were images for the newest commit already built (the bot pull request may be waiting)?
    sha = main_sha()
    if not sha:
        return fail("trig", "could not read the latest commit on main from GitHub")
    sha7 = sha[:7]
    STATE["sha7"] = sha7
    if images_exist(sha) or images_exist(sha7):
        for sid in ("trig", "test", "build", "push"):
            stage(sid, "skipped", f"images for {sha7} already exist in ECR")
        return True
    since = datetime.now(timezone.utc).timestamp() - 60
    rc, out = run_cmd([GH, "workflow", "run", "ci.yml", "--ref", "main"], 60)
    if rc != 0:
        return fail("trig", "gh workflow run failed:\n" + out[-800:])
    def find_run():
        rc, out = run_cmd([GH, "run", "list", "--workflow", "ci.yml", "--branch", "main",
                           "--event", "workflow_dispatch", "--limit", "5", "--json", "databaseId,createdAt,url"], 60, stdout_only=True)
        if rc != 0:
            return None
        try:
            for r in json.loads(out or "[]"):
                made = datetime.strptime(r["createdAt"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
                if made >= since:
                    return r
        except (ValueError, KeyError):
            return None
        return None
    run_info = wait_for(find_run, 3 * 60)
    if not run_info:
        return fail("trig", "the build was requested but no run appeared within 3 minutes")
    STATE["run_id"] = run_info["databaseId"]
    stage("trig", "done", run_info.get("url", ""))
    return True

def finish_build():
    ## Waits for the run. One automatic retry when AWS had not yet accepted the new role.
    if "run_id" not in STATE:
        return True              # build was skipped
    run_id = STATE["run_id"]
    for attempt in (1, 2):
        finished, conclusion, data = wait_for_ci(run_id)
        if not finished:
            return fail("build", "the build did not finish within 25 minutes")
        if conclusion == "success":
            return True
        report = failed_ci_report(run_id, data)
        if attempt == 1 and re.search(r"credential|assume|oidc", report, re.I):
            wait_s = float(os.environ.get("AGENT_RETRY_WAIT", "60"))
            print(f"The AWS role may not be active yet (new roles take about a minute). Waiting {wait_s:.0f}s, then re-running the failed job once.")
            trace(event="retry", what="ci rerun", run=run_id)
            time.sleep(wait_s)
            rc, out = run_cmd([GH, "run", "rerun", str(run_id), "--failed"], 60)
            if rc == 0:
                continue
        bad = [k for k, v in ci_stages(data).items() if v == "failed"]
        return fail(bad[0] if bad else "build", report)
    return False

def step_bot_pr():
    branch = f"deploy/image-{STATE['sha7']}"          # the bot adds "-<run id>" after this
    def find():
        rc, out = run_cmd([GH, "pr", "list", "--state", "all", "--limit", "30",
                           "--json", "number,state,url,mergeCommit,headRefName"], 60, stdout_only=True)
        if rc != 0:
            return None
        try:
            prs = json.loads(out or "[]")
        except ValueError:
            return None
        mine = [p for p in prs if re.fullmatch(re.escape(branch) + r"(-\d+)?", p.get("headRefName", ""))]
        mine.sort(key=lambda p: p["number"], reverse=True)       # newest first
        live = [p for p in mine if p["state"] != "CLOSED"]
        return (live or mine or [None])[0]
    pr = wait_for(find, 10 * 60)
    if not pr:
        return fail("bot", f"no pull request from branch {branch} appeared within 10 minutes")
    STATE["pr"] = pr
    stage("bot", "done", f"#{pr['number']} {pr['url']}")
    return True

def adopt_latest_bot_pr():
    ## Used when START is resumed after the build: take the newest open (or merged) bot pull request.
    rc, out = run_cmd([GH, "pr", "list", "--state", "all", "--limit", "30",
                       "--json", "number,state,url,mergeCommit,headRefName"], 60, stdout_only=True)
    try:
        prs = [p for p in json.loads(out or "[]") if p.get("headRefName", "").startswith("deploy/image-")]
    except ValueError:
        prs = []
    prs.sort(key=lambda p: p["number"], reverse=True)
    live = [p for p in prs if p["state"] != "CLOSED"]
    pr = (live or [None])[0]
    if not pr:
        return fail("bot", "no open or merged bot pull request found. Press Start to build a new one.")
    STATE["pr"] = pr
    stage("bot", "done", f"#{pr['number']} {pr['url']}")
    return True

def step_merge_gate():
    ## The human gate. We only watch; the merge happens on GitHub, by you.
    pr = STATE["pr"]
    n = pr["number"]
    if pr["state"] == "MERGED":
        STATE["merge_oid"] = (pr.get("mergeCommit") or {}).get("oid", "")
        stage("merge", "skipped", f"#{n} was already merged")
        return True
    rc, checks = run_cmd([GH, "pr", "checks", str(n)], 60)
    print(f"\n=== ACTION FOR YOU ===\nMerge pull request #{n}: {pr['url']}\nChecks:\n{checks.strip()[:800]}")
    stage("merge", "running", f"waiting for you to merge #{n}")
    waited = {"t": time.time()}
    def merged():
        rc, out = run_cmd([GH, "pr", "view", str(n), "--json", "state,mergeCommit"], 60, stdout_only=True)
        if rc != 0:
            return None
        try:
            d = json.loads(out)
        except ValueError:
            return None
        if d.get("state") == "MERGED":
            return d
        if d.get("state") == "CLOSED":
            return d
        if time.time() - waited["t"] > 300:
            waited["t"] = time.time()
            print(f"Still waiting for you to merge #{n}.")
        return None
    d = wait_for(merged, 45 * 60)
    if d is None:
        return fail("merge", f"pull request #{n} was not merged within 45 minutes")
    if d["state"] == "CLOSED":
        return fail("merge", f"pull request #{n} was closed without merging")
    STATE["merge_oid"] = (d.get("mergeCommit") or {}).get("oid", "")
    stage("merge", "done", f"#{n} merged")
    return True

def step_argo():
    ## Argo must be Synced and Healthy AT the merged commit (not at yesterday's).
    stage("argo", "running", "refreshing the application")
    run_cmd([KUBECTL, "-n", "argocd", "annotate", "application", ARGO_APP,
             "argocd.argoproj.io/refresh=hard", "--overwrite"], 60, CLEAN_ENV)
    want = STATE.get("merge_oid", "")
    seen = {"s": ""}
    def ok():
        rc, out = run_cmd([KUBECTL, "-n", "argocd", "get", "application", ARGO_APP, "-o", "json"], 60, CLEAN_ENV, stdout_only=True)
        if rc != 0:
            return None
        try:
            st = json.loads(out).get("status", {})
        except ValueError:
            return None
        sync, health = st.get("sync", {}).get("status"), st.get("health", {}).get("status")
        rev = st.get("sync", {}).get("revision", "")
        line = f"{sync}/{health} at {rev[:7]}"
        if line != seen["s"]:
            seen["s"] = line
            print("Argo CD:", line)
        if sync == "Synced" and health == "Healthy" and (not want or rev == want):
            return line
        return None
    result = wait_for(ok, 15 * 60)
    if not result:
        return fail("argo", f"Argo CD did not reach Synced/Healthy at {want[:7]} in 15 minutes (last: {seen['s']})")
    stage("argo", "done", result)
    return True

def step_ready():
    stage("ready", "running", "running the READY checks")
    out = {"text": ""}
    def good():
        out["text"] = tool_run_checks("ready")
        return True if out["text"].rstrip().endswith("exit code: 0") else None
    if wait_for(good, 5 * 60):
        STATE["ready"] = True
        stage("ready", "done")
        print(out["text"])
        return True
    print(out["text"])
    return fail("ready", "the READY checks did not all pass within 5 minutes:\n" + out["text"][-800:])

def run_start():
    problems = preflight_start()
    if problems:
        print("STOP: START cannot run yet. Nothing was changed.")
        for p in problems:
            print(" -", p)
        stage("pre", "failed", "; ".join(problems))
        STATE["stopped_at"] = "preflight"
        return
    stage("acct", "done")
    if FROM:
        print(f"\n>> Resuming START from '{FROM}'. Plan and apply are not repeated.")
        for sid in ("plan", "appr", "apply"):
            stage(sid, "skipped", "done in an earlier run")
        STATE["applied"] = True
        run_tail(ORDER.index(FROM))
        return
    stage("plan", "running")
    print("\n>> Planning (read-only)")
    show("terraform_plan", tool_terraform_plan())
    if not STATE["plan_ok"]:
        fail("plan", "the plan is not clean. Nothing was applied.")
        return
    stage("plan", "done", STATE["plan_summary"][:200])
    counts = STATE.get("plan_counts", {})
    if counts and not any(counts.values()):
        STATE["applied"] = True
        stage("appr", "skipped", "nothing to apply, the lab already exists")
        stage("apply", "skipped", "no changes")
    else:
        stage("appr", "running", "waiting for your typed word")
        print("\n>> Apply (needs your typed approval)")
        show("terraform_apply", tool_terraform_apply())
        if STATE["stop_now"] == "human did not approve":
            fail("appr", "you did not type approved. Nothing was applied.")
            return
        stage("appr", "done")
        stage("apply", "running")
        if not STATE["applied"]:
            fail("apply", STATE["stop_now"] or "apply did not finish")
            return
        stage("apply", "done")
    run_tail(0)

def run_tail(first):
    ## Everything after terraform apply. first = position in ORDER to begin at (0 = from the bootstrap).
    ## Steps before it are shown as skipped ("done in an earlier run").
    boxes = {"boot": ["boot"], "trig": ["trig", "test", "build", "push"], "bot": ["bot"],
             "merge": ["merge"], "argo": ["argo"], "ready": ["ready"]}
    for key in ORDER[:first]:
        for sid in boxes[key]:
            stage(sid, "skipped", "done in an earlier run")
    if first == 0:
        stage("boot", "running", "kubectl access and bootstrap script")
    if not step_cluster_access():              # also proves the lab exists: fails if the cluster is gone
        return
    if first == 0:
        if not step_bootstrap():               # the cluster must be up BEFORE GitHub builds anything
            return
        stage("boot", "done")
    if first <= 1:
        if not step_build():
            return
        if not finish_build():
            return
    if STATE.get("reuse"):
        stage("bot", "skipped", "the manifests already point at images that exist")
        stage("merge", "skipped", "nothing to merge")
        STATE["merge_oid"] = ""
    else:
        if first <= 2:
            ok = step_bot_pr() if "sha7" in STATE else adopt_latest_bot_pr()
            if not ok:
                return
        elif first <= 3:
            if not adopt_latest_bot_pr():
                return
        if first <= 3:
            if not step_merge_gate():
                return
        else:
            STATE["merge_oid"] = ""            # resumed later: any revision is fine, it must be Synced and Healthy
    if first <= 4:
        if not step_argo():
            return
    step_ready()

if MODE == "stop":
    print("\n>> Planning the destroy (read-only)")
    show("terraform_plan_destroy", tool_terraform_plan_destroy())
    if STATE["destroy_plan_ok"]:
        print("\n>> Destroy (needs your typed approval)")
        show("terraform_destroy", tool_terraform_destroy())
    else:
        print("STOP: the destroy plan is not clean. Nothing was deleted.")
    trace(event="stop", reason="stop sequence finished")
    print_verdict()
    raise SystemExit(0 if (STATE["destroyed"] and STATE["nothing_running"]) else 1)

if MODE == "start":
    run_start()
    trace(event="stop", reason="start sequence finished")
    print_verdict()
    raise SystemExit(0 if STATE["ready"] else 1)

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

## Dry mode ends here; start and stop print their own verdict above.
print_verdict()