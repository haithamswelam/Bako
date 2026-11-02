## DATABASE RESTORE: the agent (stage "Find saved database") passes the newest RDS snapshot here.
## "" (the default) = build an empty database, exactly as before.
variable "db_snapshot_identifier" {
  description = "RDS snapshot to build the database from. Empty = a new empty database."
  type        = string
  default     = ""
}

resource "random_password" "bako_db" {
  length  = 32
  special = false
}

resource "aws_secretsmanager_secret" "bako_db" {
  name                    = "bako/db-credentials"
  recovery_window_in_days = 0

  tags = {
    Name = "bako-db"
  }
}

resource "aws_secretsmanager_secret_version" "bako_db" {
  secret_id = aws_secretsmanager_secret.bako_db.id
  secret_string = jsonencode({
    username = "bako_admin"
    password = random_password.bako_db.result
  })
}

resource "aws_db_subnet_group" "bako" {
  name       = "bako-db-subnet-group"
  subnet_ids = [aws_subnet.private_a.id, aws_subnet.private_b.id]

  tags = {
    Name = "bako-db-subnet-group"
  }
}

resource "aws_security_group" "rds" {
  name        = "bako-rds-sg"
  description = "Allow Postgres access from the EKS cluster only"
  vpc_id      = aws_vpc.bako.id

  ingress {
    description     = "Postgres from EKS nodes"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_eks_cluster.bako.vpc_config[0].cluster_security_group_id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "bako-rds-sg"
  }
}

resource "aws_db_instance" "bako" {
  identifier     = "bako-db"
  engine         = "postgres"
  engine_version = "16.15"
  instance_class = "db.t4g.micro"

  allocated_storage = 20
  storage_type      = "gp3"

  ## Built FROM a snapshot when the agent found one, empty otherwise.
  snapshot_identifier = var.db_snapshot_identifier == "" ? null : var.db_snapshot_identifier

  ## A restore keeps the database name and the admin user stored in the snapshot, so they are only set for an empty database.
  ## The password is always set: on a restore AWS applies the new one, and the secret above holds the same value.
  db_name  = var.db_snapshot_identifier == "" ? "bako" : null
  username = var.db_snapshot_identifier == "" ? "bako_admin" : null
  password = random_password.bako_db.result

  db_subnet_group_name   = aws_db_subnet_group.bako.name
  vpc_security_group_ids = [aws_security_group.rds.id]

  publicly_accessible = false
  multi_az            = false
  skip_final_snapshot = true ## the agent saves its own snapshot before every destroy (stage "Save database")

  ## Keeps the engine at 16.15 so every snapshot can be restored by this same file.
  auto_minor_version_upgrade = false

  tags = {
    Name = "bako-db"
  }

  lifecycle {
    ## Changing the snapshot later must never replace a running database.
    ignore_changes = [snapshot_identifier]
  }
}

output "rds_endpoint" {
  value = aws_db_instance.bako.address
}

output "rds_secret_name" {
  value = aws_secretsmanager_secret.bako_db.name
}

output "rds_secret_arn" {
  value = aws_secretsmanager_secret.bako_db.arn
}
