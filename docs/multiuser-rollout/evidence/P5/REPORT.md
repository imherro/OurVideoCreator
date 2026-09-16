# P5-COLLAB-01 — READY_FOR_REVIEW

审核仓库仅为 **https://github.com/imherro/OurVideoCreator**，分支 master。MyVideoCreator 是只读单机上游，不是本轮审核或推送目标。

## 提交与取证边界

- P4-R1 外部通过基线：`c0152ffcfb5623fcc0b723dbdf450acec9f17f73`。
- P5 完整业务基线：`f4773f0075325625c6cf2e6236c5d2014d416d3f`。
- P5 最终业务：`0851dce02e0f22e87f6247b029fd3faedd39e7dd`。
- 最终 HEAD：紧接上述业务的 docs-only 证据提交；准确 SHA 以提交本文件的 Git commit 及审核消息为准，避免自引用 SHA。
- 完整后端/并发/路由回归固定在 f4773f0；最终修正只涉及 4 个 editor 源文件和 3 个前端测试文件。capture_followup.py 在实际运行前检查后端、迁移、脚本、依赖零 diff，固定新 SHA 重跑全部前端、TS/build、30 个 renderer 测试。没有冒称全量后端在新 SHA 重跑。
- 当前只是开发方请求验收；不签发 PASS，不进入 P6。请关注功能闭环与真实阻塞，不扩展为新的架构或过度设计。

## 已实现闭环

1. collaboration_objects 为对象主源；聚合 GET 为只读投影，整份项目 PUT 对所有角色明确 410。对象命令检查负责人、revision、assignment epoch，结构批量全事务，不能借 manager/owner 或全量旧快照绕过。
2. 普通对象独立修改；时间线短租约 acquire/renew/release/expiry/接管，锁等待后重查权限和真实时钟。审核绑定精确 revision；历史恢复追加新版本；评论不夹带编辑权限。
3. 章节、策划/剧本、分镜、视觉/音色版本、自由节点/图结构、导演台/截图、时间线和旧操作入口按契约映射。保持素材引用与固定 Film Bible 版本，不迁移旧测试数据。
4. 生成冻结目标对象/revision/epoch和必要引用，成功先登记候选；明确采纳再受控写入对象。迟到、重分配、混入无权对象、过期图引用不能覆盖新内容或产生半批任务。
5. 前端实际按对象保存，dirty/saving/saved/conflict/error 状态，409保留草稿并停止自动重发，切换作用域隔离旧响应。对象面板提供分配/接管、租约、审核、历史、评论和明确比较/处理。
6. 已打开 Twick 接收远端输入但不回声保存，保存回执不重载编辑器。首次规范化不当作用户编辑；标题轨映射为播放器支持的 element，标题元素内容不变。私有选择/视口/播放头不写共享工程。

实现契约：[P5_OBJECT_COLLABORATION](../../design/P5_OBJECT_COLLABORATION.md)、[API_CONTRACT](../../design/API_CONTRACT.md)、[PERMISSIONS](../../design/PERMISSIONS.md)、[ROUTE_AUTH_MAP](../../design/ROUTE_AUTH_MAP.md)。逐项验收入口见 [MATRIX](MATRIX.md)，失败、限制与修正过程见 [ATTEMPT_HISTORY](ATTEMPT_HISTORY.md)。

## 实际运行结果

| 固定业务 | 命令 | 结果 |
|---|---|---|
| f4773f0 | 完整 pytest | 458 passed，2 个既有 websockets deprecation warnings，exit 0 |
| f4773f0 | 确定性真实 PG 并发轨迹 | 10 passed，exit 0；stdout 包含 waiter/提交与拒绝轨迹 |
| f4773f0 | npm test / tsc / build | 172 passed；TS/build exit 0 |
| f4773f0 | audit_routes / compileall / diff-check | 125 总路由、122 API、122 分类、0 未分类；全部 exit 0 |
| 0851dce | npm test | 178 passed，0 failed，0 skipped，exit 0 |
| 0851dce | tsc --noEmit / build | exit 0；1837 modules；保留 chunk >500 kB 既有警告 |
| 0851dce | test_editor_renderer.py | 30 passed，exit 0，包含实际 FFmpeg |
| 0851dce | diff-check | exit 0 |

原始 stdout/stderr 合并日志、命令、UTC、退出码与耗时见 [commands-f4773f0/runs.json](commands-f4773f0/runs.json)、[commands-0851dce/runs.json](commands-0851dce/runs.json)。完整基线 UTC 21:40:24—22:00:17；受影响补跑 22:13:59—22:14:31，均为 2026-09-16 UTC。日志仅脱敏本机用户目录；没有删除失败或 warning 来换绿。P4-R1 附件原有 Markdown 行尾空格保留原件，见历史说明。

## 真实浏览器与数据库证据

- [browser-f4773f0-tools-complete.json](browser-f4773f0-tools-complete.json)：61 次实际调用及61次返回。独立 A/B 普通 editor 分别在 .11:5697/.12:5700 cookie hosts；第二 A 页做旧版本冲突。harness 管理员只建立隔离夹具，未替代 editor 操作或 SQL 改身份。
- A/B 镜头 X/Y 保存、刷新、退出重登仍保留；旧 A r2 草稿面对远端 r3，实际 commands 409，比较保留且无自动重发。时间线两页竞争 lease_busy，renew/release 后第二页 acquire/release。
- 两个本机 fake 请求原件及对象历史：第一轮 v1→人工v2→仅候选；因布局改变 graph 引用，采纳拒绝。第二轮实际按钮提交→fake收到且阻塞→人工v3→放行仅候选→B只读比较→A明确采纳r4。恢复旧历史再追加r6，不覆盖历史。
- 画布 A/B 不同选择/缩放保持，共享正文同步；章节 A 保存 r2/B只读；导演台真实生成 PNG 并创建新图像节点，没有假 graph 冲突。
- [browser-0851dce-tools.json](browser-0851dce-tools.json)：17 次实际调用及17次返回，最后修正受影响页面复测。A 0.5 秒/B 1.5 秒；A有选择/B无选择，共享标题更新后均保持。B 后续未授权测试草稿在 A 新正文到达时仍保留，比较到远端r9；明确载入远端后恢复同步。最终没有使用 reload 代替实时同步。
- B 的只读/接收期间访问日志没有时间线 commands 回声写：web-2 仅有最初镜头 Y 的一条成功 commands。B 未授权编辑的提示来自客户端校验；服务端 ACL 另有真实 API 测试，不能将此提示写成浏览器网络403。
- A 真实点击本地导出成功：`job-6a59163cb1a54dd9b8e5c4c317a53e27` → `asset-6e49a6f665f045c3828a7d9dd7ebb3d4`，3 秒、1280×720、24fps MP4。标题轨 element / 文字 text 被原有 FFmpeg 路径处理。
- [browser-followup-db.json](browser-followup-db.json) 为只读、明确项目/作品范围的SQL列投影：7对象、31历史、3任务、2素材、52审计、55事件、2 fake 请求。它的 business_sha 字段来自**环境启动 manifest f4773f0**，并不代表浏览器仍用旧前端；新前端是 0851dce 的 `index-DuioqIPf.js`。后端字节不变、进程未重启，完整来源见 [PROVENANCE](PROVENANCE.md)。

## 范围与限制

- 未调用真实付费 Provider，fake 为本机合成响应；不对真实供应商线上可用性、性能容量、公网部署、多 Worker 或计费配额作结论。
- 浏览器并非覆盖每个权限交错：锁后时间、重分配、批量回滚、旧审核、撤权等由真实 PostgreSQL/API/前端测试覆盖，MATRIX明确区分。没有虚构浏览器总 exit 0。
- 浏览器轨迹是实际工具调用/返回文本；截图曾目视检查导演台，未把没有导出为文件的图片声称为独立截图附件。没有读取 cookies、网络认证头、session 表、供应商密文、无关项目或素材二进制。访问日志投影不是完整网络 HAR。
- 已知构建警告与既有 websockets 警告保留；本轮实现不引入新队列或基础设施。Twick 输入同步会采用其 loadProject 语义刷新远端清洁对象；本地脏草稿由对象客户端隔离，不静默覆盖。
- 测试环境与旧服务全部保留，未删库/迁移已有用户实例。7868、7895、6313、6185、7028 未改动；本轮 .11/.12 ports 5697/5700，Web 42960/7672、Worker25468、harness22984，自有 DB ovc_test_22984_61a5d28b1f80。更早 P5 .3—.10 测试资源同样保留。租约已释放；第二 A 页镜头冲突草稿保留供查验。

请外部审核者以本协作版仓库审查 COLLAB-01…12 与保留能力，给出通过或需要修正的明确结论。若不通过，只处理本阶段返修；未经外部授权不开始 P6。
