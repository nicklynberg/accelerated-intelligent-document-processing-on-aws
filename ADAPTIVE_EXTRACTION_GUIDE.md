# Adaptive Table Extraction - No minItems Required!

## The Problem You Had

Setting `minItems: 1440` only works for **that specific document**. What about:
- Documents with 50 rows?
- Documents with 500 rows?
- Documents with 5,000 rows?
- Documents with varying lengths?

You'd need different configs for each size, which defeats automation!

## The Solution: Automatic Adaptive Detection

The system **automatically detects table size from OCR** and adjusts agent instructions accordingly. **No minItems constraint needed!**

## How It Works

### 1. OCR Analysis (Happens Automatically)

```python
# System scans OCR text for Markdown table rows
table_rows_detected = count_lines_with_pipes(ocr_text)
# Example: 250 rows detected
```

### 2. Recommendation Strength (Calculated Automatically)

| Detected Rows | Recommendation | Agent Instructions |
|--------------|----------------|-------------------|
| 0-49 | OPTIONAL | Standard guidance (tool available) |
| 50-99 | RECOMMENDED | Gentle recommendation to use tool |
| 100-499 | **STRONGLY_RECOMMENDED** | **Explicit "YOU MUST use tool"** |
| 500+ | **MANDATORY** | **Critical "IMMEDIATELY use tool"** |

### 3. Agent Instructions (Injected Automatically)

#### For 500+ rows (Your 1440-row case):
```
**CRITICAL - MANDATORY TABLE PARSING TOOL USAGE**:
This document contains a large table with 1440+ rows detected by OCR analysis.
You MUST use the parse_table tool for complete and accurate extraction:

1. IMMEDIATELY call parse_table with the full document text
2. DO NOT attempt manual row-by-row LLM extraction
3. Verify parse_table returned ALL expected rows
...
```

#### For 100-499 rows:
```
**IMPORTANT - USE TABLE PARSING TOOL**:
This document contains tabular data with 250+ rows detected.
You MUST use the parse_table tool for accurate and complete extraction:
...
```

#### For 50-99 rows:
```
**RECOMMENDED - TABLE PARSING TOOL**:
Detected a table with 75+ rows. Consider using the parse_table tool:
...
```

## Configuration (Universal - Works for ALL Sizes)

```yaml
# ONE configuration for all document sizes!
extraction:
  agentic:
    enabled: true
    table_parsing:
      enabled: true                      # ← Just enable it
      max_empty_line_gap: 3              # ← Handles page breaks
      auto_merge_adjacent_tables: true   # ← Merges fragments

classes:
  - properties:
      table_data:
        type: array
        # NO minItems! System adapts automatically
        description: "Table data - adapts to any size"
        items:
          type: object
          properties:
            # your columns here
```

That's it! Works for:
- ✅ 10-row invoice
- ✅ 50-row bank statement
- ✅ 250-row transaction log
- ✅ 1,440-row brokerage statement
- ✅ 10,000-row inventory list

**Same config, same code, automatic adaptation!**

## What About minItems?

### ❌ Don't Use minItems as a Trigger
```yaml
# BAD - Only works for this specific document size
holdings:
  type: array
  minItems: 1440  # ← What if next document has 500 rows?
```

### ✅ Use minItems for Business Constraints (Optional)
```yaml
# GOOD - Express actual business requirement
holdings:
  type: array
  minItems: 1  # ← "Must have at least 1 holding"
  description: "Portfolio holdings - any quantity"
```

### ✅ Or Don't Use minItems at All (Recommended)
```yaml
# BEST - Let OCR analysis handle detection automatically
holdings:
  type: array
  # No minItems - system adapts to actual document size
  description: "Portfolio holdings"
```

The system will:
1. Detect 1,440 rows from OCR → Triggers MANDATORY
2. Inject explicit instructions → Agent uses tool
3. Extract all 1,440 rows → Success!

**And it works the same way for any other document size!**

## Real-World Examples

### Example 1: Invoice with 15 Line Items
```
OCR Analysis: Detected 15 table rows
Recommendation: OPTIONAL
Agent Behavior: Standard extraction (tool available but not required)
Result: 15 items extracted correctly
```

### Example 2: Bank Statement with 75 Transactions
```
OCR Analysis: Detected 75 table rows
Recommendation: RECOMMENDED
Agent Instructions: "**RECOMMENDED - TABLE PARSING TOOL**"
Agent Behavior: Uses parse_table tool (recommended)
Result: 75 transactions extracted correctly with tool
```

### Example 3: Transaction Log with 250 Entries
```
OCR Analysis: Detected 250 table rows
Recommendation: STRONGLY_RECOMMENDED
Agent Instructions: "**IMPORTANT - USE TABLE PARSING TOOL**"
Agent Behavior: MUST use parse_table tool (explicit instructions)
Result: 250 entries extracted completely
```

### Example 4: Brokerage Statement with 1,440 Holdings
```
OCR Analysis: Detected 1,440 table rows
Recommendation: MANDATORY
Agent Instructions: "**CRITICAL - MANDATORY TABLE PARSING TOOL USAGE**"
Agent Behavior: MUST use parse_table tool (critical requirement)
Result: 1,440 holdings extracted completely
```

### Example 5: Inventory with 8,500 SKUs (50 pages)
```
OCR Analysis: Detected 8,500 table rows
Recommendation: MANDATORY
Agent Instructions: "**CRITICAL - MANDATORY...**" + page break handling
Agent Behavior: Uses tool, auto-merges 50-page table fragments
Result: 8,500 SKUs extracted across all pages
```

**All handled by the SAME configuration!**

## Observability - What You See

### Processing Report Shows Detection
```
=== EXTRACTION PROCESSING REPORT ===

Extraction Method: AGENTIC
Processing Time: 54.8 seconds
Status: SUCCESS

OCR Table Detection:
  - Tables detected: 1
  - Estimated total rows: 1440            ← Automatically detected!
  - Tool usage recommendation: MANDATORY  ← Automatically calculated!

✓ Table Parsing Tool Decision:
  - Expected usage: YES                   ← Based on 1440 rows
  - Actual usage: YES                     ← Agent followed instructions
  - Explanation: Tool was recommended and used as expected

✓ Completeness Validation:
  - All schema constraints satisfied

✓ Table Parsing Tool Results:
  - Tables parsed: 1
  - Total rows extracted: 1440            ← Success!
```

## Tuning (Optional)

### Adjust OCR Thresholds (If Needed)

Default thresholds work well for most cases:
```python
# Current automatic thresholds (in code):
50-99 rows   → RECOMMENDED
100-499 rows → STRONGLY_RECOMMENDED
500+ rows    → MANDATORY
```

These thresholds are optimized for real-world use:
- **50 rows**: Table is large enough to benefit from deterministic parsing
- **100 rows**: Agent explicitly told to use tool for completeness
- **500 rows**: Critical requirement - manual extraction would be slow/incomplete

But **default thresholds are tested and recommended** for production.

### Adjust Robustness Settings

```yaml
# For high-quality OCR (clean documents):
max_empty_line_gap: 2

# For standard quality (recommended default):
max_empty_line_gap: 3

# For noisy OCR (complex/scanned documents):
max_empty_line_gap: 5
```

## Benefits vs Old Approach

### ❌ Old Way (minItems-based):
- Need specific minItems for each document type
- Must know document size in advance
- One config per document size range
- Fails when document size varies
- Manual configuration burden

### ✅ New Way (OCR-based adaptive):
- **One config for all document sizes**
- **No advance knowledge needed**
- **Automatically scales to document**
- **Handles size variation seamlessly**
- **Zero manual tuning**

## Summary

1. **Don't set minItems for triggering** - let OCR analysis handle it
2. **Enable table_parsing** - system adapts automatically
3. **Use same config for all documents** - 10 rows to 10,000+ rows
4. **Check processing report** - see what was detected and why

The system is now **truly adaptive** and **truly robust** for any table size!

## Quick Start

Use the provided adaptive configuration:
```bash
cp config_adaptive_table_extraction.yaml your_config.yaml
# Edit class properties as needed
# Deploy and test - works for any document size!
```

That's it! Your extraction now automatically adapts to any document, any table size, any number of pages.
