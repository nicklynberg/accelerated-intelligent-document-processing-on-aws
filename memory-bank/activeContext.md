# Active Context

## Current Work Focus

### Multi-Document Discovery Pipeline — Final Bug Fix (March 28, 2026)

**Status**: Pipeline runs end-to-end successfully. Fixing last bug: save_to_config fails due to argument mismatch.

#### What's Working (Fully):
- ✅ Container-based Lambda via nested stack (Option D) — fully deployed
- ✅ Embed → Cluster → Analyze → Save pipeline completes end-to-end
- ✅ 293 documents processed, 9 clusters discovered
- ✅ All 9 clusters analyzed with Claude Sonnet 4.6 via Strands agent
- ✅ Beautiful JSON Schemas generated with proper `x-aws-idp-*` extensions
- ✅ Reflection report generated successfully
- ✅ Embedding model: `amazon.titan-embed-image-v1` (deployed), `us.cohere.embed-v4:0` (in code for next deploy)

#### Discovered Document Classes (test-forcejpeg execution):
| Cluster | Classification | Docs |
|---------|---------------|------|
| 0 | BankCheck | 52 |
| 1 | DemocraticDesignatingPetition | 51 |
| 2 | RealEstateTransactionAnalysisReport | 59 |
| 3 | CaliforniaCommercialLeaseAgreement | 52 |
| 4 | StaffShiftSchedule | 18 |
| 5 | Glossary | 31 |
| 6 | BankStatement | 11 |
| 7 | MedicalEquipmentInspectionChecklist | 11 |
| 8 | DeliveryNote | 8 |

#### Bug Fixed (March 28, 2026):
**Bug 5: save_to_config argument mismatch** (FIXED in code, deploying)
- `multi_document_discovery.py` called `_merge_and_save_class(dc.json_schema, config_version)` with 2 args
- `ClassesDiscovery._merge_and_save_class(self, new_class)` only takes 1 arg (config_version already in `self.version`)
- Also: caller expected return value but method returns `None`
- **Fix**: Removed extra `config_version` arg, get class_name from `dc.classification` instead of return value

#### Previous Bugs Fixed (March 26, 2026):
1. **Wrong embedding model**: Changed from `cohere.embed-english-v3` to `amazon.titan-embed-image-v1`
2. **Broken config loading**: Changed `get_configuration()` to `get_merged_configuration()`
3. **Image too large**: Added `MAX_IMAGE_DIMENSION = 2048` + `thumbnail()` resizing
4. **Missing IAM permission**: Added `bedrock:InvokeModelWithResponseStream` for Strands agent

### Deploy Workflow for Multi-Doc Discovery Updates:
1. Edit source files locally
2. `zip` source → upload to S3 (`multi-doc-discovery-source.zip`)
3. Trigger CodeBuild (`DockerBuildProject-SCHmXl057IyX`)
4. Update all 4 Lambda functions (`aws lambda update-function-code --image-uri ...`)
5. Test via Step Functions execution

### Key Resources:
- **State Machine**: `MultiDocDiscoveryStateMachine-dDZLuXlnPr36`
- **ECR Repo**: `idp-clustering-multidocdiscoverystack-zk22bzb3zu9f-ecrrepository-9p8uh42dbiem`
- **CodeBuild**: `DockerBuildProject-SCHmXl057IyX`
- **Source zip**: `s3://idp-accelerator-artifacts-912625584728-us-west-2/idp-cli/0.5.4.dev1/multi-doc-discovery-source.zip`
- **Discovery bucket**: `idp-clustering-discoverybucket-qw7bnpqtmdn9`
- **Test data**: `test-multi-doc-discovery/` prefix (293 OCR benchmark PNGs)
- **Nested stack**: `IDP-Clustering-MULTIDOCDISCOVERYSTACK-ZK22BZB3ZU9F`

### Lambda Functions (in nested stack):
- Embed: `IDP-Clustering-MULTIDOCDI-MultiDocDiscoveryEmbedFu-38US140aTztm`
- Cluster: `IDP-Clustering-MULTIDOCDI-MultiDocDiscoveryCluster-O45y2NnfL4xF`
- Analyze: `IDP-Clustering-MULTIDOCDI-MultiDocDiscoveryAnalyze-LhuQNvUB0KG6`
- Save: `IDP-Clustering-MULTIDOCDI-MultiDocDiscoverySaveFun-DTKnS535Ymon`

### Log Groups (custom names from nested stack):
- Save: `IDP-Clustering-MULTIDOCDISCOVERYSTACK-ZK22BZB3ZU9F-MultiDocDiscoverySaveFunctionLogGroup-r7zdVUGJHhpK`

---

## Architecture Summary

### Unified Architecture (Phase 3 Complete — Feb 26, 2026)
- Single template stack: `template.yaml` → `patterns/unified/template.yaml`
- 12 Lambda functions (BDA branch + Pipeline branch + shared tail)
- Routing via `use_bda` flag in configuration
- Full config per version stored in DynamoDB

### Multi-Document Discovery (March 25-28, 2026)
- Container-based Lambda via nested stack (`nested/multi-doc-discovery/`)
- 4 Lambda functions: Embed, Cluster, Analyze, Save
- Docker image built via CodeBuild, pushed to ECR
- Dependencies: scikit-learn, scipy, numpy, strands-agents (exceeds 250MB layer limit)
- Embedding model: `us.cohere.embed-v4:0` (in code, deploying)
- Analysis model: `us.anthropic.claude-sonnet-4-6` (via Strands agents with ConverseStream)

### SDK Architecture (March 22, 2026)
- 11 operation namespaces: stack, batch, document, config, discovery, manifest, testing, search, evaluation, assessment, **publish**
- `IDPPublisher` class lives in `idp_sdk._core.publish`
- `HeadlessTemplateTransformer` in `idp_sdk._core.template_transform`
- `publish.py` (root) is backward-compat wrapper
