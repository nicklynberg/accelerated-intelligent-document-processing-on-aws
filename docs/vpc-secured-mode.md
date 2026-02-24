# VPC Secured Mode Guide

This guide covers whats required for supporting the GenAI IDP solution in a VPC-secured environment for enhanced network isolation and security.

## Overview

VPC-secured mode enables the GenAI IDP solution to run within your private network infrastructure, providing:

- Network isolation for Lambda functions
- Private communication between AWS services through VPC endpoints
- Enhanced security through security group controls
- Compliance with organizational network security requirements

## Prerequisites

### VPC Infrastructure

You need an existing VPC with:
- Private subnets (minimum 2 for high availability)
- Public subnets with route to Internet Gateway (minimum 2 for high availability)
- NAT Gateway in each public subnet, with `0.0.0.0/0` routes in all private subnet route tables pointing to it. (Note while a single public subnet/NAT gateway can be used, this is not recommended for systems requiring high availability) 
- VPC endpoints for required AWS services (see below)
- Security groups for lambda and VPC endpoints (see below)

> **Why a NAT Gateway?** CodeBuild runs inside the VPC to build Docker images and needs internet access to pull base images and Python dependencies. The NAT Gateway provides outbound internet access from private subnets without exposing inbound access. A single NAT Gateway in one public subnet is sufficient — all private subnets can route through it.

#### Environments Without Internet Access

This solution assumes a NAT Gateway with an Internet Gateway is available. If your environment does not permit outbound internet access (e.g. air-gapped or fully isolated VPCs), the following external dependencies must be available from a private registry:

**Container images** — referenced in `Dockerfile.optimized` (project root):
- `ghcr.io/astral-sh/uv:0.9.6` — uv package manager
- `public.ecr.aws/lambda/python:3.12-arm64` — AWS Lambda Python base image

**BuildKit image** — pulled implicitly by `docker buildx create` in `patterns/pattern-2/buildspec.yml`:
- `moby/buildkit:buildx-stable-1`

**Python packages** — installed via `uv pip install` during the Docker build:
- All packages listed in each function's `requirements.txt`

To use a private registry, update the `FROM` lines in `Dockerfile.optimized` to point to your internal mirror and configure `patterns/pattern-2/buildspec.yml` to reference your private BuildKit image and Python package index.

### Required VPC Endpoints

> **Note:** VPC-Secured deployment is currently only supported for Pattern 2 (Textract + Bedrock).

#### Gateway Endpoints
- **S3**: `com.amazonaws.region.s3`
- **DynamoDB**: `com.amazonaws.region.dynamodb`

> **Note:** Gateway endpoints must be associated with the route tables of the private subnets that Lambda functions are deployed into. The [automated script](#automated-endpoint-creation) handles this automatically, but if creating endpoints manually, ensure you select the correct route tables during creation.

#### Interface Endpoints
- **SQS**: `com.amazonaws.region.sqs` — queue processing
- **Step Functions**: `com.amazonaws.region.states` — workflow orchestration
- **Lambda**: `com.amazonaws.region.lambda` — cross-function invocation
- **CloudWatch Logs**: `com.amazonaws.region.logs` — runtime logging (all functions)
- **CloudWatch Monitoring**: `com.amazonaws.region.monitoring` — metrics publishing
- **KMS**: `com.amazonaws.region.kms` — encryption/decryption
- **SSM**: `com.amazonaws.region.ssm` — Parameter Store lookups
- **STS**: `com.amazonaws.region.sts` — role assumption
- **Bedrock Runtime**: `com.amazonaws.region.bedrock-runtime` — classification, extraction, assessment, summarization, evaluation, rule validation
- **Textract**: `com.amazonaws.region.textract` — OCR processing
- **EventBridge**: `com.amazonaws.region.events` — workflow event routing
- **CodeBuild**: `com.amazonaws.region.codebuild` — Docker image builds
- **ECR API**: `com.amazonaws.region.ecr.api` — container registry
- **ECR Docker**: `com.amazonaws.region.ecr.dkr` — container image pulls
- **Glue**: `com.amazonaws.region.glue` — reporting catalog
- **Execute API**: `com.amazonaws.region.execute-api` — private API Gateway access

### Security Group Requirements

Create a security group for Lambda functions with the following rules:

**Outbound Rules:**
- Type: HTTPS
- Protocol: TCP
- Port: 443
- Destination: VPC Endpoint SG (or VPC CIDR)
- Description: Allow HTTPS traffic to AWS services via VPC endpoints

Create a security group for your VPCEs with the following rules:

**Inbound Rules:**
- Type: HTTPS
- Protocol: TCP
- Port: 443
- Source: Lambda SG
- Description: Allow HTTPS traffic from Lambda functions


### Automated Endpoint Creation

Use the provided script to create all required VPC endpoints:

```bash
./scripts/create_vpc_endpoints.sh \
  --vpc-id vpc-12345678 \
  --subnet-ids subnet-aaa,subnet-bbb \
  --security-group-id sg-12345678 \
  --region us-gov-west-1

# Preview without creating
./scripts/create_vpc_endpoints.sh \
  --vpc-id vpc-12345678 \
  --subnet-ids subnet-aaa,subnet-bbb \
  --security-group-id sg-12345678 \
  --region us-gov-west-1 \
  --dry-run
```

The script skips endpoints that already exist and reports a summary of created/skipped/failed.



## Validation

After deployment, verify VPC configuration:

1. **Lambda Functions**: Check that functions are deployed in the specified VPC and subnets
2. **Network Connectivity**: Test document processing to ensure all services can communicate through VPC endpoints

## Troubleshooting

### Common Issues

#### ECR Image Pull Failures
**Symptoms**: Lambda functions fail to start with image pull errors
**Cause**: Missing ECR VPC endpoints
**Solution**:
- Create both ECR API and ECR DKR VPC endpoints
- Verify security group allows HTTPS traffic to VPC endpoints

### Diagnostic Commands

Check VPC endpoint connectivity:
```bash
# Test from EC2 instance in same VPC/subnet
nslookup bedrock-runtime.region.amazonaws.com
curl -I https://bedrock-runtime.region.amazonaws.com
```

Verify security group rules:
```bash
aws ec2 describe-security-groups --group-ids sg-12345678
```

Check Lambda VPC configuration:
```bash
aws lambda get-function-configuration --function-name <function-name>
```