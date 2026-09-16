# P5 对象级协作实现映射

依据：外部授权 `prompts/P5_CODEX_PROMPT.md`（P5-COLLAB-01）。本文是实施映射，不是验收通过声明。当前仍在实施；旧入口只有在对应替代路径接通后一起退役，不把中间提交当作完整 P5。

## 唯一主源与命令

`src/main.tsx:save` 已切换为 `CollaborationClient` 对象差量命令；旧 `PUT /api/projects/{pid}` 已明确退役为 410，包含 owner/manager。`production_context.read_project_state` 对新协作 Episode 从对象主源只读聚合。保留 UI 纯函数所需的 document 形状，不再把它当作第二个可写数据库主源。关系表写入及生成候选接口已接通；完整回归、固定业务 SHA 证据和外部审核尚未完成，不能据此宣布 P5 完成。

| 实际可写内容 / 入口 | 唯一主源及 scope | 负责人 / 并发边界 | 命令与旧路径退役 | 验证 |
|---|---|---|---|---|
| 分镜表、shotSync、shotNodes 派生节点、镜头显式 visual bindings | `collaboration_objects(kind=shot)`，Episode → Production → Workspace | 镜头 assignee；镜头内容及其受管节点同一 revision/assignment epoch | 对象保存；受管子节点不能作为 free node 越权写；旧 document.shots/nodes PUT 退役 | COLLAB-01/02/04/05/10 |
| Film Bible visual card、不可变版本、固定音色、该卡生成节点 | `collaboration_objects(kind=visual_card)`，Production | 每卡 assignee/revision/epoch；锁定版本不可变；voice profile 同卡 | card 保存、fork/lock、显式 shot binding；移除 shared_context.visual/voices 的可写副本 | COLLAB-08/09 |
| 视觉版本使用位置（只读） | 当前存活分集的 `collaboration_objects(kind=shot).assetBindings` | Production viewer+，隐藏回收站分集/已删除镜头 | 不再从旧 projects.document.shots 统计协作分集；仍返回原 episodes/shots 形状 | test_production_context_is_shared_versioned_and_episode_documents_stay_local |
| 自由文本/图像/视频节点 | `collaboration_objects(kind=node)`，Episode | 独立 assignee/revision/epoch | 创建归创建者，内容按对象保存；旧 nodes 整体替换退役 | COLLAB-04/11 |
| 画布增删节点、边、排序/位置 | `collaboration_objects(kind=graph)`，Episode | 结构 revision；创建、删除涉及对象逐项授权，批量原子 | 小范围结构命令，不接收整份项目；镜头文字不增加结构 revision | COLLAB-01/10/11 |
| Twick、legacy Clip 投影、audio_id、导出设置 | `collaboration_objects(kind=timeline)`，Episode | 单负责人、revision/epoch、短独占 lease；取得行锁后核验时间 | 同一 timeline 命令；旧 Clip 输入转换为该主源，不保留双写 | COLLAB-06/12、FFmpeg 回归 |
| 3D 导演台 / capture | `collaboration_objects(kind=director)`，Episode | 独立负责人、revision/epoch；无全剧集 lease | stage 保存；`director-captures` 原子校验 stage/graph 版本及本集图片素材、建 node；上传 I/O 后再复核权限 | COLLAB-11、test_p5_collaboration_actions |
| 正式剧本、review/approve/revise、画布提升正式剧本 | 复用 `episode_scripts` / `episode_script_revisions`，Episode | 新增 assignee/epoch；沿用 revision；审核绑定 revision | `script-promotion` 同事务核剧本/自由节点/结构版本并删除自由节点主源；旧 canvasNodeId PUT 明确 410 | COLLAB-05/07/09、test_p5_collaboration_actions |
| 原文文档/章节/事件、改编计划、Production policy/style/故事设定 | 复用 source 关系表与 productions 小型 metadata | 章节独立 revision/负责人；作品级计划与策略 manager/owner；不允许修改他人已分配对象 | 现有小接口补齐版本/权限；不接受整份 shared_context 替换 | COLLAB-10/11 |
| 原文提取/改编/剧本生成 | `jobs.collaboration` 冻结目标、`jobs.result` 候选及显式采纳收据；不另建队列 | 章节/剧本负责人；改编 manager；目标 revision/epoch 及来源快照 | Worker 仅校验结果，旧 apply/replace 自动写退役；`candidates/{jid}/adopt` 写内容/历史/审计/事件/收据同事务；任务中心先比较 | COLLAB-09/10、test_p5_relation_candidates（页面还待浏览器验证） |
| 普通节点/镜头附属节点、视觉参考、音色试听、镜头对白 | `jobs.collaboration` 冻结真实对象/引用 revision/epoch，`jobs.result` 候选 | 提交及采纳均核当前负责人；Production/分集元数据、图及必要上游/音色/剧本版本在短事务核验；音频混合批次全败 | 任务中心比较后通过同一 adopt 命令采纳；提交不回写视觉卡或音色；视频/初剪仅取镜头明确采纳的对白 asset ID | test_p5_object_candidates、dialogue_assets、initial_timeline、video_production；普通文本节点已实际浏览器验证迟到候选/非负责人不可采纳/明确采纳/历史恢复，正式 SHA 证据待补 |
| 图工作流批量 `/run` | 同一已读取对象/剧本/元数据快照 + 各 job 固定引用 | 对象集合排序锁；全批逐项核负责人及准备快照版本，禁止借上游展开生成别人的节点 | 同步准备/事务进入既有 ASGI 线程池，等待 PG 不阻塞同服务其他请求；失败整批 rollback，不提交部分 jobs/events/private bindings | test_p5_run_permissions：混合权限、4 类准备期变化、只读引用与展开生成、真实 PG 等待 |
| 单遍/双遍分镜导入 | jobs 候选 + 当前集 shot/node/graph 对象；新 visual_card 追加 | 提交冻结来源、graph、原镜头集合/版本及可能受移除连线影响的目标；采纳须拥有每个被替换镜头，删除额外旧镜头还需 manager/owner | `storyboard_candidates` 经同一候选 API 原子建立/替换镜头、子节点和结构，记录采纳；保留旧卡、锁定版本、音色、素材和时间线；main 导入按钮只打开比较，不再本地聚合覆盖 | test_p5_storyboard_candidates；实际浏览器验证待完成 |
| 纯导出 | 绑定 timeline 负责人及快照；只登记素材 | 保留 P4 模型/凭证边界与 FFmpeg | 不需要生成结果回写创作对象；后续完整 FFmpeg 回归仍必需 | 全量回归待完成 |
| Assets / 历史 / 评论 | 现有稳定 asset ID；对象历史与 append-only 评论 | 同 Production 读取；viewer 可评论；成员退出保留成果 | 跨作品引用拒绝；成员退出不删素材；恢复新增 revision | COLLAB-07/08/10 |
| 分集/原著/章节回收站 | 原主源 + deleted_items；不复制正文 | 短生命周期事务先取 P3 身份排他屏障、重验当前会话及 manager；章节删除仍核负责人/版本 | 删除和恢复各增加受影响对象 revision/epoch，清除分集旧租约；保留内容/负责人；分集不修改作品共享视觉卡；单独删除章节不会随原著恢复而自动恢复 | test_p5_lifecycle；旧回收站业务测试 |
| selection、viewport、playhead、panorama viewpoint | 当前浏览器本地状态 | 不进入共享对象 | 不作为 autosave patch；远端只刷新未 dirty 对象 | COLLAB-03/12 |

同构的六类 JSON 内容共用一张带受限 kind 的对象表，不再为每种 payload 引入一套仓储层；已有关系型剧本/原文继续复用，不能把其正文复制到对象表形成第二主源。scope 从受外键约束的 Episode/Production 父级推导，不接受客户端作者或租户字段。

## 事务与失效

- 对象写操作先取得现有身份不变量 advisory lock 的共享锁，再按 ID 顺序锁对象行；成员变更继续使用其独占锁。不同镜头不互斥，权限撤销与对象提交有明确顺序。
- 锁后复核当前账号/session、成员关系、assignee、expected_revision 和 assignment_epoch。更新、history、audit、持久 SSE event 同一短事务；不在事务中调用 HTTP/上传/FFmpeg。
- 分配、显式接管、撤权均增加 assignment epoch，撤权保留内容并置为待分配；A→B→A 不能复用旧页面凭据。manager/owner 也必须先显式接管他人对象。
- Timeline lease 绑定对象、用户、随机 token 摘要及 epoch；核验采用锁后的当前时间。旧 token 的释放不能影响新 lease。
- 批量先验证所有权限、版本和引用，再执行全部写入。409 不返回越权内容，不留下半批历史或事件。

## 实施与验证顺序

1. 对象表、短事务保存/分配/租约/审核/历史/评论及真实 PG 测试。
2. 只读聚合与实际 UI 的逐对象 dirty/save/conflict；旧 PUT 明确 410。
3. 原文/剧本及所有旧写入入口闭合，任务候选/受控采纳。
4. 全回归与两位普通 editor 的真实浏览器证据；固定业务 SHA 后归档 P5 原始证据并提交外部审核。

仅第 4 项全部完成才可标记 READY_FOR_REVIEW；P6 未授权。
