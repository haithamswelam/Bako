"""Run once from the repo root:  python patch_tracing.py
Two small changes, both safe to run twice, each with a backup (.bak):

1. K8s/backend-deployment.yaml: adds the four OTEL_ variables so the backend sends its traces to the receiver (K8s/tracing.yaml).
2. app/security.py: wraps the password check and the password hash in named spans ("password.verify", "password.hash"), so a trace shows
   that step on its own instead of hiding it inside "other code".
It also adds tests/test_security_spans.py (the safety net for change 2: logging in and hashing still work).

The app change goes out like any change: commit, CI builds, the bot PR, merge. Nothing here touches the cluster directly."""
import os, re, shutil, sys

ENV = [("OTEL_TRACING_ENABLED", "true"), ("OTEL_SERVICE_NAME", "bako-backend"), ("OTEL_DEPLOYMENT_ENVIRONMENT", "eks-lab"),
       ("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "http://jaeger.bako.svc.cluster.local:4318/v1/traces")]

def read(p):
    return open(p, encoding="utf-8", newline="").read()

def write(p, s):
    shutil.copyfile(p, p + ".bak")
    open(p, "w", encoding="utf-8", newline="").write(s)

def patch_deployment():
    p = "K8s/backend-deployment.yaml"
    if not os.path.exists(p):
        print(f"[1] {p} not found. Run this from the repo root. Skipped."); return False
    s = read(p)
    if "OTEL_TRACING_ENABLED" in s:
        print("[1] backend deployment already has the OTEL variables. Nothing to do."); return True
    nl = "\r\n" if "\r\n" in s else "\n"
    lines = s.split(nl)
    start = next((i for i, l in enumerate(lines) if re.match(r"^\s*containers:\s*$", l)), None)
    if start is None:
        print("[1] could not find 'containers:' in", p, "- nothing changed. Send me the file."); return False
    end = next((i for i in range(start, len(lines)) if lines[i].startswith("---")), len(lines))      # the Deployment's own document
    env_i = next((i for i in range(start, end) if re.match(r"^\s*env:\s*$", lines[i])), None)
    if env_i is not None:                                           # an env: list already exists: add to it
        l = lines[env_i]
        ind = len(l) - len(l.lstrip())
        item_ind = ind + 2
        if env_i + 1 < len(lines) and lines[env_i + 1].lstrip().startswith("- "):
            item_ind = len(lines[env_i + 1]) - len(lines[env_i + 1].lstrip())
        add = []
        for k, v in ENV:
            add += [" " * item_ind + f"- name: {k}", " " * (item_ind + 2) + f'value: "{v}"']
        write(p, nl.join(lines[:env_i + 1] + add + lines[env_i + 1:]))
        print("[1] added the OTEL variables to the existing env: list of", p); return True
    img_i = next((i for i in range(start, end) if re.match(r"^\s*image:\s", lines[i])), None)
    if img_i is not None:                                           # no env: yet: add a block after the image line
        ind = len(lines[img_i]) - len(lines[img_i].lstrip())
        add = [" " * ind + "env:"]
        for k, v in ENV:
            add += [" " * (ind + 2) + f"- name: {k}", " " * (ind + 4) + f'value: "{v}"']
        write(p, nl.join(lines[:img_i + 1] + add + lines[img_i + 1:]))
        print("[1] added an env: block with the OTEL variables to", p); return True
    print("[1] could not find where the backend's containers start in", p, "- nothing changed. Send me the file."); return False

SECURITY_NEW = '''from opentelemetry import trace as _trace

_tracer = _trace.get_tracer("bako.security")      # does nothing when tracing is off

# Hash password
def hash_password(password: str):
    with _tracer.start_as_current_span("password.hash"):
        return pwd_context.hash(password)

# Verify password
def verify_password(
    plain_password: str,
    hashed_password: str
):
    with _tracer.start_as_current_span("password.verify"):
        return pwd_context.verify(
            plain_password,
            hashed_password
        )
'''

def patch_security():
    p = next((x for x in ("app/security.py", "Bako/app/security.py") if os.path.exists(x)), None)
    if not p:
        print("[2] app/security.py not found. Run this from the repo root. Skipped."); return False
    s = read(p)
    if "password.verify" in s:
        print("[2] security.py already has the password spans. Nothing to do."); return True
    nl = "\r\n" if "\r\n" in s else "\n"
    t = s.replace("\r\n", "\n")
    pat = re.compile(r"# Hash password\ndef hash_password\(password: str\):\n    return pwd_context\.hash\(password\)\n\n"
                     r"# Verify password\ndef verify_password\(\n    plain_password: str,\n    hashed_password: str\n\):\n"
                     r"    return pwd_context\.verify\(\n        plain_password,\n        hashed_password\n    \)\n")
    m = pat.search(t)
    if not m:
        print("[2] hash_password / verify_password do not look as expected in", p, "- nothing changed. Send me the file."); return False
    t = t[:m.start()] + SECURITY_NEW + t[m.end():]
    write(p, t.replace("\n", nl))
    print("[2] password spans added to", p)
    test = "tests/test_security_spans.py"
    if not os.path.exists(test):
        os.makedirs("tests", exist_ok=True)
        open(test, "w", encoding="utf-8", newline="\n").write(TEST)
        print("    added", test)
    return True

TEST = '''"""Safety net for the password spans: the spans must not change what the functions do."""
from app.security import hash_password, verify_password


def test_hash_then_verify_works():
    h = hash_password("correct horse")
    assert h != "correct horse"
    assert verify_password("correct horse", h) is True


def test_wrong_password_is_refused():
    h = hash_password("correct horse")
    assert verify_password("wrong horse", h) is False
'''

if __name__ == "__main__":
    a = patch_deployment()
    b = patch_security()
    print("\nDone." if a and b else "\nFinished with problems (see above).")
    print("Next: git add -A, commit, push. CI builds the image; the bot PR deploys it. Also add K8s/tracing.yaml (included in the zip).")
