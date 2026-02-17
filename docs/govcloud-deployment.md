# GovCloud Deployment Guide

## Overview

The GenAI IDP Accelerator supports "headless" deployment to AWS GovCloud regions through a specialized template generation script. This solution addresses two key GovCloud requirements:

1. **ARN Partition Compatibility**: All ARN references use `arn:${AWS::Partition}:` instead of `arn:aws:` to work in both commercial and GovCloud regions
2. **Service Compatibility**: Removes services not available in GovCloud (AppSync, CloudFront, WAF, Cognito UI components)

For details on what services are removed vs. retained, see [GovCloud Architecture](./govcloud-architecture.md).

## Deployment Packages

The GovCloud template supports three deployment configurations. Choose the one that matches your use case:

| | Vanilla | API + Private Networking | API + Private Networking + Bastion |
|---|---|---|---|
| **Use Case** | Simplest deployment; manual document processing via S3 upload or IDP CLI | Production workloads with programmatic API access from within your VPC | Development/testing environments needing local API access |
| **Access Methods** | S3 direct upload, IDP CLI, SDK | All vanilla methods + REST API (`/jobs` endpoints) | All API methods + local access via SSM tunnel |
| **Networking** | No VPC required | Deploys API Gateway (private) + Lambda functions into your VPC | Same as API, plus an EC2 bastion host for tunneling |
| **Authentication** | IAM only | Cognito client credentials (OAuth2 bearer tokens) | Same as API |
| **VPC Parameters** | None | `VpcId`, `PrivateSubnetIds`, `ApiGatewayVpcEndpointId`, `LambdaSecurityGroupId` | Same as API |
| **Bastion Parameters** | None | None | `DeployBastionHost=true`, `BastionHostSubnetId`, `BastionHostSecurityGroupId` |
| **When to Choose** | You have your own integration layer, or are evaluating the solution | You need API-based access from applications running in AWS | You need to call the API from your laptop during development |

### What Gets Deployed in Each Package

**Vanilla (all packages include this):**
- Core document processing engine (all 3 patterns)
- Step Functions workflows
- S3 buckets, DynamoDB tables, SQS queues, EventBridge rules
- CloudWatch dashboards, alarms, SNS notifications
- KMS encryption keys

**API + Private Networking adds:**
- Private API Gateway with `/jobs` endpoints (POST, GET)
- Cognito User Pool with machine-to-machine client credentials
- VPC-enabled Lambda functions for API handling
- VPC endpoint integration for private API access

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

Deploy the generated template using the AWS CloudFormation console (recommended) or the AWS CLI. Choose the command that matches your desired [deployment package](#deployment-packages).

### Option A: Vanilla (no API, no VPC)

```bash
aws cloudformation deploy \
  --template-file .aws-sam/idp-govcloud.yaml \
  --stack-name my-idp-govcloud-stack \
  --region us-gov-west-1 \
  --s3-bucket {s3-bucket-govcloud} \
  --s3-prefix idp-headless \
  --capabilities CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND \
  --parameter-overrides \
    IDPPattern="Pattern2 - Packet processing with Textract and Bedrock"
```

With this deployment, interact with the system via:
- Direct S3 upload to the input bucket
- IDP CLI (`idp-cli`)
- SDK integration

### Option B: API + Private Networking (production)

```bash
aws cloudformation deploy \
  --template-file .aws-sam/idp-govcloud.yaml \
  --stack-name my-idp-govcloud-stack \
  --region us-gov-west-1 \
  --s3-bucket {s3-bucket-govcloud} \
  --s3-prefix idp-headless \
  --capabilities CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND \
  --parameter-overrides \
    IDPPattern="Pattern2 - Packet processing with Textract and Bedrock" \
    VpcId=vpc-xxxxxxxxx \
    PrivateSubnetIds=subnet-xxxxx,subnet-xxxxx,subnet-xxxxx \
    ApiGatewayVpcEndpointId=vpce-xxxxxxxxx \
    LambdaSecurityGroupId=sg-xxxxxxxxx \
    ApiStageName=beta
```

This enables the `/jobs` REST API accessible from within your VPC. See [Batch Jobs REST API](./govcloud-batch-api.md) for usage.

### Option C: API + Private Networking + Bastion (development)

```bash
aws cloudformation deploy \
  --template-file .aws-sam/idp-govcloud.yaml \
  --stack-name my-idp-govcloud-stack \
  --region us-gov-west-1 \
  --s3-bucket {s3-bucket-govcloud} \
  --s3-prefix idp-headless \
  --capabilities CAPABILITY_NAMED_IAM CAPABILITY_AUTO_EXPAND \
  --parameter-overrides \
    IDPPattern="Pattern2 - Packet processing with Textract and Bedrock" \
    VpcId=vpc-xxxxxxxxx \
    PrivateSubnetIds=subnet-xxxxx,subnet-xxxxx,subnet-xxxxx \
    ApiGatewayVpcEndpointId=vpce-xxxxxxxxx \
    LambdaSecurityGroupId=sg-xxxxxxxxx \
    ApiStageName=beta \
    DeployBastionHost=true \
    BastionHostSubnetId=subnet-xxxxxxxxx \
    BastionHostSecurityGroupId=sg-xxxxxxxxx
```

This adds a bastion host for local API access via SSM tunnel. See [Batch Jobs REST API — Local Access via Bastion Tunnel](./govcloud-batch-api.md#local-api-access-via-bastion-tunnel) for setup.

## Parameter Reference

### VPC Parameters (required for Options B and C)

| Parameter | Description |
|---|---|
| `VpcId` | VPC for Lambda functions |
| `PrivateSubnetIds` | Comma-separated private subnet IDs (minimum 2 for HA) |
| `ApiGatewayVpcEndpointId` | VPC endpoint for private API Gateway access |
| `LambdaSecurityGroupId` | Security group for VPC-enabled Lambda functions |
| `ApiStageName` | API Gateway deployment stage name (default: `beta`) |

### Bastion Parameters (Option C only)

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
