# The zone. prevent_destroy: deleting it would hand out NEW name servers when it is created again, and the
# delegation in Cloudflare would silently stop working. To really remove it, delete that lifecycle block first.
resource "aws_route53_zone" "bako" {
  name    = var.domain_name
  comment = "Delegated from Cloudflare (awsbako.site). Managed by infra-Bako-persistent."

  lifecycle {
    prevent_destroy = true
  }
}

# The certificate. Created only on the second apply (create_certificate = true).
resource "aws_acm_certificate" "bako" {
  count             = var.create_certificate ? 1 : 0
  domain_name       = var.domain_name
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

# The DNS record that proves to AWS that you control the name. It lives in the zone above.
resource "aws_route53_record" "cert_validation" {
  for_each = var.create_certificate ? {
    for dvo in aws_acm_certificate.bako[0].domain_validation_options : dvo.domain_name => {
      name   = dvo.resource_record_name
      type   = dvo.resource_record_type
      record = dvo.resource_record_value
    }
  } : {}

  allow_overwrite = true
  zone_id         = aws_route53_zone.bako.zone_id
  name            = each.value.name
  type            = each.value.type
  ttl             = 60
  records         = [each.value.record]
}

# Waits until AWS says the certificate is ISSUED. This only works once Cloudflare delegates the subdomain to Route 53.
resource "aws_acm_certificate_validation" "bako" {
  count                   = var.create_certificate ? 1 : 0
  certificate_arn         = aws_acm_certificate.bako[0].arn
  validation_record_fqdns = [for r in aws_route53_record.cert_validation : r.fqdn]

  timeouts {
    create = "20m"
  }
}
