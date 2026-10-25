## ---------------------------------------------------------------
## prmerge.py - open, review and merge pull requests from the Bako window (no browser sign-in needed).
## The dashboard calls review() to show you exactly what will change, and merge() only after you type "merge bako".
##
## Two kinds of pull request may be handled, and ONLY these two (enforced here, in code):
##   image : from a branch named deploy/image-...  (the bot's image bump after a CI build). Changes about 2 files.
##   code  : from a branch named bako/update-...   (a branch Bako itself pushed after you typed "push bako").
## Rules for both: the pull request must be open, aim at main, and have no merge conflict.
## Rules for code: at most 50 files, no secret-looking files (.env, *.tfvars, keys, state), and no failing CI check.
## It uses your signed-in gh. Nothing else on GitHub is touched. The branch is not deleted.
## ---------------------------------------------------------------
import json, re, subprocess

import bako_chat                 # for is_blocked(): the same list of secret-looking files Bako can never read or commit

ALLOWED = (("deploy/image-", "image"), ("bako/update-", "code"))
MAX_FILES = 4                    # an image bump changes about 2 files
MAX_CODE_FILES = 50
MAX_DIFF_CHARS = 20000           # the diff shown on screen is cut here (the pull request on GitHub is not)

## Paths where a change deserves a loud heads-up (shown, not blocked: you decide).
def heads_up(path):
    if path.startswith(".github/"):
        return "changes CI: what runs on GitHub"
    if path.startswith(("K8s/", "k8s/")):
        return "Kubernetes manifests: Argo CD deploys these"
    if path.endswith(".tf"):
        return "Terraform: changes AWS at the next apply"
    if path == "bootstrap-cluster.sh":
        return "the cluster bootstrap script"
    if path.startswith("agent/env/"):
        return "Bako's own code"
    return ""

def _run(cmd, cwd, timeout=90):
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL,
                           encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return p.returncode, p.stdout or "", p.stderr or ""
    except Exception as e:
        return 1, "", str(e)

def _checks(rollup):
    """(passed, running, failed) from gh's statusCheckRollup list."""
    ok = run = bad = 0
    for c in rollup or []:
        state = str(c.get("conclusion") or c.get("state") or "").upper()
        status = str(c.get("status") or "").upper()
        if state in ("FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE"):
            bad += 1
        elif state in ("SUCCESS", "NEUTRAL", "SKIPPED"):
            ok += 1
        elif status and status != "COMPLETED" or state == "PENDING" or not state:
            run += 1
    return ok, run, bad

def _files(gh, n, cwd):
    """[{path, status, additions, deletions}] for the pull request."""
    names = {"added": "new", "modified": "modified", "removed": "deleted", "renamed": "renamed", "changed": "modified"}
    rc, out, _ = _run([gh, "api", f"repos/{{owner}}/{{repo}}/pulls/{n}/files?per_page=100"], cwd)
    if rc == 0:
        try:
            return [{"path": f["filename"], "status": names.get(f.get("status"), f.get("status", "changed")),
                     "additions": f.get("additions", 0), "deletions": f.get("deletions", 0)} for f in json.loads(out)]
        except (ValueError, KeyError, TypeError):
            pass
    rc, out, _ = _run([gh, "pr", "view", str(n), "--json", "files"], cwd)
    try:
        return [{"path": f["path"], "status": "modified", "additions": f.get("additions", 0), "deletions": f.get("deletions", 0)}
                for f in json.loads(out).get("files", [])]
    except (ValueError, KeyError, TypeError):
        return []

def review(gh, n, cwd):
    """A dict: title, url, kind, additions, deletions, changedFiles, files, checks, diff, warnings, problems.
    problems = reasons NOT to merge (empty means the rules allow it); warnings = things to look at first."""
    rc, out, err = _run([gh, "pr", "view", str(n), "--json",
                         "title,state,headRefName,baseRefName,additions,deletions,changedFiles,url,mergeStateStatus,statusCheckRollup"], cwd)
    if rc != 0:
        return {"problems": ["could not read the pull request: " + (err or out).strip()[:300]]}
    try:
        info = json.loads(out)
    except ValueError:
        return {"problems": ["could not read the pull request (unexpected answer from gh)"]}
    problems, warnings = [], []
    branch = str(info.get("headRefName", ""))
    kind = next((k for prefix, k in ALLOWED if branch.startswith(prefix)), None)
    info["kind"] = kind
    if info.get("state") != "OPEN":
        problems.append(f"It is {info.get('state')}, not open.")
    if kind is None:
        problems.append("It is not one of Bako's pull requests (its branch must start with deploy/image- or bako/update-).")
    if info.get("baseRefName", "main") != "main":
        problems.append(f"It aims at {info.get('baseRefName')}, not main.")
    if info.get("mergeStateStatus") == "DIRTY":
        problems.append("It has a merge conflict with main. Fix that on GitHub first.")
    files = _files(gh, n, cwd)
    count = int(info.get("changedFiles", 0) or len(files))
    for f in files:
        f["note"] = heads_up(f["path"]) if kind == "code" else ""      # an image bump always touches K8s/: no noise there
    info["files"] = files
    if kind == "image" and count > MAX_FILES:
        problems.append(f"It changes {count} files. A bot image bump changes about 2.")
    if kind == "code":
        if count > MAX_CODE_FILES:
            problems.append(f"It changes {count} files (the limit here is {MAX_CODE_FILES}). Review it on GitHub.")
        if len(files) < count:
            problems.append(f"Only {len(files)} of its {count} files could be listed, so it cannot be reviewed fully here.")
        secret = [f["path"] for f in files if bako_chat.is_blocked(f["path"])]
        if secret:
            problems.append("It contains secret-looking files: " + ", ".join(secret[:5]) + ". Remove them from the branch first.")
    ok, running, bad = _checks(info.get("statusCheckRollup"))
    info["checks"] = {"passed": ok, "running": running, "failed": bad}
    if bad:
        (problems if kind == "code" else warnings).append(f"{bad} CI check(s) failed.")
    if running:
        warnings.append(f"{running} CI check(s) are still running. Review again when they finish.")
    for f in files:
        if f["note"]:
            warnings.append(f"{f['path']}: {f['note']}")
    rc, diff, _ = _run([gh, "pr", "diff", str(n)], cwd)
    if rc != 0:
        diff = "(could not read the diff)"
    elif len(diff) > MAX_DIFF_CHARS:
        diff = diff[:MAX_DIFF_CHARS] + "\n...(the diff is longer; the rest is on GitHub)"
    info["diff"] = diff
    info["warnings"], info["problems"] = warnings, problems
    return info

def merge(gh, n, cwd):
    """Re-checks the rules, then merges. Returns (ok, text)."""
    info = review(gh, n, cwd)
    if info["problems"]:
        return False, "Not merged. " + " ".join(info["problems"])
    last = ""
    for flag in ("--squash", "--merge", "--rebase"):          # use whatever the repository allows
        rc, out, err = _run([gh, "pr", "merge", str(n), flag], cwd, timeout=120)
        last = (out + err).strip()
        if rc == 0:
            if info.get("kind") == "code":
                return True, (f"Merged pull request #{n} into main ({flag[2:]}). Your folder is still on the branch: "
                              "run `git switch main` and `git pull` to catch up.")
            return True, f"Merged pull request #{n} ({flag[2:]}). Bako continues by itself."
        if "not allowed" not in last.lower():
            break
    return False, "Not merged: " + last[:400]

def open_pr(gh, branch, title, cwd):
    """Opens a pull request into main for a branch Bako pushed. Returns (ok, number, url_or_message). Reuses an open one."""
    if not str(branch).startswith("bako/update-"):
        return False, 0, "Only a branch that Bako created (bako/update-...) can be opened from here."
    rc, out, _ = _run([gh, "pr", "list", "--head", branch, "--state", "open", "--json", "number,url"], cwd)
    try:
        found = json.loads(out) if rc == 0 else []
    except ValueError:
        found = []
    if found:
        return True, int(found[0]["number"]), found[0].get("url", "")
    body = "Opened from the Bako window. Review the file list there before merging."
    rc, out, err = _run([gh, "pr", "create", "--base", "main", "--head", branch, "--title", (title or "Update Bako files")[:200],
                         "--body", body], cwd, timeout=120)
    text = (out + "\n" + err).strip()
    m = re.search(r"https://\S+/pull/(\d+)", text)
    if rc != 0 or not m:
        return False, 0, "Could not open the pull request: " + text[:300]
    return True, int(m.group(1)), m.group(0)