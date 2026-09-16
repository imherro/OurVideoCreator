# P4 实际尝试记录

本文件区分开发调试、正式提交后的复跑和预期拒绝用例；不把早期失败重写成通过。

## 开发调试（业务提交之前）

- 初次使用旧 55432 测试 PostgreSQL 端口连接超时，未开始用例；改用自己创建的 55434 隔离 PostgreSQL 18.6。未停止/重启 7868 或复用 7895 数据。
- 最早 foundation 27 passed；随后 28 passed、60 passed、68 passed 的定向回归逐步接通。原始工具结果在当前 Codex 任务，不冒充最终 SHA 的正式日志。
- 第一次完整后端回归：**97 failed / 237 passed / 10 errors / 3 warnings / 306.33s**。旧测试依赖已退役的 settings.providers、旧 provider/model 输入和全局 HTTP 客户端 monkeypatch；逐一改为真实平台管理 API、冻结版本和内层 transport fixture，保留业务断言，不取消 PG/鉴权/解析。该轮控制台输出被截断，未保存完整文件，不能事后补造原始红测。
- 定向复跑 86 passed；Provider 协议回归 58 passed / 2 failed（RunningHub 文本地址需显式 /v1、一个 Maestro 直接协议 fixture 缺私有模型字段）；43 passed / 1 failed 和 14 passed / 1 failed 仍使用先于 fixture 修复收集的同一 Maestro 用例。随后完整复跑 **346 passed / 2 warnings / 441.83s / exit 0**。
- 新增真实 A/B HTTP 轮换用例 1 passed / 22.70s；新增四角色矩阵 foundation 36 passed / 26.31s；加入独立 Worker FFmpeg 导出后 submission 11 passed / 37.31s。
- 前端从 126 增至 128 passed；TypeScript 和构建通过，原有大 chunk warning 保留。一次暂存 diff 检查发现新 helper 尾部多余空行，提交前修复。

## 第一轮浏览器调试（6313，非正式新实例）

- 实际后台填写 Provider/合成 Key/发布文本和图片，普通账号选模型提交，两项成功；不是 API 填模型后刷新冒充 UI。
- 初始测试节点 type 错写 studio，改为 media；初始普通账号是 editor，P3 整份作品写入门槛不允许其保存模型选择。仅在该隔离夹具把普通账号调整为 production manager（仍 platform_role=user / workspace member），不改产品权限。正式夹具已固定正确节点和 manager，无需手工改库。
- 精确 label “所属 Provider”选择器没有匹配，改用可见 combobox 角色和名称；无提交发生。部分 AX 读取在异步加载中，之后根据稳定页面再次确认。
- 浏览器 content.export 和 Browser.getVersion 返回不支持；不伪造导出文件或浏览器内核版本。第一次长时间 CDP 缓冲不足以完整保留所有请求，正式复跑更频繁采集，并用服务日志和实际 DB 行交叉核对。
- 只读证据采集脚本第一次误用不存在的 jobs.created_by / job_private.model_id；修正为 actor_user_id / model_versions join 后成功。未改业务数据。

## 正式验证（业务 SHA 0e64bd0540ad53de5ea6d93013c14d5154760867）

- 后端、前端/构建、路由、编译均从该已提交业务运行。最终证据提交只允许 docs 改变。
- 全新浏览器夹具：6185 Web、6962 fake、独立 PostgreSQL 数据库及媒体目录，2026-09-16T16:54:28Z 启动。预置仅合成账号/团队/作品和无模型节点，Provider/Key/模型必须通过 UI 填写发布。
- 普通 manager 访问 /admin 为“无权访问”；相关管理请求 403 是预期拒绝。
- 普通文本 max_tokens=201 超出平台上限 200，POST jobs 400，页面显示“生成参数超出允许范围”，fake 全部计数仍为 0。修正至 100 后再提交是预期负例后的正例，不是自动重试付费请求。
- 浏览器工具不是命令行程序，无总 exit code；记录每次工具调用/返回、UTC、AX、CDP 方法/路径/状态。未要求用户操作确认框，无真实凭据或付费调用。

两个浏览器夹具及其数据库/媒体保留待查；不声称已经清理。pytest 只按既有白名单规则删除它当轮自己创建的临时数据库。

## 最终测试断言补强及复跑

- 0e64bd0 正式后端：351 passed / 2 warnings / 485.49s / exit 0。
- 整理 SECRET-01 时，为缺失、错误、格式错误主密钥及损坏密文四项增加真实 Worker.execute 和 HTTP sentinel 断言，定向 4 passed / 32 deselected / 6.09s。提交 `3a73165f74520d0c15ec6f0750d7b2c105108744` 仅改测试，运行时不变。
- 最终业务完整复跑 UTC 2026-09-16T17:03:37.7463019Z 至 17:12:02.5591828Z：**351 passed / 0 failed / 0 skipped / 2 warnings / 502.37s / exit 0**。原始日志本机保留，共享版仅脱敏 warning 中两处本机用户名路径。
- 浏览器 trace 初次提取遗漏工具返回的 input_text 类型，修正证据提取器并重新从实际会话抽取后，30 次调用和 30 次返回齐全；没有重造 UI 输出。提取器随后改为读取测试源码的合成常量做脱敏，避免在证据目录重复写入明文常量；实际 trace 内容未改变。
