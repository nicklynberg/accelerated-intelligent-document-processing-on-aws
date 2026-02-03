# IDP SDK Examples

This directory contains example scripts demonstrating how to use the IDP SDK.

## Prerequisites

1. Install the IDP SDK in development mode:
   ```bash
   cd lib/idp_sdk
   pip install -e .
   ```

2. Configure AWS credentials with access to your IDP stack.

## Available Examples

### 1. Basic Processing (`basic_processing.py`)

**Requires: Deployed IDP stack**

Demonstrates the most common workflow: submit documents, monitor progress, download results.

```bash
# Process local directory
python basic_processing.py \
    --stack-name IDP-Nova-1 \
    --directory ./samples \
    --output-dir /tmp/results

# Process from S3
python basic_processing.py \
    --stack-name IDP-Nova-1 \
    --s3-uri s3://my-bucket/documents/ \
    --output-dir /tmp/results

# Process from manifest
python basic_processing.py \
    --stack-name IDP-Nova-1 \
    --manifest ./my-manifest.csv \
    --output-dir /tmp/results
```

### 2. Manifest Operations (`manifest_operations.py`)

**Does NOT require a deployed stack**

Demonstrates manifest generation and validation.

```bash
# Generate manifest from directory
python manifest_operations.py --directory ./samples --output manifest.csv

# Generate with baselines for evaluation
python manifest_operations.py \
    --directory ./samples \
    --baseline-dir ./baselines \
    --output manifest.csv

# Validate existing manifest
python manifest_operations.py --validate-only ./manifest.csv
```

### 3. Configuration Operations (`config_operations.py`)

**Create/Validate: No stack required | Download/Upload: Requires stack**

Demonstrates configuration creation, validation, download, and upload.

```bash
# Create minimal configuration template
python config_operations.py create --features min --pattern pattern-2

# Create config with all features
python config_operations.py create --features all --output my-config.yaml

# Validate a configuration file
python config_operations.py validate my-config.yaml --pattern pattern-2

# Download config from deployed stack
python config_operations.py download --stack-name IDP-Nova-1 --output current-config.yaml

# Upload config to deployed stack
python config_operations.py upload my-config.yaml --stack-name IDP-Nova-1
```

### 4. Workflow Control (`workflow_control.py`)

**Requires: Deployed IDP stack**

Demonstrates workflow management: listing batches, getting status, rerunning documents, stopping workflows.

```bash
# List recent batches
python workflow_control.py --stack-name IDP-Nova-1 list --limit 10

# Get batch status
python workflow_control.py --stack-name IDP-Nova-1 status --batch-id my-batch-123

# Get single document status
python workflow_control.py --stack-name IDP-Nova-1 status --document-id "batch/doc.pdf"

# Rerun a batch from extraction step
python workflow_control.py --stack-name IDP-Nova-1 rerun --batch-id my-batch-123 --step extraction

# Stop all running workflows
python workflow_control.py --stack-name IDP-Nova-1 stop

# Show stack resources
python workflow_control.py --stack-name IDP-Nova-1 resources
```

### 5. Lambda Function (`lambda_function.py`)

Example Lambda function that uses the SDK for document processing automation.

See the file for deployment instructions and IAM requirements.

## SDK Quick Reference

```python
from idp_sdk import IDPClient

# Create client with default stack
client = IDPClient(stack_name="my-stack", region="us-west-2")

# Or create client and specify stack per-operation
client = IDPClient()

# Stack-dependent operations
result = client.run_inference(source="./documents/")
status = client.get_status(batch_id=result.batch_id)
client.download_results(batch_id=result.batch_id, output_dir="./results")

# Stack-independent operations
manifest = client.generate_manifest(directory="./docs/")
config = client.config_create(features="min")
validation = client.config_validate(config_file="my-config.yaml")
```

## Common Patterns

### Wait for Processing to Complete

```python
import time
from idp_sdk import IDPClient

client = IDPClient(stack_name="my-stack")
result = client.run_inference(source="./documents/")

# Poll until complete
while True:
    status = client.get_status(batch_id=result.batch_id)
    print(f"Progress: {status.completed}/{status.total}")
    
    if status.all_complete:
        print(f"Done! Success rate: {status.success_rate:.1%}")
        break
    
    time.sleep(10)

# Download results
client.download_results(batch_id=result.batch_id, output_dir="./results")
```

### Process with Custom Configuration

```python
from idp_sdk import IDPClient

client = IDPClient(stack_name="my-stack")

# Upload custom config first
client.config_upload(config_file="my-config.yaml")

# Then process documents (they will use the uploaded config)
result = client.run_inference(directory="./documents/")
```

### Error Handling

```python
from idp_sdk import (
    IDPClient, 
    IDPConfigurationError,
    IDPProcessingError,
    IDPStackError,
    IDPResourceNotFoundError
)

client = IDPClient(stack_name="my-stack")

try:
    result = client.run_inference(source="./documents/")
except IDPConfigurationError as e:
    print(f"Configuration error: {e}")
except IDPProcessingError as e:
    print(f"Processing error: {e}")
except IDPStackError as e:
    print(f"Stack error: {e}")
except IDPResourceNotFoundError as e:
    print(f"Resource not found: {e}")
```

## Available Methods

| Method | Requires Stack | Description |
|--------|----------------|-------------|
| `run_inference()` | Yes | Submit documents for processing |
| `get_status()` | Yes | Get batch/document status |
| `list_batches()` | Yes | List recent batch jobs |
| `download_results()` | Yes | Download processing results |
| `rerun_inference()` | Yes | Rerun documents from a step |
| `stop_workflows()` | Yes | Stop all running workflows |
| `get_resources()` | Yes | Get stack resource details |
| `config_download()` | Yes | Download configuration |
| `config_upload()` | Yes | Upload configuration |
| `deploy()` | Optional* | Deploy/update stack |
| `delete()` | Yes | Delete stack |
| `generate_manifest()` | No | Generate manifest from files |
| `validate_manifest()` | No | Validate manifest file |
| `config_create()` | No | Create config template |
| `config_validate()` | No | Validate config file |
| `load_test()` | Yes | Run load test |

*Deploy can create a new stack (no existing stack required)