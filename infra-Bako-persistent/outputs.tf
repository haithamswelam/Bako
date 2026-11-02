output "name_servers" {
  description = "Add these 4 as NS records named 'bako' in Cloudflare (Step B of the README)."
  value       = aws_route53_zone.bako.name_servers
}

output "zone_id" {
  value = aws_route53_zone.bako.zone_id
}

output "certificate_arn" {
  description = "Paste this into K8s/ingress.yaml (annotation certificate-arn)."
  value       = try(aws_acm_certificate_validation.bako[0].certificate_arn, "not created yet: apply again with -var create_certificate=true after Cloudflare delegates the subdomain")
}

output "bucket_name" {
  value = aws_s3_bucket.ops.bucket
}
