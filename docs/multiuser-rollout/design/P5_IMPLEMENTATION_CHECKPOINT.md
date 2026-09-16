# P5 开发检查点（非交付、未提交验收）

2026-09-17，当前仍是同一任务 **P5-COLLAB-01**。P4 外部通过原件及完整 P5 提示词已归档，GATE_LOG/阶段索引已同步。基线 HEAD `c0152ffcfb5623fcc0b723dbdf450acec9f17f73`；本检查点代码尚未提交、推送或用于正式验收。

## 已有中间实现

- 新增显式 Alembic `0004_object_collaboration`：对象内容/负责人/revision/epoch/租约、历史、评论；未修改前三个迁移，未导入旧业务内容。
- `backend/collaboration.py` + scoped routes：逐对象保存、原子批量保存、显式分配/接管、审核、历史恢复、评论、时间线 lease。身份共享锁与 P3 成员变更独占锁配合；数据库锁等待后重新核验会话与租约时间。成员移除/降为 viewer/停用账号使对象待分配、epoch 前进、租约失效，内容保留。
- 稳定素材 ID 的嵌套引用复核；批次混入越权对象、旧 revision 或跨作品素材全败。
- `src/objectDrafts.ts`：逐对象保存状态、保留冲突草稿、禁止定时器重发冲突、迟到查询/保存响应与分集隔离。
- `src/collaborationDocument.ts`：既有编辑文档按镜头及子节点/自由节点/视觉卡及音色/结构/时间线/导演台拆分；私人 UI 状态不进入保存。
- `backend/collaboration_document.py`：只读聚合纯函数，明确忽略旧 metadata 中残留的大文档内容，避免它覆盖对象。
- `src/editor/legacyTimeline.ts`：旧 Clip 导入为单一 Twick 时间线、只读 Clip 投影，保留 trim/音量/音乐/稳定素材 ID。
- 新 Episode 创建时初始化 graph/timeline/director；`read_project_state` 已接只读聚合，`project()` 返回当前对象列表。六种严格 envelope、不可变语义 ID、子节点独占归属、跨集素材验证、Film Bible 锁定版本和音色校验已接入。
- 原子 `/objects/commands` 支持受控结构创建/更新/删除；修改依赖边先按统一顺序锁定目标对象负责人行。历史恢复复用相同命令和锁序，避免 restore 独立路径绕过竞争校验。创建唯一键锁等待后再次核验 timeline lease 实际时间。
- 实际 `main.tsx` 自动/手动保存已切为对象命令；元数据用白名单 PATCH，旧大文档 PUT 返回 410。`CollaborationPanel` 已接入分配/接管、逐对象保存和比较、审核、历史恢复、评论与 lease。409 不自动提版本重发；明确比较后提交使用当时比较的 revision，仍可能再次 409。
- 时间线统一写入：简剪修改转换到 Twick 主轨、保留其他轨和字幕；背景音乐及导出设置存入 timeline，root 字段仅作投影。前端单元测试验证 trim/音量、其他音轨、间隙和字幕保留。尚须最终实际 FFmpeg 回归。
- 虚拟视觉节点与正式剧本投影的 graph 位置在 GET 后保留。派生 stale/counter 的单独变化不再触发对其他负责人对象的保存；真实提示词、结果引用、fingerprint、state_reviewed 仍受对象 ACL。自由节点跨对象依赖的重读过期判断仍须与候选结果 provenance 一并补齐。

## 不能误报为完成的部分

当前已接实际前后端对象保存/读取，不再是未接线的纯函数。已有两个普通 editor 的浏览器中间验证，但尚未覆盖全 COLLAB-01…12，也未固定业务 SHA 取最终证据。

正式剧本/source 关系表及对应负责人 UI、草稿保护、历史恢复已接线并做中间验证（见下方最新记录），但生成目标冻结与候选/采纳、旧 Worker/visual-reference 自动回写入口收口仍未完成。浏览器任务成功的自动 accept 已移除，但服务端仍有旧回写；不能声称全部生成已安全候选化。完整 P5 不能停在目前 UI 闭环，不能请求外部通过。

## 当前开发验证（不是最终 SHA 绑定证据）

- 最初对象事务 8 passed（28.78s），含真实 PG 同版本等待链、一成功一 409、不同镜头不互相阻塞。
- 对象事务加 P3 身份 ACL 回归 28 passed、2 条既有依赖弃用 warning（97.57s）。
- 扩展对象专项 15 passed（51.85s），包括四种撤权、批量回滚与嵌套跨作品素材；随后微调 singleton 创建锁后会话复核，需继续重跑受影响测试。
- 聚合纯函数 3 passed（1.68s）。
- 前端完整 141 passed；TypeScript/Vite build 通过（1827 modules，8.29s），保留 >500 kB chunk 警告。
- 路由审计：111 registered / 108 API classified / 0 unclassified；compileall、git diff --check 通过。
- 前述完整后端 pytest 已结束：383 passed / 2 条依赖 warning / 594.50s。它在当前严格 envelope、对象实际切换和旧 PUT 410 **之前**开始，且漏掉 collection 后新增测试，故只是旧阶段回归基线，不能作为当前代码全量通过证明。旧 API 测试夹具仍需改用对象命令且保留业务断言。

### 2026-09-17 03:08 左右继续验证

- 严格对象+聚合先前 18 passed / 51.64s；当前对象事务+聚合+实际集成 23 passed / 67.58s（后来又新增一项 projection 测试，不在 23 的 collection）。
- 最新聚合+实际集成 9 passed / 17.85s；metadata 素材引用/嵌套类型检查后集成专项 5 passed / 17.53s。补齐字段负例与风格版本单调测试后，最新专项 **6 passed / 21.11s**。风格变更推进 styleVersion，但不更新其他负责人镜头 revision。
- 保存适配器、聚合和时间线 23 passed；再补“租约响应迟到不能触发旧工程保存”后，完整前端最新 **158 passed** / 1009.35ms；TypeScript 和 compileall 通过。`openProject` 也在读取返回后再次检查是否新增本地草稿，防止载入期间的编辑被覆盖。
- 构建成功：1833 modules / 7.95s；保留已有 >500 kB chunk 警告。这次构建用于下面浏览器中间验证；之后派生状态比较、投影位置及 metadata 检查又有源码修改，浏览器验证不冒充最新全部源码验证。
- 路由审计最新：114 registered / 111 API classified / 0 unclassified，fail-closed 保持。`git diff --check` 通过，仅 LF→CRLF 提示。
- 中间红转绿：一次新增时间线保留断言失败，原因是测试 fixture 对话音轨缺标准 asset metadata，adapter 正常补齐；补齐标准夹具后保留完整等值断言通过。更早严格结构请求曾暴露 KeyError，已改为入锁前 envelope 验证并重跑通过。未删除业务断言。

### 实际浏览器中间验证（非最终 SHA 证据）

新增 `tests/p5_browser_harness.py`，通过公开注册/成员/对象接口创建两个普通 editor、manager 和 viewer；只有初始 test owner 使用现有 bootstrap helper。零 Provider、零模型、零 Worker、零付费调用。

- 自有目录：`C:\Users\kunpeng\AppData\Local\Temp\ovc-p5-browser-5hid254t`。
- 自有库：`ovc_test_38832_16f1e849c66a`；harness PID 38832，web PID 39544 / 34948。
- 两个 cookie 隔离的本机入口：`http://127.0.0.3:8010`、`http://127.0.0.4:8015`。后台启动，不绑定公网。
- Project `project-acb4ef9e0f3549aaba9153836558cf36`；完整资源 manifest 在该目录。未将测试口令写入本记录或验收材料。
- A/B 在真实分镜表各编辑自身镜头并保存；各自刷新及退出重登后均读到 X/Y 两份内容，角色界面均是 editor。B 镜头 r2 提交审核到 r3/待确认，评论实际回显。
- A 时间线租约实际申请/续租/释放，释放后界面显示“本页尚未取得租约”；竞争/过期/接管的最终浏览器覆盖仍待补。
- A 第二页在同一 r2 编辑同镜头，真实 `/objects/commands` 返回 **409**；保留本地草稿、显示冲突。CDP 观察冲突后至明确操作前仅 GET，无额外 POST。比较远端 r3 后点击“已比较，明确提交此对象草稿”，实际命令 **200**，面板显示 r4/已保存，B 镜头不变。
- 已用 computer-use 的实际 DOM/网络事件/截图检查，不以 source grep 替代；原始调用返回在本 Codex 运行记录中。尚未制作正式 evidence/P5 包，不把手工摘要称原始完整证据。
- 浏览器 tabs 5(A)/6(B)/7(A 第二页) 已标记 handoff，服务保留供后续测试；浏览器仍加载上述已构建版本，后续代码变更须重建、必要时仅重启本轮自有进程，再 reload 验证。

所有测试仅使用独立 `ovc_test_*` 数据库和 loopback，不调用付费 Provider。未停止或重启保留的 7868/7895/6313/6185/7028 服务，未修改它们的数据库；未开始 P6。

## 紧接着的实现顺序

1. 原文/剧本既有关系表补负责人/epoch/版本，小接口和原子批次补 ACL；Production 改编/策略按 manager/owner 控制。导演台 capture/导出小接口补对象边界。
2. 所有生成入口统一冻结真实目标 ID/revision/epoch 和必要引用；Worker 只登记候选/素材；显式采纳在当前权限和 expected_revision 下原子写回。重点检查 app.create_job_record/submit/run/audio、visual_references.record_visual_reference_submission、worker.text 的 apply_* / replace_events，及 main.generateVisualReference 的整份 project_document 回写。
3. 将旧接口回归夹具改用对象命令但不删业务断言；补齐来源指纹/stale 的跨对象只读派生，保持 P4 模型/凭证边界不变。
4. 两普通 editor 浏览器完整 COLLAB-01…12 + 当前完整后端/前端/TS/Vite/ACL/FFmpeg 回归；固定业务 SHA 后新建 evidence/P5，docs-only 证据提交，推送 origin 再发主 ChatGPT 验收。未完成这些不能标 READY_FOR_REVIEW；P6 未授权。

### 后续续做：既有章节/剧本所有权（本轮尚未提交）

- 显式新增 `0005_owned_source_scripts`，未重写旧迁移：在现有 episode_scripts/source_chapters 上加 assignee、assignment_epoch、created_by/updated_by；章节审核状态/历史和关系表评论。正文仍只有现有表一份，历史旧内容不导入新对象表。新测试库成功执行完整迁移；保留的所有服务/数据库均未迁移或重启。
- `owned_content.py` 复用 P3 身份共享锁、实时会话校验及对象 revision/epoch 检查；负责人分配、撤权、历史、审计/SSE 同事务。撤权后保留正文、置待分配并推进 epoch。
- 章节创建/导入由会话确定作者和负责人；章节 PUT、正式剧本 PUT/review 强制负责人和版本/epoch，manager 不可静默改正文。剧本 approve/needs-changes 仍由 manager 执行且绑定版本/epoch。
- 新 `owned-content/{chapter|script}/{id}` 小接口提供 assign/history/comments；viewer 可评论不能夹带字段；章节 submit/approve/return 已接。剧本沿用原审核接口中的改编就绪检查。章节修改已完成内容会回到 in_progress。
- 整本原著删除须 manager 显式接管每个当前章节，并提供完整版本集合；章节批量删除先逐项校验，旧版或无权条目使全批失败。单章节 DELETE 也须 body 中 revision/assignment_epoch。Source 父行 KEY SHARE/UPDATE 协调章节编辑与整本删除。
- 新 Episode 的 script seed 仅针对调用方新建 project_id，不再扫描全部项目、复制旧画布正文；既有分集缺 script 不自动修复导入。
- 改编 GET 不再隐式持久化“默认格式升级”；改编保存/审核执行事务内 manager 校验。派生 stale 时 Production 与目标脚本加行锁，防止无锁覆盖 revision。
- 现有 ScriptRoom、SourceLibrary 和 main 的请求已携带 epoch，删除携带逐章版本；但**负责人分配/评论/历史 UI 与原文、剧本页面的 dirty/迟到响应保护尚未接好**。不要误认为单纯添加请求字段已经完成前端闭环。

最新开发测试（不是固定 SHA 验收）：

- `test_p5_canonical_integration.py`：6 passed / 22.00s（本轮初期）。
- `test_p5_owned_content.py`：最初 9 passed / 34.05s；增加删除用例后，组合运行 24 passed / 1 failed / 96.95s，失败是测试误用不存在的 `/api/auth/me`。改为真实 `/api/auth/status`，保留全部断言，最新专项 **10 passed / 43.58s**。两类内容各有真实 PG 阻塞轨迹的一成功一 409；覆盖 ABA、manager 须接管、撤权保留、评论、审核和删除全败。
- 最新前端 **158 passed / 899.2892ms**；`npx tsc --noEmit` 通过。此次没有重新 build 或浏览器验证，不以先前浏览器替代本轮新接口证据。
- 实际路由审计 **119 registered / 116 API classified / 0 unclassified**；compileall、diff --check 通过（仅已有 LF→CRLF 提示）。

下次优先续接：章节/剧本页负责人和评论历史控件，复用逐对象草稿逻辑防止 refreshKey 覆盖；关系表历史恢复；source/chapter 软删除后的恢复/旧代际与 create 等待后的 deleted 状态复核；画布提升正式剧本必须移除原 free node 主源并同时核两对象/结构权限，目前仍读旧 projects.document，不能算已修复。之后是全部生成候选/采纳入口、director capture、全量旧接口夹具适配与最终验收矩阵。所有旧 Worker 自动回写仍是未闭合项。

### 再次续做：关系表页面实际接线与浏览器验证

- `OwnedContentDrafts` 只适配既有章节/剧本小 API，复用 `ObjectDrafts` 状态机；`OwnedContentPanel` 接入实际 SourceLibrary/ScriptRoom 页面，提供负责人、显式接管/分配、评论、历史恢复、冲突比较/明确放弃/明确提交。脚本审批仍走其已有改编就绪检查，不能借通用章节审核绕过。
- 草稿 store 放在 Workspace 中，切工作流页面不会丢失；切作品/分集/团队前检查未保存关系表草稿，载入返回后再次检查；页面刷新远端只合并干净内容。保存请求冻结字段/版本，打字发生在保存过程中时保留后续输入；409 不自动升版本或重试。对已删除的未保存对象保留复制与明确放弃入口，避免无解地阻挡切换。
- 增加关系表 GET detail/POST restore：恢复只复制正文业务字段，不恢复旧负责人/epoch；追加新 revision，回到 draft/in_progress，当前 ACL 与来源引用仍校验。
- 修正共用 `ObjectDrafts.acknowledge`：较新远端版本先于旧保存响应到达时不丢失；新前端用例覆盖此顺序。
- 新增 chapter/script SSE 触发页面刷新；主保存按钮与 Ctrl+S 路由到当前章节/剧本对象，不再只保存背后的画布而忽略正文。最后这项在第一批浏览器验证后加上，随后重新构建并验证 Ctrl+S（见下）。
- 章节写入、source 新建章节等待行锁后重新查询 deleted_items，避免 SQL 首次快照在等待期间过期后仍写已删除内容。专项使用真实 PG 阻塞和提交轨迹验证 save/create 两路径。

测试：

- 关系表专项 12 passed / 49.02s（新增两种历史恢复）；随后 tombstone 等待链专项 2 passed / 8.58s，12 deselected。组合 P5（关系表、对象事务、实际聚合集成、投影）**37 passed / 123.57s**；两个 tombstone 用例在组合 collection 之后新增，因此另报，不冒充该次 37 包含它们。
- 前端最新 165 passed / 1014.761ms；TS 通过。最初新增模块使用 Node strip-only 不支持的参数属性，测试启动失败；改为普通属性声明及显式 .ts import 后全部通过，未削弱断言。
- 两次构建均通过，最新用于浏览器的构建 1835 modules / 7.98s，仍有 >500 kB chunk warning。浏览器验证后 added unavailable-draft discard、全局保存路由及后端 tombstone 复核，没有把这些变化算作已做浏览器验证。
- 路由审计 121 registered / 118 API classified / 0 unclassified，compileall 和 diff --check 通过。

真实浏览器中间验证（不是固定 SHA 正式证据）：

- **新建独立资源**：目录 `C:\Users\kunpeng\AppData\Local\Temp\ovc-p5-browser-fw77cli8`，数据库 `ovc_test_29836_a1355ee08feb`，harness PID 29836 / web PID 18476、15596。新入口 `http://127.0.0.5:10548`、`http://127.0.0.6:10549`；独立 cookie host，不升级或重启原有 8010/8015 及 P4 保留资源。
- harness `--owned-content` 用公开接口为 A/B 各建章节，并将正式剧本分配给普通 editor A；零 Provider、零模型、零 Worker、零付费调用。
- A 编辑章节未保存，点页面刷新仍保留；切剧本再返回仍保留。B 看到 A 章节只读、保存禁用，自己章节可独立保存到 r2。A 保存章节后 B 重读看到相同正文。
- A 剧本草稿跨页面保留，保存到 r3，浏览器 reload 后仍有相同正文。B 退出后通过正常登录切 manager；manager 接管前字段与保存禁用，点击“明确接管到我”后 r4/epoch3、获得可编辑状态。
- A 的另一份未保存剧本草稿在 manager 接管后保留为冲突；比较后点击明确提交，页面拒绝复用旧 epoch，未丢草稿。该测试结束后明确放弃测试草稿，并刷新到 r5/epoch3，显示 manager 所有、正文只读。
- manager 从历史 r3 点击“恢复为新版本”，实际回到相同正文但产生 r5，负责人仍 manager；评论实际回显。已检查最终页面截图，协作控件在现有剧本室内正常排布。
- tabs 8（A）、9（当前 manager）已标 handoff。最新服务保留供继续测试；所有浏览器工具调用、DOM 返回与截图在运行记录，尚未固定 SHA 制作 evidence/P5。

补充最后验证：最新前端再次构建通过，1835 modules / 8.24s，chunk warning 保持。manager 标签 reload 后修改剧本正文，用实际 `Control_L+s` 提交，界面从 r5 保存中变 r6 已保存；A 页面刷新读到 r6 的相同正文且只读。最新 unavailable-draft 放弃控件已进入该构建但尚未专门浏览器触发。服务未重启，最后后端 tombstone 锁后复核由上述真实 PG 测试验证，不冒充已在保留浏览器进程载入。

接下来优先：正式剧本画布提升双主源问题、director capture、全部生成入口的冻结/候选/明确采纳（包括 source/adaptation/scripts/visual/voice/节点/双遍分镜），软删除/恢复旧代际补审；再适配旧测试夹具并跑完整回归和最终 COLLAB 浏览器矩阵。不能停在本轮 UI 子闭环宣布 P5 通过。

### 本轮续做：画布提升、导演台截图与关系表生成候选

当前仍未 commit/push，HEAD 保持 `c0152ffcfb5623fcc0b723dbdf450acec9f17f73` / master；origin 为协作库，upstream push 仍 DISABLED。浏览器已重读主 ChatGPT 会话末尾，最新仍是 P4-R1 通过并授权 P5-COLLAB-01，与本地完整提示词一致；没有 P5 通过结论或 P6 授权。

已实现：

- `collaboration_actions.py` 新增两个小命令：`script-promotion` 在同一事务核正式剧本、自由文本节点、graph 的当前负责人及 revision/epoch，将节点正文保存至正式剧本并移除自由节点主源，保留同 ID 的只读投影及合法出边；旧 ScriptSave.canvasNodeId 明确 410。普通 editor 可提升自己同时负责的两个内容对象，manager 不能绕过接管。
- `director-captures` 核导演台负责人/revision/epoch、graph 版本及当前分集已上传图片，在同一事务创建图像节点和结构，记录 stage/asset 来源，不修改 stage 内容。上传和图片解码仍在事务外，素材注册前重新校验活跃身份与作品权限。无效 node envelope 在使用 ID 前拒绝，不以 KeyError 返回 500。
- main 的实际提升/截图回调已改为上述命令，冻结版本并检查作品代际；上传/保存期间 stage 或正文变化会拒绝继续。请求期间新增草稿保留，不因操作完成覆盖后续编辑。当前这些新回调有 TS/build/API 验证，**尚未做本轮浏览器操作验证**。
- 显式新增 migration `0006_job_candidate_targets`，只在现有 jobs 增加 JSONB `collaboration`：冻结 target、必要来源版本、明确采纳收据。候选正文复用 jobs.result，不另建队列或重复正文主源。没有升级任何保留服务数据库；新隔离测试库自行完整迁移。
- `job_candidates.py` 当前只完整接入 chapter/script/adaptation。原著章节批量提交先稳定排序锁全批并核各负责人；剧本提交核负责人、规划指纹和原著 revision/epoch；改编提交限 manager。P4 模型/凭证冻结继续沿用。普通对象任务暂返回空 target，**不能误认为所有生成入口已经完成对象授权**。
- Worker 的原著事件/改编/正式剧本三条分支仅校验并返回候选，不再写主数据。旧 apply_adaptation_generation / apply_episode_script_generation / replace_events 改为明确拒绝的退役函数，旧写入主体已移除。事件写入只由候选命令在已锁定授权章节的事务内调用。
- `GET candidates/{jid}` 返回候选及当前内容用于比较；POST adopt 核成功状态、当前负责人/manager、expected_revision/epoch、来源指纹/版本。默认拒绝目标修改/重新分配后的旧候选；比较后用户可显式 accept_stale，仍须提供当前版本和当前负责人的权限。来源规划/原著快照变化仍拒绝，不允许 accept_stale 绕过来源检查。正文/事件、历史、审计、SSE、采纳收据同事务，一次采纳只成功一次；脚本/改编采纳回 draft，不自动批准。
- `CandidateReview.tsx` 接入现有任务中心，显示“候选尚未写入”、当前内容与候选 JSON、版本/epoch 和明确采纳按钮，viewer/非负责人仅查看。Workspace 的采纳回调先阻止未保存草稿，检查当前作品/代际；完成后只在无新草稿时刷新投影。原来“脚本任务成功就重新载入整份画布”的逻辑已删除。
- ROUTE_AUTH_MAP / P5_OBJECT_COLLABORATION / README 阶段描述已更新。未把 P5 改成通过或 READY_FOR_REVIEW。

本轮实际测试（开发工作区，非固定 SHA 正式证据）：

- action 专项首跑 **7 passed / 1 failed / 32.84s**。失败是新测试的 EpisodeCreate 夹具错误使用 episode_no/name；改成公开 API 的 title，保留跨分集素材拒绝断言。补真实 PG 行锁等待后导演台版本变化用例。其后 actions + 原 P5 组合 **48 passed / 162.14s**（这次启动早于 0006，不冒称包含新候选）。
- 新 relation candidates 首跑 **3 passed / 2 failed / 30.73s**：两个迟到 HTTP 用例已得到正确候选，断言因章节 list/detail 的展示字段不同、错误 `/events` 路径失败。改成在 fake 阻塞期间从同一 detail API 取得人工修改后的完整快照，再比较 Worker 返回后的同一快照；事件改用真实 `/source-events`，没有删业务断言。第二跑 **5 passed / 28.64s**。
- 最终当前 P5 六文件组合（relations candidates、actions、canonical、objects、owned-content、projection）**56 passed / 212.02s / exit 0**，包含新增候选竞争和来源变更拒绝用例。真实 PG 在 loopback 55434 下的独立 `ovc_test_*` 库，测试结束只清理该次自有库。
- 两个 source 迟到用例实际经发布模型、任务 API、冻结 P4 binding、Worker.execute 和 guarded HTTP/SSE；自有 loopback fake 在收到原文 v1 后通过 Event 屏障阻塞，分别人工正文 v2 / 分配给 B 后放行。结果成功但不改主数据；旧版本采纳 409，非负责人/manager 未接管 403，新负责人明确比较旧候选后采纳成功，重复采纳 409。每例 HTTP 一次，零真实供应商调用。
- 两个候选竞争同一 chapter revision 使用真实 PG blocker/waiter 轨迹，精确一 200 / 一 409，只有一份采纳收据和一次 revision 增量。原著正文变化或仅 assignment epoch 变化均阻止旧剧本候选采纳，不留下历史/收据半写。
- 剧本及改编的计算路径测试替换 `_chat_text` 返回值来验证候选契约，**不冒称这两条各自有真实 HTTP 或浏览器验证**；保留上面两个 source 的真实 HTTP 测试边界。
- 当前前端 **165 passed / 926.1168ms**；TS 通过，最新构建 **1836 modules / 8.55s / exit 0**，原 >500 kB chunk warning 保留。CandidateReview 尚无本轮真实浏览器交互证据。
- 实际路由审计 **125 registered / 122 API classified / 0 unclassified**；ACL-09 注入新未分类路由专项 **1 passed / 1.11s**。compileall 通过；diff --check 发现并修正 source_library.py EOF 空行，最终再核对。既有 LF→CRLF 提示保留。

资源和下一步：

- 未新开、停止或重启任何 Web/Worker，也未升级保留的 7868/7895/6313/6185/7028、8010/8015、10548/10549 数据库。现有 10548/10549 后端仍是先前版本，不支持本轮新候选 API；不能用保留页面冒称新后端验证。dist 已更新，后续完整验证要启动新的自有隔离 0006 环境，不自动迁移旧实例。
- 主会话 tab1、原著/剧本测试 tabs8/9 再标 handoff；仅阅读 ChatGPT，没有发送未完成验收请求。
- 紧接着完成普通 node/shot、visual_card/voice、storyboard（含双遍）的统一目标冻结与明确采纳；`app.submit/run/audio` 的旧参考编译版本检查、`visual_references.record_visual_reference_submission` 仍写 shared_context、`main.generateVisualReference` 接收 project_document、`main.adoptShots` 本地聚合导入等仍需收口。Worker.video 仍读旧 projects.document 做 state review，须改 canonical。
- 随后补 source/chapter/project/asset 软删除恢复与旧凭证代际审查，适配旧回归接口夹具（特别 test_source_library/test_adaptation 的自动写断言要改为候选→明确采纳，不能删行为覆盖），完整后端/P4/Provider/FFmpeg 回归、COLLAB-01…12 两用户浏览器矩阵，固定业务 SHA 后正式证据包、push origin、主 ChatGPT 外部验收。
- **本轮未跑当前完整后端、未准备正式 evidence/P5、未提交/推送、未宣布 P5 完成；goal 保持 active。**

### 续做：普通对象候选、音色/视觉采纳及显式对白音轨

仍在 P5-COLLAB-01，未 commit/push，未进入 P6。以下为开发工作区验证，不是固定 SHA 外部验收证据。

- 新增 `object_job_candidates.py`：根据实际自由节点/镜头附属节点/视觉版本/音色卡/对白所属镜头解析真实目标，不信任任意 node_id；提交冻结对象 revision/epoch、必要上游/graph/视觉音色/正式剧本引用版本及作品/分集元数据 revision。身份 shared lock → Production → Episode → script → 排序后的对象短事务；不存在/无权目标、冲突 marker、版本变化均拒绝。普通节点无入边也冻结 graph，防止准备期间新增边。
- `app.submit/run/audio-jobs` 接入，批量预锁全批对象并在同一事务核验/入队。`run` 使用同一 read_project_state 脚本快照形成投影。Worker 视频初始状态核验改读 canonical document，不再读旧 projects.document。
- 已接入普通文本/媒体节点、视觉参考、音色试听和镜头对白的服务端明确采纳。当前负责人和当前版本、来源依赖、合法未删除任务素材都须通过；一次收据及正文/历史/审计/事件同事务。旧候选显式允许仍不能绕过来源变化；普通节点保留 prompt/generation_revision 的 stale 语义，图片重置人工首帧核验状态。视觉锁定版本拒绝改写；音色锁定/身份变化拒绝采纳；对白文本/角色变化拒绝旧台词音频。
- 删除视觉提交的 shared_context 写入主体，旧 record_visual_reference_submission 明确退役。main 不再期待 project_document，也不在排队后写 generationJobId；参考图/音色只刷新任务列表并提示任务中心采纳，保留当前草稿。任务中心 CandidateReview 接入上述对象，旧节点“使用版本/文本”改为打开比较入口。分镜结构候选尚未接入，不能把其它候选通过等同 P5 全部完成。
- 补齐实际音频消费链：`backend/video_dialogue.py`、`videoProduction.ts`、`dialogueAssets.ts` 和 `editor/initialTimeline.ts` 都只认镜头已采纳的 audioAssetId/audioVoiceVersion，核对台词和任务元数据，不自动挑最新生成素材。未采纳候选不插入初剪、不静音原视频。任务成功在对白列表显示“候选待采纳（任务中心）”。生成批次判断也按当前台词和已采纳版本处理。
- 新 `test_p5_object_candidates.py`：普通 editor 的真实 guarded loopback HTTP 由 Event 屏障阻塞，人工 v2 / 分配 B 后结果仅候选；未经接管的 manager/viewer 不可采纳，当前新负责人明确接受旧候选后才能成功；来源变化不留半写。音色、对白、视觉用现有 provider.register 登记本轮自有 PCM/PNG 素材，无付费网络调用；混合无权镜头的对白批次不留任何 job。

验证历程（原失败不删）：

- 新普通节点四项首跑 4 passed / 22.92s；加入音色与对白后 6 passed / 31.39s。
- 组合回归第一次 38 passed / 1 failed / 121.50s：视觉测试漏传现有必需 `asset_category=character`，服务端正确 400；只补夹具字段，不删除业务断言。单项重跑 1 passed / 6.53s。
- 对白后端原专项 9 passed / 1.02s；前端最终 167 passed / 925.562ms，包含新增“较新但未采纳”及“初剪不隐式采纳”断言；TypeScript 通过。
- 最后构建 1836 modules / 9.01s / exit 0，既有 chunk >500 kB warning 保留。compileall 通过；实际路由 125 registered / 122 API classified / 0 unclassified。diff --check 未报空白错误，LF→CRLF 提示保留。
- 最新候选/关系/动作/对白/视觉及 ACL-09 注入负例组合 **40 passed / 118.97s**，实际真实 PG 隔离库；前述视觉夹具失败已修复后整体重跑。没有运行当前完整后端套件，不以这 40 项代替全量回归。

接续工作（尚未完成）：

1. `main.adoptShots` 和双遍分镜结构导入仍为本地聚合导入，应接到原子候选采纳命令；服务端 object adopt 对 storyboard 目前明确 422，不能删除该功能作为验收方案。
2. 审查 `/jobs/{jid}/resume`：目前只沿用项目 editor ACL 与来源是否删除检查，尚须接入当前对象负责人/原冻结代际，防止非负责人重新排队。并补 `/run` 混合权限及 snapshot 准备期间真实 PG 交错测试。
3. 继续 source/chapter/project/asset 软删除/恢复旧代际检查。适配旧回归夹具到公开对象命令，保留原断言；跑完整 backend/P4/Provider/FFmpeg 回归。
4. 新候选 UI 尚无实际浏览器验证；需要新开本轮自有 0006 隔离服务做最终 COLLAB 矩阵，不迁移保留实例。最后固定业务 SHA、正式 evidence/P5、push origin OurVideoCreator，再直接发送主 ChatGPT 外部审核。

本轮没有重启/停止/迁移任何保留服务或用户数据库；未操作浏览器；dist 已更新，旧服务仍不能作为本轮新 API 的验收环境。没有向主会话发送未完成的验收请求，goal 仍 active。

### 续做：任务恢复的对象授权与远程句柄回归

上一轮属于 progress（对象候选及对白消费路径实际修改，40 项后端/167 项前端通过）。当前 live worktree 保持 P5 未提交；重新读根规则，未发现相关 memory 命中，不依据缓存猜测外部验收结果。

- `/api/jobs/{jid}/resume` 在取得任务行锁前加入身份 shared lock，锁后重新核真实作品访问权限。只在 interrupted → queued 变更前调用 `job_candidates.authorize_resume`；queued/running/succeeded 原有幂等读取不重置状态。
- 原 P3 的“普通 editor 只能恢复本人提交任务”仍保留，不放宽为任意作品成员。P5 再核实际当前对象负责人，manager 未明确接管不能重排别人的对象。
- 有原上游句柄：保留原 provider_job_id、输入、P4 binding，只允许当前负责人且原 assignment epoch 未变时恢复查询；人工内容修改不要求重新提交远端付费任务，结果仍只登记候选。A→B→A 后旧句柄恢复也拒绝。
- 无句柄：复用实际 `freeze_relation` / `object_job_candidates.freeze` 短事务检查原目标、负责人、epoch、内容 revision、必要引用及元数据；与原 job.collaboration 不同则 409，要求从当前对象提交新任务，不把旧输入偷偷重新标成新版。无协作快照的旧任务明确 410。没有新队列、配额或自动重试。
- 新增 `test_p5_resume_permissions.py` 六项：普通 editor/manager/viewer 边界；旧内容、ABA；原著章节；真实 PG 对象行等待；原远端句柄继续查询。PG blocker 用自有夹具 SQL 在持有锁的事务修改 content/revision 来确定等待轨迹，不改变用户身份或伪称浏览器操作；其他编辑/分配均通过实际 API。
- 原 `test_api.py` 的 Maestro/Comfy/video_api、无句柄恢复和 Replicate 恢复/取消测试仅新增公开对象创建夹具，让 `node_id=n` 指向合法当前负责人对象；保留原 frozen provider URL、只 GET 不 POST、输入/状态/telemetry、远端取消及 cancelled 不可恢复断言。

测试与问题修正：

- 首批五项 5 passed / 22.16s。
- 新远端例第一次 5 passed / 1 failed / 24.76s：夹具用了 MiniMax 不支持的通用 upstream_model，改为已接通的 MiniMax-Hailuo-2.3，没有放宽平台协议校验。
- 单例下一次 1 failed / 5.66s：预期 B 的 409，但 P3 提交者规则更早正确返回 403；保留该更严格边界，增加 A→B→A 后由原提交者触发 409 的实证，而非削弱权限。
- 最终恢复六项 + 原三个远程协议恢复 + 原同步恢复 + MiniMax 协议套件：**15 passed / 37.53s / exit 0**。测试仅用隔离真实 PG 与 fake/测试媒体，零真实供应商调用。
- Replicate 原恢复/取消 + 两组候选回归：**16 passed / 82.68s / exit 0**。全部本轮测试进程已结束。compileall / diff --check 通过；路由审计仍为 125 registered / 122 API classified / 0 unclassified。本轮未改前端，不重复宣称新浏览器证据。

下一步仍是分镜候选原子导入：当前 main.adoptShots 会替换整集 shots 和 Film Bible visual，必须改成服务端候选命令；需要保留现有镜头身份/附属节点、核被替换或移除镜头的当前负责人及版本，保留已有视觉卡/锁定版本及音色，原子建立新卡、新镜头节点、结构与采纳收据。不能把不同负责人对象变成隐式整份覆盖，也不能靠禁止分镜功能通过验收。现有 `object_job_candidates.adopt` 对 storyboard 仍 422；本轮未声称该项完成。

其它未完成项保持：soft-delete/restore 代际、完整后端回归夹具适配、真实浏览器 COLLAB 矩阵、固定 SHA 正式 evidence、origin 推送与主 ChatGPT 外部验收。未提交/推送，未操作保留服务，未进入 P6，goal active。

### 续做：单遍/双遍分镜候选的原子导入

上一轮是 progress（恢复权限实际实现及 15+16 项回归通过）。当前仍只推进 P5，未声明阶段通过，未 commit/push。

- `object_job_candidates.dependencies/freeze` 对 storyboard 增加完整旧镜头集合、各镜头 revision/epoch，以及可能移除连线所影响目标的引用快照；保存 `replacement_shots`，没有这份完整快照的旧候选明确 410，要求新任务。原 graph 和上游/正式剧本快照继续核验。
- 新增 `storyboard_candidates.py`：复用 `candidates/{jid}/adopt`，在既有排序对象锁和元数据/脚本锁下核原镜头集合、每个镜头当前负责人、引用版本，最后调用原子 objects command，一次完成新卡/镜头/子节点、旧镜头替换/移除、graph、来源节点 resultJob 及外层候选收据。没有 HTTP 或 FFmpeg 放进事务。
- 保持“导入本集完整分镜表”的既有语义，不改成只追加部分镜头。匹配显示 id 时保留原 object ID、uid、负责人和子节点 ID；新增镜头归当前采纳人。替换属于其他人的镜头必须先显式接管且按新版本重新生成；移除候选外的旧镜头还须 manager/owner。锁/权限失败不留半写。
- 已有视觉卡、版本、音色、素材和时间线保留，不再用 result.filmBible.visual 整份覆盖。双遍生成的新视觉卡追加，所有 binding 和冻结父版本通过既有 Film Bible 校验；新卡 ID 冲突拒绝，不按名字偷偷覆盖既有卡。旧镜头子节点保留所选模型/参数、人工改过的节点提示词和媒体，标 stale，并清除旧首帧人工确认；仍跟随旧生成提示词的节点才同步为新提示词。
- 新节点调用已有 `model_validation.shot_parameters` 推导图片尺寸及视频帧数。只新增内部关键字 `complete=False` 供未提交生成的可编辑节点初始化，默认仍 True；实际付费提交完整参数校验不变，缺失参数不会自动补未经发布的值，也不另选模型。
- 同一内部 `storyboard.adopt` command 上限 302，覆盖最多 100 新视觉卡 + 100 新镜头 + 100 旧镜头移除 + graph/来源节点；公开 objects commands 原 200 上限不变。不新增队列或对象层。
- CandidateReview 的分镜比较展示旧镜头正文、负责人/revision/epoch、替换数量、新卡数量和待移除编号；服务端返回基本替换权限提示。实际采纳仍核所有依赖/版本，不凭提示授权。main.adoptShots 不再调用本地 importStoryboardShots，也不覆盖聚合 Film Bible；原按钮现在打开任务中心比较/明确采纳入口。

测试边界和实际结果：

- 新 `test_p5_storyboard_candidates.py` 首跑 **4 passed / 1 failed / 27.74s**，失败是新管理接管夹具读了不存在的 `/api/auth/me`；改为项目真实 `/api/auth/status`，保留原 manager + 对象负责人双重权限断言。
- 第二跑 **7 passed / 35.03s**：真实 PG/API；双遍实际 Worker.execute + 原 normalize/validate（`_chat_text` 替换为两次 synthetic 回答，**不是本例的真实外部 HTTP**），结果仅候选；成功导入后 canonical GET/graph/bindings/voice 正确；非负责人/迟到版本拒绝无半写；子节点身份和人工提示词保留；移除需要管理权限；两候选经真实 PG graph blocker/waiter 轨迹精确一 200 / 一 409；节点推导保留 P4 完整参数提交约束。
- 随后补了实际 PNG 上传/旧 assetId 保留以及 timeline/director 对象不变断言，最终组合 **72 passed / 146.30s / exit 0**。该组合还含普通对象候选、恢复权限、canonical、P4 model foundation、Film Bible；进程已结束。没有冒称当前完整后端套件已通过。
- 最新前端 **167 passed / 917.5638ms**；TypeScript 通过；构建 **1836 modules / 7.71s / exit 0**，既有 >500 kB chunk warning 保留。compileall 和 diff --check 通过；实际 route audit 仍为 **125 / 122 / 122 / 0 unclassified**。
- 没有本轮实际浏览器导入证据；旧保留服务不支持全部新 API，不可拿旧标签冒充新实现。未调用真实付费 Provider，未迁移/重启/清理保留服务。

下一步：先补 lifecycle 的软删除/恢复代际（快速定位 `app.delete_project` 及 `restore_deleted_item`，当前代码还未为对象/关系表旧凭证统一失效）；补 `/run` 混合权限/准备快照交错；适配全量后端旧聚合 PUT/任意 node_id/自动回写夹具，但保留原业务断言；启动新的自有 0006 隔离浏览器服务，补候选/分镜/冲突/租约的真实 UI 证据，再固定 SHA 做完整 P5 evidence 并发送主 ChatGPT 审核。goal active，P6 未授权。

### 续做：回收站生命周期与旧编辑凭证

本轮为 progress，仍仅 P5；上一轮分镜候选已有 72 项组合回归，不重复实现。HEAD/master 仍为 c0152ffcfb5623fcc0b723dbdf450acec9f17f73，所有 P5 工作尚未提交/推送。

- 新 `backend/collaboration_lifecycle.py` 复用 P3 身份排他屏障；仅短时删除/恢复事务排他，普通对象编辑仍使用共享屏障、独立行锁。入口在任何行锁之前取屏障，随后重验实际 session 和当前 manager，防止请求进入后撤权仍继续删除/恢复。无新依赖/表/租约系统，无文件或 HTTP 工作放在事务内。
- 分集删除和恢复各递增本集存活对象 revision/assignment_epoch、清除旧租约并增 lease_epoch；正式剧本同样追加历史和递增编辑代际，分集 metadata revision 也递增。正文、负责人、状态及稳定 ID 保留，Production 共享视觉卡/锁定音色不因一集回收而变化。
- 原著/章节删除与恢复递增已有章节主源 revision/epoch，记录历史、审计及事件。原著恢复不会撤销独立章节 tombstone，隐藏父原著时恢复章节仍 409，事务回滚无半条历史。原著删除仍检查存活章节当前负责人和全部版本，不赋予 manager 隐式编辑别人章节的权限。
- 素材删除/恢复在相同生命周期屏障内；分类编辑用共享屏障、事务内复查项目权限与素材引用。素材文件/ID 不变。回收站恢复与正文历史 restore 是不同动作，历史动作使用 untrash 区分。
- fence 结束再次检查当前 session，过行锁等待后会话过期则整体回滚。
- 新 `tests/test_p5_lifecycle.py` 七例（含参数化）：项目对象/剧本/metadata/旧 lease、source/chapter 旧页面即便伪造新 revision 也因旧 epoch 被拒、源父子回收站、真实 PG 行锁→身份 advisory 排他等待轨迹、请求进入后通过公开成员 API 降权再继续删除/恢复均 403。
- 原 `test_projects_and_assets_move_to_trash_and_restore` 用公开对象创建替代退役 aggregate PUT，并新增正文/epoch 保留检查；原 source 回收站综合测试补当前 revision/epoch，原任务运行阻止删除、事件保留、重新编号、批量删除和逐章恢复断言均保留。

实际验证与失败记录：

- 首跑新增专项 **1 passed / 1 failed / 11.37s**：新测试错误读取不存在的 GET chapters/{id}，改用真实 owned-content/chapter/{id} 接口且先检查 200；未放宽业务断言。
- 新生命周期 + 既有 owned_content/object_transactions 组合 **36 passed / 132.65s / exit 0**。
- 补真实共享视觉卡保留断言 + 两项既有回收站业务测试 **9 passed / 43.50s / exit 0**；最后增加 fence 后 session 检查后重复该组合，最终 **9 passed / 40.08s / exit 0**。
- compileall / diff --check 通过；route audit **125 registered / 122 API / 122 classified / 0 unclassified**。本轮仅后端及测试文档变更，不冒称重新运行前端或浏览器。上述测试进程全部结束；仅自有临时 PostgreSQL/测试媒体，无真实 Provider 费用，保留实例未动。

下一步：补 `/run` 混合对象权限与准备快照的确定性交错；完整后端旧接口夹具适配和全量回归；新自有 0006 浏览器环境的 COLLAB 实际矩阵；固定业务 SHA 正式 evidence、推送 origin 与主 ChatGPT 外部验收。当前并未 READY_FOR_REVIEW，不自行签 P5 通过、不进入 P6，goal active。

### 续做：批量 run 交错验证、事件循环修复及首批旧回归接入

上一轮为 progress（回收站实现和 36/9 项回归）。本轮仍仅 P5；实时复核 master / c0152ffcfb5623fcc0b723dbdf450acec9f17f73，origin OurVideoCreator，upstream push DISABLED，保留全部脏工作区。

- 新 `tests/test_p5_run_permissions.py` 七例：mixed owner 批次真实插入第一项后第二项 403，整事务回滚 jobs/private binding/events；准备结束但入事务之前，公开 API 分别修改 node/graph/assignment/metadata，旧准备快照整批 409，重新获取后可成功；引用其他负责人节点允许只读，但展开生成其上游须 403；两个实际 PG 等待批次各完整产生两条任务且无半批。
- 首次并发测试 **1 passed / 1 failed / 23.98s**，不是提高 timeout 解决：`run_workflow` 为 async，但同步 PostgreSQL 等待/准备直接在 ASGI loop 执行，阻塞同 TestClient portal 上另一个保存请求，15 秒屏障超时。保留测试屏障，在 `await request.json()` 后用既有 Starlette `run_in_threadpool(prepare_run_workflow, pid, body)` 执行同步部分，保留 ContextVar/session 和原子事务，不新增队列或依赖。重跑 **7 passed / 33.89s**。
- 全套 collect 为 **458 tests**；第一次全套诊断用 `--maxfail=12 --tb=short`，**12 failed / 9 passed / 32.03s** 后按设定停止，绝非全套通过。前 12 项为 adaptation 旧自动回写/epoch/aggregate PUT，以及 test_api 旧 aggregate PUT/任意 node ID 夹具。
- `test_adaptation.py` 八项原业务断言接到实际新接口：AI 成功仅候选，正文仍空；显式采纳为 draft，再显式 review；正式剧本读写及审核带 epoch；画布正文通过公开对象创建 + script-promotion 原子提升，沿用原节点 ID/quick planning bypass；旧整份 PUT 明确 410 且不能覆盖正式剧本/作品改编数据；原著编辑仍使已批准计划和派生剧本 stale。原测试直接 SQL 写 generationPolicy 改为公开 context PATCH。
- `test_api.py` 初批接入：模型策略 roundtrip 改用 context PATCH；Ark 原发布能力、引用上限/尾帧错误、取消费用提示和秘密投影断言保留，仅先通过 objects 建立真实目标节点；共享视觉/跨分集素材测试用 card/shot 小接口和 context revision，不走整份 PUT。
- 共享视觉使用位置回归在真实新 shot 创建后观察到返回 `[]`（**1 failed / 5.03s**）：`production_visual_usage` 仍读取旧 document.shots。修复为协作分集读取存活 `collaboration_objects(kind=shot)`，按 production 一次取数；仍过滤回收站分集、保留原响应形状和非协作只读路径，不建第二主源。原完整 usage/跨作品素材拒绝/稳定文件及恢复断言保留。

中间修正与最终结果：

- adaptation 初次接入组合 **5 passed / 1 failed / 13.88s**：测试 node 仍携带已分离到 graph 的 position，删除内容对象中的旧 UI 字段；未放宽服务端对象 envelope。
- 下一组合 **16 passed / 1 failed / 62.95s**：Ark 夹具漏建用于取消测试的 ark-video 节点，补公开节点创建，保留原费用提示断言。
- 最终 adaptation 全文件 + run 七项 + 三项既有 API 回归：**18 passed / 71.28s / exit 0**，进程结束。compileall / diff --check 通过；路由分类 **125 / 122 / 122 / 0 unclassified**。未调用真实付费 Provider，未操作保留服务器；本轮未改前端，未新增浏览器证据。

下一步从全量旧测试适配继续，优先 test_api 中剩余 Film Bible/shot roundtrip、视觉候选、单次/批量编译、普通任务 node 夹具和后续生成/导出回归；不得恢复 aggregate PUT 或自动回写以换绿，不删除业务断言。完整测试、最新隔离浏览器 COLLAB 矩阵、固定 SHA evidence、origin 推送与 ChatGPT 外部审核仍未完成。全部 P5 尚未提交/推送，goal active，未进入 P6。

### 续做：API / 视觉 / 参考图 / 原著回归收口

上一轮为 progress（run 阻塞修复、视觉使用位置修复及 18 项组合通过）。本轮未更换阶段，保留现有全部脏工作区。

- 新 `tests/collaboration_helpers.py` 仅封装公开对象 create/patch、版本票据、按卡创建及图边保存；不接收整份 aggregate document、不绕过 assignee、不直接 SQL 改身份。用于既有业务测试真实创建协作目标。
- `test_api.py`：Film Bible/镜头 roundtrip 改为独立 card/shot 保存；原锁定版本不可改/不可硬删、派生版本不漂移旧绑定、仅升级镜头 A 标 stale、镜头 B 保持 current、指纹/旧媒体/历史信息保留、零新 jobs 等断言保留。虚构 asset-reference 改成实际 PNG 上传。
- 视觉生成测试核入队后对象/分集/作品 revision 与内容不变，合法 synthetic PNG 在服务端登记任务结果后仍不改卡；显式候选采纳才写 primary reference / provenance / pending_reference，禁止重复采纳。保留模型能力拒绝、相同目标活动任务去重、角色状态父参考、作品改编数据不受影响；旧 aggregate 覆盖明确 410。结果登记走本地测试媒体，无真实 Provider HTTP。
- 单次/批量 shot reference compiler 测试使用真实 card + 附属 image node + reference node + graph 小接口，保留能力上限、引用顺序、忽略手工旁路图和同一 prompt 编译断言。
- 时间线 roundtrip 通过真实 FFmpeg 生成小 MP4、公开上传、取得真实短租约后保存，原 Twick frame/transition/音量关键帧/fade/filter/rate 字段断言保持。metadata 冲突与历史走小 PATCH；普通生成/取消/恢复/跨作品媒体边界测试先公开创建对应对象。图 cycle/scheduler/双遍默认/后项验证全批 rollback 仍保留。
- 在接入空名称测试时保留原产品行为：metadata 名称空白仍归一为“未命名短片”，而非新接口意外返回 422；`check_episode` 仍检查字符串和最长 100 字符，拒绝非白名单字段。没有改变对象 ACL。
- `test_batch_references.py` 六项全部用真实 nodes/graph 小接口，原 MiniMax 单首帧、精确批次复用旧首帧、Seedream 动态/静态/手动引用顺序、Seedance 首尾帧能力和失败零 jobs 断言保持。
- `test_source_library.py` 五项：补章节 expected epoch；120 章导入/编辑/搜索/120 项任务去重完整保留；无效输出与旧事件保留，迟到结果默认采纳旧/新 revision 均拒；合法提取在完成前后都不自动写 events，明确采纳后保留 chapter/job 归属；旧 replace_events 退役也有断言。回收站综合测试保持。

实际测试结果和失败修正：

- 两项版本/镜头回归 **2 passed / 6.93s**；两项视觉候选/编译回归 **2 passed / 13.95s**。
- test_api 初次余项诊断 **12 failed / 23 passed / 79.69s**（旧 PUT/缺目标等，未修改业务断言换绿）；接入后 **2 failed / 33 passed / 100.82s**，剩余两个图夹具没有连线 id，补真实图 envelope 必需 id。
- 批量参考图全文件 **6 passed / 31.99s**。
- 最终 test_api + test_batch_references + test_p5_canonical_integration 组合 **47 passed / 138.31s / exit 0**，session 32635 已完成。
- 原著首次 **3 failed / 2 passed / 16.21s**（缺 epoch 和旧自动写语义）；接入后全文件 **5 passed / 19.28s / exit 0**，session 10660 已完成。
- compileall / diff --check 通过；实际路由 **125 / 122 / 122 / 0 unclassified**。未改前端，未声称新增浏览器业务证据，未调用真实付费 API，保留实例未动。

实时核对项目 ChatGPT：使用 computer-use 指引和 CUA 已绑定 browser 1/tab 1 读取 DOM 尾部，最新仍为“P4 通过、仅授权 P5-COLLAB-01”，未出现更新的验收意见；本轮没有向其发送未完成工作或请求提前验收。旧测试 tab 8/9 与主会话继续 markHandoff，没有重载/修改旧服务。

**仍在运行的具体诊断进程，下一轮必须先续读，不要因观察超时重新启动：**

- unified exec **session_id=39928**。
- 命令：`C:/Python314/python.exe -m pytest -q --tb=short --maxfail=12 --ignore=tests/test_api.py --ignore=tests/test_source_library.py --ignore=tests/test_batch_references.py`，使用现有 55434 测试管理连接和 pytest 自有临时数据库。
- 最近 `write_stdin` 返回 **仍运行**，输出已超过 17%，随后出现少量 F，但尚无最终失败明细或退出码。不能写成完整后端已通过，也不能猜测失败原因。先 `write_stdin(39928)` 收集结果；若工具句柄不可用再查实际进程，不先重跑。

后续依旧：完整后端回归清零且保留 P1–P4/Provider/FFmpeg 能力；新 0006 自有浏览器实例与 COLLAB 矩阵；固定 SHA evidence；origin push 和主 ChatGPT 外部验收。当前所有 P5 未提交/推送，goal active，P6 未授权。

### 续做：P1–P4 回归适配与真实页面节点顺序误判修复

上一段 session 39928 已续读完成：**12 failed / 187 passed / 4 warnings / 277.69s / exit 1**，达到 maxfail=12 停止，不是完整回归。失败为 P1 缺真实节点，P2 旧 aggregate PUT / 直接路由调用缺 session，P3 删除章节缺版本及旧整份保存预期，P4 缺真实生成目标。原有并发、回滚、Provider 与权限断言保留，未恢复旧写入口。

- `test_p2_postgresql.py` 改公开 metadata PATCH 和提取 POST；同版本竞争持有真实 projects 行锁后等待两个 PostgreSQL waiter，仍精确一成功一 409；事件失败回滚以初始化后的事件数为基线。全文件 **10 passed / 13.39s / exit 0**（session 69417 完成）。
- P1 用公开 HTTP 创建目标节点，原双 Web / 独立 Worker / Web 重启不中断 / 单 Worker 锁断言保留。P2-R1 分集与章节创建、恢复/取消、改编/剧本回滚都用真实 session 的 HTTP；恢复任务通过实际节点和入队产生冻结目标。组合 **6 passed / 24.18s / exit 0**（14837 完成）。
- P3 角色矩阵新增明确断言：manager 未接管别人的章节不能删除，公开 assign 接管并取得新票据后才可删除。编辑者旧 PUT 仍在权限层 403，manager/owner 410；metadata 历史改走小 PATCH，跨作品历史/素材/任务/回收站/撤权断言保留。首轮 **1 failed / 13 passed / 2 既有 websockets deprecation warnings / 49.48s**，纠正 editor 403 与 manager 410 的层次预期，未改权限实现。
- P4 公共 submit 夹具使用提交者创建相应 kind 的实际节点，存在目标不接管、不改身份；批量、音频、镜头时长用真实对象。三个文件首轮 **2 failed / 27 passed / 110.14s / exit 1**（93271 完成），两个失败为夹具还带 graph-owned position 和镜头 envelope 漏 nodes；修正后与 P3 失败项合并 **3 passed / 17.89s / exit 0**（53983 完成）。27 项已涵盖原参数限制、匿名 native Provider、轮换、独立 Worker 真实 loopback HTTP 和 FFmpeg 导出；不据此声称全套 P4 已最终通过。

最新浏览器实例仅新增自己的临时库与服务（旧用户/测试实例保持）：

- `tests/p5_browser_harness.py --owned-content --latest` 新选项只改为独立 .7/.8 hosts，避免混用保留实例 cookie。session **78675** 保持运行。
- 目录 `C:\Users\kunpeng\AppData\Local\Temp\ovc-p5-browser-vc3i9ale`，manifest.json 保留；结构已迁移至 0006，零 Provider/模型/Worker。
- DB `ovc_test_33712_1180a073f91e`；harness PID 33712；Web PID 24220 / 7372。
- A `http://127.0.0.7:4815`，B `http://127.0.0.8:4816`；project `project-7f163790f574446a91a6f50b67286007`，production `production-b2993a8e97654cd2995c6b8a98b5afe2`。普通 editor A/B 对象与账号 ID 见 manifest；不在文档写密码。
- CUA tab 10/11，句柄 `p5latestA` / `p5latestB`（advanced），`p5latestRawA` / `p5latestRawB`（wrapper）。主会话与旧 tab 8/9 均保留 markHandoff。

真实页面发现并修复：镜头 envelope 附属 nodes 的存储顺序与画布投影顺序不同，A 编辑后未编辑的 B 被误标 dirty。DOM 比较明确显示唯一差别为 B 的 image/video 子节点顺序反转。新增 `canvas child order never dirties another owner shot or blocks its remote update` 回归先得到 **1 failed**（dirty != saved）；`samePartContent` 仅对比较副本中的 shot nodes 按 ID 排序，不改变内容、权限、服务端 envelope 或 graph.nodeOrder。该回归同时验证仅发送 A 更新、B 的远端变化正常合入且保持 saved。

修复后 **npm test 168 passed / 0 failed / 0 skipped**。TypeScript/Vite **exit 0 / 1836 modules / 8.32s**，仅原有 >500 kB chunk 警告；修复前的独立 `tsc --noEmit` 也 exit 0。compileall / diff --check 通过；路由 **125 / 122 / 122 / 0 unclassified**。

最新 UI 复测通过的实际观察（还不是固定 SHA 正式 evidence）：

- A/B 使用两 host 独立 cookie 普通 editor，分别编辑 shot-a/shot-b 动作并点击真实“保存项目”。服务端日志 A 两次、B 一次 `POST .../objects/commands` 均 200，没有旧 aggregate PUT。
- 修复后 A 再次编辑保存，协作面板先为 A 保存中/B 已保存，随后全部已保存；B 页面实时显示 A 更新，没有假冲突。
- 双端刷新均保留 `P5 latest A 顺序回归通过` / `P5 latest B 独立保存`；两账号又分别经过账号页退出、输入测试凭据重新登录、返回分镜页，DOM 两个动作框仍各自为上述值。当前角色为 editor，无管理员代操作。
- computer-use 技能引导使用支持的 CUA 页面读写，并在构建后 reload 验证；没有操作原有 7895 或旧测试页。
- 主 ChatGPT 尾部实时读取仍仅授权 P5-COLLAB-01，没有新验收结论；本轮未发送未完成工作请求通过。

**仍在运行，下一轮先续读：session_id=22260**。完整命令 `C:/Python314/python.exe -m pytest -q --tb=short --maxfail=12`，这次无 ignore，用 55434 管理连接创建 pytest 自有隔离数据库。最近输出已过 31% 后继续出现数十个点，尚无最终结果/退出码；不要重启、不要写成后端全绿。旧 39928/69417/14837/62295/93271/53983 均已结束。

接下来收齐全后端结果并处理后续失败，再补最新实例冲突/租约/候选/其他 COLLAB 浏览器矩阵、固定 SHA 原始证据、origin 推送与 ChatGPT 外部审核。所有 P5 仍未提交/推送，本段只是开发续做记录，不是 READY_FOR_REVIEW 或外部 PASS。goal active，未进入 P6。

### 续做：后端最后一批旧夹具、真实候选/租约/冲突及导演台同步修复

上一段 **22260 已完成 exit 1：433 passed / 12 failed / 2 条既有 websockets deprecation warnings / 1013.93s**，达到 maxfail=12 后停止，458 项中的最后 13 项未运行。不是全套通过。失败集中于项目设置 2 项和 Ark/Seedance 10 项：已退役整份 PUT、GET 隐式修复旧默认值的旧预期，以及直接插入的 Ark project 缺 Production 上下文。

- `test_project_setup.py` 保存设置改公开 context PATCH，保留原改编/集纲/变现上下文断言并新增旧 PUT 410 和 revision 前进。旧默认值测试明确验证 GET 不迁移、不改 context/revision/updated/history/events；原格式初始化能力仍通过纯 configure helper 及新建项目 API 断言保留。没有恢复读接口隐式写。
- `test_volcengine_ark.py` 的 adapter fixture 改为登录后公开创建作品/分集及真实节点；保留协议级 stored job 和现有平台模型固定引用夹具，原 HTTP payload、引用顺序、远程恢复和实际音频混合断言未删。没有放宽 Worker 对 Production 的要求。
- 两个文件最终 **34 passed / 48.78s / exit 0**（3336 已结束）。

此前未归档的真实 UI 中间观察（全部还不是固定业务 SHA 正式证据）：

- .7/.8 latest 环境同上，另建 A 第二页 tab 12。仅此页用受支持 CDP 暂时 offline，编辑 `P5 stale local draft 保留不得自动覆盖`；正常 A 页保存远端 r4，第二页恢复 online 后明确保存得到真实 commands 409。比较面板保留本地 r3 与远端 r4，保存/审核禁用，未自动提版本重发；约 30 秒网络观察无额外 commands，B 读到远端新内容。网络已恢复 online，未丢弃第二页冲突草稿。
- A 第一页取得/续租/释放时间线租约；A 第二页竞争返回 lease_busy 409，释放后才能取得再释放；B 非负责人按钮禁用。测试结束两页均不持有租约。
- `p5_browser_harness.py --owned-content --candidates` 新增仅受控 loopback fake + 一个独立 Worker；假接口收到请求后等待自有目录 release-candidate 控制文件，保存收到的请求（不记录密钥）。最新源码另为每次请求保存唯一时间戳原件，保留 latest 文件供观察；当前保留进程早于这一日志增强，第二请求覆盖了 first 的 latest 文件，第一条只在既有工具返回中，不能冒称磁盘有两份。
- 启动失败历史：第一次因未配置 synthetic master key 在 seed Provider 前失败，未起 Web/Worker；第二次早期导入测试 MASTER 导致 store 路径初始化过早，保留目录 `ovc-p5-browser-355jho7y` / DB `ovc_test_22420_1164c03af5e8`，向该自有目录写 stop 后 session 14264 exit 0，未删库。随后直接用 Fernet 生成仅进程内 synthetic key，避免 backend 提前导入。未使用真实凭据/付费服务。

当前候选环境保持运行（**session 96722**）：

- 目录 `C:\Users\kunpeng\AppData\Local\Temp\ovc-p5-browser-oxszxqsl`；DB `ovc_test_17920_18722a82d82e`。
- harness PID 17920，Web 8836/33276，Worker 20428；A `http://127.0.0.9:11201`（tab 13），B `http://127.0.0.10:11203`（tab 14）。
- project `project-feebea3e41a54eb79336687a9c8a3a02`，production `production-6f5ef64704334bd5bc345cdd32708a48`；身份与模型 ID 在 manifest。测试密码不写此文或 evidence。
- 实际节点对象 `object-086a2576eb4a4e15b1ed3311a5db70f5`。第一任务 `job-2109cb1d0c4c4e60823a4cc1331f4f7d` 阻塞期间改正文为人工 v2；结果成功仍只候选。因其间真实“自动排列”改变 graph 引用版本，明确采纳返回 409，正文不变，属正确依赖校验。
- 第二任务 `job-5407d6582d5b4ffc9a0ca274cb897977` 由真实“开始生成”发起，fake UTC `2026-09-16T21:12:49.626016+00:00` 收到后阻塞；改为人工 v3 后放行，正文仍人工 v3。B 普通 editor 比较可读、采纳禁用；A 比较后明确采纳 200 形成 r4，B 可见采纳收据。A 历史恢复 r3 追加 r5，正文恢复人工 v3，不倒退 revision。
- A/B 不同选中节点和缩放：A 选文本目标，B 选 B video 后 Zoom Out；A transform `translate(83.7554px,165.347px) scale(0.356115)`，B `translate(139.046px,187.456px) scale(0.296763)`。A 保存 `P5 shared v6 共享内容同步但选择和视口独立` 后 B 读到新内容，但仍选 B video，两 transform 原值不变。该例未验证实际播放头；不要把单元测试和浏览器覆盖混淆。

真实导演台发现并修复第二个 UI 同步问题：

- A 通过分镜规划 → 3D 导演台添加角色并命名 `P5 协作构图角色`，实际保存构图。素材上传和 director-captures 均 200，但随后载入误报“载入期间又有编辑”，留在导演台；没有重复点击创建。原因是单事务新 node 和 graph 的事件分别合并，中间投影被误当成本地 graph 改动。
- `CollaborationClient.mergeRemoteRows` 与实际 SSE 入口改读取已授权的 objects 集合，在一次投影中合并各对象；仍逐项应用 revision/草稿保护，不恢复 aggregate 写入。只对本次事件确实移除的对象处理删除，不把旧快照缺项当作批量删除。
- 新回归先模拟原逐对象 reduce 合并，出现 **1 failed / 16 passed**（hasChanges true != false）；改一次合并后通过。另补真实本地草稿保留、删除与图同步、迟到旧响应不倒退和本地图冲突不清除。
- 全前端 **172 passed / 0 failed / 0 skipped / 1415.6615ms**；独立 `tsc --noEmit` exit 0；TypeScript/Vite build **1836 modules / 8.84s / exit 0**（71681 已结束），原 >500 kB chunk warning 保留。diff --check、compileall exit 0；route audit **125 / 122 / 122 / 0 unclassified**。
- 确认首个截图及对象均已保存后，仅 reload 自有 tab 13/14 加载新构建。第二次实际截图成功跳转高级画布并选中新图像节点，带构图提示词及一个真实 PNG 引用；预览中黄色角色/地面正确渲染、无辅助网格。素材 `asset-57217ce3f34044e69b8e837458932e33`，真实 upload/capture/file 均 200。第一次失败创建的测试素材/节点保留，没有删除历史数据。原用户及旧测试服务未停止、迁移或重启。

**新的完整后端正在运行：session_id=55260**。命令 `C:/Python314/python.exe -m pytest -q --tb=short`，无 ignore、无 maxfail，仍使用 55434 管理连接及 pytest 自有临时数据库。最近超过 47% 后又输出 23 个通过点，尚无最终结果。下轮先续读，不重新启动。此次运行期间只再改前端和 browser harness 的日志保留，不改后端或已收集的 pytest 用例。

CUA 原绑定 `p4browser`、`p5candidateA/B`、`p5latestA/B`、`p5secondA` 保留；tabs 1/3/8/9/10/11/12/13/14 本轮已 markHandoff。保留 latest session 78675 与 candidate session 96722。仍未固定业务 SHA、未建正式 evidence/P5、未提交或推送 P5、未发送外部验收，不标 READY_FOR_REVIEW、不进入 P6。接下来收完整后端结果，复测受此次 SSE 变更影响的两用户/冲突/候选 UI，然后固定 SHA 取正式原始证据和提交审核。

同轮后续复测补充（以上“第二次成功”不是全部边界的证明）：

- B 首次 reload 实际没有生效：旧冲突阻止了离页，DOM scripts 仍为 `index-DUQ93clj.js`，不能声称当时双端均新版本。明确比较确认仅为自动同步造成的测试 graph 假草稿后，在页面点击放弃该对象草稿/载入远端，再 reload；验证实际 script 为 `index-B4Elc8w5.js`。没有放弃任何真实用户内容或重新发保存覆盖远端。
- 第三张构图（机位 26°）在双端 batch 合并代码下，B 全对象已保存，但 A 仍有一次载入误报。进一步定位：capture 的 graph.nodeOrder 包含新节点，但 positions 合法省略该节点；compose 补 `(0,0)`，比较把这个默认表示视作新移动。扩展回归覆盖“显式坐标/省略坐标 × graph/node 顺序”，得到 **1 failed / 18 passed**，原因仍是 hasChanges true != false，不是抬高超时。
- `samePartContent('graph')` 只在比较副本里为 nodeOrder 中缺省 positions 补 `{x:0,y:0}`；不改共享主源、不忽略真实位置变化、不动 nodeOrder 顺序。之后全前端 **172 passed / 0 failed / 0 skipped / 1268.2197ms**；最新 TS/Vite **1836 modules / 9.20s / exit 0**（74441 完成），保留 chunk warning。此前独立 tsc 在该小比较修复之前；最新 build 已包含完整 tsc。
- 两页再次 reload 并分别验证 scripts 都是 **index-CFQdNSDl.js**。第四张实际构图保存：A 正常跳转高级画布选中新图像，提示词带 26°、真实参考 PNG；B 的 director/graph/所有节点/镜头/timeline 均“已保存”，没有假冲突。新 PNG `asset-afffbd3326354feea30e2bdc93988f15`，upload/capture/file 日志均 200，随后只观察到读取，没有默认坐标补写 commands。全部四张测试截图保留。
- **完整 pytest 55260 仍运行**，最新已经超过 62% 后继续输出通过点，尚无最终结果/exit code。没有重启或提前截断。该进程的后端/pytest 测试代码未在运行中更改。

### 续做：完整开发回归通过，准备固定业务提交

- **55260 已结束 exit 0：458 passed / 2 warnings / 1062.35s（17:42）**。无 ignore、无 maxfail；两条 warning 仍为既有 websockets legacy/server 弃用。该次是开发工作区完整回归，不冒称固定 SHA 运行原始证据。
- 实时读取主 ChatGPT 尾部，仍是 P4 外部通过并仅授权 P5-COLLAB-01；未收到新任务或 P5 通过。
- README 更正旧 document 可写、双时间线和分镜自动导入描述；API_CONTRACT 追加实际接口（保留下方 P0 原冻结草案），PERMISSIONS 追加 P5 已实现边界；没有把未来 P6 quota/fencing 写成已实现。
- 新 `scripts/capture_p5_evidence.py` 只针对指定且已提交的 business SHA 运行正式完整后端、关键真实 PG 轨迹、前端、TS/build、routes/compile/diff；输出自有临时目录，不自动发布或签验收。当前脏工作区试运行按预期 exit 1 拒绝，未重复启动完整套件。脚本 compile 通过。
- 浏览器 harness 新 `--formal-sha SHA` 在创建资源前复核 clean runtime，使用独立 .11/.12 cookie hosts 并在 manifest 记录业务 SHA。现有 .7/.8、.9/.10 服务未变更。
- 新 `scripts/collect_p5_browser_evidence.py` 使用只读事务和明确列/项目/作品过滤导出 objects/history/jobs/assets/audit/events 与匹配该 scope 的访问日志，不读凭证、session、手机号、Cookie 或素材字节。已在本轮自有候选环境实际运行 exit 0：10 objects、31 history、2 jobs、4 assets、42 audit、40 events。输出只保留在该环境 `development-db-projection.json`；不是正式 evidence。fake_requests 为 0，因为该旧进程尚未带逐请求原件日志增强，不冒称未调用或零费用以外的证明。
- diff --check、相关 Python compile 通过。接下来固定业务提交，再在该 SHA 上执行正式取证；P5 仍未外部通过，P6 未授权。
