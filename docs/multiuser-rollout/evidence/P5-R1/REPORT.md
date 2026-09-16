# P5-R1 结构一致性返修记录

交付状态：**READY_FOR_REVIEW（仅 P5-R1 / OVC-P5-01）**，不是外部通过。P5 首轮外部不通过绑定 `5143ee36f55ab783f203832558cfedd4efce4936`；本轮唯一返修项为 OVC-P5-01（S2）。补充缺陷OVC-P5-02保留待随后独立执行P5-R2，P5整体未通过，P6未授权。

固定业务：`34d646d5c17d5ba12fdc56d4948ab513703731ff`。相对送审基线只修改一个运行时文件 `backend/collaboration.py`，保留原有锁顺序、权限及事务；另增加真实 PG 回归和前端命令回归。无迁移、新依赖、前端运行时代码变化或真实付费Provider调用。

## 根因和最小修复

旧实现已经将附属节点 ID 集合变化识别为 structural，但后面的 graph 必带检查仅覆盖顶层 creates/deletes。修复把相同的节点身份变化布尔值也用于 graph 必带检查；有 graph 时继续执行原有完整拟提交状态验证与依赖目标负责人检查。没有自动删边、自动接管或增加整份项目锁。

普通正文/提示词不改变节点 ID 集合，仍可独立保存，不要求 graph。已有客户端 split/diff 会把附属节点增删/改名投影为 graph.nodeOrder/positions 变化，实际 CollaborationClient 回归确认镜头和 graph 当前版本同一 commands 提交，无须改页面。

## 基线红测与开发绿测

- 审核原件位于 `../../reviews/P5/`，完整任务在 `../../prompts/P5_R1_CODEX_PROMPT.md`。下载包 SHA256：`5cd00bbec53779f93268ff0abf65fd03ff0a28cdd28dbf2c073577ece28cfc25`。
- `baseline-red.txt`：未修改运行时的 5143ee3；审核者提供的测试原样复制到 tests 后，实际应用 TestClient + 自有隔离 PG；PATCH、batch、commands 全部错误返回 200，镜头 r1→r2、graph r4 不变、topological 报悬空节点；**3 failed / 15.46s / exit 1**。测试源码 SHA256 在原始日志头，拒绝断言确实失败，不是把错误行为当预期通过。
- `development-green.txt`：修复后开发工作区 **15 passed / 63.71s / exit 0**。包含上述三个入口、增删/改名必须 graph、合法原子结构、旧 graph、悬空边/排序/位置拒绝、他人边权限、混合批次全部回滚、历史恢复不能单对象改变身份、真实 PG 等待及一成功一409。
- 开发前端 npm test：**179 passed / 0 failed / 0 skipped**；正式固定 SHA 补跑另见下节，不混写两次输出。

## 正式固定 SHA 验证

`targeted-green.txt`：34d646d 固定 SHA，UTC22:51:58.9606649Z—22:53:07.7216636Z，**15 passed / 66.21s / exit 0**。三个原负例全部422、版本及历史/审计/事件不变；真实PG等待轨迹两请求结果[409,200]，与开发期[200,409]均保持精确一成功一冲突及完整提交状态。

正式capture UTC **2026-09-16T22:53:07.925732Z—23:13:49.061445Z**，整个进程exit0。命令、stdout/stderr、UTC、退出码及含启动的wall time在 `commands-34d646d/`；以下pytest/Vite耗时来自命令自身汇总，不与进程wall time混用。

| 验证 | 固定34d646d实际结果 |
|---|---|
| 完整后端真实PG | **473 passed，2 warnings，1162.95s，exit0**；无失败或跳过 |
| 原确定性并发轨迹 | **10 passed，43.52s，exit0**；真实PG等待链 |
| 全部默认前端 | **179 passed，0 failed/skipped，exit0**；不包含明确另列的OVC-P5-02红测 |
| TypeScript | exit0 |
| Vite/TypeScript build | **1837 modules，9.03s，exit0**；旧大chunk警告保留 |
| 实际路由 | **125注册项，122/122 API分类，0未分类，exit0** |
| compile / diff-check | 均exit0 |

完整后端包含原P1–P4及P5保留能力、FFmpeg、结构导入/候选/恢复与新增15个结构测试。两条warning仍为websockets legacy/server弃用，不删除或隐藏。

## 浏览器和保留能力边界

这次仅后端运行时改变；前端现有合法附属节点更新已带 graph，新增 adapter 回归实际验证请求，不是源码字符串检查。依外部提示词，本轮不重做此前 61+17 次浏览器操作。原双用户正文、真实409、候选采纳和 Twick/FFmpeg 浏览器证据继续保留在 `../P5/`，不写成本轮重跑。

完整后端与额外并发轨迹已验证本次套件内的原 P1–P4、COLLAB-01/02/06/09/11 保留能力，不声称形式化覆盖所有交错。所有用户和保留测试实例未停止、未重置，旧草稿/租约/媒体未操作。本轮只使用 fixture 创建的独立临时 PG 库，fixture 仅清理其显式安全命名、当前活动且自己创建的库。无真实付费 API、P6、多 Worker 或公网部署。

## 独立补充缺陷（不隐藏、不混入当前修复）

审核中途曾提及、最终未列为 P5-R1 范围的迟到回执问题，在当前运行时仍有独立确定性复现：保存 v2 回执延迟期间观察到同对象 v3，旧回执到达后，下一次仅改 note 却发送 expected_revision=3 与 v2 正文，服务端变为 v4 丢失 v3 正文、前端显示 saved。

`deferred/frontend-late-ack-red.txt` 是基线真实 stdout/stderr，**1 failed**；它用实际 CollaborationClient 和可控 mock CAS transport，不是浏览器/HTTP/PG 实验。复现源码保留在 `deferred/p5_late_ack.mjs`（仅相对 import 路径调整，新增范围说明），可显式运行 `node --test docs/multiuser-rollout/evidence/P5-R1/deferred/p5_late_ack.mjs`。

该测试作为独立补充证据，不在 npm 的默认 `tests/*.test.mjs` 范围，**不能把 179 项通过解读为这个复现已通过或问题已消失**。主会话随后正式确认 **OVC-P5-02（S2）**，授权本轮独立提交/取证完成后执行P5-R2，原件 `../../reviews/P5-Supplement/DECISION.md`。这不是本轮结构修复或P5的通过结论，前端问题必须另修、分别关闭。当前不申请或声明 P5 整体通过。
