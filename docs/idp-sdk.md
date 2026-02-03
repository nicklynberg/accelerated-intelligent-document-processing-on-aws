# IDP SDK Documentation

The IDP SDK provides programmatic Python access to all IDP Accelerator capabilities. It wraps the `idp-cli` functionality in a native Python API with typed responses.

## Installation

```bash
# Install from local development
pip install -e ./lib/idp_sdk

# Or with uv
uv pip install -e ./lib/idp_sdk

# For Lambda deployment (minimal dependencies)
pip install idp-sdk[lambda]
```

## Quick Start

```python
from idp_sdk import IDPClient

# Create client with stack configuration
client = IDPClient(stack_name="my-idp-stack", region="us-west-2")

# Process documents
result = client.run_inference(source="./documents/")
print(f"Batch: {result.batch_id}, Queued: {result.documents_queued}")

# Check status
status = client.get_status(batch_id=result.batch_id)
print(f"Progress: {status.completed}/{status.total}")
```

## Client Initialization

The `IDPClient` can be created with or without stack configuration:

```python
from idp_sdk import IDPClient

# With default stack (used for all operations)
client = IDPClient(stack_name="my-stack", region="us-west-2")

# Without stack (for stack-independent operations)
client = IDPClient()

# Stack can be set later
client.stack_name = "new-stack"

# Or passed per-operation
client.run_inference(stack_name="specific-stack", source="./docs/")
```

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `stack_name` | str | No | Default CloudFormation stack name |
| `region` | str | No | AWS region (defaults to boto3 default) |

---

## Stack-Independent Operations

These operations do NOT require a deployed stack:

### generate_manifest()

Generate a manifest file from a directory or S3 URI.

```python
result = client.generate_manifest(
    directory="./documents/",       # Local directory to scan
    baseline_dir="./baselines/",    # Optional baseline directory
    output="manifest.csv",          # Output file path
    file_pattern="*.pdf",           # File pattern (default: *.pdf)
    recursive=True                  # Include subdirectories
)

print(f"Documents: {result.document_count}")
print(f"Baselines matched: {result.baselines_matched}")
```

### validate_manifest()

Validate a manifest file without processing.

```python
result = client.validate_manifest(manifest_path="./manifest.csv")

if result.valid:
    print(f"Valid manifest with {result.document_count} documents")
else:
    print(f"Invalid: {result.error}")
```

### config_create()

Generate an IDP configuration template.

```python
result = client.config_create(
    features="min",           # min, core, all, or comma-separated list
    pattern="pattern-2",      # pattern-1, pattern-2, pattern-3
    output="config.yaml",     # Output file path
    include_prompts=False,    # Include full prompt templates
    include_comments=True     # Include explanatory comments
)

print(result.yaml_content)
```

### config_validate()

Validate a configuration file.

```python
result = client.config_validate(
    config_file="./config.yaml",
    pattern="pattern-2",
    show_merged=False
)

if result.valid:
    print("Configuration is valid")
else:
    for error in result.errors:
        print(f"Error: {error}")
    for warning in result.warnings:
        print(f"Warning: {warning}")
```

---

## Stack-Dependent Operations

These operations require a valid `stack_name`.

### run_inference()

Process documents through the IDP pipeline.

```python
# Auto-detect source type
result = client.run_inference(source="./documents/")
result = client.run_inference(source="s3://bucket/path/")
result = client.run_inference(source="./manifest.csv")

# Explicit source types
result = client.run_inference(directory="./documents/")
result = client.run_inference(manifest="./manifest.csv")
result = client.run_inference(s3_uri="s3://bucket/path/")
result = client.run_inference(test_set="my-test-set")

# With options
result = client.run_inference(
    source="./documents/",
    batch_prefix="my-batch",
    file_pattern="*.pdf",
    recursive=True,
    number_of_files=10,        # Limit number of files
    config_path="./config.yaml"
)

print(f"Batch ID: {result.batch_id}")
print(f"Documents queued: {result.documents_queued}")
print(f"Document IDs: {result.document_ids}")
```

### get_status()

Get processing status for a batch or document.

```python
# By batch ID
status = client.get_status(batch_id="batch-20250123-123456")

# By document ID
status = client.get_status(document_id="batch-20250123-123456/document.pdf")

print(f"Total: {status.total}")
print(f"Completed: {status.completed}")
print(f"Failed: {status.failed}")
print(f"In Progress: {status.in_progress}")
print(f"Success Rate: {status.success_rate:.1%}")
print(f"All Complete: {status.all_complete}")

# Individual document status
for doc in status.documents:
    print(f"  {doc.document_id}: {doc.status.value}")
    if doc.error:
        print(f"    Error: {doc.error}")
```

### list_batches()

List recent batch processing jobs.

```python
batches = client.list_batches(limit=10)

for batch in batches:
    print(f"{batch.batch_id}: {batch.queued} docs ({batch.timestamp})")
```

### download_results()

Download processing results.

```python
result = client.download_results(
    batch_id="batch-20250123-123456",
    output_dir="./results",
    file_types=["summary", "sections"]  # or ["all"]
)

print(f"Downloaded {result.files_downloaded} files")
```

### rerun_inference()

Rerun processing from a specific step.

```python
from idp_sdk import RerunStep

result = client.rerun_inference(
    step=RerunStep.EXTRACTION,  # or "extraction"
    batch_id="batch-20250123-123456"
)

# Or with specific documents
result = client.rerun_inference(
    step="classification",
    document_ids=["batch/doc1.pdf", "batch/doc2.pdf"]
)

print(f"Queued: {result.documents_queued}")
```

### delete_documents()

Delete documents and all associated data from the IDP system.

```python
# Delete specific documents by ID
result = client.delete_documents(
    document_ids=["batch-123/doc1.pdf", "batch-123/doc2.pdf"]
)

# Delete all documents in a batch
result = client.delete_documents(batch_id="cli-batch-20250123")

# Delete only failed documents in a batch
result = client.delete_documents(
    batch_id="cli-batch-20250123",
    status_filter="FAILED"  # FAILED, COMPLETED, PROCESSING, QUEUED
)

# Dry run to see what would be deleted
result = client.delete_documents(
    batch_id="cli-batch-20250123",
    dry_run=True
)

print(f"Success: {result.success}")
print(f"Deleted: {result.deleted_count}/{result.total_count}")
print(f"Failed: {result.failed_count}")

# Check individual results
for doc_result in result.results:
    if not doc_result.success:
        print(f"  Failed: {doc_result.object_key}")
        for error in doc_result.errors:
            print(f"    {error}")
```

**What gets deleted:**
- Source files from input bucket
- Processed outputs from output bucket  
- DynamoDB tracking records
- List entries in tracking table

### stop_workflows()

Stop all running workflows.

```python
result = client.stop_workflows()

print(f"Queue purged: {result.queue_purged}")
```

### load_test()

Run load testing.

```python
result = client.load_test(
    source_file="./sample.pdf",
    rate=100,              # Files per minute
    duration=5,            # Duration in minutes
    dest_prefix="load-test"
)

print(f"Total files: {result.total_files}")
```

---

## Configuration Operations

### config_download()

Download configuration from a deployed stack.

```python
result = client.config_download(
    output="downloaded-config.yaml",
    format="minimal"  # "full" or "minimal"
)

print(result.yaml_content)
```

### config_upload()

Upload configuration to a deployed stack.

```python
result = client.config_upload(
    config_file="./my-config.yaml",
    validate=True
)

if result.success:
    print("Configuration uploaded successfully")
else:
    print(f"Upload failed: {result.error}")
```

---

## Deployment Operations

### deploy()

Deploy or update an IDP stack.

```python
from idp_sdk import Pattern

result = client.deploy(
    stack_name="my-new-stack",
    pattern=Pattern.PATTERN_2,
    admin_email="admin@example.com",
    max_concurrent=10,
    wait=True
)

if result.success:
    print(f"Stack deployed: {result.stack_name}")
    print(f"Outputs: {result.outputs}")
else:
    print(f"Failed: {result.error}")
```

### delete()

Delete an IDP stack.

```python
result = client.delete(
    empty_buckets=True,
    force_delete_all=False,
    wait=True
)

print(f"Deletion status: {result.status}")
```

### get_resources()

Get stack resource information.

```python
resources = client.get_resources()

print(f"Input Bucket: {resources.input_bucket}")
print(f"Output Bucket: {resources.output_bucket}")
print(f"Queue URL: {resources.document_queue_url}")
```

---

## Response Models

All operations return typed Pydantic models:

```python
from idp_sdk import (
    BatchResult,
    BatchStatusResult,
    DocumentStatusInfo,
    DeploymentResult,
    ManifestResult,
    ConfigValidationResult,
    # ... and more
)
```

### Key Models

| Model | Description |
|-------|-------------|
| `BatchResult` | Result of `run_inference()` |
| `BatchStatusResult` | Result of `get_status()` |
| `DocumentStatusInfo` | Individual document status |
| `DeploymentResult` | Result of `deploy()` |
| `ManifestResult` | Result of `generate_manifest()` |
| `ConfigValidationResult` | Result of `config_validate()` |
| `StackResources` | Stack resource information |

---

## Exceptions

```python
from idp_sdk import (
    IDPError,                  # Base exception
    IDPConfigurationError,     # Missing stack_name, invalid params
    IDPStackError,            # Stack not found, deployment failed
    IDPProcessingError,        # Batch processing failed
    IDPValidationError,        # Invalid manifest/config
    IDPResourceNotFoundError,  # Batch/document not found
    IDPTimeoutError           # Operation timeout
)

try:
    result = client.run_inference(source="./docs/")
except IDPConfigurationError as e:
    print(f"Configuration error: {e}")
except IDPProcessingError as e:
    print(f"Processing failed: {e}")
```

---

## Lambda Function Example

See `lib/idp_sdk/examples/lambda_function/` for a complete SAM template.

```python
import os
from idp_sdk import IDPClient

def handler(event, context):
    client = IDPClient(
        stack_name=os.environ["IDP_STACK_NAME"],
        region=os.environ.get("IDP_REGION", "us-west-2")
    )
    
    result = client.run_inference(
        s3_uri=event["source_uri"]
    )
    
    return {
        "batch_id": result.batch_id,
        "documents_queued": result.documents_queued
    }
```

Deploy with SAM:
```bash
cd lib/idp_sdk/examples/lambda_function
sam build
sam deploy --guided
```

---

## CLI Mapping

| CLI Command | SDK Method |
|-------------|------------|
| `idp run` | `client.run_inference()` |
| `idp status` | `client.get_status()` |
| `idp download` | `client.download_results()` |
| `idp rerun` | `client.rerun_inference()` |
| `idp deploy` | `client.deploy()` |
| `idp delete` | `client.delete()` |
| `idp create-manifest` | `client.generate_manifest()` |
| `idp validate-manifest` | `client.validate_manifest()` |
| `idp config-create` | `client.config_create()` |
| `idp config-validate` | `client.config_validate()` |
| `idp config-download` | `client.config_download()` |
| `idp config-upload` | `client.config_upload()` |
| `idp list-batches` | `client.list_batches()` |
| `idp delete-documents` | `client.delete_documents()` |
| `idp stop` | `client.stop_workflows()` |
| `idp load-test` | `client.load_test()` |

---

## See Also

- [IDP CLI Documentation](./idp-cli.md) - Command-line interface
- [Configuration Guide](./configuration.md) - Configuration options
- [Evaluation Guide](./evaluation.md) - Evaluation and test sets