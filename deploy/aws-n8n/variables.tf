variable "aws_region" {
  description = "AWS region for the n8n deployment."
  type        = string
  default     = "ap-south-1"
}

variable "name_prefix" {
  description = "Short, lowercase prefix used for AWS resource names."
  type        = string
  default     = "n8n-b2b-bi"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{1,14}$", var.name_prefix))
    error_message = "name_prefix must be 2-15 lowercase letters, digits, or hyphens and start with a letter."
  }
}

variable "n8n_image_tag" {
  description = "Pinned n8n container image version tag. Do not use latest for production."
  type        = string

  validation {
    condition = can(regex("^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$", var.n8n_image_tag)) && !contains(
      ["latest", "stable"],
      lower(var.n8n_image_tag)
    )
    error_message = "Set an explicit, non-floating n8n image tag."
  }
}

variable "vpc_cidr" {
  description = "IPv4 CIDR block for the dedicated VPC."
  type        = string
  default     = "10.40.0.0/16"
}

variable "database_instance_class" {
  description = "RDS PostgreSQL instance class."
  type        = string
  default     = "db.t4g.micro"
}

variable "postgres_engine_version" {
  description = "Exact PostgreSQL engine version supported by RDS in the selected region."
  type        = string
  default     = "16.4"
}

variable "backup_retention_days" {
  description = "Automated RDS backup retention in days."
  type        = number
  default     = 7

  validation {
    condition     = var.backup_retention_days >= 1 && var.backup_retention_days <= 35
    error_message = "backup_retention_days must be between 1 and 35."
  }
}

variable "database_multi_az" {
  description = "Enable a standby database in another Availability Zone (higher cost)."
  type        = bool
  default     = false
}

variable "deletion_protection" {
  description = "Protect the database and load balancer from accidental deletion."
  type        = bool
  default     = true
}

variable "task_cpu" {
  description = "Fargate task CPU units."
  type        = number
  default     = 1024
}

variable "task_memory" {
  description = "Fargate task memory in MiB."
  type        = number
  default     = 2048
}

variable "timezone" {
  description = "Timezone used by scheduled n8n workflows."
  type        = string
  default     = "UTC"
}

variable "execution_data_max_age_hours" {
  description = "Age in hours after which execution data is pruned."
  type        = number
  default     = 336

  validation {
    condition     = var.execution_data_max_age_hours >= 1
    error_message = "execution_data_max_age_hours must be at least 1."
  }
}

variable "log_retention_days" {
  description = "CloudWatch log retention in days."
  type        = number
  default     = 30
}

variable "cloudfront_price_class" {
  description = "CloudFront edge location set. PriceClass_100 is the lowest-cost option."
  type        = string
  default     = "PriceClass_100"

  validation {
    condition     = contains(["PriceClass_100", "PriceClass_200", "PriceClass_All"], var.cloudfront_price_class)
    error_message = "cloudfront_price_class must be PriceClass_100, PriceClass_200, or PriceClass_All."
  }
}
