# Self-hosted n8n for B2B lead generation and BI

This Terraform configuration deploys a standalone n8n instance in `ap-south-1`
on ECS/Fargate, with resource names prefixed `n8n-b2b-bi`. It is an orchestration
runtime for B2B lead-generation and business-intelligence workflows, not a CRM,
lead database, or analytics warehouse. It is separate from the Vidya app in
this repository.

An importable, manual-trigger demo is included at
[`workflows/b2b-lead-generation-demo.json`](./workflows/b2b-lead-generation-demo.json).
Import it from the n8n editor using **Overview → Import from File**, then select
**Run synthetic demo → Execute workflow**. It creates three fictional lead
items, calculates a transparent score preview, and marks each item for review.
It has no network, CRM, database, or email nodes and causes no external side
effects. The values are for demonstration only and must not be used for outreach.

## Architecture

- CloudFront provides an HTTPS URL without requiring a custom domain or ACM
  certificate. HTTP requests redirect to HTTPS.
- An internet-facing ALB accepts origin traffic only from CloudFront's managed
  origin-facing prefix list. A generated origin header prevents requests that
  bypass the distribution from reaching n8n.
- One Fargate task runs a pinned n8n image. Its ENI has a public IP for outbound
  image pulls and service access, but its security group accepts inbound traffic
  only from the ALB.
- RDS PostgreSQL and encrypted EFS storage are in private subnets. EFS preserves
  n8n local data across task replacements.
- Database and n8n encryption-key secrets are generated and stored in Secrets
  Manager. RDS backups, EFS backups, CloudWatch logs, and deletion protection
  are enabled.

This is a single n8n task, not a horizontally scaled or queue-mode deployment.
The sample defaults favor a small evaluation footprint; CloudFront, ALB, Fargate,
RDS, EFS, Secrets Manager, backups, and data transfer incur AWS charges. Check
current pricing for your region before applying.

## Workload guidance

- Use n8n to orchestrate approved source intake, normalization, deduplication,
  enrichment, human review, and delivery to an explicitly approved CRM or BI
  destination. Keep the system of record and reporting store in that destination,
  not in n8n's internal PostgreSQL database.
- Review each data source's terms and your organization's privacy requirements
  before using it. Do not collect sensitive personal information or automate
  access to sites that prohibit it. Preserve source URLs and retrieval dates so
  leads and market claims can be checked.
- Require human review before a workflow writes new leads or derived claims to
  the system of record. Prefer idempotent upserts and explicit duplicate keys so
  retries do not create duplicate prospects.
- Create separate least-privilege credentials for each source and destination.
  Add them to n8n's credential store after deployment; do not put tokens, lead
  records, or API keys in workflow names, URLs, source code, or execution logs.
- n8n execution history is operational state, not the durable business-data
  store. The stack prunes it after the configured `execution_data_max_age_hours`
  (336 hours by default). Review retention against debugging needs and data
  policy; avoid retaining unnecessary lead/contact payloads in workflow runs.
- The current deployment is a single n8n task and is not connected to the Vidya
  app or any CRM. Integration requires a separately reviewed API/credential and
  network path; the n8n database endpoint is not an integration interface.
- To try the same kind of synthetic records in the Vidya dashboard, sign in as
  an admin, open the CSV import control, and import
  [`data/lead-generation-demo.csv`](../../data/lead-generation-demo.csv). Its
  entries are explicitly unverified and use reserved `example.com` URLs; they
  are not real businesses or source evidence.

## Prerequisites

- Terraform 1.6 or newer
- AWS CLI configured with credentials for an account authorized to create VPC,
  ECS, IAM, RDS, EFS, Secrets Manager, CloudWatch, ALB, and CloudFront resources
- A pinned n8n version tag from the official `docker.n8n.io/n8nio/n8n` image

Do not put AWS credentials, database passwords, or encryption keys in Terraform
variables. Terraform generates the database password and encryption key and
stores them in Secrets Manager.

## Deploy

Run these commands from this directory. Copy the example values and replace
`n8n_image_tag` with an explicit version tag; floating tags such as `latest` and
`stable` are rejected.

```powershell
Copy-Item terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars and set n8n_image_tag to a pinned version.
terraform init
terraform validate
terraform plan -out n8n.tfplan
terraform apply n8n.tfplan
terraform output -raw n8n_url
```

Use an encrypted, access-controlled remote Terraform state backend before
deploying beyond evaluation. Terraform state contains generated secrets and
the CloudFront-to-ALB origin header, even though the passwords are also stored
in Secrets Manager. The local `.tfstate`, `.tfvars`, and plan files are ignored
by Git, but that is not encryption or a substitute for secure state storage.

When the CloudFront distribution is deployed, open the output URL and complete
n8n's owner-account setup promptly. Use a unique strong password and MFA where
available. The endpoint is internet-accessible; do not treat the CloudFront
hostname as access control.

## Operations and lifecycle

- Change n8n versions by setting a new explicit `n8n_image_tag`, reviewing
  `terraform plan`, and applying. Back up the database and verify the n8n
  upgrade path before upgrading.
- Monitor the ECS service and `/ecs/n8n` CloudWatch log group. RDS automated
  backups and EFS backups are enabled, but restoration has not been tested by
  this template.
- The database and ALB have deletion protection enabled by default. To destroy
  the stack, first set `deletion_protection = false`, apply that change, then
  destroy. RDS takes a final snapshot; EFS backups are retained by AWS Backup
  according to the account's backup defaults.
- Secrets Manager schedules secret deletion for seven days after Terraform
  destroy. Review recovery and retention settings before removing the stack.
- For a production deployment, add an organization-controlled domain and ACM
  certificate, multi-AZ database availability, alerting, tested restore
  procedures, and a reviewed workflow/execution data retention policy.
