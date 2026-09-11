output "alb_dns_name" {
  description = "Public DNS name of the load balancer. Frontend: http://<this>  Backend API: http://<this>:8080"
  value       = aws_lb.main.dns_name
}

output "backend_ecr_repository_url" {
  value = aws_ecr_repository.backend.repository_url
}

output "frontend_ecr_repository_url" {
  value = aws_ecr_repository.frontend.repository_url
}

output "github_actions_role_arn" {
  description = "Set this as the AWS_DEPLOY_ROLE_ARN repository variable in GitHub (Settings > Secrets and variables > Actions > Variables)."
  value       = aws_iam_role.github_actions_deploy.arn
}

output "ecs_cluster_name" {
  value = aws_ecs_cluster.main.name
}

output "backend_service_name" {
  value = aws_ecs_service.backend.name
}

output "frontend_service_name" {
  value = aws_ecs_service.frontend.name
}
