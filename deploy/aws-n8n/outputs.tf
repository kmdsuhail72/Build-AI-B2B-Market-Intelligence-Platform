output "n8n_url" {
  description = "HTTPS URL for the n8n editor and webhook base URL."
  value       = "https://${aws_cloudfront_distribution.n8n.domain_name}"
}

output "ecs_cluster_name" {
  description = "ECS cluster containing the n8n service."
  value       = aws_ecs_cluster.n8n.name
}

output "ecs_service_name" {
  description = "ECS service name for deployment monitoring."
  value       = aws_ecs_service.n8n.name
}

output "database_endpoint" {
  description = "Private RDS endpoint; reachable only from the n8n task security group."
  value       = aws_db_instance.n8n.address
}
