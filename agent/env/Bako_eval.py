## ---------------------------------------------------------------
## BAKO EVAL - run the same questions through Bako in two modes and compare.
##   old  = the behaviour before the improvements (BAKO_LEAN=0)
##   lean = the improved behaviour (default)
## It uses your real OpenAI key, so it costs real tokens (about 100,000 for 5 questions x 2 modes).
## Nothing is changed: Bako's tools are read-only, and proposals are only recorded, never run.
##
## Which questions: 5 fixed ones as a baseline, PLUS your own real questions. Every message you send Bako is
## saved in agent/env/reports/chat-traces.jsonl, so the test set grows from how you really ask.
##
## Run from the repo folder:   python agent/env/bako_eval.py
##   --real 10         use your last 10 distinct real questions (default 5; 0 = none)
##   --no-fixed        skip the 5 fixed baseline questions
##   --modes lean      run only one mode (old, lean or old,lean) - cheaper
## Dollars use the prices saved on the Reports page (defaults: gpt-5.4-nano on OpenAI's page).
## The full result is saved to agent/env/reports/eval-<time>.json
## ---------------------------------------------------------------
import datetime, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bako_chat
import usage

REPO_ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))

MODEL = os.environ.get("AGENT_MODEL", "gpt-5.4-nano")

## What a good answer looks like is written next to each question, so you can judge the result yourself.
QUESTIONS = [
    ("why did my flow fail?",
     "Looks at GitHub runs, says which failure and how old it is, notes that newer runs passed. Does not read a destroy log."),
    ("what branch am I on?",
     "One call: git branch. Nothing else."),
    ("what changed in the last commit?",
     "One call: git show. Short summary."),
    ("did my last build work?",
     "github runs, then answers yes or no with the run id and age."),
    ("merge the open pull request into main",
     "No tool can do it. Tells you to use the Review and merge here button."),
]

def real_questions(repo, n):
    ## Your own earlier questions, newest first, with what happened back then (tools and tokens).
    path = os.path.join(repo, "agent", "env", "reports", "chat-traces.jsonl")
    seen, out = set(), []
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return out
    for line in reversed(lines):
        try:
            t = json.loads(line)
        except ValueError:
            continue
        q = (t.get("question") or "").strip()
        key = q.lower()
        if not q or key in seen or q.startswith("Troubleshoot the") or "```" in q or len(q) > 300:
            continue                     # skip the long auto-written questions from the Flow tab's button
        seen.add(key)
        use = [(r.get("usage") or {}) for r in t.get("rounds", [])]
        was = (f"{' -> '.join(c['name'] for c in t.get('calls', [])) or 'no tool'}; "
               f"{sum(u.get('total_tokens', 0) for u in use):,} tokens ({t.get('mode', 'old')} mode, {str(t.get('time', ''))[:16]})")
        out.append((q, "your own question: judge the reply yourself", was))
        if len(out) >= n:
            break
    return out

def get_client():
    try:
        from openai import OpenAI
        import keyring
        key = os.environ.get("OPENAI_API_KEY") or keyring.get_password("bako-agent", "OPENAI_API_KEY")
    except Exception:
        key = None
    return OpenAI(api_key=key) if key else None

def run_one(client, repo, question):
    history = []
    reply, action, tokens = bako_chat.run_turn(client, MODEL, history, question, repo)
    tr = bako_chat.LAST_TRACE or {}
    rounds = tr.get("rounds", [])
    use = [r.get("usage") or {} for r in rounds]
    return {
        "question": question,
        "mode": tr.get("mode"),
        "tools": [f"{c['name']}({bako_chat_args(c['arguments'])})" for c in tr.get("calls", [])],
        "model_calls": len(rounds),
        "in": sum(u.get("prompt_tokens", 0) for u in use),
        "out": sum(u.get("completion_tokens", 0) for u in use),
        "cached": sum(u.get("cached_tokens", 0) for u in use),
        "seconds": round(sum((r.get("ms") or 0) for r in rounds) / 1000
                         + sum(c.get("ms", 0) for c in tr.get("calls", [])) / 1000, 1),
        "stopped_by": tr.get("stopped_by"),
        "reply": reply,
    }

def bako_chat_args(a):
    try:
        return ", ".join(f"{k}={v}" for k, v in json.loads(a or "{}").items())
    except ValueError:
        return str(a)[:40]

def cost(r):
    ## same prices as the Reports page (editable there; defaults from OpenAI's page for gpt-5.4-nano)
    return usage.turn_cost(r["in"], r["cached"], r["out"], usage.get_prices(REPO_ROOT))

QUESTIONS_RUN = []          # the questions of this run: (question, what a good answer looks like, what happened before)

def main():
    client = get_client()
    if client is None:
        print("No OpenAI key found (environment OPENAI_API_KEY or keyring bako-agent). Nothing was run.")
        return 1
    repo = os.path.abspath(os.path.join(HERE, "..", ".."))
    args = sys.argv[1:]
    def opt(name, default):
        return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else default
    modes = [m for m in opt("--modes", "old,lean").split(",") if m in ("old", "lean")] or ["old", "lean"]
    qs = ([] if "--no-fixed" in args else [(q, g, None) for q, g in QUESTIONS])
    try:
        qs += real_questions(repo, int(opt("--real", "5")))
    except ValueError:
        pass
    if not qs:
        print("No questions to run.")
        return 1
    print(f"{len(qs)} questions x {len(modes)} mode(s) = {len(qs) * len(modes)} runs, each about 10,000 tokens.")
    QUESTIONS_RUN[:] = qs
    results = []
    for mode in modes:
        bako_chat.LEAN = (mode == "lean")
        for q, _, _ in qs:
            print(f"[{mode}] {q} ...", flush=True)
            try:
                results.append(run_one(client, repo, q))
            except Exception as e:
                results.append({"question": q, "mode": mode, "error": f"{type(e).__name__}: {e}"[:200]})
    show(results)
    d = os.path.join(repo, "agent", "env", "reports")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "eval-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S") + ".json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"model": MODEL, "results": results}, f, indent=2, ensure_ascii=False)
    print("\nSaved:", path)
    return 0

def show(results):
    print("\n" + "=" * 78)
    for q, good, was in QUESTIONS_RUN:
        print(f"\nQ: {q}\n   good answer: {good}" + (f"\n   back then:   {was}" if was else ""))
        for r in (x for x in results if x["question"] == q):
            if r.get("error"):
                print(f"   {r['mode']:>4}: ERROR {r['error']}")
                continue
            c = cost(r)
            print(f"   {r['mode']:>4}: {r['model_calls']} model calls, {r['in'] + r['out']:,} tokens "
                  f"({r['in']:,} in, {r['cached']:,} cached, {r['out']:,} out), {r['seconds']} s"
                  + f", ${c:.5f}"
                  + (f", cut by {r['stopped_by']}" if r["stopped_by"] else ""))
            print(f"         tools: {' -> '.join(r['tools']) or 'none'}")
            print(f"         reply: {r['reply'][:230].replace(chr(10), ' ')}")
    print("\nTOTALS (judge the pattern across all questions, not any single one)")
    for mode in ("old", "lean"):
        rs = [r for r in results if r.get("mode") == mode and not r.get("error")]
        if not rs:
            continue
        tot = sum(r["in"] + r["out"] for r in rs)
        cs = [cost(r) for r in rs]
        print(f"   {mode:>4}: {len(rs)} questions, {tot:,} tokens in all ({tot // len(rs):,} per question), "
              f"{sum(r['seconds'] for r in rs) / len(rs):.1f} s each, "
              f"{sum(1 for r in rs if not r['tools'])} answered without a tool, {sum(1 for r in rs if r['stopped_by'])} cut by a limit, "
              f"{sum(r['model_calls'] for r in rs) / len(rs):.1f} model calls each"
              + f", ${sum(cs):.4f} (${sum(cs) / len(rs):.5f} per question)")

if __name__ == "__main__":
    sys.exit(main())