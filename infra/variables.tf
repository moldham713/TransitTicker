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

variable "google_client_id" {
  description = <<-EOT
    OAuth 2.0 Client ID from Google Cloud Console (APIs & Services >
    Credentials > Create Credentials > OAuth client ID > Web application).
    Not a secret - it's meant to be embedded in frontend JS - but it has no
    sensible default since it's specific to whoever's Google Cloud project
    this points at. Set it in terraform.tfvars or pass
    -var="google_client_id=..." at apply time. Add both the frontend URL
    (http://localhost:5001 for local dev) and the ALB's URL (see the
    alb_dns_name output, port 80) as Authorized JavaScript origins on the
    credential itself, or the Google sign-in button will fail with an
    origin-mismatch error.
  EOT
  type        = string
}
