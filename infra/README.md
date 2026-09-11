# Infrastructure (ECS Fargate)

Terraform for running both containers (`Backend/`, `Frontend/`) on AWS: one
VPC, one Application Load Balancer (frontend on port 80, backend API on port
8080), one ECS cluster running both as Fargate services, one ECR repo per
image, and an IAM role GitHub Actions assumes via OIDC to deploy.

No NAT Gateway is used - tasks sit in public subnets with locked-down
security groups. This alone saves roughly $32/month, the single biggest
potential line item in this stack for a low-traffic project.

## One-time setup

Both the infrastructure and the app deploy entirely through GitHub Actions -
no Terraform or AWS CLI needed on your own machine. There's exactly one
unavoidable manual step first: establishing GitHub's initial trust into your
AWS account, since nothing can grant a workflow its first AWS credential
without a human doing something inside AWS itself.

1. Run [infra/bootstrap/bootstrap.sh](bootstrap/bootstrap.sh) once, in AWS
   CloudShell (browser-based, nothing to install locally) - see
   [infra/bootstrap/README.md](bootstrap/README.md) for the exact steps. It
   creates the GitHub OIDC provider, an IAM role scoped to this repo that
   Terraform runs will assume, and the S3 bucket + DynamoDB table Terraform's
   state lives in.

2. Set the three repo variables it prints (Settings → Secrets and variables →
   Actions → Variables tab):
   - `TF_APPLY_ROLE_ARN`
   - `TF_STATE_BUCKET`
   - `TF_STATE_LOCK_TABLE`

3. Create a GitHub Environment named `aws-infra` (Settings → Environments →
   New environment) and add yourself as a required reviewer. This is what
   makes the apply job pause for a manual approval click before it touches
   any real AWS resource - the same "someone watching it happen" property a
   local `terraform apply` had, just without needing a local `terraform apply`.

4. Push to `main` (or run the "Terraform (AWS infrastructure)" workflow
   manually from the Actions tab). The `plan` job runs first and posts what
   it would create to the job summary; the `apply` job then waits for your
   approval in the `aws-infra` environment before actually creating anything.
   This first apply creates everything except running containers - the ECS
   services will exist but have zero *healthy* tasks, because nothing has
   been pushed to the ECR repos yet. That's expected.

5. Open the finished apply job's "Show outputs" step and copy
   `github_actions_role_arn`. Set it as a repo variable:
   - `AWS_DEPLOY_ROLE_ARN` = that value.

6. Push to `main` again, or run the "Deploy to AWS" workflow manually. This
   builds both images, pushes them to ECR, and rolls both ECS services onto
   the new images - after it finishes, the services should have healthy
   tasks.

7. Visit `http://<alb_dns_name>` for the frontend (also in that same outputs
   step, or the AWS Console under EC2 → Load Balancers). The frontend's
   `Frontend/Dockerfile` `BACKEND_API_URL` default doesn't matter here -
   Terraform sets it directly in the task definition to
   `http://<alb_dns_name>:8080`.

## Day-to-day changes

**App code changes** (`Backend/`, `Frontend/`): push to `main`. The "Deploy to
AWS" workflow pushes new images tagged with the commit SHA (kept in ECR for
traceability/rollback) and `:latest`, then runs
`aws ecs update-service --force-new-deployment`, which pulls whatever
`:latest` currently points to.

**Infrastructure changes** (anything under `infra/`): open a PR. The
`terraform.yml` workflow's `plan` job runs automatically and shows what would
change in the job summary - review it there before merging. Merging to `main`
triggers `apply`, which pauses for your approval in the `aws-infra`
environment, then applies exactly the plan that was reviewed (not a fresh
re-plan, so nothing can drift between review and apply). Routine applies
won't touch running app deployments either way - the ECS service resources
have `lifecycle { ignore_changes = [task_definition] }` specifically so
CI-driven app deploys and infrastructure changes don't fight each other.

## Cost

Roughly, always-on: ALB ~$16-20/month plus usage, two 0.25 vCPU / 512 MB
Fargate tasks around $9-18/month combined, ECR storage and CloudWatch logs
negligible. No NAT Gateway. Ballpark **$25-40/month** while both services are
running continuously.

To stop paying between demos without deleting anything: scale both services
to zero. This keeps the same ALB DNS name for next time (the ALB itself
still incurs its base hourly charge, just not the Fargate compute). Run this
in AWS CloudShell (or anywhere with the AWS CLI configured) - it's an
operational action, not an infrastructure change, so it deliberately isn't
part of either GitHub Actions workflow:

```
aws ecs update-service --cluster transitticker-cluster --service transitticker-backend  --desired-count 0
aws ecs update-service --cluster transitticker-cluster --service transitticker-frontend --desired-count 0
```

Then set `--desired-count 1` again (or re-run the "Deploy to AWS" workflow,
which doesn't touch desired count) to bring it back. For truly zero cost
between demos, `terraform destroy` (run from CloudShell, with the same
backend-config flags as `init` above, or with a local `terraform` install -
there's no `destroy` step in either workflow, deliberately, since a one-click
path to tear down all the infrastructure isn't something worth having sit in
CI) removes everything including the ALB - just note the DNS name will be
different next time you apply, since there's no Route 53 hosted zone/custom
domain wired up here.

## Known gaps

- No custom domain or HTTPS - reachable over plain HTTP at the ALB's own AWS-
  assigned DNS name. Adding a domain would need a Route 53 hosted zone you
  own, plus an ACM certificate and HTTPS listeners.
- The backend's health check hits `/`, which returns 200 once Flask is up
  even if the GTFS feed itself failed to load - not a true readiness check
  until the backend gets a dedicated `/health` endpoint.
- The `transitticker-terraform` role (created in bootstrap) is fairly broad
  within the services it covers - full access to EC2/VPC, ELB, ECS, ECR, and
  CloudWatch Logs, since hand-scoping every individual action Terraform needs
  across those services would be fragile and likely to break `apply`
  partway through on some missing permission. IAM management is the one
  exception, scoped tightly to `transitticker-*` role names only. See
  [infra/bootstrap/README.md](bootstrap/README.md) for the full reasoning.
