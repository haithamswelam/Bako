## ---------------------------------------------------------------
## redact.py - hides secrets in text BEFORE it is shown to the model or written to the trace.
## Used by agent.py (trace), bako_chat.py (every tool result) and dashboard.py (Ask Bako).
## The files on your disk are not changed; only the copy that leaves for OpenAI is cleaned.
## ---------------------------------------------------------------
import re

HIDDEN = "[hidden]"
_KEYS = r"(?:password|passwd|pwd|token|secret|api[_-]?key|access[_-]?key|secret[_-]?access[_-]?key|private[_-]?key)"

_RULES = [
    ## JSON / Go-map style:  "password":"abc==",  "token": "abc"
    (re.compile(r'("?' + _KEYS + r'"?\s*:\s*)"[^"]*"', re.I), r'\1"' + HIDDEN + '"'),
    ## plain lines:  Argo CD admin password: abc   /   token=abc   /   secret_access_key = abc
    (re.compile(r"(\b[\w .-]*" + _KEYS + r"\b\s*[:=]\s*)(?!\[hidden\])\S+", re.I), r"\1" + HIDDEN),
    ## well-known key shapes
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), HIDDEN),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"), HIDDEN),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"), HIDDEN),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{20,}"), r"\1" + HIDDEN),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S), HIDDEN),
]

def redact(text):
    text = "" if text is None else str(text)
    for pattern, repl in _RULES:
        text = pattern.sub(repl, text)
    return text