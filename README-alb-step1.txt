ALB STEP 1  (plain HTTP, TEST DATA ONLY)
=======================================
Unzip at the ROOT of your Bako repo (the folder that holds infra-Bako-eks, K8s and agent). Folders merge; say yes to overwrite.

Files and where they go
  infra-Bako-eks/variables.tf                                        NEW   (if you already have a variables.tf, merge the 3 variables into it)
  infra-Bako-eks/vpc.tf                                              CHANGED  subnet tags only (public: role/elb, private: role/internal-elb, plus the cluster tag)
  infra-Bako-eks/eks.tf                                              CHANGED  one line: name = var.cluster_name  (same value, so no change in AWS)
  infra-Bako-eks/alb-controller.tf                                   NEW   IAM role + policy for the controller (IRSA, same pattern as eso-irsa.tf)
  infra-Bako-eks/iam-policies/aws-load-balancer-controller-v3.6.2.json   NEW   official policy of controller v3.6.2
  K8s/ingress.yaml                                                   NEW   the Ingress: one ALB in the public subnets, everything to the frontend
  bootstrap-cluster.sh                                               CHANGED  installs the controller (step 3b) before Argo CD; settings can come from the environment
  agent/env/pre-destroy-alb.sh                                       NEW   releases the ALB before the cluster is destroyed
  agent/env/agent.py                                                 CHANGED  the destroy tool runs pre-destroy-alb.sh first and REFUSES to destroy if the ALB is still there

What to expect from "terraform plan"
  4 subnets: update in place (tags).   1 IAM policy, 1 IAM role, 1 role attachment: add.   EKS cluster: no change.
  Nothing is destroyed or replaced. If the plan shows anything else, stop and send it to me.

If the lab is already running
  1. terraform apply
  2. bash bootstrap-cluster.sh        (safe to run again; it installs the controller)
  3. Push K8s/ingress.yaml with the Bako window (new branch, then Review and merge). Argo CD creates the ALB.
  4. kubectl get ingress bako -n bako      (the ADDRESS column fills in after 2 to 3 minutes)
  5. Open http://<that address> on your phone. TEST DATA ONLY: this is plain HTTP.
If the lab is stopped: nothing to do now. The next START creates the role (terraform apply), installs the controller (bootstrap) and Argo CD creates the ALB.

Stopping
  Always stop with the Bako STOP flow. It now removes the ALB first.
  A manual "terraform destroy" would leave the ALB running and billing, and block the VPC delete.
  If you must destroy by hand, run  bash agent/env/pre-destroy-alb.sh  first and only continue when it says "Safe to destroy".

Line endings: these files use Unix (LF) endings. Git may warn about LF/CRLF on Windows. That is harmless. bootstrap-cluster.sh and pre-destroy-alb.sh must stay LF.
