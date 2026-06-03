Here are your 4 daily updates plus everything you need to create the Jira task.

Jira Task

Title: Private VPC Infrastructure for Keycloak Secret Rotation — No-Internet Sandbox Environment
Description: Design and implement a fully private AWS environment replicating company-grade infrastructure where Keycloak runs inside a VPC with zero internet access. All service communication happens through VPC endpoints, Docker images are served from a private ECR registry, and EC2 access is handled via SSM Session Manager — no SSH, no public IPs, no bastion host.


Day 1 — Architecture Design & VPC Foundation

Designed private VPC architecture (10.0.0.0/16) with no Internet Gateway — replicating a real company sandbox environment with zero public internet exposure
Provisioned two private subnets across eu-north-1a and eu-north-1b for EC2 and Lambda high-availability placement
Created private route tables with no default internet route — all traffic stays inside AWS network
Mapped out all required VPC Interface Endpoints (secretsmanager, lambda, ecr.api, ecr.dkr, ssm, ssmmessages, ec2messages) and Gateway Endpoint (s3) needed for fully air-gapped operation
Defined endpoint security groups allowing only inbound HTTPS 443 from within VPC CIDR


Day 2 — Private Container Registry & EC2 Setup

Set up ECR private repository as a replacement for quay.io — EC2 has no internet so all Docker images must be pre-staged internally
Configured ECR lifecycle policy to auto-expire old images keeping storage costs controlled
Pulled Keycloak image on local machine, tagged and pushed to ECR via docker push — establishing the internal image promotion workflow
Provisioned EC2 in private subnet with no public IP and no SSH key pair — access exclusively via SSM Session Manager
Attached IAM instance profile with scoped ECR pull permissions (ecr:GetAuthorizationToken, ecr:BatchGetImage) and AmazonSSMManagedInstanceCore policy for SSM access
Wrote user_data bootstrap script to authenticate to ECR using instance role, pull Keycloak image, start container, and auto-disable SSL on master realm — fully hands-free, no manual SSH required


Day 3 — Lambda Inside VPC & Rotation Logic

Placed Lambda rotation function inside the private VPC so it can reach Keycloak's private IP directly on port 8080
Configured Lambda vpc_config with both private subnets and a dedicated security group
Added ec2:CreateNetworkInterface / DescribeNetworkInterfaces / DeleteNetworkInterface IAM permissions — required for Lambda to attach to VPC networking, commonly missed and causes silent deploy failures
Updated rotation logic to read KEYCLOAK_URL from the secret payload (private IP) rather than env var — makes IP changes require only a secret update, not a Lambda redeploy
Fixed core bug from public setup: set_secret now does full GET + PUT to Keycloak instead of partial PUT — partial PUT was silently resetting serviceAccountsEnabled to false on every rotation causing 403s on testSecret
Added structured logging across all 4 rotation steps (createSecret, setSecret, testSecret, finishSecret) for CloudWatch visibility


Day 4 — Integration Testing, Hardening & Documentation

Validated full end-to-end rotation flow inside private VPC — all 4 Lambda steps completing cleanly with no internet egress
Confirmed SSM port forwarding (AWS-StartPortForwardingSession) as the access pattern for Keycloak admin console — no public IP, no SSH tunnel needed
Tested ECR image pull via VPC endpoint from within private subnet — verified ecr.dkr + s3 gateway endpoint combination works correctly for full image layer retrieval
Documented terraform apply -target=aws_ecr_repository.keycloak as required first step before full apply — prevents EC2 boot race condition where user_data fires before image exists in ECR
Wrote complete infrastructure-as-code in standard single terraform/ folder structure — vpc.tf, ecr.tf, ec2.tf, secrets.tf, lambda.tf — one terraform apply deploys everything
Added troubleshooting runbook covering stuck rotation recovery, ECR pull failures, SSM connectivity issues, and VPC endpoint DNS resolution