# P5 补充缺陷确认：OVC-P5-02

## 结论与范围

仓库仅为 `imherro/OurVideoCreator`。本次复读代码固定在 `5143ee36f55ab783f203832558cfedd4efce4936`，对应运行时代码 `0851dce02e0f22e87f6247b029fd3faedd39e7dd`。

**确认需要修复：OVC-P5-02，S2，P5 阻塞。**

这是客户端将新 revision 与旧正文组合后造成的静默覆盖，不是优化建议，不是 P6 功能，也不要求实时逐字共编。原 P5 首轮只列 OVC-P5-01 的问题清单需追加本项，不能据此宣称该时序已经验收安全。P0–P4 历史通过不变。

本次不是正在开发中的 P5-R1 正式复验，也不提前认定其 15 项专项结果通过；该轮仍按原结构修复任务独立交付。

## 实际读取的代码

- `src/objectDrafts.ts`：`remote()`、`acknowledge()`、`edit()`、`begin()`。
- `src/collaborationClient.ts`：`save()`、`mergeRemoteRows()`。
- `src/main.tsx`：SSE object 分支、`save()`、`acceptObjectDocument()`、`saveObject()`。
- `tests/collaboration_client.test.mjs` 和 `tests/object_drafts.test.mjs` 的现有覆盖。

## 触发前提成立

1. r2 已经由服务端提交；暂停的是成功响应交付，不是暂停请求执行或数据库提交。
2. 同一负责人另一个页面读取 r2 后，合法提交同对象 r3。普通镜头或自由节点不需要时间线租约，assignment epoch 可保持不变；不需要假设两个无权用户同时拥有编辑权。
3. 第一个页面在保存响应仍未到达时，通过现有对象事件分支取得 r3，并调用实际 `mergeRemoteRows()`。
4. 随后旧 r2 成功响应到达。在下一次有效对象快照纠正它之前，用户只修改 note 等另一字段，或后续自动保存处理仍显示的旧正文。

主页面的 object SSE 分支没有以 saveFlight 阻止这类读取；saveFlight 只协调本页保存，不会串行另一个页面的写入与 SSE。保存成功回调更新版本及对象列表，但没有将 acknowledge 内部采纳的 r3 正文同步回页面文档。

## 根因

`ObjectDrafts.acknowledge()` 先将 r2 回执标为 saved；发现先前缓存的 r3 后调用 `remote()`。在没有保存期间新输入的分支中，`remote()` 将 draft 的 base/content 换成 r3 并保持 saved。

但是 `CollaborationClient.save()` 把自己的 rows 写为 r2，baseline.parts 写为本次提交的 r2 内容；主页面正文同样仍可能为 r2。结果形成：

| 状态载体 | 值 |
|---|---|
| PostgreSQL / CAS 模拟服务当前对象 | r3 / v3 正文 |
| ObjectDrafts.base | r3 / v3 正文 |
| CollaborationClient.rows | r2 / v2 正文 |
| CollaborationClient.baseline | v2 正文 |
| 页面实际可编辑文档 | v2 正文 |

下一次保存读取页面 v2+新 note，经 `drafts.edit()`、`begin()` 生成 `expected_revision=3`。服务端 CAS 可以合法成功，但把当前正文改回 v2，产生 r4；这属于当前内容的静默丢更新，不声称历史版本不可恢复。

## 证据等级

实施端报告已用实际 CollaborationClient 和可控 CAS transport 得到一项失败。该新增测试原件本次未另行读取；不将实施端消息改写为审核端复跑证据。

审核端实际读取了以上固定 SHA 的代码及现有测试，确认其控制流支持上述交错，且主页面没有必然纠正该状态的回调。本次未独立运行新增测试、浏览器、真实 HTTP 或 PostgreSQL。

mock CAS 本身不会使这个客户端缺陷失效；关键是必须严格模拟真实 CAS 和提交先于响应交付的语义，不能无条件接受旧版本、跳过 epoch，或直接伪造实际页面不会执行的状态更新。

## 执行顺序

1. 当前单一任务仍为 P5-R1 / OVC-P5-01：完成结构修复，单独固定业务提交和证据，不混入本前端修正。
2. P5-R1 独立提交及取证完成后，下一单一授权任务为 **P5-R2 / OVC-P5-02**，按随附完整提示词执行。以届时 P5-R1 的实际最终提交为 base，保留其更改，不回退到 5143ee3。
3. 两项分别审查、分别关闭；P5 整体通过前必须关闭本项。不得自签 P5 PASS 或进入 P6。

## 最小通过标准

允许两种最小安全行为：

- 无后续本地编辑时，原子地让页面正文、client rows、baseline、drafts 都对应实际已应用的 r3，再允许下一次编辑。
- 或保留 r2 本地正文并进入明确 conflict，缓存 r3 供比较；在用户明确处理前不能取得 r3 作为旧正文的新保存基线。

有保存期间的后续输入时必须保留草稿，不可直接用 r3 覆盖。禁止通过屏蔽 SSE、刷新整个页面、丢弃所有迟到响应、自动提高 revision、无限重试，或放宽后端 CAS 来规避。

保存、SSE 和响应乱序中的不变量是：**生成保存票据所用的 revision 必须与这份可编辑正文的已知基线一致；自动接收新 revision 不能表示用户已经看到或明确接受新正文。**

## 固定来源

- https://github.com/imherro/OurVideoCreator/blob/5143ee36f55ab783f203832558cfedd4efce4936/src/objectDrafts.ts
- https://github.com/imherro/OurVideoCreator/blob/5143ee36f55ab783f203832558cfedd4efce4936/src/collaborationClient.ts
- https://github.com/imherro/OurVideoCreator/blob/5143ee36f55ab783f203832558cfedd4efce4936/src/main.tsx
- https://github.com/imherro/OurVideoCreator/blob/5143ee36f55ab783f203832558cfedd4efce4936/tests/collaboration_client.test.mjs
- https://github.com/imherro/OurVideoCreator/blob/5143ee36f55ab783f203832558cfedd4efce4936/tests/object_drafts.test.mjs
