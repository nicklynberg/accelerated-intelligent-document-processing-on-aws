# VPC Deployment Guide

This guide covers deploying the GenAI IDP solution in a VPC-secured environment for enhanced network isolation and security.

## Overview

VPC-secured deployment mode enables the GenAI IDP solution to run within your private network infrastructure, providing:

- Network isolation for Lambda functions
- Private communication between AWS services through VPC endpoints
- Enhanced security through security group controls
- Compliance with organizational network security requirements

## Prerequisites

### VPC Infrastructure

You need an existing VPC with:
- Private subnets (minimum 2 for high availability)
- At least one public subnet with an Internet Gateway route
- A NAT Gateway in the public subnet, with `0.0.0.0/0` routes in all private subnet route tables pointing to it
- Security group allowing HTTPS outbound traffic (port 443)
- VPC endpoints for required AWS services (see below)

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

> **Note:** VPC-only deployment is currently supported for Pattern 2 (Textract + Bedrock) only.

#### Gateway Endpoints (no additional cost)
- **S3**: `com.amazonaws.region.s3`
- **DynamoDB**: `com.amazonaws.region.dynamodb`

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

#### API Package Endpoints (GovCloud Deployment Options B and C)
- **Execute API**: `com.amazonaws.region.execute-api` — private API Gateway access

### Security Group Requirements

Create a security group with the following rules:

**Outbound Rules:**
- Type: HTTPS
- Protocol: TCP
- Port: 443
- Destination: 0.0.0.0/0
- Description: Allow HTTPS traffic to AWS services

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

## Deployment

### Using CloudFormation Console

1. Deploy the stack using the standard deployment method
2. In the **Parameters** section, provide the VPC configuration:
   - **VpcId**: Your VPC ID (e.g., `vpc-12345678`)
   - **LambdaSecurityGroupId**: Security group for VPC-enabled Lambda functions and CodeBuild projects (e.g., `sg-12345678`)
   - **PrivateSubnetIds**: Comma-separated list of private subnet IDs (e.g., `subnet-12345678,subnet-87654321`)

### Using AWS CLI

```bash
aws cloudformation create-stack \
  --stack-name GenAI-IDP-VPC \
  --template-url https://s3.us-west-2.amazonaws.com/aws-ml-blog-us-west-2/artifacts/genai-idp/idp-main.yaml \
  --parameters \
    ParameterKey=AdminEmail,ParameterValue=admin@example.com \
    ParameterKey=VpcId,ParameterValue=vpc-12345678 \
    ParameterKey=LambdaSecurityGroupId,ParameterValue=sg-12345678 \
    ParameterKey=PrivateSubnetIds,ParameterValue="subnet-12345678,subnet-87654321" \
  --capabilities CAPABILITY_IAM CAPABILITY_AUTO_EXPAND
```

### Using IDP CLI

```bash
# Deploy with VPC configuration
idp-cli deploy \
  --stack-name GenAI-IDP-VPC \
  --admin-email admin@example.com \
  --vpc-id vpc-12345678 \
  --lambda-security-group-id sg-12345678 \
  --private-subnet-ids subnet-12345678,subnet-87654321
```

## Validation

After deployment, verify VPC configuration:

1. **Lambda Functions**: Check that functions are deployed in the specified VPC and subnets
2. **Network Connectivity**: Test document processing to ensure all services can communicate through VPC endpoints

## Troubleshooting

### Common Issues

#### Lambda Function Timeout
**Symptoms**: Lambda functions timing out during execution
**Cause**: Missing or misconfigured VPC endpoints
**Solution**: 
- Verify all required VPC endpoints are created and accessible
- Check security group rules allow HTTPS outbound traffic
- Ensure DNS resolution is working in the VPC

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

### Performance Considerations

- VPC deployment may have slightly higher latency due to network routing
- Ensure VPC endpoints are in the same Availability Zones as your subnets
- Monitor CloudWatch metrics for any performance degradation
- Consider using VPC endpoint policies to restrict access if needed

## Security Best Practices

1. **Least Privilege**: Configure security groups with minimal required access
2. **VPC Endpoint Policies**: Implement resource-based policies on VPC endpoints
3. **Network ACLs**: Use network ACLs for additional subnet-level security
4. **Monitoring**: Enable VPC Flow Logs to monitor network traffic
5. **Regular Audits**: Periodically review VPC configuration and access patterns