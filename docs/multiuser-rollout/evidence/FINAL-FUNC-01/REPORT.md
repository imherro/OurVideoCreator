# FINAL-FUNC-01：当前约定功能范围收尾

状态：**READY_FOR_REVIEW**，请求外部最终功能验收；不预写外部通过。

## 版本与实际范围

- 唯一协作仓库：imherro/OurVideoCreator，master；不向 MyVideoCreator 推送。
- 起点：`1ca827212bdc411c7cccf093687482f47cdc9251`。
- 主浏览器链路：`7a54da479808b7f05d3fd78ff48d29b167fe20a3`；其业务运行时代码与 P6-SINGLE-01 已通过的 `c1b1695b6a2ef907647284bf1474a8d08537432f` 完全相同，只增加 FINAL 测试夹具模式与任务归档。
- 最终修复/测试候选：`018a6049bde4e47226ff41ff3b289d3496f75446`。业务差异仅 `backend/app.py` 删除入口增加一行保护、`collaboration_lifecycle.py` 当前引用检查、`collaboration.py` 原有引用解析原样提取复用。没有修改认证、锁顺序、公共事务实现、任务 admission/Worker、FFmpeg、前端、依赖或迁移。
- 浏览器前缀证据不改标成新 SHA。最终候选的补验包括真实 PG/API 删除与引用回归，以及同一隔离数据上的新 Web 5459 页面持久性读取。新 Web 不另启 Worker、不提交 Provider 任务。未受影响的页面创作、候选、剪辑、导出前缀继续有效。
- evidence HEAD 是随后仅归档文档/脱敏记录的提交，完整 SHA 在送审消息提供。

P0–P5 和 P6-SINGLE-01 历史通过不变。本任务承接当前集成功能收尾，不表示原 P7/P8 全部条目或九阶段全部通过。P7-RECOVERY-01 暂缓且未开始；不自动继续任何新阶段。

## 六项证据

| ID | 本轮实测及继承依据 |
|---|---|
| FUNC-01 | A/B 是平台普通 user、作品 editor，不使用初始化管理员编辑。实际页面各自保存镜头 A/B 动作；B 不刷新即收到 A 的新动作；双方刷新后正文都保留。`browser-tools.json` 是实际工具调用/返回，`browser-db.json` 有对象、历史和审计。服务端分工拒绝继承并重跑 `test_p5_object_transactions.py::test_two_editors_independent_objects_and_no_management_bypass`，不以按钮禁用替代 ACL。 |
| FUNC-02 | 页面提交 2 个图片、1 个文本任务，由一个独立 Worker 调用 loopback fake。三项都先比较、再明确采纳 r3；文本人工正文在采纳前保持 P5 initial v1。A/B 各自提交审核 r4，普通 manager M 确认到 r5/completed，未接管或提升编辑者权限。任务/对象/审计和 fake 账本在 `browser-db.json`。 |
| FUNC-03 | A 申请现有时间线租约，将 B/A 两张图片各设为 2 秒，加入标题，保存到 timeline r10；B 可读取，但对象面板的保存/申请租约/审核按钮不可用。刷新后 V1/T1、4 秒、标题和成果保持。页面导出经真实 Worker/FFmpeg 成功，见下方任务 ID；`media-check.json` 是实际 ffprobe 和完整解码命令、输出、退出码。 |
| FUNC-04 | 新 `tests/test_final_functional.py` 在真实 PG 上验证同作品跨分集时间线引用、A/B 读取、无权用户 404、被引用素材删除 409、来源分集软删除后素材仍可读、移除引用后软删除/恢复。现有 `test_api.py` 验证其他作品引用 400/嵌套对象 404，旧锁定视觉引用删除预期修正为拒绝。P3 ACL、签名/撤权及 Range 相关用例继续有效；本轮定向重跑对应 P3 两项。 |
| FUNC-05 | 主链实测 B 页面不刷新接收 A 保存。脏草稿/晚回执继承 P5-R2 `aebffe364313601aceb611fbcd0ca2b01a42e29d` 的 `evidence/P5-R2/REPORT.md`、`commands-aebffe3/`：49 项专项、195 项前端；src 至最终候选 Git 等同。重连与撤权补跑实际 PG 的 `test_p2_r1_sse_event_ids_follow_commit_order_and_rollback_gaps_reconnect_safely` 和实际 SSE `test_event01_02_live_sse_filters_tenants_and_stops_after_membership_and_session_revocation`；不要求窗口外无限补发。 |
| FUNC-06 | 一处已复现素材删除缺陷按本任务修复；保留 P5 结构原子校验、晚回执、P6 提交幂等必要回归。未改能力沿用原证据，不重新签发历史阶段。无依赖/迁移/后台页面新增；四项未验边界见末节。 |

## 实际链路、任务及媒体

隔离 PG 18.6：loopback 55438；浏览器数据库 `ovc_test_33184_2595cd697016`。Web A/B/M 为 `127.0.0.21:5456` / `.22:5457` / `.23:5458`，独立主机 Cookie 上下文；新修复 Web 为 `.23:5459`。数据目录是本轮新建临时目录，未连接用户或历史实例。

原 Web PID 41108/38208/42648，单 Worker 25872，夹具 33184；修复 Web 16992。测试数据、媒体及这些本轮资源保留，未删除历史库/草稿或停止用户服务。本轮 pytest 仍按既有夹具仅创建、回收其精确命名临时测试库。

浏览器作品 `production-6120005f1400401db7ace325435b97a8`，分集 `project-e6f8b73de9d94c6c9803ee40f81dd41e`。

| 类型 | Job | 产物 |
|---|---|---|
| A 图片 | `job-d588f3b237cf47f5a1ceac70d886e2df` | `asset-317fb69eb17a49a9a964c574e209b6c6` |
| B 图片 | `job-147d841be3984fe084fa73d20f4a1288` | `asset-e2d5ac8a64294b57a762e50d805c8860` |
| 文本 | `job-0896e47e973f479bb3573d29763f7edd` | FINAL 功能收尾：两名成员合作完成短片。 |
| 导出 | `job-a9d5c4b4bf3c43f9829b7ce098bb8589` | `asset-55170aa2b376478b9836d8570c431118` |

fake 账本是 **3 次生成 submit POST = 2 图片 + 1 文本，2 次 poll GET，2 次 PNG download GET**。导出是另外 1 个本机任务，不调用 fake，不是第四次 Provider 生成。没有真实付费供应商请求。

MP4 实测 4.000 秒，1280×720，24fps，H.264 96 帧 + AAC，13885 字节；ffprobe exit 0，`ffmpeg -v error -i <本轮MP4> -f null -` exit 0、无解码错误。这里证明本地实际解码；不把页面的“正在同步预览”提示或文件链接当作已证实的浏览器播放。刷新后页面“成片.mp4 / 4.0 秒”和时间线仍可见。

正常使用顺序：管理者按对象分工 → 成员编辑并保存 → 选平台已发布模型生成 → 比较候选、明确采纳 → 提交当前版本给管理者确认 → 时间线负责人申请租约、加入素材/标题并保存 → 导出成片。另一成员等待或只读，不做同时共编。图片可直接加入时间线；“生成初剪”要求已有视频，不能以只有图片调用它替代视频。

## 缺陷及如实保留的过程

**FINAL-01：被引用素材可软删除，导致其他分集时间线悬空。** 新 PG 测试先保存跨集引用，原接口返回 200/soft，而非预期 409；媒体读取原实现会排除回收站资产。最小修复在既有 lifecycle 独占屏障内检查同作品当前未删除 collaboration_objects；拒绝删除并明确提示先移除引用。引用提取复用原验证器，ID 和媒体 URL 语义不变。保留可恢复分集中的引用，不扫描不可变历史，不建设全局引用计数/GC。

旧 API 测试曾允许删除正在使用的锁定视觉素材，现改为 409 并核对文件与列表仍在；无引用后的软删除/恢复覆盖移至新增测试，未删除功能覆盖。

开发过程不累计到最终测试结果：

- 首次夹具在 f7df431 配置图片适配器时失败（该适配器要求 API Key）；7a54da4 改为本轮随机合成凭证，没有放宽校验。失败夹具资源保留。
- B 首次图片操作遇到并发画布结构 CAS 冲突，没有创建第二个任务。比较显示两边分别增加 A/B 图像至视频的边；显式放弃该对象草稿并载入远端后重提成功。镜头正文未被丢弃；不是“全程无冲突”。
- 跨集删除新回归原版 1 failed；首轮修复漏解码 TEXT JSON，2 failed；修正后新用例通过、旧锁定视觉夹具试图移除引用被原契约 400 拒绝，1 passed/1 failed；改为保留锁定引用、把无引用删除/恢复放入新用例后 **2 passed / 13.66 秒**。
- 第一次专项命令误写不存在的 test_p6_single_idempotency.py，exit 4/no tests ran；随后改为实际 P6 三个文件，没有将其记作通过。
- 最终 Web 页面尝试删除仍被引用的 B 图片，出现 JavaScript 确认框；调用浏览器对话框接受后没有观察到 DELETE 请求或拒绝提示，因此**不计作页面删除拒绝成功**。修复功能的证明是实际 PG/HTTP 回归；该页面补验只证明新 Web 能读取同一持久化成果。没有请用户手动点框，也没有伪造结果。

## 回归、命令与继承

日期 2026-09-17，主浏览器开始 UTC 02:44:45；实际调用/返回逐条时间见 `browser-tools.json`。无统一浏览器进程退出码，不虚构 browser exit 0。

固定候选定向命令：

```text
python -m pytest -q --tb=short tests/test_final_functional.py tests/test_api.py tests/test_p5_lifecycle.py tests/test_p5_object_transactions.py tests/test_p5_r1_structure.py tests/test_p5_relation_candidates.py tests/test_p6_admission.py tests/test_p6_single_chain.py tests/test_p6_single_resources.py tests/test_p3_identity_acl.py::test_acl01_to_08_role_matrix_nested_ids_files_jobs_trash_and_admin_boundary tests/test_p3_identity_acl.py::test_media04_signed_capability_binds_asset_method_purpose_expiry_and_revocation tests/test_p3_identity_acl.py::test_event01_02_live_sse_filters_tenants_and_stops_after_membership_and_session_revocation tests/test_p2_r1.py::test_p2_r1_sse_event_ids_follow_commit_order_and_rollback_gaps_reconnect_safely
```

实际结果 **99 passed，2 warnings，409.38 秒，exit 0**；2026-09-17 UTC 02:58:10 启动，03:05:27 读取到完成结果，见 `targeted-018a604.txt`。两条是既有 websockets/uvicorn 弃用提示。错误文件名的首轮命令日志是 `targeted.txt`（exit 4），不覆盖或相加。

不重新跑完整 490 项：本次没有改变认证、公共事务、锁顺序或任务主链，按任务授权只补跑受影响的媒体/API/生命周期/引用/结构/候选及 P6 必要专项。未改其余后端继承 P6-SINGLE-01 `c1b1695` 的 **490 passed / 2 warnings / 1126.57 秒**及外部通过 evidence `026cddf92776595164e752fea704444daea1f871`；不声称完整后端在 018a604 重跑。

本轮为页面准备执行 `npm run build`，exit 0，1837 modules / 6.74 秒，已有大 chunk 提示；bundle `index-CuW21jP_.js`。最终 src/依赖不变，继承 P5-R2 195 项前端及 TS/build；不声称本轮重跑195项。最终 `python -m compileall -q backend tests` 和 `git diff --check` exit 0。

公开材料只保留必要合成对象、任务、事件、审计、fake 请求及实际浏览器返回；由 `collect.py` 导出。测试登录输入和本机用户目录脱敏；不导出 Cookie、密钥、完整 DSN、原始 HAR 或整个数据库/媒体。原始记录保留本地，未重写断言或隐去失败。

## 四项独立边界

1. **运维暂缓**：未做备份恢复、Docker、部署、HTTPS、上线；P7-RECOVERY-01 未开始。
2. **容量未验**：本轮小样本功能链不是压测或生产容量认证。
3. **真实供应商未验**：fake/协议范围已验；没有真实付费调用或全供应商/格式矩阵。
4. **旧 P6 平台延期且未启用**：多 Worker、完整配额、公平调度、逐步骤自动恢复、人工对账继续延期。

待本任务外部功能验收后停止，不恢复任何延期计划；Codex 不自行签发 PASS。
