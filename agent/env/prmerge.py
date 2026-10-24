## ---------------------------------------------------------------
## prmerge.py - merge the BOT pull request from the Bako window (no browser sign-in needed).
## The dashboard calls review() to show you what will change, and merge() only after you type "merge bako".
## Safety rules enforced here, in code:
##   - only a pull request from a branch named deploy/image-... (the bot's image bump)
##   - only while it is open, and only if it changes a few files (a bot bump changes 2)
##   - it uses your signed-in gh. Nothing else on GitHub is touched. The branch is not deleted.
## ---------------------------------------------------------------
import json, subprocess

MAX_FILES = 4

def _run(cmd, cwd, timeout=90):
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL,
                           encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return p.returncode, p.stdout or "", p.stderr or ""
    except Exception as e:
        return 1, "", str(e)

def review(gh, n, cwd):
    """Returns a dict: title, url, additions, deletions, changedFiles, diff, problems (list of reasons NOT to merge)."""
    rc, out, err = _run([gh, "pr", "view", str(n), "--json",
                         "title,state,headRefName,additions,deletions,changedFiles,url,mergeStateStatus"], cwd)
    if rc != 0:
        return {"problems": ["could not read the pull request: " + (err or out).strip()[:300]]}
    try:
        info = json.loads(out)
    except ValueError:
        return {"problems": ["could not read the pull request (unexpected answer from gh)"]}
    problems = []
    if info.get("state") != "OPEN":
        problems.append(f"It is {info.get('state')}, not open.")
    if not str(info.get("headRefName", "")).startswith("deploy/image-"):
        problems.append("It is not a bot image pull request (its branch must start with deploy/image-).")
    if int(info.get("changedFiles", 0)) > MAX_FILES:
        problems.append(f"It changes {info.get('changedFiles')} files. A bot image bump changes about 2.")
    rc, diff, _ = _run([gh, "pr", "diff", str(n)], cwd)
    info["diff"] = diff if rc == 0 else "(could not read the diff)"
    info["problems"] = problems
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
            return True, f"Merged pull request #{n} ({flag[2:]}). Bako continues by itself."
        if "not allowed" not in last.lower():
            break
    return False, "Not merged: " + last[:400]