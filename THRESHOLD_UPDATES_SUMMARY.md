# Threshold Updates & New System Defaults

## Changes Made

### 1. ✅ Updated Thresholds (500-row large document)

**New Adaptive Thresholds:**
| Detected Rows | Recommendation | Agent Instructions |
|--------------|----------------|-------------------|
| **50-99** | RECOMMENDED | Gentle: "Consider using parse_table" |
| **100-499** | STRONGLY_RECOMMENDED | Explicit: "YOU MUST use parse_table" |
| **500+** | **MANDATORY** | **Critical: "IMMEDIATELY use parse_table"** |

**Your 1,440-row document:** MANDATORY (automatically detected!)

### 2. ✅ Agentic Extraction is Now the Default!

**Updated:** `lib/idp_common_pkg/idp_common/config/system_defaults/base-extraction.yaml`

**OLD Defaults (Before):**
```yaml
extraction:
  agentic:
    enabled: false           # ❌ Disabled by default
    table_parsing:
      enabled: false         # ❌ Tool not enabled
  model: us.amazon.nova-2-lite-v1:0  # ❌ Less capable model
```

**NEW Defaults (Now):**
```yaml
extraction:
  agentic:
    enabled: true            # ✅ Enabled by default!
    table_parsing:
      enabled: true          # ✅ Tool enabled by default!
      max_empty_line_gap: 3              # ✅ Handles page breaks
      auto_merge_adjacent_tables: true   # ✅ Merges fragments
  model: us.anthropic.claude-sonnet-4-20250514-v1:0  # ✅ Best model for agentic
  max_tokens: "64000"        # ✅ Claude 4 maximum
```

**Impact:**
- ✅ **All new deployments** get agentic extraction + table parsing by default
- ✅ **All patterns** inherit these defaults (pattern-2, unified, etc.)
- ✅ **Existing deployments** unaffected (your overrides preserved)
- ✅ **Better out-of-box experience** for all users

### 3. ✅ Updated All Documentation

**Files Updated:**
- `config_adaptive_table_extraction.yaml` - Reflects 500+ row threshold
- `ADAPTIVE_EXTRACTION_GUIDE.md` - Updated thresholds and examples
- `CHANGELOG.md` - Comprehensive entry with new defaults
- `lib/idp_common_pkg/idp_common/extraction/service.py` - All code thresholds updated

## What This Means for You

### For Your 1,440-Row Document

**Automatic Detection:**
```
1. OCR Analysis: Detects 1,440 table rows
2. Threshold Check: 1440 >= 500 → MANDATORY
3. Agent Instructions: "CRITICAL - MANDATORY TABLE PARSING TOOL USAGE"
4. Agent Behavior: MUST use parse_table immediately
5. Result: All 1,440 rows extracted ✅
```

### For Any Other Document Size

**Automatic Adaptation:**
```
75-row bank statement:
  - OCR detects 75 rows → RECOMMENDED
  - Agent receives: "RECOMMENDED - TABLE PARSING TOOL"
  - Agent uses tool (recommended)
  - Result: 75 rows extracted ✅

250-row transaction log:
  - OCR detects 250 rows → STRONGLY_RECOMMENDED
  - Agent receives: "IMPORTANT - USE TABLE PARSING TOOL"
  - Agent MUST use tool (explicit instructions)
  - Result: 250 rows extracted ✅

750-row inventory:
  - OCR detects 750 rows → MANDATORY
  - Agent receives: "CRITICAL - MANDATORY..."
  - Agent MUST use tool (critical requirement)
  - Result: 750 rows extracted ✅
```

**One config, all document sizes!**

## New System Defaults Benefits

### For New Users
- ✅ Get best extraction out-of-box (agentic + table parsing)
- ✅ Claude Sonnet 4 by default (best performance)
- ✅ No configuration needed for robust table extraction
- ✅ Works for any document size automatically

### For Existing Users
- ✅ Your existing configs preserved (overrides respected)
- ✅ Can adopt new defaults by removing overrides
- ✅ Or keep current settings - everything still works

### For You
- ✅ No `minItems` values needed in schema
- ✅ System automatically detects and adapts
- ✅ Works for 10-row invoice or 10,000-row inventory
- ✅ Same config, all documents

## Testing the Changes

### Quick Test

Your simplest config (no minItems needed!):
```yaml
extraction:
  agentic:
    enabled: true
    table_parsing:
      enabled: true
      max_empty_line_gap: 3
      auto_merge_adjacent_tables: true

classes:
  - properties:
      holdings:
        type: array
        # NO minItems - adapts automatically!
        items:
          type: object
          properties:
            symbol: {type: string}
            shares: {type: number}
```

### What You'll See

**Processing Report:**
```
OCR Table Detection:
  - Tables detected: 1
  - Estimated total rows: 1440           ← Auto-detected!
  - Tool usage recommendation: MANDATORY ← 1440 >= 500
  - Reason: "Detected 1 table(s) with ~1440 total rows"

✓ Table Parsing Tool Decision:
  - Expected usage: YES  ← Based on 500+ threshold
  - Actual usage: YES    ← Agent followed instructions
  - Explanation: Tool was recommended and used as expected

✓ Table Parsing Tool Results:
  - Total rows extracted: 1440 ← Success!
```

## Summary of All Thresholds

### OCR-Based (Primary - Adaptive)
```python
50-99 rows    → RECOMMENDED        (gentle)
100-499 rows  → STRONGLY_RECOMMENDED (explicit "MUST")
500+ rows     → MANDATORY          (critical "IMMEDIATELY")
```

### Schema-Based (Optional Reinforcement)
```python
minItems 50-99   → RECOMMENDED
minItems 100-499 → STRONGLY_RECOMMENDED
minItems 500+    → MANDATORY
```

**But you don't need minItems at all!** OCR handles it automatically.

## Key Takeaways

1. **500 rows** is now the threshold for "large document" (MANDATORY)
2. **Agentic extraction + table parsing** is now the default for everyone
3. **No minItems required** - system adapts to actual document size
4. **Claude Sonnet 4** is now the default extraction model
5. **One config works for all document sizes** - 10 to 10,000+ rows

Your extraction is now **truly adaptive** and **truly the default**! 🎉
