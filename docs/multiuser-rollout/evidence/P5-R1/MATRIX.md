# P5-R1 返修验证映射

只覆盖 OVC-P5-01 的最小修复及必要回归，不自行签发外部 PASS。固定业务 `34d646d5c17d5ba12fdc56d4948ab513703731ff`。

| 要求 | 测试与原始证据 | 当前结果/边界 |
|---|---|---|
| 普通 A 改附属源 ID 不能破坏 B 的依赖；直接删 B 边作403对照 | `tests/test_p5_review_child_identity.py`，`baseline-red.txt`/`targeted-green.txt` | 原版3入口200/悬空而失败；修复后PATCH/batch/commands均422；对象/graph/history/audit/event不变 |
| 附属节点新增、移除、改名均须graph | `test_identity_changes_require_graph_but_valid_atomic_changes_work`，3参数 | 不带graph422；有权完整原子命令200；实际聚合通过topological |
| 不能只检查是否带了graph字段 | `test_graph_presence_alone_cannot_bypass_integrity_or_revision`，5参数 | retained边、旧位置、旧nodeOrder、无效shotOrder422；旧graph版本409；夹带create没有半写，计数不变 |
| 不通过自动删边/接管绕过他人目标权 | `test_valid_graph_cleanup_still_requires_foreign_target_permission`，2参数 | 移除/改名携带有效清理后的graph仍403，B依赖保留 |
| 历史恢复使用同一规则 | `test_identity_changes_require_graph_but_valid_atomic_changes_work` 的restore断言 | 合法结构更新后，仅restore旧shot改变附属集合422，全部状态不变；没有新恢复旁路 |
| graph与附属结构竞争无半写 | `test_graph_and_child_change_compete_through_real_pg_waiters` | 真实PG blocker链，正式[409,200]、开发[200,409]；精确一个提交、另一个409；镜头/图及历史审计事件数量对应获胜者，无固定sleep |
| 前端合法结构编辑仍可提交 | `tests/collaboration_client.test.mjs` 新增child identity用例 | add/remove/rename均通过真实适配器向同一commands提交shot+graph当前版本；传输为mock，不冒称浏览器/HTTP |
| 普通正文不争用图版本 | 既有 `actual persistence adapter sends only changed shot`、真实PG `test_locked_shot_does_not_lock_other_shot`/双editor用例 | 固定SHA前端、完整后端及并发专项均通过 |
| P1–P4/COLLAB-01/02/06/09/11回归 | `commands-34d646d/backend-full.txt`、`concurrency-traces.txt` | 473完整后端、10并发均通过，exit0 |
| COLLAB-03/12草稿和Twick | `commands-34d646d/frontend.txt`；原 `../P5/browser-*` | 固定SHA默认前端179通过，原浏览器证据保持；补充OVC-P5-02红测仍未解决，见下方 |

固定专项：15 passed、66.21s、exit0。审核原草案未修改，真实运行结果与审核者源码逻辑实验分开归档。此次后端修复没有前端运行时变化，按外部提示词不重做61+17全部浏览器操作。

## 不得被绿色专项掩盖的补充问题

`deferred/p5_late_ack.mjs` 仍是独立失败复现，位于默认npm测试集之外；它**不是已通过测试、不是skip、不是当前结构修复解决的能力**。已提交主ChatGPT作后续独立任务判断，不能仅凭本矩阵的结构绿测宣告P5整体通过。
