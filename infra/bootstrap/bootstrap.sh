#!/usr/bin/env bash
# One-time bootstrap: creates just enough AWS identity/trust infrastructure
# for GitHub Actions to take over everything else on its own - the Terraform
# state backend, and every AWS resource in infra/*.tf, including future
# changes to them.
#
# This is the one step that genuinely cannot be done from GitHub Actions:
# nothing can grant a GitHub Actions run its first AWS credential without a
# human performing one action inside the AWS account itself. Every CI/OIDC
# setup has this same one-time step - the point is that it's small, and after
# it, nothing else requires local tooling.
#
# Run this in AWS CloudShell (console.aws.amazon.com -> the terminal icon in
# the top nav bar) so nothing needs installing on your own machine - it comes
# with the AWS CLI pre-installed and already authenticated as your console
# user. A local shell with the AWS CLI configured works too, if you prefer.
#
# Safe to re-run: every step checks whether its resource already exists
# before creating it.
set -euo pipefail

# ---- Adjust if needed - must match infra/variables.tf ----
GITHUB_REPO="moldham713/TransitTicker"
AWS_REGION="us-east-1"
TF_ROLE_NAME="transitticker-terraform"
LOCK_TABLE="transitticker-tf-locks"
# ------------------------------------------------------------

ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
# Bucket names are global across all of AWS, so this can't be a fixed literal
# - the account id suffix is what makes it unique to you.
STATE_BUCKET="transitticker-tfstate-${ACCOUNT_ID}"
OIDC_PROVIDER_ARN="arn:aws:iam::${ACCOUNT_ID}:oidc-provider/token.actions.githubusercontent.com"

echo "== GitHub OIDC identity provider =="
if aws iam get-open-id-connect-provider --open-id-connect-provider-arn "$OIDC_PROVIDER_ARN" >/dev/null 2>&1; then
  echo "Already exists, skipping."
else
  aws iam create-open-id-connect-provider \
    --url "https://token.actions.githubusercontent.com" \
    --client-id-list "sts.amazonaws.com" \
    --thumbprint-list "6938fd4d98bab03faadb97b34396831e3780aea"
fi

echo "== Terraform state S3 bucket ($STATE_BUCKET) =="
if aws s3api head-bucket --bucket "$STATE_BUCKET" >/dev/null 2>&1; then
  echo "Already exists, skipping."
else
  if [ "$AWS_REGION" = "us-east-1" ]; then
    aws s3api create-bucket --bucket "$STATE_BUCKET" --region "$AWS_REGION"
  else
    aws s3api create-bucket --bucket "$STATE_BUCKET" --region "$AWS_REGION" \
      --create-bucket-configuration LocationConstraint="$AWS_REGION"
  fi
  aws s3api put-bucket-versioning --bucket "$STATE_BUCKET" \
    --versioning-configuration Status=Enabled
  aws s3api put-bucket-encryption --bucket "$STATE_BUCKET" \
    --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
  aws s3api put-public-access-block --bucket "$STATE_BUCKET" \
    --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
fi

echo "== Terraform state lock DynamoDB table ($LOCK_TABLE) =="
if aws dynamodb describe-table --table-name "$LOCK_TABLE" >/dev/null 2>&1; then
  echo "Already exists, skipping."
else
  aws dynamodb create-table \
    --table-name "$LOCK_TABLE" \
    --attribute-definitions AttributeName=LockID,AttributeType=S \
    --key-schema AttributeName=LockID,KeyType=HASH \
    --billing-mode PAY_PER_REQUEST
fi

echo "== $TF_ROLE_NAME IAM role =="
TRUST_POLICY=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "Federated": "${OIDC_PROVIDER_ARN}" },
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": { "token.actions.githubusercontent.com:aud": "sts.amazonaws.com" },
      "StringLike": { "token.actions.githubusercontent.com:sub": "repo:${GITHUB_REPO}:*" }
    }
  }]
}
EOF
)

if aws iam get-role --role-name "$TF_ROLE_NAME" >/dev/null 2>&1; then
  echo "Role already exists, updating trust policy."
  aws iam update-assume-role-policy --role-name "$TF_ROLE_NAME" --policy-document "$TRUST_POLICY"
else
  aws iam create-role --role-name "$TF_ROLE_NAME" \
    --assume-role-policy-document "$TRUST_POLICY" \
    --description "Assumed by GitHub Actions (via OIDC) to run terraform plan/apply for TransitTicker"
fi

echo "== Attaching AWS managed policies, scoped per-service (not AdministratorAccess) =="
for POLICY_ARN in \
  "arn:aws:iam::aws:policy/AmazonEC2FullAccess" \
  "arn:aws:iam::aws:policy/ElasticLoadBalancingFullAccess" \
  "arn:aws:iam::aws:policy/AmazonECS_FullAccess" \
  "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryFullAccess" \
  "arn:aws:iam::aws:policy/CloudWatchLogsFullAccess"
do
  aws iam attach-role-policy --role-name "$TF_ROLE_NAME" --policy-arn "$POLICY_ARN"
done

# None of the FullAccess policies above cover IAM itself (by design - AWS
# excludes IAM from them). Terraform needs to create/manage a couple of IAM
# roles (the ECS task execution role, and the app-deploy role from the
# previous step), so this grants exactly that: create/manage/pass-role, but
# ONLY for role names prefixed "transitticker-", not IAM in general.
echo "== Attaching scoped inline policy for IAM role management (transitticker-* only) =="
IAM_SCOPE_POLICY=$(cat <<EOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Sid": "ManageProjectRolesOnly",
    "Effect": "Allow",
    "Action": [
      "iam:CreateRole", "iam:DeleteRole", "iam:GetRole", "iam:TagRole", "iam:UntagRole",
      "iam:PutRolePolicy", "iam:DeleteRolePolicy", "iam:GetRolePolicy", "iam:ListRolePolicies",
      "iam:AttachRolePolicy", "iam:DetachRolePolicy", "iam:ListAttachedRolePolicies",
      "iam:PassRole"
    ],
    "Resource": "arn:aws:iam::${ACCOUNT_ID}:role/transitticker-*"
  }]
}
EOF
)
aws iam put-role-policy --role-name "$TF_ROLE_NAME" \
  --policy-name "transitticker-scoped-iam" \
  --policy-document "$IAM_SCOPE_POLICY"

TF_ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${TF_ROLE_NAME}"

echo
echo "Done. Set these as GitHub repository variables"
echo "(Settings > Secrets and variables > Actions > Variables tab):"
echo
echo "  TF_APPLY_ROLE_ARN   = ${TF_ROLE_ARN}"
echo "  TF_STATE_BUCKET     = ${STATE_BUCKET}"
echo "  TF_STATE_LOCK_TABLE = ${LOCK_TABLE}"
echo
echo "Then see infra/README.md for the rest of the setup (a GitHub Environment"
echo "for apply approvals, and the first plan/apply run)."
