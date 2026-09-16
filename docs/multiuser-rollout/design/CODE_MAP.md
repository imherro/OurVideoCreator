# P0 实际代码地图

## 进程与启动

| 路径 | 实际职责 | 多用户改造阶段 |
|---|---|---|
| `backend/app.py:29` `lifespan` | 仅调用 `store.init()`；不创建 Worker、不取 worker.lock、不加载模型 | P1 已拆分；P2 替换存储 |
| `backend/worker.py:19` `Worker` | 独立单 Worker 进程默认创建 4 个领取线程；Ark/豆包语音可并发，其他路径受 `serial_execution_lock` 串行；进程级锁禁止第二 Worker | P1 已由 `backend.worker_cli` 独立启动；P6 多 Worker lease/fencing |
| `backend/runtime.py`、`inference/` | P1 已删除内置 llama/Maestro 启动、GPU/权重环境和模型安装代码 | 删除目标；Maestro 仅保留外部 HTTP 适配器 |
| `backend/process_lock.py` | 单机进程锁 | P1 保留为过渡或移除；不能作为 P6 正确性依据 |
| `backend/instance_identity.py` / `Studio-Process.ps1` | 用脚本工程根 + 实际数据目录生成实例 ID；身份查询受控切换到目标根并核对返回根，相对数据目录也按该根绝对化；生命周期记录校验角色、PID、创建时间、可执行文件和完整命令行 | P1-R1/P1-R2 补强本机进程所有权；P7 部署加固 |
| `Start-Studio.ps1` / `Stop-Studio.ps1` | 分别管理 Web 与 Worker；只复用/停止可证明属于当前实例的进程，支持 `-WebOnly` / `-WorkerOnly` | P1 已拆分；P1-R1 所有权校验；P7 部署加固 |
| `Install-Studio.ps1` | 安装 Python/Node 依赖并构建 | P1/P7 移除推理假设、补部署路径 |

## 当前持久化与主源

| 路径/函数 | 当前主数据 | 观察 |
|---|---|---|
| `backend/store.py:28` `db` | SQLite connection | 每次操作新连接；`PRAGMA foreign_keys=ON` |
| `backend/store.py:41` `init` | 建表及启动迁移 | 应用启动执行 DDL、旧数据包装和全表迁移，P2 退役 |
| `backend/store.py:196` `get_setting/set_setting` | 全局 JSON 设置 | 包含 Provider 与 Key；P4 关系化并加密 |
| `backend/app.py:391` `save_project` | `projects.document` + `productions.shared_context` | 整份 document PUT；项目/Production 两个 revision |
| `backend/production_context.py:138` `read_project_state` | 聚合 episode document 与 production context | 可演进为只读聚合器 |
| `backend/adaptation.py` | 改编计划、逐集剧本、事件 | 已有独立 revision 和事务逻辑，可迁移到 PG |
| `backend/project_schema.py` | document schema v6 与旧版本迁移 | 新系统不迁旧库；纯函数仍可服务聚合读取 |
| `backend/provider_assets.py` | 签名素材 URL | secret 当前自动写入 settings；P3/P4/P7 重做作用域与密钥管理 |

直接执行 SQL 的运行模块：`backend/app.py`、`store.py`、`worker.py`、`adaptation.py`、`production_context.py`、`source_library.py`、`model_migrations.py`、`contact_sheet.py`、`visual_references.py`、`providers/common.py`、`providers/hc_atom.py`。P2 不能只替换 `store.py`。

## API 与安全边界

| 路径/函数 | 当前行为 | 缺口 |
|---|---|---|
| `backend/app.py:44` `auth` | 非公开 `/api` 路由检查同一全局 session；写请求做 Origin/Host 检查 | 无 user/workspace/production/object 授权 |
| `backend/app.py:93` `setup` | 首位访问者可设置共享工作室密码 | P3 改为安全 CLI 初始化 |
| `backend/app.py:648` `asset_file` | 登录后按 asset id 读取文件 | 不校验作品成员 |
| `backend/app.py:655` `provider_asset_file` | HMAC + expiry 的无 cookie capability | 未绑定方法、用途、撤销或租户 |
| `backend/app.py:678` `update_settings` | 任意已登录者写 Provider、URL、Key 和本地设置 | P4 仅 platform_admin |
| `backend/app.py:975` `submit` | 校验项目存在、素材 Production 边界、Provider 能力并入队 | 无用户/角色/额度/平台 model_id 边界 |
| `backend/app.py:1763` `read_job` | 按 job id 全局读取 | 无项目归属授权 |
| `backend/app.py:1849` `events` | 广播事件表全部记录 | 无用户作品过滤或撤权复核 |

完整路由逐项分类见 `ROUTE_AUTH_MAP.md`。

## 任务与 Provider

| 路径 | 职责 |
|---|---|
| `backend/app.py:871` `create_job_record` | submission_id 幂等、输入冻结、素材与模型能力校验、`job_private` Provider 快照 |
| `backend/store.py:234` `job_update` | 任务更新、取消优先、终态时间 |
| `backend/store.py:252` `attach_provider_job_id` | 持久化远端句柄并检测冲突 |
| `backend/worker.py` | 队列领取、dispatch、轮询、下载、登记、FFmpeg |
| `backend/providers/common.py` | 引用素材、下载与资产登记 |
| `backend/providers/volcengine_ark.py` | 方舟文本/Seedream/Seedance |
| `backend/providers/runninghub.py` | RunningHub 文本/图片/视频 |
| `backend/providers/hc_atom.py` | 幻场文本/图片/视频与远端素材登记 |
| `backend/providers/volcengine_speech.py` | 豆包语音 |
| `backend/replicate_api.py` | Replicate prediction |
| `backend/minimax_video.py` | MiniMax 原生视频 |

## 前端保存与功能入口

| 路径 | 实际职责 | P5 影响 |
|---|---|---|
| `src/main.tsx:719` `update` | 任意画布/Film Bible/镜头/设置修改标记同一 document dirty | 拆成对象 dirty 状态 |
| `src/main.tsx:989` `save` | 2.5 秒自动 PUT 整份 project document | 改为对象 API；旧 PUT 退役 |
| `src/main.tsx:868` | 全局 EventSource `/api/events` | 按权限订阅与局部刷新 |
| `src/pages/SourceLibraryPage.tsx` | 原著与章节独立保存 | 保留，补对象负责人/授权 |
| `src/pages/AdaptationPage.tsx` | 改编计划 revision 保存与审核 | 保留，补角色授权 |
| `src/pages/ScriptRoomPage.tsx` | 一集剧本 revision 保存与审核 | 最接近目标对象模型 |
| `src/pages/StoryboardWorkspace.tsx` | 镜头规划/分镜图入口 | 镜头独立主源和负责人 |
| `src/filmBible/` | 卡片、不可变视觉版本、绑定、锁定 | 关系化主源，保留纯函数投影 |
| `src/editor/` | Twick 多轨工程、素材绑定和导出数据 | 独立 timeline + 服务端租约 |
| `src/pages/TaskCenter.tsx` / `TaskDetailPage.tsx` | 任务查看、恢复、取消 | 按作品授权，显示 unknown/费用风险 |

## 测试地图

- 后端/API/事务：`tests/test_api.py`、`test_adaptation.py`、`test_source_library.py`。
- Film Bible/绑定/指纹：`test_film_bible*.py`、`test_reference_compiler.py`、`test_generation_fingerprint.py`、`test_generation_staleness.py`。
- Provider：`test_volcengine_ark.py`、`test_runninghub.py`、`test_hc_atom.py`、`test_replicate_api.py`、`test_minimax_video.py`、`test_volcengine_speech.py`。
- 任务恢复/竞态：`test_job_contracts.py`、`test_job_timing.py`、`test_worker_prompt_freeze.py`、`test_asset_registration.py`。
- 媒体/剪辑：`test_export.py`、`test_editor_renderer.py`、前端 `editor_*.test.mjs`、`initial_timeline.test.mjs`。
- 前端业务纯函数：43 个 `.test.mjs` 文件，共 123 个测试。

当前缺少：路由授权清单自动比对、真实 PostgreSQL、双浏览器 E2E、两 Worker、多租户越权、配额并发、部署/恢复和负载测试。这些按 P2–P8 分阶段补齐，P0 不伪造为已覆盖。
