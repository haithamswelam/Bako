# One bucket for operations data. Prefixes:
#   alb-logs/   written by the load balancer (turned on in the SLI/SLO step, not in this step)
#   db-dumps/   pg_dump copies of the database (added to the Stop in a later step)
# It lives here, not in the lab folder, because the lab is destroyed every night and the data must not be.

data "aws_elb_service_account" "main" {}   # the AWS account that delivers ALB logs in this region

resource "aws_s3_bucket" "ops" {
  bucket = local.bucket_name

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_public_access_block" "ops" {
  bucket                  = aws_s3_bucket.ops.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "ops" {
  bucket = aws_s3_bucket.ops.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# SSE-S3 (AES256) is the only encryption ALB access logs support.
resource "aws_s3_bucket_server_side_encryption_configuration" "ops" {
  bucket = aws_s3_bucket.ops.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Old data deletes itself, so the bucket never grows and the cost stays at cents.
resource "aws_s3_bucket_lifecycle_configuration" "ops" {
  bucket = aws_s3_bucket.ops.id

  rule {
    id     = "alb-logs-expire-after-90-days"
    status = "Enabled"

    filter {
      prefix = "alb-logs/"
    }

    expiration {
      days = 90
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  rule {
    id     = "db-dumps-expire-after-365-days"
    status = "Enabled"

    filter {
      prefix = "db-dumps/"
    }

    expiration {
      days = 365
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# Lets the load balancer write its logs, and only under alb-logs/ for this account.
resource "aws_s3_bucket_policy" "ops" {
  bucket     = aws_s3_bucket.ops.id
  depends_on = [aws_s3_bucket_public_access_block.ops]

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AlbWritesAccessLogs"
        Effect    = "Allow"
        Principal = { AWS = data.aws_elb_service_account.main.arn }
        Action    = "s3:PutObject"
        Resource  = "${aws_s3_bucket.ops.arn}/alb-logs/AWSLogs/${var.account_id}/*"
      }
    ]
  })
}
