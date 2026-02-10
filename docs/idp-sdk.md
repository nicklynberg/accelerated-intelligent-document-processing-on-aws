# IDP SDK Documentation

The IDP SDK provides programmatic Python access to all IDP Accelerator capabilities with a clean, namespaced API.

## Installation

```bash
# Install from local development
pip install -e ./lib/idp_sdk

# Or with uv
uv pip install -e ./lib/idp_sdk
```

## Quick Start

```python
from idp_sdk import IDPClient

# Create client with stack configuration
client = IDPClient(stack_name="my-idp-stack", region="us-west-2")

# Upload and process a single document
result = client.document.upload(file_path="./invoice.pdf")
print(f"Document ID: {result.document_id}, Status: {result.status}")

# Process a batch of documents
batch_result = client.batch.run(source="./documents/")
print(f"Batch: {batch_result.batch_id}, Queued: {batch_result.queued}")

# Check status
status = client.batch.get_status(batch_id=batch_result.batch_id)
print(f"Progress: {status.completed}/{status.total}")
```

## Architecture

The SDK follows a namespaced operation pattern for better organization:

```python
client = IDPClient(stack_name="my-stack")

# Stack operations
client.stack.deploy(...)
client.stack.delete()
client.stack.get_resources()

# Batch operations (multiple documents)
client.batch.run(...)
client.batch.get_status(...)
client.batch.list()
client.batch.download_results(...)
client.batch.download_sources(...)
client.batch.delete_documents(...)
client.batch.rerun(...)
client.batch.stop_workflows()

# Document operations (single document)
client.document.upload(...)
client.document.get_status(...)
client.document.download_results(...)
client.document.download_source(...)
client.document.rerun(...)
client.document.delete(...)

# Configuration operations
client.config.create(...)
client.config.validate(...)
client.config.upload(...)
client.config.download(...)

# Manifest operations
client.manifest.generate(...)
client.manifest.validate(...)

# Testing operations
client.testing.load_test(...)
```

## Client Initialization

```python
from idp_sdk import IDPClient

# With stack name (for stack-dependent operations)
client = IDPClient(stack_name="my-stack", region="us-west-2")

# Without stack (for stack-independent operations)
client = IDPClient()

# Stack can be set later
client.stack_name = "new-stack"
```

### Parameters

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `stack_name` | str | No | CloudFormation stack name |
| `region` | str | No | AWS region (defaults to boto3 default) |

---

## Document Operations

Operations for processing individual documents.

### document.upload()

Upload and process a single document.

**Parameters:**
- `file_path` (str, required): Path to local file to upload
- `document_id` (str, optional): Custom document ID (defaults to filename without extension)
- `stack_name` (str, optional): Stack name override

**Returns:** `DocumentUploadResult` with `document_id`, `status`, and `timestamp`

```python
result = client.document.upload(
    file_path="/path/to/invoice.pdf",
    document_id="custom-id"  # Optional
)

print(f"Document ID: {result.document_id}")
print(f"Status: {result.status}")  # "queued"
print(f"Timestamp: {result.timestamp}")
```

### document.get_status()

Get processing status for a single document.

**Parameters:**
- `document_id` (str, required): Document identifier (S3 key format: batch-id/filename)
- `stack_name` (str, optional): Stack name override

**Returns:** `DocumentStatus` with processing information including status, duration, pages, sections, and errors

```python
status = client.document.get_status(document_id="batch-123/invoice.pdf")

print(f"Status: {status.status.value}")
print(f"Pages: {status.num_pages}")
print(f"Duration: {status.duration_seconds}s")
```

### document.download_results()

Download processing results (processed outputs) from OutputBucket for a single document.

**Parameters:**
- `document_id` (str, required): Document identifier (S3 key)
- `output_dir` (str, required): Local directory to save results
- `file_types` (list[str], optional): File types to download - "pages", "sections", "summary", "evaluation" (defaults to all)
- `stack_name` (str, optional): Stack name override

**Returns:** `DocumentDownloadResult` with `document_id`, `files_downloaded`, and `output_dir`

```python
result = client.document.download_results(
    document_id="batch-123/invoice.pdf",
    output_dir="./results",
    file_types=["pages", "sections", "summary"]  # Optional
)

print(f"Downloaded {result.files_downloaded} files")
```

### document.download_source()

Download original document source file from InputBucket.

**Parameters:**
- `document_id` (str, required): Document identifier (S3 key)
- `output_path` (str, required): Local file path to save document
- `stack_name` (str, optional): Stack name override

**Returns:** `str` - Local file path where document was saved

```python
file_path = client.document.download_source(
    document_id="batch-123/invoice.pdf",
    output_path="./downloads/invoice.pdf"
)

print(f"Downloaded to: {file_path}")
```

### document.rerun()

Rerun processing for a single document from a specific pipeline step.

**Parameters:**
- `document_id` (str, required): Document identifier (S3 key)
- `step` (str or RerunStep, required): Pipeline step to rerun from (e.g., "classification", "extraction", RerunStep.EXTRACTION)
- `stack_name` (str, optional): Stack name override

**Returns:** `DocumentRerunResult` with `document_id`, `step`, and `queued` status

```python
from idp_sdk import RerunStep

result = client.document.rerun(
    document_id="batch-123/invoice.pdf",
    step=RerunStep.EXTRACTION
)

print(f"Queued: {result.queued}")
```

### document.delete()

Permanently delete a single document and all associated data from InputBucket, OutputBucket, and DynamoDB.

**Parameters:**
- `document_id` (str, required): Document identifier (S3 key)
- `stack_name` (str, optional): Stack name override
- `dry_run` (bool, optional): If True, simulate deletion without actually deleting (default: False)

**Returns:** `DocumentDeletionResult` with `success`, `object_key`, `deleted` (dict of deleted items), and `errors`

```python
result = client.document.delete(
    document_id="batch-123/invoice.pdf",
    dry_run=False
)

print(f"Success: {result.success}")
print(f"Deleted: {result.deleted}")
```

---

## Batch Operations

Operations for processing multiple documents.

### batch.run()

Process multiple documents through the IDP pipeline.

**Parameters:**
- `source` (str, optional): Auto-detected source - directory path, manifest file, or S3 URI
- `manifest` (str, optional): Path to manifest CSV file
- `directory` (str, optional): Local directory path
- `s3_uri` (str, optional): S3 URI (s3://bucket/prefix/)
- `test_set` (str, optional): Test set identifier
- `batch_prefix` (str, optional): Batch ID prefix (default: "sdk-batch")
- `file_pattern` (str, optional): File pattern for filtering (default: "*.pdf")
- `recursive` (bool, optional): Recursively process subdirectories (default: True)
- `number_of_files` (int, optional): Limit number of files to process
- `config_path` (str, optional): Path to custom configuration file
- `stack_name` (str, optional): Stack name override

**Returns:** `BatchResult` with `batch_id`, `document_ids`, `queued`, `uploaded`, `failed`, and `timestamp`

```python
# From directory
result = client.batch.run(source="./documents/")

# From manifest
result = client.batch.run(source="./manifest.csv")

# From S3
result = client.batch.run(source="s3://bucket/path/")

# With options
result = client.batch.run(
    source="./documents/",
    batch_prefix="my-batch",
    file_pattern="*.pdf",
    recursive=True,
    number_of_files=10,
    config_path="./config.yaml"
)

print(f"Batch ID: {result.batch_id}")
print(f"Documents queued: {result.queued}")
```

### batch.get_status()

Get processing status for all documents in a batch.

**Parameters:**
- `batch_id` (str, required): Batch identifier
- `stack_name` (str, optional): Stack name override

**Returns:** `BatchStatus` with `batch_id`, `documents` (list of DocumentStatus), `total`, `completed`, `failed`, `in_progress`, `queued`, `success_rate`, and `all_complete`

```python
status = client.batch.get_status(batch_id="batch-20250123-123456")

print(f"Total: {status.total}")
print(f"Completed: {status.completed}")
print(f"Failed: {status.failed}")
print(f"Success Rate: {status.success_rate:.1%}")

for doc in status.documents:
    print(f"  {doc.document_id}: {doc.status.value}")
```

### batch.list()

List recent batch processing jobs.

**Parameters:**
- `limit` (int, optional): Maximum number of batches to return (default: 10)
- `stack_name` (str, optional): Stack name override

**Returns:** `list[BatchInfo]` with batch metadata including `batch_id`, `document_ids`, `queued`, `failed`, and `timestamp`

```python
batches = client.batch.list(limit=10)

for batch in batches:
    print(f"{batch.batch_id}: {batch.queued} docs")
```

### batch.download_results()

Download processing results (processed outputs) from OutputBucket for all documents in a batch.

**Parameters:**
- `batch_id` (str, required): Batch identifier
- `output_dir` (str, required): Local directory to save results
- `file_types` (list[str], optional): File types to download - "pages", "sections", "summary", "evaluation", or "all" (default: ["all"])
- `stack_name` (str, optional): Stack name override

**Returns:** `BatchDownloadResult` with `files_downloaded`, `documents_downloaded`, and `output_dir`

```python
result = client.batch.download_results(
    batch_id="batch-20250123-123456",
    output_dir="./results",
    file_types=["summary", "sections"]
)

print(f"Downloaded {result.files_downloaded} files")
```

### batch.download_sources()

Download original source files from InputBucket for all documents in a batch.

**Parameters:**
- `batch_id` (str, required): Batch identifier
- `output_dir` (str, required): Local directory to save source files
- `stack_name` (str, optional): Stack name override

**Returns:** `BatchDownloadResult` with `files_downloaded`, `documents_downloaded`, and `output_dir`

```python
result = client.batch.download_sources(
    batch_id="batch-20250123-123456",
    output_dir="./source_files"
)

print(f"Downloaded {result.files_downloaded} source files")
```

### batch.delete_documents()

Permanently delete all documents in a batch and their associated data from InputBucket, OutputBucket, and DynamoDB.

**Parameters:**
- `batch_id` (str, required): Batch identifier
- `status_filter` (str, optional): Filter by document status (e.g., "FAILED", "COMPLETED")
- `stack_name` (str, optional): Stack name override
- `dry_run` (bool, optional): If True, simulate deletion without actually deleting (default: False)
- `continue_on_error` (bool, optional): Continue deleting if one document fails (default: True)

**Returns:** `BatchDeletionResult` with `success`, `deleted_count`, `failed_count`, `total_count`, `dry_run`, and `results` (list of DocumentDeletionResult)

```python
# Delete entire batch
result = client.batch.delete_documents(batch_id="batch-123")

# Delete with status filter
result = client.batch.delete_documents(
    batch_id="batch-123",
    status_filter="FAILED"
)

# Dry run
result = client.batch.delete_documents(
    batch_id="batch-123",
    dry_run=True
)

print(f"Deleted: {result.deleted_count}/{result.total_count}")
```

### batch.rerun()

Rerun processing for multiple documents from a specific pipeline step.

**Parameters:**
- `step` (str or RerunStep, required): Pipeline step to rerun from (e.g., "classification", "extraction", RerunStep.EXTRACTION)
- `document_ids` (list[str], optional): Specific document IDs to rerun
- `batch_id` (str, optional): Batch ID to rerun all documents in batch
- `stack_name` (str, optional): Stack name override

**Note:** Must specify either `document_ids` or `batch_id`

**Returns:** `BatchRerunResult` with `documents_queued`, `documents_failed`, `failed_documents`, and `step`

```python
from idp_sdk import RerunStep

# Rerun batch
result = client.batch.rerun(
    step=RerunStep.EXTRACTION,
    batch_id="batch-20250123-123456"
)

# Rerun specific documents
result = client.batch.rerun(
    step="classification",
    document_ids=["batch/doc1.pdf", "batch/doc2.pdf"]
)

print(f"Queued: {result.documents_queued}")
```

### batch.stop_workflows()

Stop all running Step Functions workflows and purge the SQS queue.

**Parameters:**
- `stack_name` (str, optional): Stack name override
- `skip_purge` (bool, optional): Skip purging the SQS queue (default: False)
- `skip_stop` (bool, optional): Skip stopping executions (default: False)

**Returns:** `StopWorkflowsResult` with `executions_stopped`, `documents_aborted`, and `queue_purged`

```python
result = client.batch.stop_workflows()

print(f"Queue purged: {result.queue_purged}")
print(f"Executions stopped: {result.executions_stopped}")
```

---

## Stack Operations

Operations for deploying and managing IDP stacks.

### stack.deploy()

Deploy or update an IDP stack.

```python
from idp_sdk import Pattern

result = client.stack.deploy(
    stack_name="my-new-stack",
    pattern=Pattern.PATTERN_2,
    admin_email="admin@example.com",
    max_concurrent=100,
    wait=True
)

if result.success:
    print(f"Stack deployed: {result.stack_name}")
    print(f"Outputs: {result.outputs}")
```

### stack.delete()

Delete an IDP stack.

```python
result = client.stack.delete(
    empty_buckets=True,
    force_delete_all=False,
    wait=True
)

print(f"Status: {result.status}")
```

### stack.get_resources()

Get stack resource information.

```python
resources = client.stack.get_resources()

print(f"Input Bucket: {resources.input_bucket}")
print(f"Output Bucket: {resources.output_bucket}")
print(f"Queue URL: {resources.document_queue_url}")
```

---

## Configuration Operations

Operations for managing IDP configurations.

### config.create()

Generate an IDP configuration template.

```python
result = client.config.create(
    features="min",           # min, core, all, or comma-separated
    pattern="pattern-2",
    output="config.yaml",
    include_prompts=False,
    include_comments=True
)

print(result.yaml_content)
```

### config.validate()

Validate a configuration file.

```python
result = client.config.validate(
    config_file="./config.yaml",
    pattern="pattern-2"
)

if result.valid:
    print("Configuration is valid")
else:
    for error in result.errors:
        print(f"Error: {error}")
```

### config.upload()

Upload configuration to a deployed stack.

```python
result = client.config.upload(
    config_file="./my-config.yaml",
    validate=True
)

if result.success:
    print("Configuration uploaded")
```

### config.download()

Download configuration from a deployed stack.

```python
result = client.config.download(
    output="downloaded-config.yaml",
    format="minimal"  # "full" or "minimal"
)

print(result.yaml_content)
```

---

## Manifest Operations

Operations for manifest generation and validation.

### manifest.generate()

Generate a manifest file from a directory or S3 URI.

```python
result = client.manifest.generate(
    directory="./documents/",
    baseline_dir="./baselines/",
    output="manifest.csv",
    file_pattern="*.pdf",
    recursive=True
)

print(f"Documents: {result.document_count}")
print(f"Baselines matched: {result.baselines_matched}")
```

### manifest.validate()

Validate a manifest file.

```python
result = client.manifest.validate(manifest_path="./manifest.csv")

if result.valid:
    print(f"Valid manifest with {result.document_count} documents")
else:
    print(f"Invalid: {result.error}")
```

---

## Testing Operations

Operations for load testing and performance validation.

### testing.load_test()

Run load testing.

```python
result = client.testing.load_test(
    source_file="./sample.pdf",
    rate=100,              # Files per minute
    duration=5,            # Duration in minutes
    dest_prefix="load-test"
)

print(f"Total files: {result.total_files}")
```

---

## Response Models

All operations return typed Pydantic models:

```python
from idp_sdk import (
    # Document models
    DocumentUploadResult,
    DocumentStatus,
    DocumentDownloadResult,
    DocumentRerunResult,
    DocumentDeletionResult,
    
    # Batch models
    BatchResult,
    BatchStatus,
    BatchInfo,
    BatchRerunResult,
    BatchDownloadResult,
    BatchDeletionResult,
    
    # Stack models
    StackDeploymentResult,
    StackDeletionResult,
    StackResources,
    
    # Config models
    ConfigCreateResult,
    ConfigValidationResult,
    ConfigUploadResult,
    ConfigDownloadResult,
    
    # Manifest models
    ManifestResult,
    ManifestValidationResult,
    
    # Testing models
    LoadTestResult,
    StopWorkflowsResult,
    
    # Enums
    DocumentState,
    Pattern,
    RerunStep,
    StackState,
    
    # Exceptions
    IDPError,
    IDPConfigurationError,
    IDPStackError,
    IDPProcessingError,
    IDPResourceNotFoundError,
    IDPValidationError,
    IDPTimeoutError,
)
```

---

## Error Handling

```python
from idp_sdk import IDPClient, IDPProcessingError, IDPResourceNotFoundError

client = IDPClient(stack_name="my-stack")

try:
    result = client.document.upload(file_path="./invoice.pdf")
except IDPProcessingError as e:
    print(f"Processing error: {e}")
except IDPResourceNotFoundError as e:
    print(f"Resource not found: {e}")
except Exception as e:
    print(f"Unexpected error: {e}")
```

---

## Complete Example

```python
from idp_sdk import IDPClient, RerunStep
import time

# Initialize client
client = IDPClient(stack_name="my-idp-stack", region="us-west-2")

# Upload single document
doc_result = client.document.upload(file_path="./invoice.pdf")
doc_id = doc_result.document_id

# Monitor document processing
while True:
    status = client.document.get_status(document_id=doc_id)
    print(f"Status: {status.status.value}")
    
    if status.status.value in ["COMPLETED", "FAILED"]:
        break
    
    time.sleep(5)

# Download results if successful
if status.status.value == "COMPLETED":
    client.document.download_results(
        document_id=doc_id,
        output_dir="./results"
    )
    print("Results downloaded successfully")

# Process a batch
batch_result = client.batch.run(source="./documents/")
batch_id = batch_result.batch_id

# Monitor batch progress
while True:
    batch_status = client.batch.get_status(batch_id=batch_id)
    print(f"Progress: {batch_status.completed}/{batch_status.total}")
    
    if batch_status.all_complete:
        break
    
    time.sleep(10)

# Download batch results
client.batch.download_results(
    batch_id=batch_id,
    output_dir="./batch_results"
)

print(f"Batch complete! Success rate: {batch_status.success_rate:.1%}")
```

---

## See Also

- [IDP CLI Documentation](./idp-cli.md) - Command-line interface
- [SDK Examples](../lib/idp_sdk/examples/) - Code examples
- [API Reference](../lib/idp_sdk/README.md) - Detailed API documentation
