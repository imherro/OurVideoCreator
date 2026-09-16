# P4-R1 审核来源

仅审查 `imherro/OurVideoCreator`。下列为实际读取的代码、证据与后续阶段冻结规范。代码按业务 SHA，证据按 evidence HEAD 绑定。历史总册文件名不代表另行读取单机仓库。

| 编号 | 内容 | 固定来源 | 会话引用 |
|---|---|---|---|
| S01 | master / evidence parent | [打开](https://api.github.com/repos/imherro/OurVideoCreator/branches/master) | `turn463file0` |
| S02 | business commit parent | [打开](https://api.github.com/repos/imherro/OurVideoCreator/git/commits/e6c3edd95830d4c778fee357b8807d1443920a04) | `turn471file0` |
| S03 | business diff | [打开](https://github.com/imherro/OurVideoCreator/commit/e6c3edd95830d4c778fee357b8807d1443920a04) | `turn465file0` |
| S04 | business root tree | [打开](https://api.github.com/repos/imherro/OurVideoCreator/git/trees/88b0fc154cfad017a3409321f80ee08c7e1fe69c) | `turn472file0` |
| S05 | evidence root tree | [打开](https://api.github.com/repos/imherro/OurVideoCreator/git/trees/0cc1d0892f18d2e96d0f27e79ec18dbfdf54fb62) | `turn473file0` |
| S06 | backend/model_validation.py | [打开](https://github.com/imherro/OurVideoCreator/blob/e6c3edd95830d4c778fee357b8807d1443920a04/backend/model_validation.py) | `turn466file0` |
| S07 | backend/platform_models.py | [打开](https://github.com/imherro/OurVideoCreator/blob/e6c3edd95830d4c778fee357b8807d1443920a04/backend/platform_models.py) | `turn470file0` |
| S08 | src/PlatformModels.tsx | [打开](https://github.com/imherro/OurVideoCreator/blob/e6c3edd95830d4c778fee357b8807d1443920a04/src/PlatformModels.tsx) | `turn477file0` |
| S09 | tests/test_p4_r1_regressions.py | [打开](https://github.com/imherro/OurVideoCreator/blob/e6c3edd95830d4c778fee357b8807d1443920a04/tests/test_p4_r1_regressions.py) | `turn468file0 / turn469file0` |
| S10 | docs/multiuser-rollout/evidence/P4-R1/baseline-red.txt | [打开](https://github.com/imherro/OurVideoCreator/blob/c0152ffcfb5623fcc0b723dbdf450acec9f17f73/docs/multiuser-rollout/evidence/P4-R1/baseline-red.txt) | `turn474file0` |
| S11 | docs/multiuser-rollout/evidence/P4-R1/targeted-green.txt | [打开](https://github.com/imherro/OurVideoCreator/blob/c0152ffcfb5623fcc0b723dbdf450acec9f17f73/docs/multiuser-rollout/evidence/P4-R1/targeted-green.txt) | `turn467file0` |
| S12 | docs/multiuser-rollout/evidence/P4-R1/backend-full.txt | [打开](https://github.com/imherro/OurVideoCreator/blob/c0152ffcfb5623fcc0b723dbdf450acec9f17f73/docs/multiuser-rollout/evidence/P4-R1/backend-full.txt) | `turn475file0` |
| S13 | docs/multiuser-rollout/evidence/P4-R1/frontend-test-build.txt | [打开](https://github.com/imherro/OurVideoCreator/blob/c0152ffcfb5623fcc0b723dbdf450acec9f17f73/docs/multiuser-rollout/evidence/P4-R1/frontend-test-build.txt) | `turn484file0` |
| S14 | docs/multiuser-rollout/evidence/P4-R1/routes-compile.txt | [打开](https://github.com/imherro/OurVideoCreator/blob/c0152ffcfb5623fcc0b723dbdf450acec9f17f73/docs/multiuser-rollout/evidence/P4-R1/routes-compile.txt) | `turn485file0 / turn485file1` |
| S15 | docs/multiuser-rollout/evidence/P4-R1/REPORT.md | [打开](https://github.com/imherro/OurVideoCreator/blob/c0152ffcfb5623fcc0b723dbdf450acec9f17f73/docs/multiuser-rollout/evidence/P4-R1/REPORT.md) | `turn464file0` |
| S16 | docs/multiuser-rollout/evidence/P4-R1/SUMMARY.json | [打开](https://github.com/imherro/OurVideoCreator/blob/c0152ffcfb5623fcc0b723dbdf450acec9f17f73/docs/multiuser-rollout/evidence/P4-R1/SUMMARY.json) | `turn476file0` |
| S17 | docs/multiuser-rollout/evidence/P4-R1/ATTEMPT_HISTORY.md | [打开](https://github.com/imherro/OurVideoCreator/blob/c0152ffcfb5623fcc0b723dbdf450acec9f17f73/docs/multiuser-rollout/evidence/P4-R1/ATTEMPT_HISTORY.md) | `turn482file0` |
| S18 | docs/multiuser-rollout/evidence/P4-R1/browser-tool-trace.json | [打开](https://github.com/imherro/OurVideoCreator/blob/c0152ffcfb5623fcc0b723dbdf450acec9f17f73/docs/multiuser-rollout/evidence/P4-R1/browser-tool-trace.json) | `turn478file0 / turn479file0` |
| S19 | docs/multiuser-rollout/evidence/P4-R1/browser-db-audit.json | [打开](https://github.com/imherro/OurVideoCreator/blob/c0152ffcfb5623fcc0b723dbdf450acec9f17f73/docs/multiuser-rollout/evidence/P4-R1/browser-db-audit.json) | `turn481file0` |
| S20 | docs/multiuser-rollout/evidence/P4-R1/browser-web-access.txt | [打开](https://github.com/imherro/OurVideoCreator/blob/c0152ffcfb5623fcc0b723dbdf450acec9f17f73/docs/multiuser-rollout/evidence/P4-R1/browser-web-access.txt) | `turn489file0` |
| S21 | docs/MyVideoCreator_Codex_Full_Playbook_v1.md | [打开](https://github.com/imherro/OurVideoCreator/blob/c0152ffcfb5623fcc0b723dbdf450acec9f17f73/docs/MyVideoCreator_Codex_Full_Playbook_v1.md) | `turn486file0` |
| S22 | docs/multiuser-rollout/design/DATA_OWNERSHIP.md | [打开](https://github.com/imherro/OurVideoCreator/blob/c0152ffcfb5623fcc0b723dbdf450acec9f17f73/docs/multiuser-rollout/design/DATA_OWNERSHIP.md) | `turn487file0` |
| S23 | docs/multiuser-rollout/design/PERMISSIONS.md | [打开](https://github.com/imherro/OurVideoCreator/blob/c0152ffcfb5623fcc0b723dbdf450acec9f17f73/docs/multiuser-rollout/design/PERMISSIONS.md) | `turn488file0` |

本轮未独立执行项目测试；审核环境探测见 `checks/environment.json`。公开链接未必对无仓库权限的访问者可读。
