resource "aws_ecr_repository" "backend" {
  name                 = "bako-backend"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name = "bako-backend-ecr"
  }
}

resource "aws_ecr_repository" "frontend" {
  name                 = "bako-frontend"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Name = "bako-frontend-ecr"
  }
}

output "backend_ecr_repository_url" {
  value = aws_ecr_repository.backend.repository_url
}

output "frontend_ecr_repository_url" {
  value = aws_ecr_repository.frontend.repository_url
}