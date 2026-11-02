# infra-Bako-persistent: the things that must SURVIVE the nightly destroy of the lab.
#   - the DNS zone for bako.awsbako.site   (its name servers must never change, or the Cloudflare delegation breaks)
#   - the HTTPS certificate                (free, validated once through DNS)
#   - one S3 bucket                        (ALB access logs for the SLI/SLO work, and database dump copies)
# The agent's START and STOP never touch this folder. Run terraform here by hand, rarely (see README-https-step2.txt).
# Its state file stays on this computer (terraform.tfstate in this folder): keep a copy somewhere safe.

terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0, < 7.0"
    }
  }
}

provider "aws" {
  region = var.region
  # Empty = use whatever profile is already active in your shell (AWS_PROFILE), the same as the lab folder.
  profile = var.aws_profile == "" ? null : var.aws_profile
  # Terraform refuses to run against any other account. This is the guard against the wrong AWS login.
  allowed_account_ids = [var.account_id]

  default_tags {
    tags = {
      Project = "bako"
      Layer   = "persistent"
    }
  }
}

locals {
  bucket_name = var.bucket_name != "" ? var.bucket_name : "bako-ops-${var.account_id}-${var.region}"
}
