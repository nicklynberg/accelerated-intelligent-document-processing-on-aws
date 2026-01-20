# Active Context

## Current Work Focus

### GitHub Issue #166 - Fixed ✅
**Issue:** Missing Bedrock Model access does not fail Step Function execution
**Reporter:** nicklynberg (Jan 15, 2026)
**Environment:** us-gov-west-2, Pattern 2, Version 0.4.10

## Recent Changes (January 20, 2026)

### Fix Applied to Summarization Service
Fixed the issue where Bedrock `AccessDeniedException` errors were silently swallowed in the summarization service, causing Step Functions to complete successfully instead of failing.

**File Modified:** `lib/idp_common_pkg/idp_common/summarization/service.py`

**Changes Made:**
1. **`process_document_section` method**: Changed from returning silently on exceptions to re-raising them
   - Before: `return document, {}` after catching exception
   - After: `raise` to propagate exception to caller

2. **`process_document` method**: Added exception tracking for parallel section processing
   - Added `section_exceptions = {}` to track failed sections
   - After parallel processing completes, checks if any sections failed
   - Re-raises the first exception to ensure proper workflow failure
   - Added detailed logging for debugging

### Root Cause Analysis

The bug was **specific to the Summarization service only**. Analysis of all Pattern 2 services:

| Service | Re-raises Exceptions? | Workflow Fails Properly? |
|---------|----------------------|--------------------------|
| Classification | ✅ Yes | ✅ Yes |
| Extraction | ✅ Yes | ✅ Yes |
| Assessment | ✅ Yes | ✅ Yes |
| **Summarization** | ❌ No (was broken) | ❌ No (was broken) |

### Error Flow (After Fix)
```
Bedrock AccessDeniedException
    ↓
process_text() - raises
    ↓
process_document_section() - NOW re-raises
    ↓
process_document() - NOW collects and re-raises section exceptions
    ↓
Lambda handler outer except - sets status to FAILED
    ↓
Lambda handler status check - raises Exception
    ↓
Step Functions - workflow FAILS ✅
```

## Next Steps

1. **Unit Tests**: Add tests for `AccessDeniedException` propagation in summarization service
2. **Integration Test**: Deploy and verify fix in test environment
3. **PR**: Create pull request referencing GitHub Issue #166

## Important Patterns and Preferences

### Error Handling Pattern for Bedrock Services
All services that use Bedrock should follow this pattern:
- Catch exceptions for logging and error tracking (add to `document.errors`)
- **Always re-raise exceptions** to propagate them to the Lambda handler
- The Lambda handler checks `document.status == Status.FAILED` and raises
- Step Functions sees Lambda error and properly fails the workflow

### Pattern 2 Service Structure
- **OCR** → **Classification** → **Extraction/Assessment (parallel per section)** → **Process Results** → **Summarization** → **Evaluation**
- Each step has its own Lambda function
- Step Functions has retry logic for transient errors, but not for `AccessDeniedException`

## Learnings and Project Insights

1. **Silent error swallowing is dangerous**: The summarization service was catching exceptions to handle partial failures gracefully, but this meant critical errors like `AccessDeniedException` were never visible to users.

2. **Consistent error handling is important**: Classification, Extraction, and Assessment services all correctly re-raise exceptions, but Summarization didn't follow the same pattern.

3. **Parallel processing complicates error handling**: When using `ThreadPoolExecutor`, exceptions from worker threads must be explicitly collected and re-raised after all workers complete.

4. **Step Functions rely on Lambda errors**: The workflow only fails if the Lambda function raises an exception. Returning a document with `status=FAILED` is not enough if the Lambda doesn't subsequently raise.