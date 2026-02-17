# Active Context

## Current Work Focus

### Pattern Unification: Phase 2b+2c - Unified Template (February 17, 2026)
**Status:** ✅ Completed

#### What Was Done
Merged the two separate pattern templates (pattern-1/BDA and pattern-2/Pipeline) into a single unified template, and updated the main template.yaml to reference it.

#### Files Created/Modified

**New files in `patterns/unified/`:**
- `template.yaml` (3849 lines, 175KB) - Unified CloudFormation template combining both patterns
- `buildspec-bda.yml` - CodeBuild buildspec for BDA Lambda container images
- `buildspec-pipeline.yml` - CodeBuild buildspec for Pipeline Lambda container images
- `statemachine/workflow.asl.json` (pre-existing) - Unified state machine routing via `use_bda` flag

**Modified:**
- `template.yaml` (main) - Replaced dual `PATTERN1STACK`/`PATTERN2STACK` with single `PATTERNSTACK`

#### Design Decisions

1. **Two ECR repos + Two CodeBuild projects**: BDA and Pipeline have separate source zips, so they need separate build infrastructure. Named `BDAECRRepository`/`PipelineECRRepository` and `BDADockerBuildProject`/`PipelineDockerBuildProject`.

2. **Resource naming to avoid conflicts**: 
   - Pattern-1 infra: `BDA*` prefix (BDADockerBuildRole, BDACodeBuildTrigger, etc.)
   - Pattern-2 infra: `Pipeline*` prefix (PipelineDockerBuildRole, PipelineCodeBuildTrigger, etc.)
   - Pattern-1 ProcessResults → `BDAProcessResultsFunction` (to avoid conflict with Pipeline's `ProcessResultsFunction`)
   - BDA-unique functions keep original names: `InvokeBDAFunction`, `BDACompletionFunction`

3. **Schema uses Pattern-2's superset**: The `UpdateSchemaConfig` from pattern-2 includes the `use_bda` toggle and all pipeline-specific config sections (OCR, classification, extraction, assessment, rule_validation), plus shared sections (summarization, evaluation, discovery, agents).

4. **Shared functions from Pipeline**: Summarization and Evaluation Lambda functions from pattern-2 are the superset versions (support LambdaHook, etc.). BDA's versions were removed to avoid duplication.

5. **Single PATTERNSTACK**: Main template now has one `PATTERNSTACK` instead of conditional `PATTERN1STACK`/`PATTERN2STACK`. All `!If [IsPattern2, PATTERN2STACK, PATTERN1STACK]` references simplified to direct `!GetAtt PATTERNSTACK.Outputs.*`.

6. **Parameters changed**: `SourceZipfile` split into `BDASourceZipfile` and `PipelineSourceZipfile`. `ImageVersion` is shared (same content-based hash approach).

#### Remaining IsPattern References
- `IsPattern1`/`IsPattern2` conditions still defined in main template (4 refs remaining)
- Used by: BDA sample project condition, AppSync stack parameter
- These will be cleaned up in a future phase when full unification is complete

#### 51 Resources in Unified Template
- Config: UpdateSchemaConfig, UpdateDefaultConfig
- BDA Build: BDAECRRepository, BDADockerBuildRole, BDADockerBuildProject, BDACodeBuildExecutionRole, BDACodeBuildTrigger, BDACodeBuildTriggerLogGroup, BDADockerBuildRun, BDAEcrRepositoryCleanup, BDALambdaECRAccessPolicy
- Pipeline Build: PipelineECRRepository, PipelineDockerBuildRole, PipelineDockerBuildProject, PipelineCodeBuildExecutionRole, PipelineCodeBuildTrigger, PipelineCodeBuildTriggerLogGroup, PipelineDockerBuildRun, PipelineEcrRepositoryCleanup, PipelineLambdaECRAccessPolicy
- BDA Functions: InvokeBDAFunction, BDAProcessResultsFunction, BDACompletionFunction + log groups, DLQ, EventBridge
- Pipeline Functions: OCRFunction, ClassificationFunction, ExtractionFunction, AssessmentFunction, ProcessResultsFunction, SummarizationFunction, EvaluationFunction, RuleValidationFunction, RuleValidationOrchestrationFunction + log groups
- Shared: DocumentProcessingStateMachine, StateMachineLogGroup, BDAMetadataTable

#### Next Steps (Phase 2d+)
- Create unified buildspec that builds ALL images in one CodeBuild
- Add combined CloudWatch Dashboard to unified template
- Clean up remaining IsPattern1/IsPattern2 conditions from main template
- Update publish.py to handle unified pattern packaging
- Update config_library to work with unified pattern

---

### Configuration Storage: Full Configs Per Version (February 14, 2026)
**Status:** ✅ Completed - Core refactoring done

#### Problem
The previous "sparse delta" pattern for config versions was introducing significant complexity and bugs.

#### Decision
Each version stores a **complete, self-contained configuration snapshot**.

---

## Important Patterns and Preferences

### Resource Naming Convention (Unified Pattern)
- BDA-specific resources: `BDA*` prefix
- Pipeline-specific resources: `Pipeline*` prefix
- Shared resources: No prefix (e.g., `DocumentProcessingStateMachine`)

### Template Outputs Interface
The unified template maintains the same outputs as both patterns:
- `StateMachineName`, `StateMachineArn`, `StateMachineLogGroup`
- `PatternLogGroups` (comma-separated, now includes ALL log groups)
- `DashboardName`, `DashboardArn`
