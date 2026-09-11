terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # State lives in S3 with a DynamoDB lock table: Terraform runs from GitHub
  # Actions, where each workflow run is a fresh, throwaway runner, so a local
  # .tfstate file wouldn't survive between the plan job and the apply job,
  # let alone between separate runs. The bucket/table names are supplied at
  # init time via `-backend-config` (see .github/workflows/terraform.yml)
  # since the bucket name is chosen per-AWS-account during the one-time
  # bootstrap in infra/bootstrap/ (bucket names must be globally unique) and
  # so can't be a fixed literal here. Running `terraform init` by hand
  # instead, pass the same three flags:
  #   terraform init \
  #     -backend-config="bucket=<TF_STATE_BUCKET>" \
  #     -backend-config="key=transitticker/terraform.tfstate" \
  #     -backend-config="region=<aws region>" \
  #     -backend-config="dynamodb_table=<TF_STATE_LOCK_TABLE>"
  backend "s3" {
    encrypt = true
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project   = var.project_name
      ManagedBy = "terraform"
    }
  }
}
