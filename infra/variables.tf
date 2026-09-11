variable "aws_region" {
  description = "AWS region to deploy into."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Short name used to prefix/tag every resource this stack creates."
  type        = string
  default     = "transitticker"
}

variable "github_repo" {
  description = "GitHub repo allowed to assume the deploy role via OIDC, as \"owner/repo\"."
  type        = string
  default     = "moldham713/TransitTicker"
}

variable "backend_image_tag" {
  description = <<-EOT
    Image tag baked into the backend task definition at `terraform apply` time.
    Day-to-day deploys do NOT change this and re-apply - the GitHub Actions
    workflow pushes new images tagged `:latest` (and `:<git-sha>` for
    traceability/manual rollback) and rolls the service with
    `aws ecs update-service --force-new-deployment`, which re-pulls whatever
    `:latest` now points to. This variable only matters for the very first
    apply (see infra/README.md) or if you want to pin the service to a
    specific SHA tag on purpose.
  EOT
  type    = string
  default = "latest"
}

variable "frontend_image_tag" {
  description = "Same purpose as backend_image_tag, for the frontend service."
  type        = string
  default     = "latest"
}

variable "backend_cpu" {
  description = "Fargate task vCPU units for the backend (256 = 0.25 vCPU)."
  type        = number
  default     = 256
}

variable "backend_memory" {
  description = "Fargate task memory (MB) for the backend."
  type        = number
  default     = 512
}

variable "frontend_cpu" {
  description = "Fargate task vCPU units for the frontend (256 = 0.25 vCPU)."
  type        = number
  default     = 256
}

variable "frontend_memory" {
  description = "Fargate task memory (MB) for the frontend."
  type        = number
  default     = 512
}
