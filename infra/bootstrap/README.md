# Bootstrap (one-time, not repeated per deploy)

This creates the minimum AWS identity/trust infrastructure GitHub Actions
needs before it can do anything else: the GitHub OIDC identity provider, an
IAM role scoped to this repo that Terraform runs will assume, and the S3
bucket + DynamoDB table Terraform's remote state lives in.

This is the one step that can't run *from* GitHub Actions - nothing can grant
a workflow run its first AWS credential without a human performing one action
inside the AWS account itself. Every OIDC-based CI setup has this same
one-time step; the goal is just to keep it small and run it without
installing anything locally.

## Run it

1. Push this repo to GitHub first (the script is meant to be fetched from
   there, though you can also just copy/paste it).
2. Open the [AWS Console](https://console.aws.amazon.com), click the
   CloudShell icon in the top navigation bar. This gives you a browser-based
   shell with the AWS CLI already installed and authenticated as your console
   session - nothing to configure locally.
3. In CloudShell:

   ```
   curl -O https://raw.githubusercontent.com/moldham713/TransitTicker/main/infra/bootstrap/bootstrap.sh
   bash bootstrap.sh
   ```

4. Copy the three values it prints at the end into GitHub repo variables
   (Settings → Secrets and variables → Actions → Variables tab):
   - `TF_APPLY_ROLE_ARN`
   - `TF_STATE_BUCKET`
   - `TF_STATE_LOCK_TABLE`

Then continue with the rest of the setup in [../README.md](../README.md).

## What it creates, and why it's scoped the way it is

- The role it creates (`transitticker-terraform`) gets AWS's managed
  `*FullAccess` policies for exactly the services this stack uses (EC2/VPC,
  ELB, ECS, ECR, CloudWatch Logs) - broad within each service, but nowhere
  near `AdministratorAccess`.
- None of those managed policies grant IAM permissions (AWS deliberately
  excludes IAM from them), so a separate inline policy grants IAM role
  management too - but only for role names starting with `transitticker-`,
  which is all this project ever creates. It can't touch any other IAM role
  in the account.
- Safe to re-run: every step checks whether its resource already exists
  first, so running it again after adding a new AWS service to the Terraform
  config (and updating the policy list) won't duplicate anything.
