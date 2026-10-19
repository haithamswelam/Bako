# Environment Agent — Charter

## Goal
Bring the Bako lab up at the start of a session and confirm it is ready;
take it down at the end and confirm nothing billable is left running in AWS.

## What it does
- START: check AWS account -> terraform plan -> show me the plan
       -> wait for my typed approval -> terraform apply (creates everything incl. empty ECR)
       -> trigger image build (gh workflow run) -> bootstrap-cluster.sh
       -> wait for the bot PR that bumps the image tags -> ASK ME to merge it
       -> wait for Argo CD sync -> run the READY checks -> report "READY".
- STOP:  check AWS account -> terraform plan -destroy (FULL, everything incl. ECR)
       -> show me the plan -> wait for my typed approval -> destroy
       -> run the NOTHING RUNNING checks -> report "NOTHING RUNNING".

## Allowed
- Run terraform, bootstrap-cluster.sh, and read-only aws / kubectl commands.
- Write its own trace and log files under agent/env/reports/ (never committed to git).
- Trigger the CI build with gh workflow run, and read PR/workflow status with read-only gh commands.

## Never allowed
- Apply or destroy anything without my typed approval.
- Apply or destroy a plan that I haven't seen.
- Edit .tf files, workflows, or this charter.
- Run more than one apply or destroy at the same time.
- Run against any AWS account other than 483272865934 (checked first by code; abort if it differs).
- Treat silence as approval. No answer within 10 minutes = do nothing and remind me.
- Push to main, edit any file in git, or merge anything except the one bot PR from this START, and only after I say so.

## Limits
- Max model calls per run: 15
- Max LLM cost per run: $0.50.
- If a step fails: try at most 2 fixes, then stop and report.
- A "fix" may only be: re-run bootstrap, re-trigger the build once, or re-run a read-only check.
  Anything destructive (for example deleting a secret) needs my approval.
- Max time per run: 60 minutes for START, 30 minutes for STOP, then stop and tell me.

## Human gate
- I approve by typing "approved" (apply) or "destroy bako" (destroy).
  Anything else, or silence, means no.
- I approve the merge of the bot PR (START) by saying so in chat.
- No approval needed: build trigger, bootstrap, and read-only checks.

## "Ready" means
- Cluster context ends in 483272865934:cluster/bako-eks
- Argo CD app bako: Synced and Healthy
- Backend and frontend pods Running, 0 restarts
- Image tags running in the cluster exist in ECR

## "Nothing running" means (all must be zero)
EKS clusters, EC2 instances, NAT gateways, Elastic IPs, RDS instances,
load balancers, EBS volumes, ECR repositories, Secrets Manager secrets.

## Assumptions (if any is false, stop and report)
- ci.yml can be started manually (workflow_dispatch) and builds both images.
- The CI role can call ecr:DescribeImages.
- The ECR repositories have force_delete = true, so destroy works with images inside.
- The Bako secret has recovery_window_in_days = 0, so it can be recreated the next day.
- Terraform state is intact and reachable.
- AWS profile bakolab is logged in to account 483272865934.

## Report style
- Final report: 5 lines maximum. Say PASS or FAIL, the key numbers, and anything that needs my attention.
- Only state what the tool results show. Never claim an action or a file that has no tool result.
- Never repeat raw tool output. It is already in the trace.