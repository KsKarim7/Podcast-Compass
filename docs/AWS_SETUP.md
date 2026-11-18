# Deploying to AWS

Every push to `main` that passes the tests is built into an image, pushed to Amazon ECR and
started on one EC2 instance. This page is the one-time setup that makes that possible, what
it costs, and how to remove all of it.

## How a deploy works

1. The `deploy` job in `.github/workflows/ci.yml` runs only on a push to `main`, and only
   after the test, secret-scan and image jobs pass.
2. It asks GitHub for a short-lived OIDC token and exchanges it with AWS for temporary
   credentials of one IAM role. No AWS access keys are stored in GitHub.
3. It builds the image and pushes it to ECR, tagged with the commit SHA and `latest`.
4. It sends `deploy/ec2-deploy.sh` to the instance with SSM Run Command. The instance has no
   SSH key and no SSH port open; SSM works through an agent on the instance that makes
   outbound connections to AWS.
5. On the instance, the script pulls the image, reads the Gemini key from SSM Parameter
   Store, and replaces the running container. The key is never part of the command GitHub
   sends, so it is never in GitHub's logs or the SSM command history.
6. The job polls `http://<instance>/_stcore/health` and fails if it does not answer within
   150 seconds.

## Before you start

- An AWS account. Accounts created on or after 15 July 2025 start on the Free plan with
  USD 100 in credits (up to 100 more for completing set-up activities), lasting six months
  or until the credits run out ([EC2 Free Tier](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-free-tier-usage.html)).
- **Set a budget alert first.** In the Billing console, open **Budgets → Create budget →
  Use a template → Zero spend budget**, and enter your email.
- A second Gemini API key, from a separate Google AI Studio project. The request counter
  lives in each running copy of the app, so this deployment and Streamlit Community Cloud
  would otherwise both spend the same key's free daily quota without knowing about each
  other.
- Run everything below in **AWS CloudShell** (the terminal icon in the AWS console). It
  already has the AWS CLI and your credentials, so nothing needs installing.

## One-time setup

Set these once per CloudShell session. The region is Mumbai, the closest to Dhaka.

```bash
REGION=ap-south-1
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
REPO_NAME=podcast-compass
GITHUB_REPO=KsKarim7/Podcast-Compass
PARAM_NAME=/podcast-compass/gemini-api-key
```

### 1. Container registry

```bash
aws ecr create-repository --repository-name "$REPO_NAME" --region "$REGION"

# Keep the last five images so storage does not grow with every push.
aws ecr put-lifecycle-policy --repository-name "$REPO_NAME" --region "$REGION" \
  --lifecycle-policy-text '{"rules":[{"rulePriority":1,"description":"Keep the last 5 images","selection":{"tagStatus":"any","countType":"imageCountMoreThan","countNumber":5},"action":{"type":"expire"}}]}'
```

### 2. The Gemini key, encrypted

`read -s` takes the key without echoing it or saving it in the shell history.

```bash
read -rs GEMINI_KEY            # paste the key, press Enter
aws ssm put-parameter --region "$REGION" --name "$PARAM_NAME" \
  --type SecureString --value "$GEMINI_KEY"
unset GEMINI_KEY
```

A `SecureString` is encrypted with the account's default `aws/ssm` key. That key lets any
IAM principal in the account decrypt, so access is controlled by who is allowed
`ssm:GetParameter` on this parameter
([Parameter Store access](https://docs.aws.amazon.com/systems-manager/latest/userguide/sysman-paramstore-access.html)).

### 3. A role for the instance

The instance needs three things: to register with SSM, to pull our image, and to read the
key.

```bash
cat > ec2-trust.json <<'EOF'
{"Version":"2012-10-17","Statement":[{"Effect":"Allow",
  "Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}
EOF
aws iam create-role --role-name podcast-compass-ec2 \
  --assume-role-policy-document file://ec2-trust.json
aws iam attach-role-policy --role-name podcast-compass-ec2 \
  --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore

cat > ec2-permissions.json <<EOF
{"Version":"2012-10-17","Statement":[
  {"Sid":"EcrLogin","Effect":"Allow","Action":"ecr:GetAuthorizationToken","Resource":"*"},
  {"Sid":"PullOurImage","Effect":"Allow",
   "Action":["ecr:BatchGetImage","ecr:GetDownloadUrlForLayer","ecr:BatchCheckLayerAvailability"],
   "Resource":"arn:aws:ecr:$REGION:$ACCOUNT_ID:repository/$REPO_NAME"},
  {"Sid":"ReadTheKey","Effect":"Allow","Action":"ssm:GetParameter",
   "Resource":"arn:aws:ssm:$REGION:$ACCOUNT_ID:parameter$PARAM_NAME"}]}
EOF
aws iam put-role-policy --role-name podcast-compass-ec2 \
  --policy-name pull-image-and-read-key --policy-document file://ec2-permissions.json

aws iam create-instance-profile --instance-profile-name podcast-compass-ec2
aws iam add-role-to-instance-profile --instance-profile-name podcast-compass-ec2 \
  --role-name podcast-compass-ec2
```

`AmazonSSMManagedInstanceCore` is the AWS-managed policy for the SSM agent. Check what it
grants with the command below; if it includes `ssm:GetParameter` on every resource, the
`ReadTheKey` statement documents intent rather than adding the only permission, and a
tighter set-up would copy the managed policy and remove that line.

```bash
aws iam get-policy-version \
  --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore \
  --version-id $(aws iam get-policy --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore --query Policy.DefaultVersionId --output text)
```

### 4. A security group that allows HTTP only

No SSH rule, because nothing uses SSH. Outbound traffic stays open: the instance has to
reach ECR, SSM and the Gemini API.

```bash
VPC_ID=$(aws ec2 describe-vpcs --region "$REGION" --filters Name=is-default,Values=true \
  --query 'Vpcs[0].VpcId' --output text)
SG_ID=$(aws ec2 create-security-group --region "$REGION" --vpc-id "$VPC_ID" \
  --group-name podcast-compass-web --description "Podcast Compass, HTTP only" \
  --query GroupId --output text)
aws ec2 authorize-security-group-ingress --region "$REGION" --group-id "$SG_ID" \
  --protocol tcp --port 80 --cidr 0.0.0.0/0
```

### 5. The instance

Amazon Linux 2023 already has the SSM agent and the AWS CLI; the user-data script adds
Docker. `t3.micro` is on the Free plan's list of eligible types. There is no key pair,
so no one can SSH in. `HttpTokens=required` turns on the safer version of the instance
metadata service.

```bash
cat > user-data.sh <<'EOF'
#!/bin/bash
dnf install -y docker
systemctl enable --now docker
EOF

AMI_ID=$(aws ssm get-parameter --region "$REGION" \
  --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 \
  --query Parameter.Value --output text)

sleep 15   # a new instance profile takes a few seconds to become usable

INSTANCE_ID=$(aws ec2 run-instances --region "$REGION" \
  --image-id "$AMI_ID" --instance-type t3.micro \
  --iam-instance-profile Name=podcast-compass-ec2 \
  --security-group-ids "$SG_ID" \
  --user-data file://user-data.sh \
  --metadata-options HttpTokens=required \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=podcast-compass}]' \
  --query 'Instances[0].InstanceId' --output text)
echo "$INSTANCE_ID"
```

Wait two or three minutes, then check that the instance has registered with SSM. It should
print `Online`:

```bash
aws ssm describe-instance-information --region "$REGION" \
  --filters "Key=InstanceIds,Values=$INSTANCE_ID" \
  --query 'InstanceInformationList[0].PingStatus' --output text
```

### 6. Let GitHub Actions in, through OIDC

This tells AWS to trust tokens issued by GitHub Actions, then creates a role that only
workflows on this repository's `main` branch can assume.

```bash
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com
```

If this command asks for a thumbprint, your CLI is older than the change that made it
optional; add `--thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1`. AWS no longer
uses the thumbprint to validate GitHub's tokens, but older CLIs still require the field.

```bash
cat > github-trust.json <<EOF
{"Version":"2012-10-17","Statement":[{"Effect":"Allow",
  "Principal":{"Federated":"arn:aws:iam::$ACCOUNT_ID:oidc-provider/token.actions.githubusercontent.com"},
  "Action":"sts:AssumeRoleWithWebIdentity",
  "Condition":{"StringEquals":{
    "token.actions.githubusercontent.com:aud":"sts.amazonaws.com",
    "token.actions.githubusercontent.com:sub":"repo:$GITHUB_REPO:ref:refs/heads/main"}}}]}
EOF
aws iam create-role --role-name podcast-compass-github-deploy \
  --assume-role-policy-document file://github-trust.json

cat > github-permissions.json <<EOF
{"Version":"2012-10-17","Statement":[
  {"Sid":"EcrLogin","Effect":"Allow","Action":"ecr:GetAuthorizationToken","Resource":"*"},
  {"Sid":"PushOurImage","Effect":"Allow",
   "Action":["ecr:BatchCheckLayerAvailability","ecr:InitiateLayerUpload","ecr:UploadLayerPart",
             "ecr:CompleteLayerUpload","ecr:PutImage","ecr:BatchGetImage","ecr:GetDownloadUrlForLayer"],
   "Resource":"arn:aws:ecr:$REGION:$ACCOUNT_ID:repository/$REPO_NAME"},
  {"Sid":"RunTheDeployScriptOnOurInstance","Effect":"Allow","Action":"ssm:SendCommand",
   "Resource":["arn:aws:ssm:$REGION::document/AWS-RunShellScript",
               "arn:aws:ec2:$REGION:$ACCOUNT_ID:instance/$INSTANCE_ID"]},
  {"Sid":"ReadTheResult","Effect":"Allow","Action":"ssm:GetCommandInvocation","Resource":"*"},
  {"Sid":"FindThePublicAddress","Effect":"Allow","Action":"ec2:DescribeInstances","Resource":"*"}]}
EOF
aws iam put-role-policy --role-name podcast-compass-github-deploy \
  --policy-name deploy-podcast-compass --policy-document file://github-permissions.json

echo "AWS_ROLE_ARN=arn:aws:iam::$ACCOUNT_ID:role/podcast-compass-github-deploy"
echo "EC2_INSTANCE_ID=$INSTANCE_ID"
```

The `sub` condition is what limits the role to this repository's `main` branch. It is
compared exactly, including upper and lower case, so it must match the repository name as
GitHub writes it. If the deploy job fails with "Not authorized to perform
sts:AssumeRoleWithWebIdentity", check the case first.

`ssm:GetCommandInvocation` and `ec2:DescribeInstances` are read-only and do not support
limiting to one resource, which is why they use `*`.

### 7. Tell the workflow where things are

In GitHub, open **Settings → Secrets and variables → Actions → Variables** and add these
**variables** (not secrets — none of them is sensitive, and variables are visible in logs,
which helps debugging):

| Name | Value |
|---|---|
| `AWS_REGION` | `ap-south-1` |
| `AWS_ROLE_ARN` | printed at the end of step 6 |
| `ECR_REPOSITORY` | `podcast-compass` |
| `EC2_INSTANCE_ID` | printed at the end of step 6 |
| `GEMINI_KEY_PARAMETER` | `/podcast-compass/gemini-api-key` |

The deploy job is skipped while `AWS_ROLE_ARN` is unset, so pushes before this point do not
fail.

### 8. First deploy

Push to `main`, or re-run the latest CI run on `main` from the Actions tab. The deploy job
ends by printing the address it checked, for example `http://13.x.x.x`. Open that address
in a browser.

The address is the instance's public IPv4 address, which changes if the instance is
stopped and started. It does not change on a reboot or a redeploy.

## What it costs

These are list prices to check, not a bill I have seen. Confirm them in the
[AWS Pricing Calculator](https://calculator.aws/) for `ap-south-1` before launching.

| Item | Charge |
|---|---|
| EC2 `t3.micro`, running all month | On-demand hourly rate × ~730 hours `[UNVERIFIED for ap-south-1; check the calculator]` |
| Public IPv4 address | USD 0.005 per hour, about USD 3.60 a month, charged whether the instance is busy or idle |
| EBS root volume, 8 GB gp3 | Per GB-month rate `[UNVERIFIED; check the calculator]` |
| ECR storage, five images of a few hundred MB | Per GB-month rate `[UNVERIFIED; check the calculator]` |
| SSM Parameter Store, one standard parameter | No charge for standard parameters `[UNVERIFIED; check the pricing page]` |
| SSM Run Command, IAM, OIDC | No charge `[UNVERIFIED; check the pricing page]` |

On the Free plan these are taken from the credits rather than charged to your card, and the
account cannot spend beyond them. On a paid plan they are billed. Either way, the zero
spend budget emails you as soon as anything is charged.

**Stopping the instance** ends the EC2 hourly charge and releases its automatically
assigned public address, but the EBS volume is still charged while it exists. When you are
finished, remove everything as below.

## Removing everything

Run in CloudShell, with the variables from the top of this page set again. Order matters:
the instance must be gone before its security group and instance profile can be deleted.

```bash
INSTANCE_ID=<the instance id>

aws ec2 terminate-instances --region "$REGION" --instance-ids "$INSTANCE_ID"
aws ec2 wait instance-terminated --region "$REGION" --instance-ids "$INSTANCE_ID"

SG_ID=$(aws ec2 describe-security-groups --region "$REGION" \
  --filters Name=group-name,Values=podcast-compass-web --query 'SecurityGroups[0].GroupId' --output text)
aws ec2 delete-security-group --region "$REGION" --group-id "$SG_ID"

aws ecr delete-repository --region "$REGION" --repository-name "$REPO_NAME" --force
aws ssm delete-parameter --region "$REGION" --name "$PARAM_NAME"

aws iam remove-role-from-instance-profile --instance-profile-name podcast-compass-ec2 \
  --role-name podcast-compass-ec2
aws iam delete-instance-profile --instance-profile-name podcast-compass-ec2
aws iam delete-role-policy --role-name podcast-compass-ec2 --policy-name pull-image-and-read-key
aws iam detach-role-policy --role-name podcast-compass-ec2 \
  --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
aws iam delete-role --role-name podcast-compass-ec2

aws iam delete-role-policy --role-name podcast-compass-github-deploy \
  --policy-name deploy-podcast-compass
aws iam delete-role --role-name podcast-compass-github-deploy
aws iam delete-open-id-connect-provider --open-id-connect-provider-arn \
  "arn:aws:iam::$ACCOUNT_ID:oidc-provider/token.actions.githubusercontent.com"
```

Then delete `AWS_ROLE_ARN` from the repository variables, which turns the deploy job off
again.

## When something fails

| Symptom | Likely cause |
|---|---|
| `Not authorized to perform sts:AssumeRoleWithWebIdentity` | The `sub` in `github-trust.json` does not match the repository name exactly, or the run was not on `main` |
| `InvalidInstanceId` from `send-command` | The instance has not registered with SSM yet; check `PingStatus` from step 5 |
| Deploy script fails at `docker` | User data has not finished installing Docker; wait a minute and re-run the job |
| Deploy script fails at `get-parameter` | The parameter name in the repository variable differs from the one created in step 2 |
| Smoke test times out | The security group is missing the port 80 rule, or the container is crash-looping; run `docker logs podcast-compass` through **Systems Manager → Run Command** |
