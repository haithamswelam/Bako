"""Run once from the repo root:  python patch_bootstrap_argo.py
Replaces step 7 of bootstrap-cluster.sh (which printed the Argo CD admin password) with a message that tells you
the command to read it only when you need it. Safe to run twice. Makes a backup: bootstrap-cluster.sh.bak"""
import re, shutil, sys
P = "bootstrap-cluster.sh"
s = open(P, encoding="utf-8", newline="").read()
nl = "\r\n" if "\r\n" in s else "\n"
if "Argo CD admin password: not printed" in s:
    print("Already patched. Nothing to do."); sys.exit(0)
pat = re.compile(r'echo "== 7\. Print the Argo CD initial admin password[^\r\n]*"\r?\n'
                 r'echo -n "Argo CD admin password: "\r?\n'
                 r'kubectl -n argocd get secret argocd-initial-admin-secret[^\r\n]*\r?\n'
                 r'echo\r?\n')
new = nl.join([
    'echo "== 7. Argo CD admin password: not printed on purpose =="',
    'echo "When you need it, read it on demand (it is never shown in this window):"',
    "echo \"  kubectl -n argocd get secret argocd-initial-admin-secret -o jsonpath='{.data.password}' | base64 -d; echo\"",
    'echo',
    ''])
m = pat.search(s)
if not m:
    print("Step 7 was not found in the expected shape. Nothing changed. Send me the lines around 'Argo CD admin password'."); sys.exit(1)
shutil.copyfile(P, P + ".bak")
open(P, "w", encoding="utf-8", newline="").write(s[:m.start()] + new + s[m.end():])
print("Patched. Backup saved as", P + ".bak")
