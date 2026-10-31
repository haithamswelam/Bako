variable "cluster_name" {
  description = "Name of the EKS cluster. The subnets are tagged with it so the load balancer controller can find them."
  type        = string
  default     = "bako-eks"
}

variable "alb_controller_namespace" {
  description = "Kubernetes namespace where the AWS Load Balancer Controller runs."
  type        = string
  default     = "kube-system"
}

variable "alb_controller_service_account" {
  description = "Kubernetes service account used by the AWS Load Balancer Controller (the IAM role trusts exactly this one)."
  type        = string
  default     = "aws-load-balancer-controller"
}
