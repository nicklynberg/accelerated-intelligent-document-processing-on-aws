---
title: "GovCloud Deployment Guide"
---

# GovCloud Deployment Guide

## Overview

The GenAI IDP Accelerator supports GovCloud deployment to AWS GovCloud regions through a specialized template generation script. This solution addresses two key GovCloud requirements:

1. **ARN Partition Compatibility**: All ARN references use `arn:${AWS::Partition}:` instead of `arn:aws:` to work in both commercial and GovCloud regions
2. **Service Compatibility**: Removes services not available in GovCloud (AppSync, CloudFront, WAF, Cognito UI components)

For details on what services are removed vs. retained, see [GovCloud Architecture](./govcloud-architecture.md).

## Deployment Packages

The GovCloud template supports four deployment configurations. Choose the one that matches your use case:

| | Vanilla | Headless API | Headless API + VPC Secured Mode | Headless API + VPC Secured Mode + Bastion |
|---|---|---|---|---|
| **Use Case** | Simplest deployment; manual document processing via S3 upload or IDP CLI | Programmatic API access; only headless resources in VPC | Production workloads with all compute in VPC for full network isolation | Development/testing with private API access from local machine via bastion tunnel |
| **Access Methods** | S3 direct upload, IDP CLI, SDK | All vanilla methods + REST API (`/jobs` endpoints) | Same as Headless API | All API methods + local access via SSM tunnel |
| **Networking** | No VPC required | Private API Gateway + headless Lambdas in VPC; core Lambdas outside VPC | All Lambda functions + Private API Gateway in VPC | Same as VPC Secured Mode, plus an EC2 bastion host for tunneling |
| **Authentication** | IAM only | Cognito client credentials (OAuth2 bearer tokens) | Same as Headless API | Same as Headless API |
| **Key Parameters** | None | `EnableHeadless=true` | Same as Headless API + `DeployInVPC=true` | Same as VPC Secured Mode + `DeployBastionHost=true` |
| **VPC Parameters** | None | `VpcId`, `PrivateSubnetIds`, `ApiGatewayVpcEndpointId`, `LambdaSecurityGroupId` | Same as Headless API | Same as Headless API |
| **Bastion Parameters** | None | None | None | `BastionHostSubnetId`, `BastionHostSecurityGroupId` |
| **When to Choose** | You have your own integration layer, or are evaluating the solution | You need API access but don't require full network isolation for core processing | You need API access with all compute isolated in your VPC | You need to call the API from your laptop during development |

### What Gets Deployed in Each Package

**Vanilla (all packages include this):**
- Core document processing engine (unified pattern with pipeline mode)
- Step Functions workflows
- S3 buckets, DynamoDB tables, SQS queues, EventBridge rules
- CloudWatch dashboards, alarms, SNS notifications
- KMS encryption keys

**Headless API adds:**
- Private API Gateway with `/jobs` endpoints (POST, GET)
- Cognito User Pool with machine-to-machine client credentials
- VPC-enabled Lambda functions for API handling and batch pre-processing

**VPC Secured Mode adds:**
- Deploys all core document processing Lambda functions into the VPC

**Bastion adds:**
- EC2 instance in a public subnet for SSM Session Manager tunneling
- No inbound security group rules required — access is via AWS SSM

## Prerequisites

You need the following installed on your computer:

1. bash shell (Linux, MacOS, Windows-WSL)
2. aws (AWS CLI)
3. [sam (AWS SAM)](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html)
4. python 3.12 (required to generate templates)
5. Node.js >=22.12.0
6. npm >=10.0.0
7. A local Docker daemon
8. Python packages for publish.py. You are encouraged to configure a virtual environment for dependency management, ie. `python -m venv .venv`. Activate the environment (`. .venv/bin/activate`) and then install dependencies via `pip install boto3 rich PyYAML botocore setuptools docker ruff build`

## Step 1: Generate GovCloud Template

Generate the GovCloud-compatible template — this runs the standard build process first to create all Lambda functions and artifacts, then creates a stripped-down version for GovCloud:

```bash
# Note: The Python script will create an S3 bucket automatically by concatenating
# the provided bucket name and region, ie. my-govcloud-bucket-us-gov-west-1.
# You can change the bucket base name as desired.
# Files will be placed under [my-prefix] prefix within the generated bucket.

# Build for GovCloud region
python scripts/generate_govcloud_template.py my-bucket-govcloud my-prefix us-gov-west-1

# Or build for commercial region first (for testing)
python scripts/generate_govcloud_template.py my-bucket my-prefix us-east-1
```

## Step 2: Deploy

Deploy the generated template using the AWS CloudFormation console or the AWS CLI. Choose the CLI command that matches your desired [deployment package](#deployment-packages).

> **Note:** The `--s3-bucket` value must be the full bucket name created in Step 1 (`{bucket-basename}-{region}`, e.g. `my-bucket-govcloud-us-gov-west-1`).

### Option A: Vanilla (no API, no VPC)

```bash
aws cloudformation deploy \
  --template-file .aws-sam/idp-govcloud.yaml \
  --stack-name {your-stack-name} \
  --region us-gov-west-1 \
  --s3-bucket {s3-bucket-govcloud} \
  --s3-prefix {your-s3-prefix} \
  --capabilities CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND 
```

With this deployment, interact with the system via:
- Direct S3 upload to the input bucket
- IDP CLI (`idp-cli`)
- SDK integration

### Option B: Headless API


```bash
aws cloudformation deploy \
  --template-file .aws-sam/idp-govcloud.yaml \
  --stack-name {your-stack-name} \
  --region us-gov-west-1 \
  --s3-bucket {s3-bucket-govcloud} \
  --s3-prefix {your-s3-prefix} \
  --capabilities CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND \
  --parameter-overrides \
    EnableHeadless=true \
    VpcId=vpc-xxxxxxxxx \
    PrivateSubnetIds=subnet-xxxxx,subnet-xxxxx,subnet-xxxxx \
    ApiGatewayVpcEndpointId=vpce-xxxxxxxxx \
    LambdaSecurityGroupId=sg-xxxxxxxxx \
    ApiStageName=beta
```

This enables the `/jobs` REST API as a Private API Gateway accessible only from within your VPC. Core document processing Lambdas remain outside the VPC. See [Batch Jobs REST API](./govcloud-batch-api.md) for usage.

### Option C: Headless API + VPC Secured Mode (full isolation)
Make sure that all prerequisites defined [here](./vpc-secured-mode.md) are met before deploying into a managed VPC.  

```bash
aws cloudformation deploy \
  --template-file .aws-sam/idp-govcloud.yaml \
  --stack-name {your-stack-name} \
  --region us-gov-west-1 \
  --s3-bucket {s3-bucket-govcloud} \
  --s3-prefix {your-s3-prefix} \
  --capabilities CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND \
  --parameter-overrides \
    EnableHeadless=true \
    DeployInVPC=true \
    VpcId=vpc-xxxxxxxxx \
    PrivateSubnetIds=subnet-xxxxx,subnet-xxxxx,subnet-xxxxx \
    ApiGatewayVpcEndpointId=vpce-xxxxxxxxx \
    LambdaSecurityGroupId=sg-xxxxxxxxx \
    ApiStageName=beta
```

This deploys all Lambda functions (headless and core processing) into the VPC for full network isolation. See [Batch Jobs REST API](./govcloud-batch-api.md) for usage.

### Option D: Headless API + VPC Secured Mode + Bastion (development)
Make sure that all prerequisites defined [here](./vpc-secured-mode.md) are met before deploying into a managed VPC.

```bash
aws cloudformation deploy \
  --template-file .aws-sam/idp-govcloud.yaml \
  --stack-name {your-stack-name} \
  --region us-gov-west-1 \
  --s3-bucket {s3-bucket-govcloud} \
  --s3-prefix {your-s3-prefix} \
  --capabilities CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND \
  --parameter-overrides \
    EnableHeadless=true \
    DeployInVPC=true \
    VpcId=vpc-xxxxxxxxx \
    PrivateSubnetIds=subnet-xxxxx,subnet-xxxxx,subnet-xxxxx \
    ApiGatewayVpcEndpointId=vpce-xxxxxxxxx \
    LambdaSecurityGroupId=sg-xxxxxxxxx \
    ApiStageName=beta \
    DeployBastionHost=true \
    BastionHostSubnetId=subnet-xxxxxxxxx \
    BastionHostSecurityGroupId=sg-xxxxxxxxx
```

This adds a bastion host for local API access via SSM tunnel. See [Private API Access via Bastion Tunnel](./govcloud-batch-api.md#private-api-access-via-bastion-tunnel) for setup.

## Step 3: Verify Your Deployment

After the stack reaches `CREATE_COMPLETE`, verify it's working.

### All Deployments

```bash
# Confirm stack status
aws cloudformation describe-stacks \
  --stack-name {your-stack-name} \
  --region us-gov-west-1 \
  --query 'Stacks[0].StackStatus'

# Get key outputs
aws cloudformation describe-stacks \
  --stack-name {your-stack-name} \
  --region us-gov-west-1 \
  --query 'Stacks[0].Outputs'
```

### Test Document Processing (Vanilla / All Options)

Upload a sample document and monitor progress:

```bash
# Upload to input bucket (get bucket name from stack outputs: S3InputBucketName)
aws s3 cp my-document.pdf s3://{input-bucket}/my-document.pdf

# Monitor processing status
./scripts/lookup_file_status.sh my-document.pdf {your-stack-name}
```

Or navigate to the Step Functions console using the `StateMachineConsoleURL` from stack outputs to visually monitor workflow progress.

### Test API (Options B, C, and D)

For Option D (Bastion), start the SSM tunnel first — see [Private API Access via Bastion Tunnel](./govcloud-batch-api.md#private-api-access-via-bastion-tunnel).

```bash
# Generate a bearer token
TOKEN=$(./scripts/get_api_token.sh {your-stack-name})

# Create a job (get endpoint URL from stack outputs: ApiGatewayEndpoint)
curl -X POST {api-endpoint}/jobs \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"fileName": "my-documents.zip"}'

# Check job status (use jobId from the POST response)
# Note: will return PENDING_UPLOAD status until the ZIP file is uploaded
curl {api-endpoint}/jobs/{job-id} \
  -H "Authorization: Bearer $TOKEN"
```

See [Batch Jobs REST API](./govcloud-batch-api.md) for the full API reference including file upload and response formats.

## Parameter Reference

### Headless API Parameters (required for Options B, C, and D)

| Parameter | Description |
|---|---|
| `EnableHeadless` | Set to `true` to deploy the Jobs REST API Gateway and supporting Lambda functions |
| `ApiStageName` | API Gateway deployment stage name (default: `beta`) |

### VPC Secured Mode Parameter (required for Options C and D)

| Parameter | Description |
|---|---|
| `DeployInVPC` | Set to `true` to deploy all core document processing Lambda functions into the VPC |

### VPC Parameters (required for Options B, C, and D)

| Parameter | Description |
|---|---|
| `VpcId` | VPC for Lambda functions |
| `PrivateSubnetIds` | Comma-separated private subnet IDs (minimum 2 for HA) |
| `ApiGatewayVpcEndpointId` | VPC endpoint for private API Gateway access |
| `LambdaSecurityGroupId` | Security group for VPC-enabled Lambda functions |

### Bastion Parameters (Option D only)

| Parameter | Description |
|---|---|
| `DeployBastionHost` | Set to `true` to deploy the bastion EC2 instance |
| `BastionHostSubnetId` | A **public** subnet for the bastion host |
| `BastionHostSecurityGroupId` | Security group for the bastion host (no special inbound rules required — the tunnel operates via AWS SSM Session Manager) |

## Migration from Commercial AWS

If migrating an existing deployment:

1. **Export Configuration**: Download all configuration from existing stack
2. **Export Data**: Copy any baseline or reference data
3. **Deploy GovCloud**: Use the generated template
4. **Import Configuration**: Upload configuration to new stack
5. **Validate**: Test processing with sample documents

## Cost Considerations

GovCloud pricing may differ from commercial regions:

- Review [GovCloud Pricing](https://aws.amazon.com/govcloud-us/pricing/)
- Update cost estimates in configuration files
- Monitor actual usage through billing dashboards

## Compliance Notes

- The GovCloud version maintains the same security features
- Data encryption and retention policies are preserved
- All processing remains within GovCloud boundaries
- No data egress to commercial AWS regions

## Related Documentation

- [GovCloud Architecture](./govcloud-architecture.md) — services removed vs. retained, limitations, and workarounds
- [Batch Jobs REST API](./govcloud-batch-api.md) — API reference, authentication, and bastion tunnel setup
- [GovCloud Operations](./govcloud-operations.md) — monitoring, troubleshooting, and best practices
