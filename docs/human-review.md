# Human-in-the-Loop (HITL) Review

Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
SPDX-License-Identifier: MIT-0

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [User Management](#user-management)
  - [User Personas](#user-personas)
  - [Managing Users](#managing-users)
- [Workflow](#workflow)
- [Configuration](#configuration)
- [Review Portal](#review-portal)
- [Best Practices](#best-practices)
- [Troubleshooting](#troubleshooting)

## Overview

The GenAI-IDP solution supports Human-in-the-Loop (HITL) review capabilities through a built-in review system integrated directly into the Web UI. This feature enables human reviewers to validate and correct extracted information when the system's confidence falls below a specified threshold, ensuring accuracy for critical document processing workflows.

**Supported Patterns:**
- Pattern 1: BDA processing with HITL review
- Pattern 2: Textract + Bedrock processing with HITL review

**Key Features:**
- Built-in review portal within the GenAI-IDP Web UI
- Role-based access control with Admin and Reviewer personas
- Section-by-section review workflow
- Visual editor for viewing and correcting extracted data
- Automatic workflow continuation after review completion

## Architecture

The HITL system integrates with the document processing workflow through:

- **Built-in Review Portal**: Web interface integrated into the GenAI-IDP UI for validation and correction
- **User Management**: Cognito-based authentication with role-based access control
- **Section Review Tracking**: DynamoDB-based tracking of review progress per document section
- **Workflow Integration**: Step Functions integration for automatic workflow continuation after review

### Review Flow

![Review Process Flow](../images/hitl_workflow.png)

## User Management

### User Personas

The system supports two user personas with different permission levels:

#### Admin Persona

Admins have full access to all system features:

| Feature | Access |
|---------|--------|
| View Documents | ✅ Full access |
| Upload Documents | ✅ Allowed |
| View/Edit Extraction Results | ✅ Full access |
| Complete Section Reviews | ✅ Allowed |
| View/Edit Configuration | ✅ Full access |
| User Management | ✅ Full access (create/delete users) |
| Discovery | ✅ Full access |
| Analytics & Agents | ✅ Full access |

#### Reviewer Persona

Reviewers have limited access focused on document review tasks:

| Feature | Access |
|---------|--------|
| View Documents | ✅ Full access |
| Upload Documents | ❌ Not allowed |
| View/Edit Extraction Results | ✅ Can view and edit |
| Complete Section Reviews | ✅ Allowed (only for pending sections) |
| View/Edit Configuration | ❌ Not allowed |
| User Management | ❌ Not allowed |
| Discovery | ❌ Not allowed |
| Analytics & Agents | ❌ Limited access |

**Note:** Once a Reviewer completes a section review, they cannot re-edit that section. Only pending sections can be reviewed.

### Managing Users

User management is available to Admin users through the Web UI.

#### Accessing User Management

1. Log in to the GenAI-IDP Web UI with Admin credentials
2. Navigate to **User Management** in the left navigation menu
3. View the list of all users with their email, persona, and status

#### Creating a New User

1. Click the **Create User** button
2. Enter the user's email address
3. Select the persona:
   - **Admin**: Full system access
   - **Reviewer**: Limited access for document review
4. Click **Create**

The system will:
- Create a user record in DynamoDB
- Create a corresponding user in Cognito
- Add the user to the appropriate Cognito group (Admin or Reviewer)
- Send a temporary password to the user's email

#### Deleting a User

1. Find the user in the user list
2. Click the **Delete** button in the Actions column
3. Confirm the deletion

The system will remove the user from both DynamoDB and Cognito.

#### User Synchronization

The system automatically synchronizes users between Cognito and DynamoDB:
- Existing Cognito users are synced to DynamoDB when the user list is loaded
- User persona is determined by Cognito group membership
- Users in the "Admin" group are assigned Admin persona
- All other users are assigned Reviewer persona

## Workflow

### 1. Automatic Triggering

HITL review is automatically triggered when:
- HITL feature is enabled in your configuration (`assessment.enable_hitl = true`)
- Extraction confidence score falls below the configured threshold
- The workflow pauses and waits for human review completion

### 2. Review Process

**Accessing Documents for Review:**
1. Log in to the GenAI-IDP Web UI
2. Navigate to the **Documents** page
3. Documents requiring review show status **HITL_IN_PROGRESS**
4. Click on a document to view its details

**Reviewing Sections:**
1. In the document detail view, locate the **Sections** panel
2. Sections pending review are indicated with a review status
3. Click **View/Edit Data** to open the visual editor
4. Review the extracted key-value pairs against the document
5. Make corrections as needed using the editor
6. Click **Mark Review Complete** to complete the section review

**Visual Editor Features:**
- Side-by-side view of document image and extracted data
- Bounding box highlighting for field locations
- Inline editing of extracted values
- Confidence score display for each field

### 3. Result Integration

When all sections are reviewed:
- The workflow automatically resumes
- Corrected data is saved to S3
- Document status changes from `HITL_IN_PROGRESS` to `SUMMARIZING`
- Processing continues with summarization and subsequent steps
- Review history is recorded with reviewer information and timestamps

## Configuration

### Enabling HITL

HITL can be enabled through two methods:

#### Method 1: CloudFormation Parameter (Initial Setup)

Set the `EnableHITL` parameter to `true` during stack deployment or update.

#### Method 2: Configuration UI (Runtime Toggle)

1. Log in as an Admin user
2. Navigate to **Configuration** in the Web UI
3. Find the **Assessment & HITL Configuration** section
4. Toggle **Enable Human-in-the-Loop (HITL) review** to enable/disable
5. Click **Save** to apply changes

**Note:** Configuration settings take precedence over CloudFormation parameters at runtime.

### Confidence Threshold Configuration

The confidence threshold determines when human review is triggered:

1. Navigate to **Configuration** in the Web UI
2. Find the **Assessment & HITL Configuration** section
3. Set **HITL Confidence Threshold** (0.0-1.0):
   - `0.8` = 80% confidence threshold (recommended starting point)
   - Fields with confidence below this threshold trigger HITL review
4. Click **Save** to apply changes

## Review Portal

### Document List View

The document list shows all processed documents with their current status:
- **HITL_IN_PROGRESS**: Document is awaiting human review
- **SUMMARIZING**: Review complete, processing continues
- **COMPLETED**: All processing finished

### Section Review Interface

The section review interface provides:

- **Section List**: All document sections with review status
- **View/Edit Data**: Opens the visual editor for a section
- **Download Data**: Export extraction results as JSON
- **Mark Review Complete**: Complete the review for a section

### Visual Editor

The visual editor provides a comprehensive review experience with a modern tabbed interface:

#### Navigation Controls
- **Mouse Wheel Zoom**: Zoom in/out using the mouse wheel without requiring modifier keys
- **Click-and-Drag Panning**: Pan around zoomed images by clicking and dragging (cursor shows grab/grabbing state)
- **Section Navigation**: Use Previous/Next buttons to navigate between document sections without closing the editor

#### Tabbed Interface

**Visual Editor Tab**
- Split-pane layout with document image (left) and form-based field editing (right)
- Bounding box overlay highlighting field locations on the document
- Color-coded confidence indicators (green=meets threshold, red=below threshold, black=no threshold)
- Inline editing with visual change tracking (✏️ Edited badges)

**JSON Editor Tab**
- Raw JSON editing for advanced users
- Section filtering with multiselect dropdown to focus on specific sections
- Full JSON validation before saving

**Revision History Tab**
- Complete audit trail of all edits to the document
- Timestamps showing when edits were made
- Reviewer identification showing who made each change
- Field-level diff information showing exactly what was modified

#### Editing Features

**Prediction Editing**
- Edit extracted field values directly in the visual editor
- Change tracking with visual indicators (blue left border on modified fields)
- Save changes directly to S3 with proper versioning
- Discard changes button to revert all edits

**Evaluation Baseline Editing** (when evaluation is enabled)
- Edit baseline (expected) values alongside predictions
- Independent change tracking from predictions (orange left border on modified baseline fields)
- Separate save/discard controls for baseline edits
- Side-by-side comparison of predicted vs expected values

**Save & Reprocess Workflow**

After making edits to predictions or baselines, you can trigger reprocessing to re-run downstream steps with the updated data:

1. **Save Your Edits**: Click "Save Changes" to persist prediction edits or "Save Baseline" to persist baseline edits to S3
2. **Trigger Reprocessing**: After saving, click the "Reprocess" button (or use the document toolbar "Reprocess" action)
3. **Automatic Pipeline Execution**: The document automatically transitions through processing stages:
   - `SUMMARIZING` → Re-generates document summary using updated extraction data
   - `EVALUATING` → Re-runs evaluation comparing updated predictions against baselines
   - `COMPLETE` → Processing finished with updated results
4. **View Updated Results**: Once complete, the evaluation scores and comparison results reflect your edits

**Key Benefits of Save & Reprocess:**
- **Iterative Refinement**: Make corrections and immediately see how they affect evaluation scores
- **Baseline Correction**: Fix ground truth errors and re-evaluate without re-uploading documents
- **Prompt Tuning Workflow**: Edit predictions to match desired output, save as baseline, then use for prompt improvement
- **Quality Assurance**: Verify that corrections properly resolve evaluation mismatches

#### Smart Filtering

- **Low Confidence Filter**: Toggle to show only fields with confidence scores below threshold
- **Evaluation Mismatches Filter**: Toggle to show only fields that don't match baseline (when evaluation enabled)
- **Collapsible Tree Navigation**: Expand/Collapse All buttons for nested data structures
- **Individual Node Toggle**: Click ▶/▼ to expand or collapse specific objects/arrays

#### Evaluation Comparison Mode

When evaluation data is available:
- Side-by-side display of prediction and baseline values for each field
- Match indicators showing ✓ Match or ⚠ Mismatch status
- Evaluation scores and LLM-generated comparison reasons
- Aggregate scores for nested groups and arrays

## Best Practices

### Review Management

- **Process Promptly**: Review documents promptly to avoid processing delays
- **Consistent Standards**: Establish consistent correction guidelines across reviewers
- **Quality Checks**: Implement spot-checks on completed reviews for quality assurance

### Threshold Optimization

- **Start Conservative**: Begin with higher thresholds (0.8-0.9) and adjust based on accuracy needs
- **Monitor Patterns**: Track which document types trigger reviews most frequently
- **Iterative Refinement**: Use review corrections to improve extraction prompts

### User Management

- **Least Privilege**: Assign Reviewer persona to users who only need review access
- **Admin Oversight**: Limit Admin access to users who need full system control
- **Regular Audits**: Periodically review user list and remove inactive users

## Troubleshooting

### Common Issues

**Documents Not Triggering HITL:**
- Verify HITL is enabled in Configuration
- Check confidence threshold settings
- Ensure extraction confidence scores are being calculated

**Cannot Complete Section Review:**
- Verify you have Reviewer or Admin persona
- Check if section is already completed (Reviewers cannot re-edit completed sections)
- Ensure all required fields are filled

**User Cannot Access Review Features:**
- Verify user is in the correct Cognito group
- Check user persona in User Management
- Clear browser cache and re-login

**Workflow Not Resuming After Review:**
- Verify all sections are marked complete
- Check Step Functions execution for errors
- Review CloudWatch logs for the complete_section_review Lambda

### Monitoring

Monitor HITL performance through:
- **CloudWatch Metrics**: Track review completion rates
- **Step Functions Console**: Monitor workflow execution status
- **Web UI Dashboard**: View document processing status
- **DynamoDB**: Query HITLReviewHistory for audit trails

### Review History

Each completed review is recorded with:
- Section ID
- Reviewer username and email
- Review completion timestamp

Query the tracking table for `HITLReviewHistory` to audit review activities.
