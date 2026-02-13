# VPC Deployment Guide

This guide covers deploying the GenAI IDP solution in a VPC-secured environment for enhanced network isolation and security.

## Overview

VPC-secured deployment mode enables the GenAI IDP solution to run within your private network infrastructure, providing:

- Network isolation for Lambda functions and SageMaker endpoints
- Private communication between AWS services through VPC endpoints
- Enhanced security through security group controls
- Compliance with organizational network security requirements

## Prerequisites

### VPC Infrastructure

You need an existing VPC with:
- Private subnets (minimum 2 for high availability)
- Security group allowing HTTPS outbound traffic (port 443)
- VPC endpoints for required AWS services (see below)

### Required VPC Endpoints

#### Gateway Endpoints
- **S3**: `com.amazonaws.region.s3`
- **DynamoDB**: `com.amazonaws.region.dynamodb`

#### Interface Endpoints (All Patterns)
- **Lambda**: `com.amazonaws.region.lambda`
- **STS**: `com.amazonaws.region.sts`
- **SQS**: `com.amazonaws.region.sqs`
- **Step Functions**: `com.amazonaws.region.states`
- **KMS**: `com.amazonaws.region.kms`
- **CloudWatch Logs**: `com.amazonaws.region.logs`
- **CloudWatch Monitoring**: `com.amazonaws.region.monitoring`
- **SNS**: `com.amazonaws.region.sns`
- **EventBridge**: `com.amazonaws.region.events`
- **ECR API**: `com.amazonaws.region.ecr.api`
- **ECR DKR**: `com.amazonaws.region.ecr.dkr`
- **CodeBuild**: `com.amazonaws.region.codebuild`
- **Secrets Manager**: `com.amazonaws.region.secretsmanager`
- **SSM**: `com.amazonaws.region.ssm`
- **Bedrock Runtime**: `com.amazonaws.region.bedrock-runtime`
- **Bedrock**: `com.amazonaws.region.bedrock`
- **Athena**: `com.amazonaws.region.athena`
- **Glue**: `com.amazonaws.region.glue`

#### Pattern 1 Additional Endpoints
- **BDA Runtime**: `com.amazonaws.region.bedrock-data-automation-runtime`
- **BDA**: `com.amazonaws.region.bedrock-data-automation`

#### Pattern 2 Additional Endpoints
- **Textract**: `com.amazonaws.region.textract`

#### Pattern 3 Additional Endpoints
- **Textract**: `com.amazonaws.region.textract`
- **SageMaker Runtime**: `com.amazonaws.region.sagemaker.runtime`

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
# All patterns
./scripts/create_vpc_endpoints.sh \
  --vpc-id vpc-12345678 \
  --subnet-ids subnet-aaa,subnet-bbb \
  --security-group-id sg-12345678 \
  --region us-east-1

# Specific pattern(s) only
./scripts/create_vpc_endpoints.sh \
  --vpc-id vpc-12345678 \
  --subnet-ids subnet-aaa,subnet-bbb \
  --security-group-id sg-12345678 \
  --region us-east-1 \
  --pattern 1,2

# Preview without creating
./scripts/create_vpc_endpoints.sh \
  --vpc-id vpc-12345678 \
  --subnet-ids subnet-aaa,subnet-bbb \
  --security-group-id sg-12345678 \
  --region us-east-1 \
  --dry-run
```

The script skips endpoints that already exist and reports a summary of created/skipped/failed.

## Deployment

### Using CloudFormation Console

1. Deploy the stack using the standard deployment method
2. In the **Parameters** section, provide the VPC configuration:
   - **VpcId**: Your VPC ID (e.g., `vpc-12345678`)
   - **LambdaSecurityGroupId**: Security group ID for Lambda functions (e.g., `sg-12345678`)
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
2. **SageMaker Endpoint**: Verify the endpoint is configured with VPC settings (Pattern 3 only)
3. **Network Connectivity**: Test document processing to ensure all services can communicate through VPC endpoints

## Troubleshooting

### Common Issues

#### Lambda Function Timeout
**Symptoms**: Lambda functions timing out during execution
**Cause**: Missing or misconfigured VPC endpoints
**Solution**: 
- Verify all required VPC endpoints are created and accessible
- Check security group rules allow HTTPS outbound traffic
- Ensure DNS resolution is working in the VPC

#### SageMaker Endpoint Connection Issues (Pattern 3)
**Symptoms**: Classification function cannot invoke SageMaker endpoint
**Cause**: SageMaker endpoint not accessible from Lambda VPC
**Solution**:
- Verify SageMaker Runtime VPC endpoint exists
- Check security group allows communication between Lambda and SageMaker
- Ensure subnets have proper routing to VPC endpoints

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