# Configuration Recommendations for Large Dense Tables

## Overview
For documents with large tables (100+ rows) spanning multiple pages, the following configuration ensures robust and complete extraction.

## Recommended Configuration

```yaml
# OCR Configuration
ocr:
  service: textract
  textract_features:
    - TABLES      # Essential for Markdown table detection
    - LAYOUT      # Helps preserve table structure

# Classification Configuration
classification:
  skip: true      # Optional: Skip if document type is known

# Extraction Configuration
extraction:
  # Use Claude Sonnet 4 or Opus 4 for best agentic performance
  model: "us.anthropic.claude-sonnet-4-20250514-v1:0"

  # Temperature 0 for deterministic extraction
  temperature: 0.0

  # Use model maximum for large documents
  max_tokens: 64000

  # Agentic extraction with table parsing
  agentic:
    enabled: true

    # Table parsing configuration
    table_parsing:
      enabled: true                     # CRITICAL: Enable deterministic parser

      # Robustness settings for multi-page tables
      max_empty_line_gap: 3             # Tolerate up to 3 empty lines (page breaks)
      auto_merge_adjacent_tables: true  # Auto-merge table fragments

      # Quality thresholds (Textract-specific)
      min_confidence_threshold: 95.0    # OCR confidence target
      min_parse_success_rate: 0.90      # Parse quality threshold
      use_confidence_data: true         # Use Textract confidence data
```

## Schema Configuration

**CRITICAL**: Set `minItems` constraint on array fields to enable pre-flight analysis:

```yaml
classes:
  - $schema: https://json-schema.org/draft/2020-12/schema
    $id: BrokerageStatement
    type: object
    x-aws-idp-document-type: BrokerageStatement
    description: "Brokerage statement with portfolio holdings"
    properties:
      account_number:
        type: string
        description: "Account number"

      holdings:
        type: array
        minItems: 1000              # ← CRITICAL: Triggers MANDATORY recommendation
        description: "Portfolio holdings detail table"
        items:
          type: object
          properties:
            symbol:
              type: string
              description: "Stock ticker symbol"
            shares:
              type: number
              description: "Number of shares"
            # ... other fields
```

## How It Works

### 1. Pre-Flight Schema Analysis
When `minItems >= 100`, the system:
- Calculates recommendation strength: **MANDATORY**
- Logs: "Schema has 1 array field(s) with minItems > 50"
- Triggers dynamic prompt enhancement

### 2. Pre-Flight OCR Analysis
When OCR detects `1000+ table rows`, the system:
- Estimates total row count from Markdown table lines
- Calculates recommendation strength: **MANDATORY**
- Logs: "Detected 1 table(s) with ~1440 total rows"
- Triggers dynamic prompt enhancement

### 3. Dynamic Prompt Enhancement
For **MANDATORY** cases (minItems >= 100 OR rows >= 500), the agent receives:

```
**CRITICAL - MANDATORY TABLE PARSING TOOL USAGE**:
The document schema requires 1440+ items and OCR analysis detected 1440+ table rows.
You MUST use the parse_table tool for tabular data extraction:

1. IMMEDIATELY call parse_table with the full document text or table section
2. DO NOT attempt manual row-by-row LLM extraction for large tables
3. Verify parse_table returned ALL expected rows (check row_count in response)
4. If parse_table returns fewer rows than expected, investigate warnings...

FAILURE TO USE parse_table will result in:
- Incomplete extraction (missing rows)
- Schema validation failures
- Excessive token usage
- Poor extraction performance

This is not optional - use the tool immediately.
```

### 4. Table Parsing Tool Behavior
The `parse_table` tool provides:
- **Intelligent Lookahead Recovery**: Tolerates up to `max_empty_line_gap` empty lines
- **Auto-Merge Adjacent Tables**: Combines fragments with identical columns
- **Smart Warnings**: Alerts agent to potential completeness issues
- **Quality Metrics**: Reports parse success rate, OCR confidence, row counts

### 5. Post-Extraction Validation
The system automatically validates:
- **Tool Usage Decision**: Checks if tool was used as expected
- **Completeness**: Compares extracted count vs minItems constraint
- **Generates Report**: Creates user-friendly processing report

## Tuning Parameters

### `max_empty_line_gap`
Controls tolerance for OCR artifacts and page breaks:

- **0-1**: High-quality OCR, no page breaks expected
- **2-3**: Standard quality (RECOMMENDED for most cases)
- **3-5**: Complex documents with many page breaks
- **6-10**: Very noisy OCR or fragmented tables

**Recommendation**: Start with `3`, increase if warnings show premature table termination.

### `auto_merge_adjacent_tables`
Automatically merges tables with identical columns:

- **true** (RECOMMENDED): Merges fragments from page breaks
- **false**: Keeps tables separate (agent must extract from all)

**Recommendation**: Keep `true` for multi-page tables.

### `minItems` in Schema
Triggers pre-flight analysis and mandatory guidance:

- **< 50**: No special handling
- **50-99**: STRONGLY_RECOMMENDED
- **>= 100**: MANDATORY (explicit instructions)

**Recommendation**: Set to expected minimum count (e.g., 1000 for 1000+ row table).

## Expected Behavior

### Success Case
```
Schema Analysis:
  - Large array fields detected: 1 (holdings)
  - Maximum minItems constraint: 1440
  - Tool usage recommendation: MANDATORY

OCR Table Detection:
  - Tables detected: 1
  - Estimated total rows: 1440
  - Tool usage recommendation: MANDATORY

✓ Table Parsing Tool Decision:
  - Expected usage: YES
  - Actual usage: YES
  - Explanation: Tool was recommended and used as expected

✓ Completeness Validation:
  - All schema constraints satisfied

✓ Table Parsing Tool Results:
  - Tables parsed: 1
  - Total rows extracted: 1440
  - Parse success rate: 98.5%
  - Avg OCR confidence: 97.2%
```

### Failure Case (Tool Not Used)
```
⚠ Table Parsing Tool Decision:
  - Expected usage: YES
  - Actual usage: NO
  - Explanation: Tool was recommended but NOT used...

✗ Completeness Validation:
  - 1 constraint violation(s) detected - extraction may be incomplete

  Detected Issues:
    • Field 'holdings': Extracted 900 items but schema requires
      minimum 1440 (62.5% complete)
      Possible cause: Agent did not use table parsing tool
```

## Troubleshooting

### Issue: "Extracted fewer rows than expected"
**Possible Causes**:
1. Agent didn't use tool → Check `tool_usage_decision.actual` in metadata
2. Table parsing stopped early → Increase `max_empty_line_gap`
3. Tables not merged → Verify `auto_merge_adjacent_tables: true`

**Solution**: Check `processing_report` in extraction output for detailed diagnosis.

### Issue: "Parse success rate low (< 90%)"
**Possible Causes**:
1. Poor OCR quality → Try different OCR service or preprocessing
2. Complex table structure → Tool may not be suitable (merged cells, nested tables)

**Solution**: Review `table_parsing_stats.warnings` for specific issues.

### Issue: "Agent still not using tool despite MANDATORY"
**Possible Causes**:
1. Model doesn't follow instructions well → Try Claude Opus 4
2. Prompt conflicts → Check for custom prompts that may override
3. Tool not available → Verify `table_parsing.enabled: true`

**Solution**: Check CloudWatch logs for "Injecting dynamic table parsing guidance" message.

## Performance Characteristics

### Token Efficiency
- **Without tool**: ~500K tokens for 1440-row table (may timeout)
- **With tool**: ~50K tokens (10x reduction)

### Accuracy
- **Without tool**: 60-70% completeness (often stops early)
- **With tool**: 95-99% completeness (handles OCR artifacts)

### Speed
- **Without tool**: 3-5 minutes (may timeout on Lambda)
- **With tool**: 30-60 seconds

## Summary

For large dense tables over unlimited pages:
1. ✅ Set `minItems` >= 100 in schema (triggers MANDATORY)
2. ✅ Enable `agentic.table_parsing.enabled: true`
3. ✅ Use `max_empty_line_gap: 3` and `auto_merge_adjacent_tables: true`
4. ✅ Use Claude Sonnet 4 or Opus 4 with `temperature: 0`
5. ✅ Review `processing_report` in extraction output to verify tool usage

This configuration enables the system to automatically detect large tables, provide explicit instructions to the agent, and validate completeness after extraction.
