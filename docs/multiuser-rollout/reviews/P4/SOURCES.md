# 审核来源

只读取协作仓库 `imherro/OurVideoCreator`。代码固定到被测业务 SHA，证据固定到 evidence HEAD；没有使用单机版仓库。

| 编号 | 来源 | 连接器引用 |
|---|---|---|
| S01 | [master and evidence commit](https://api.github.com/repos/imherro/OurVideoCreator/branches/master) | `turn418file0` |
| S02 | [Implementation parent](https://api.github.com/repos/imherro/OurVideoCreator/git/commits/0e64bd0540ad53de5ea6d93013c14d5154760867) | `turn462file0` |
| S03 | [Test-only increment](https://github.com/imherro/OurVideoCreator/commit/3a73165f74520d0c15ec6f0750d7b2c105108744) | `turn431file0` |
| S04 | [Business tree](https://api.github.com/repos/imherro/OurVideoCreator/git/trees/d6d5ffd6b93775bb5d1ebab2a00b42e45f6ce2a0) | `turn454file0` |
| S05 | [Evidence tree](https://api.github.com/repos/imherro/OurVideoCreator/git/trees/9f7e9c40be088bc620951003a91274dd1f375f3d) | `turn455file0` |
| S06 | [backend/platform_models.py](https://github.com/imherro/OurVideoCreator/blob/3a73165f74520d0c15ec6f0750d7b2c105108744/backend/platform_models.py) | `turn422file0 / turn423file0` |
| S07 | [backend/model_validation.py](https://github.com/imherro/OurVideoCreator/blob/3a73165f74520d0c15ec6f0750d7b2c105108744/backend/model_validation.py) | `turn424file0` |
| S08 | [backend/worker.py](https://github.com/imherro/OurVideoCreator/blob/3a73165f74520d0c15ec6f0750d7b2c105108744/backend/worker.py) | `turn428file0 / turn429file0` |
| S09 | [backend/provider_egress.py](https://github.com/imherro/OurVideoCreator/blob/3a73165f74520d0c15ec6f0750d7b2c105108744/backend/provider_egress.py) | `turn425file0` |
| S10 | [backend/replicate_api.py](https://github.com/imherro/OurVideoCreator/blob/3a73165f74520d0c15ec6f0750d7b2c105108744/backend/replicate_api.py) | `turn441file0` |
| S11 | [backend/providers/common.py](https://github.com/imherro/OurVideoCreator/blob/3a73165f74520d0c15ec6f0750d7b2c105108744/backend/providers/common.py) | `turn439file0` |
| S12 | [backend/provider_secrets.py](https://github.com/imherro/OurVideoCreator/blob/3a73165f74520d0c15ec6f0750d7b2c105108744/backend/provider_secrets.py) | `turn426file0` |
| S13 | [backend/provider_redaction.py](https://github.com/imherro/OurVideoCreator/blob/3a73165f74520d0c15ec6f0750d7b2c105108744/backend/provider_redaction.py) | `turn427file0` |
| S14 | [backend/app.py](https://github.com/imherro/OurVideoCreator/blob/3a73165f74520d0c15ec6f0750d7b2c105108744/backend/app.py) | `turn435file0 / turn434file0 / turn446file0` |
| S15 | [tests/test_p4_model_foundation.py](https://github.com/imherro/OurVideoCreator/blob/3a73165f74520d0c15ec6f0750d7b2c105108744/tests/test_p4_model_foundation.py) | `turn437file0 / turn458file0` |
| S16 | [tests/test_p4_rotation_http.py](https://github.com/imherro/OurVideoCreator/blob/3a73165f74520d0c15ec6f0750d7b2c105108744/tests/test_p4_rotation_http.py) | `turn438file0` |
| S17 | [migrations/versions/0003_platform_models.py](https://github.com/imherro/OurVideoCreator/blob/3a73165f74520d0c15ec6f0750d7b2c105108744/migrations/versions/0003_platform_models.py) | `turn444file0` |
| S18 | [docs/multiuser-rollout/design/P4_MODEL_CONFIG.md](https://github.com/imherro/OurVideoCreator/blob/3a73165f74520d0c15ec6f0750d7b2c105108744/docs/multiuser-rollout/design/P4_MODEL_CONFIG.md) | `turn421file0` |
| S19 | [backend/store.py](https://github.com/imherro/OurVideoCreator/blob/3a73165f74520d0c15ec6f0750d7b2c105108744/backend/store.py) | `turn440file0` |
| S20 | [backend/providers/volcengine_speech.py](https://github.com/imherro/OurVideoCreator/blob/3a73165f74520d0c15ec6f0750d7b2c105108744/backend/providers/volcengine_speech.py) | `turn452file0` |
| S21 | [REPORT.md](https://github.com/imherro/OurVideoCreator/blob/c7d6a88a06a01035fd44e45309414c05e061ab64/docs/multiuser-rollout/evidence/P4/REPORT.md) | `turn419file0` |
| S22 | [SUMMARY.json](https://github.com/imherro/OurVideoCreator/blob/c7d6a88a06a01035fd44e45309414c05e061ab64/docs/multiuser-rollout/evidence/P4/SUMMARY.json) | `turn448file0` |
| S23 | [provenance.json](https://github.com/imherro/OurVideoCreator/blob/c7d6a88a06a01035fd44e45309414c05e061ab64/docs/multiuser-rollout/evidence/P4/provenance.json) | `turn442file0` |
| S24 | [backend-full.txt](https://github.com/imherro/OurVideoCreator/blob/c7d6a88a06a01035fd44e45309414c05e061ab64/docs/multiuser-rollout/evidence/P4/backend-full.txt) | `turn443file0` |
| S25 | [frontend-test-build.txt](https://github.com/imherro/OurVideoCreator/blob/c7d6a88a06a01035fd44e45309414c05e061ab64/docs/multiuser-rollout/evidence/P4/frontend-test-build.txt) | `turn456file0` |
| S26 | [browser-tool-trace.json](https://github.com/imherro/OurVideoCreator/blob/c7d6a88a06a01035fd44e45309414c05e061ab64/docs/multiuser-rollout/evidence/P4/browser-tool-trace.json) | `turn449file0 / turn450file0 / turn451file0` |
| S27 | [browser-db-audit.json](https://github.com/imherro/OurVideoCreator/blob/c7d6a88a06a01035fd44e45309414c05e061ab64/docs/multiuser-rollout/evidence/P4/browser-db-audit.json) | `turn447file0` |
| S28 | [browser-pre-generation.json](https://github.com/imherro/OurVideoCreator/blob/c7d6a88a06a01035fd44e45309414c05e061ab64/docs/multiuser-rollout/evidence/P4/browser-pre-generation.json) | `turn461file0` |
| S29 | [ATTEMPT_HISTORY.md](https://github.com/imherro/OurVideoCreator/blob/c7d6a88a06a01035fd44e45309414c05e061ab64/docs/multiuser-rollout/evidence/P4/ATTEMPT_HISTORY.md) | `turn457file0` |
| S30 | [checks.json](https://github.com/imherro/OurVideoCreator/blob/c7d6a88a06a01035fd44e45309414c05e061ab64/docs/multiuser-rollout/evidence/P4/checks.json) | `turn459file0` |
| S31 | [routes.json](https://github.com/imherro/OurVideoCreator/blob/c7d6a88a06a01035fd44e45309414c05e061ab64/docs/multiuser-rollout/evidence/P4/routes.json) | `turn460file0` |

当前工作包中的独立探针是限定范围的源码摘录实验，不是这些文件的完整应用执行。原始语义、改造点及夹具边界在脚本头和 REVIEW 中说明。
