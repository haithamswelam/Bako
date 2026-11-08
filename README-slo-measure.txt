BAKO - request numbers, measure-only version (SLO chapter, step 1)
==================================================================

What you get
  1. The load balancer writes one log line per request into your permanent bucket (K8s/ingress.yaml, one annotation).
  2. agent/env/sli.py turns each finished UTC day into one small file: s3://bako-ops-.../sli-daily/YYYY-MM-DD.json
     Counts and timings only. No address query strings, no IPs, no bodies, nothing about expenses.
  3. START has a new step "Request numbers" (inside the Argo CD box of the Flow tab, after the DNS check).
     It saves yesterday and any missing day of the last 7. It is never red: if it fails it is skipped and the lab goes on.
  4. A new SLO tab in the dashboard: counted requests, success rate, failed or slow, p95, a chart per day, a table, and the
     list of the failed or slow requests of the latest day. NO target and NO budget yet (agreed: measure about 2 weeks first).
     The tab reads S3, so it works while the lab is stopped. "Refresh" also rolls up today (partial).

What counts
  counted = the request reached a pod, or the load balancer itself answered 5xx.
  NOT counted: redirects from port 80 and bot hits the load balancer answers itself (404). Shown as "Not counted".
  good = status below 500 and under 500 ms.  bad = a 5xx, or 500 ms or slower.  4xx = good.
  Days are UTC days (Cairo is 2 hours ahead).

Files (copy to the same paths in the repo)
  K8s/ingress.yaml          one new annotation (access logs on). Check your own copy: only that block is new.
  agent/env/sli.py          NEW
  agent/env/agent.py        imports sli, new step_sli(), preflight check, run_tail calls it after the DNS check
  agent/env/flow_tab.py     new box "Request numbers", added to the re-runnable steps
  agent/env/dashboard.py    new SLO tab, label for the new step
  Before copying agent.py, dashboard.py and flow_tab.py, run:  git status   (they must be clean on main, same as last time).

Order
  1. Copy the files, then: git switch -c feature/slo-measure ; git add K8s/ingress.yaml agent/env ; commit ; push ; PR ; merge.
  2. Run the offline check:  python agent/env/sli.py selftest      (must print: sli selftest: all checks passed)
  3. START the lab as usual. Open the app on your phone for a few minutes.
  4. Wait about 10 minutes, then check the logs exist:
       aws s3 ls s3://bako-ops-483272865934-eu-north-1/alb-logs/ --recursive --profile bakolab | tail -5
  5. Dashboard, SLO tab, press Refresh. Today's row appears with "(so far)".
  6. Next day's START saves yesterday's numbers by itself (look for the "Request numbers" box in the Flow tab).

Needs: your AWS login (bakolab) must be allowed to read and write the bako-ops bucket (it does for the account owner login).
If the first Refresh says it cannot read: send me the text it shows.
