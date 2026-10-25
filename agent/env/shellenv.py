## ---------------------------------------------------------------
## shellenv.py - lets bash find Unix tools (grep, awk, base64...) when Bako starts it.
## Why: your own Git Bash window is a "login shell" and sees /usr/bin. A bash started from Python
## (the dashboard, the agent) gets plain Windows paths, so scripts say "grep: command not found".
## The fix: add Git's usr/bin folder to the END of PATH, so aws, kubectl and helm keep priority.
## Used by agent.py, dashboard.py and bako_chat.py. On Linux and macOS it changes nothing.
## ---------------------------------------------------------------
import os, shutil

NEEDED = ("grep", "awk", "base64")

def unix_env(bash, env=None):
    env = dict(os.environ if env is None else env)
    if not bash:
        return env
    key = next((k for k in env if k.upper() == "PATH"), "PATH")
    path = env.get(key, "")
    if all(shutil.which(tool, path=path) for tool in NEEDED):
        return env
    bash_dir = os.path.dirname(bash)
    for folder in (os.path.join(os.path.dirname(bash_dir), "usr", "bin"), bash_dir):
        if os.path.isdir(folder) and shutil.which("grep", path=folder):
            env[key] = path + os.pathsep + folder
            return env
    return env