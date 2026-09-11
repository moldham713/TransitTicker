# The GitHub OIDC identity provider itself is NOT managed here - it's created
# once, out-of-band, by infra/bootstrap/bootstrap.sh. That script is also what
# creates the broader "transitticker-terraform" role GitHub Actions uses to
# run *this* Terraform config in the first place (a role Terraform obviously
# can't create for itself before it has any AWS access at all). This file
# only manages the narrower role the app-deploy workflow uses afterward, and
# references the bootstrap-created OIDC provider by its well-known,
# deterministic ARN rather than by resource reference.
data "aws_caller_identity" "current" {}

locals {
  github_oidc_provider_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:oidc-provider/token.actions.githubusercontent.com"
}

resource "aws_iam_role" "github_actions_deploy" {
  name = "${var.project_name}-github-actions-deploy"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Federated = local.github_oidc_provider_arn }
      Action    = "sts:AssumeRoleWithWebIdentity"
      Condition = {
        StringEquals = {
          "token.actions.githubusercontent.com:aud" = "sts.amazonaws.com"
        }
        StringLike = {
          # Allows any branch/tag/PR in this repo to assume the role. Tighten
          # to "repo:${var.github_repo}:ref:refs/heads/main" if you only ever
          # want pushes to main able to deploy.
          "token.actions.githubusercontent.com:sub" = "repo:${var.github_repo}:*"
        }
      }
    }]
  })
}

# Deliberately narrow: push images to these two specific ECR repos, and roll
# these two specific ECS services. Not AdministratorAccess, not a wildcard
# ecs:* / ecr:* grant.
resource "aws_iam_role_policy" "github_actions_deploy" {
  name = "${var.project_name}-github-actions-deploy"
  role = aws_iam_role.github_actions_deploy.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "ECRAuth"
        Effect   = "Allow"
        Action   = "ecr:GetAuthorizationToken"
        Resource = "*" # this specific action does not support resource-level restriction
      },
      {
        Sid    = "ECRPush"
        Effect = "Allow"
        Action = [
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage",
          "ecr:PutImage",
          "ecr:InitiateLayerUpload",
          "ecr:UploadLayerPart",
          "ecr:CompleteLayerUpload",
        ]
        Resource = [
          aws_ecr_repository.backend.arn,
          aws_ecr_repository.frontend.arn,
        ]
      },
      {
        Sid    = "ECSDeploy"
        Effect = "Allow"
        Action = [
          "ecs:UpdateService",
          "ecs:DescribeServices",
        ]
        Resource = [
          aws_ecs_service.backend.id,
          aws_ecs_service.frontend.id,
        ]
      },
    ]
  })
}
