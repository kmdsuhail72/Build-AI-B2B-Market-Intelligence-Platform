terraform {
  required_version = ">= 1.6.0, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project   = var.name_prefix
      ManagedBy = "Terraform"
    }
  }
}

data "aws_availability_zones" "available" {
  state = "available"
}

data "aws_ec2_managed_prefix_list" "cloudfront_origin_facing" {
  name = "com.amazonaws.global.cloudfront.origin-facing"
}

locals {
  name               = var.name_prefix
  availability_zones = slice(data.aws_availability_zones.available.names, 0, 2)
  public_subnets     = [for subnet in aws_subnet.public : subnet.id]
  private_subnets    = [for subnet in aws_subnet.private : subnet.id]
}

resource "random_password" "database" {
  length  = 40
  special = false
}

resource "random_password" "origin_header" {
  length  = 40
  special = false
}

resource "random_password" "encryption_key" {
  length  = 32
  special = false
}

resource "random_id" "final_snapshot" {
  byte_length = 4
}

resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr
  enable_dns_hostnames = true
  enable_dns_support   = true
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id
}

resource "aws_subnet" "public" {
  count                   = 2
  vpc_id                  = aws_vpc.main.id
  availability_zone       = local.availability_zones[count.index]
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, count.index)
  map_public_ip_on_launch = true
}

resource "aws_subnet" "private" {
  count             = 2
  vpc_id            = aws_vpc.main.id
  availability_zone = local.availability_zones[count.index]
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, count.index + 10)
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }
}

resource "aws_route_table_association" "public" {
  count          = 2
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.main.id
}

resource "aws_route_table_association" "private" {
  count          = 2
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

resource "aws_security_group" "load_balancer" {
  name_prefix = "${local.name}-alb-"
  description = "Allow CloudFront origin-facing addresses to reach the ALB"
  vpc_id      = aws_vpc.main.id

  ingress {
    description     = "CloudFront origin connections"
    from_port       = 80
    to_port         = 80
    protocol        = "tcp"
    prefix_list_ids = [data.aws_ec2_managed_prefix_list.cloudfront_origin_facing.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "n8n" {
  name_prefix = "${local.name}-task-"
  description = "n8n tasks accept web traffic only from the ALB"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port       = 5678
    to_port         = 5678
    protocol        = "tcp"
    security_groups = [aws_security_group.load_balancer.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "database" {
  name_prefix = "${local.name}-db-"
  description = "PostgreSQL is reachable only from n8n tasks"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.n8n.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "efs" {
  name_prefix = "${local.name}-efs-"
  description = "EFS is reachable only from n8n tasks"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port       = 2049
    to_port         = 2049
    protocol        = "tcp"
    security_groups = [aws_security_group.n8n.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_lb" "n8n" {
  name               = substr("${local.name}-alb", 0, 32)
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.load_balancer.id]
  subnets            = local.public_subnets

  enable_deletion_protection = var.deletion_protection
}

resource "aws_lb_target_group" "n8n" {
  name        = substr("${local.name}-tg", 0, 32)
  port        = 5678
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.main.id

  health_check {
    enabled             = true
    path                = "/healthz"
    protocol            = "HTTP"
    matcher             = "200-399"
    interval            = 30
    timeout             = 10
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.n8n.arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = "fixed-response"

    fixed_response {
      content_type = "text/plain"
      message_body = "Forbidden"
      status_code  = "403"
    }
  }
}

resource "aws_lb_listener_rule" "cloudfront" {
  listener_arn = aws_lb_listener.http.arn
  priority     = 10

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.n8n.arn
  }

  condition {
    http_header {
      http_header_name = "X-Origin-Verify"
      values           = [random_password.origin_header.result]
    }
  }
}

resource "aws_efs_file_system" "n8n" {
  encrypted        = true
  creation_token   = local.name
  performance_mode = "generalPurpose"
  throughput_mode  = "bursting"

  lifecycle_policy {
    transition_to_ia = "AFTER_30_DAYS"
  }

}

resource "aws_efs_backup_policy" "n8n" {
  file_system_id = aws_efs_file_system.n8n.id

  backup_policy {
    status = "ENABLED"
  }
}

resource "aws_efs_access_point" "n8n" {
  file_system_id = aws_efs_file_system.n8n.id

  posix_user {
    uid = 1000
    gid = 1000
  }

  root_directory {
    path = "/n8n"

    creation_info {
      owner_uid   = 1000
      owner_gid   = 1000
      permissions = "0750"
    }
  }
}

resource "aws_efs_mount_target" "n8n" {
  count           = 2
  file_system_id  = aws_efs_file_system.n8n.id
  subnet_id       = aws_subnet.private[count.index].id
  security_groups = [aws_security_group.efs.id]
}

resource "aws_db_subnet_group" "n8n" {
  name       = "${local.name}-db"
  subnet_ids = local.private_subnets
}

resource "aws_secretsmanager_secret" "database_password" {
  name                    = "${local.name}/database-password"
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "database_password" {
  secret_id     = aws_secretsmanager_secret.database_password.id
  secret_string = random_password.database.result
}

resource "aws_secretsmanager_secret" "encryption_key" {
  name                    = "${local.name}/encryption-key"
  recovery_window_in_days = 7
}

resource "aws_secretsmanager_secret_version" "encryption_key" {
  secret_id     = aws_secretsmanager_secret.encryption_key.id
  secret_string = random_password.encryption_key.result
}

resource "aws_db_instance" "n8n" {
  identifier                      = "${local.name}-db"
  engine                          = "postgres"
  engine_version                  = var.postgres_engine_version
  instance_class                  = var.database_instance_class
  allocated_storage               = 20
  max_allocated_storage           = 100
  storage_type                    = "gp3"
  storage_encrypted               = true
  db_name                         = "n8n"
  username                        = "n8n"
  password                        = random_password.database.result
  port                            = 5432
  db_subnet_group_name            = aws_db_subnet_group.n8n.name
  vpc_security_group_ids          = [aws_security_group.database.id]
  publicly_accessible             = false
  backup_retention_period         = var.backup_retention_days
  copy_tags_to_snapshot           = true
  deletion_protection             = var.deletion_protection
  skip_final_snapshot             = false
  final_snapshot_identifier       = "${local.name}-final-${random_id.final_snapshot.hex}"
  auto_minor_version_upgrade      = true
  multi_az                        = var.database_multi_az
  apply_immediately               = false
  enabled_cloudwatch_logs_exports = ["postgresql", "upgrade"]
}

resource "aws_cloudwatch_log_group" "n8n" {
  name              = "/ecs/${local.name}"
  retention_in_days = var.log_retention_days
}

resource "aws_ecs_cluster" "n8n" {
  name = local.name
}

resource "aws_iam_role" "ecs_execution" {
  name = "${local.name}-ecs-execution"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
      Action = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_execution" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "read_secrets" {
  name = "${local.name}-read-secrets"
  role = aws_iam_role.ecs_execution.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["secretsmanager:GetSecretValue"]
      Resource = [
        aws_secretsmanager_secret.database_password.arn,
        aws_secretsmanager_secret.encryption_key.arn
      ]
    }]
  })
}

resource "aws_ecs_task_definition" "n8n" {
  family                   = local.name
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.task_cpu
  memory                   = var.task_memory
  execution_role_arn       = aws_iam_role.ecs_execution.arn

  volume {
    name = "n8n-data"

    efs_volume_configuration {
      file_system_id     = aws_efs_file_system.n8n.id
      transit_encryption = "ENABLED"

      authorization_config {
        access_point_id = aws_efs_access_point.n8n.id
        iam             = "DISABLED"
      }
    }
  }

  container_definitions = jsonencode([{
    name      = "n8n"
    image     = "docker.n8n.io/n8nio/n8n:${var.n8n_image_tag}"
    essential = true
    portMappings = [{
      containerPort = 5678
      hostPort      = 5678
      protocol      = "tcp"
    }]
    environment = [
      { name = "DB_TYPE", value = "postgresdb" },
      { name = "DB_POSTGRESDB_HOST", value = aws_db_instance.n8n.address },
      { name = "DB_POSTGRESDB_PORT", value = "5432" },
      { name = "DB_POSTGRESDB_DATABASE", value = "n8n" },
      { name = "DB_POSTGRESDB_USER", value = "n8n" },
      { name = "N8N_HOST", value = aws_cloudfront_distribution.n8n.domain_name },
      { name = "N8N_PROTOCOL", value = "https" },
      { name = "N8N_PORT", value = "5678" },
      { name = "N8N_PROXY_HOPS", value = "2" },
      { name = "N8N_SECURE_COOKIE", value = "true" },
      { name = "N8N_ENFORCE_SETTINGS_FILE_PERMISSIONS", value = "true" },
      { name = "N8N_EDITOR_BASE_URL", value = "https://${aws_cloudfront_distribution.n8n.domain_name}/" },
      { name = "WEBHOOK_URL", value = "https://${aws_cloudfront_distribution.n8n.domain_name}/" },
      { name = "GENERIC_TIMEZONE", value = var.timezone },
      { name = "EXECUTIONS_DATA_PRUNE", value = "true" },
      { name = "EXECUTIONS_DATA_MAX_AGE", value = tostring(var.execution_data_max_age_hours) }
    ]
    secrets = [
      {
        name      = "DB_POSTGRESDB_PASSWORD"
        valueFrom = aws_secretsmanager_secret.database_password.arn
      },
      {
        name      = "N8N_ENCRYPTION_KEY"
        valueFrom = aws_secretsmanager_secret.encryption_key.arn
      }
    ]
    mountPoints = [{
      sourceVolume  = "n8n-data"
      containerPath = "/home/node/.n8n"
      readOnly      = false
    }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.n8n.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "n8n"
      }
    }
  }])
}

resource "aws_ecs_service" "n8n" {
  name                              = local.name
  cluster                           = aws_ecs_cluster.n8n.id
  task_definition                   = aws_ecs_task_definition.n8n.arn
  desired_count                     = 1
  launch_type                       = "FARGATE"
  platform_version                  = "LATEST"
  health_check_grace_period_seconds = 120

  network_configuration {
    subnets          = local.public_subnets
    security_groups  = [aws_security_group.n8n.id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.n8n.arn
    container_name   = "n8n"
    container_port   = 5678
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  depends_on = [
    aws_lb_listener_rule.cloudfront,
    aws_iam_role_policy_attachment.ecs_execution,
    aws_iam_role_policy.read_secrets,
    aws_efs_mount_target.n8n
  ]
}

resource "aws_cloudfront_distribution" "n8n" {
  enabled         = true
  is_ipv6_enabled = true
  price_class     = var.cloudfront_price_class
  comment         = "HTTPS entry point for ${local.name}"

  origin {
    domain_name = aws_lb.n8n.dns_name
    origin_id   = "n8n-alb-origin"

    custom_header {
      name  = "X-Origin-Verify"
      value = random_password.origin_header.result
    }

    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "http-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }

  default_cache_behavior {
    target_origin_id         = "n8n-alb-origin"
    viewer_protocol_policy   = "redirect-to-https"
    allowed_methods          = ["DELETE", "GET", "HEAD", "OPTIONS", "PATCH", "POST", "PUT"]
    cached_methods           = ["GET", "HEAD", "OPTIONS"]
    compress                 = true
    cache_policy_id          = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad"
    origin_request_policy_id = "216adef6-5c7f-47e4-b989-5492eafa07d3"
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
    minimum_protocol_version       = "TLSv1.2_2021"
  }
}
