variable "region" {
  type        = string
  default     = "eu-north-1"
  description = "Same region as the lab. The certificate must be in the region of the load balancer."
}

variable "aws_profile" {
  type        = string
  default     = ""
  description = "AWS CLI profile to use. Leave empty to use the profile already active in your shell."
}

variable "account_id" {
  type        = string
  default     = "483272865934"
  description = "The only AWS account this folder may run in."
}

variable "domain_name" {
  type        = string
  default     = "bako.awsbako.site"
  description = "The subdomain AWS manages. Cloudflare delegates it to Route 53 with 4 NS records."
}

variable "create_certificate" {
  type        = bool
  default     = true
  description = "false on the first apply (creates the zone). true on the second apply, AFTER the 4 NS records exist in Cloudflare, because the certificate is validated through that DNS."
}

variable "bucket_name" {
  type        = string
  default     = ""
  description = "Leave empty to get bako-ops-<account>-<region>."
}
