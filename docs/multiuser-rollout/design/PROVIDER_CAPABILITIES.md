# P0 Provider 能力与改造矩阵

## 当前适配器

| 类型 | 文本 | 图片 | 视频 | 语音 | 异步恢复 | 参考素材 | 取消 | P0 证据 |
|---|---:|---:|---:|---:|---|---|---|---|
| 本地 llama/openai bridge | — | — | — | — | — | — | — | P1 已删除，无本地回退 |
| Maestro/WanGP 外部 API | 否 | 是 | 是 | 否 | provider_job_id 查询 | 首帧/尾帧按能力 | `/cancel` | `worker.py::maestro`；P1 仅保留 HTTP 适配器，不自动启动或读取服务端文件 |
| OpenAI-compatible | 是 | 可配置 | 否 | 否 | 多为同步 | 图片 data | 无统一协议 | `worker.py` |
| ComfyUI | 否 | 是 | 是 | **否（项目未接通）** | prompt_id | 工作流上传；当前尾帧不支持 | queue delete | `worker.py::comfy`；上游工作流潜力不等于当前能力 |
| JSON video gateway | 否 | 否 | 是 | 否 | task id 查询 | 当前不支持 | 未统一 | `worker.py::video_api` |
| MiniMax Hailuo | 否 | 否 | 是 | 否 | task id 查询 | 单首帧；尾帧不支持 | 依供应商 | `minimax_video.py`、`test_minimax_video.py` |
| Replicate | 依模板/模型 | 依模板/模型 | 依模板/模型 | **否（项目未接通）** | prediction id | 模板映射 data URI | 支持 prediction cancel | `replicate_api.py`、`test_replicate_api.py` |
| 火山方舟 | 是 | Seedream | Seedance 2.5 | 否 | 视频 task id | 图片多参考；视频首/尾帧及固定对白音频 | 视频远端取消 | `providers/volcengine_ark.py`、`test_volcengine_ark.py` |
| RunningHub | 是 | Seedream v5 Pro | Seedance 2.5 token | 否 | taskId + query | 图片最多 10；视频模式化多参考/音频 | 当前无统一取消，远端可能继续 | `providers/runninghub.py`、`test_runninghub.py` |
| 幻场 HC-ATOM | 是 | 异步图片 | 异步视频 | 否 | task id 查询 | 视频单图；图片最多 10；素材组/审核/映射 | 协议支持时请求取消 | `providers/hc_atom.py`、`test_hc_atom.py` |
| 豆包语音 | 否 | 否 | 否 | 是 | SSE 同步结果 | 固定音色/对白文本 | 无异步取消 | `providers/volcengine_speech.py`、`test_volcengine_speech.py` |

## 当前配置与风险

- Provider 数组及明文 `api_key` 存在 SQLite `settings` JSON。
- `GET /api/settings` 对普通 session 隐藏 Key 字段，但任意已登录者可调用 `PUT /api/settings` 改写配置。
- Worker 把完整 Provider JSON 写入 `job_private.provider`，因此任务快照含明文 Key。
- URL 由全局设置直接提供，缺少统一 SSRF/重定向/下载大小策略。
- 部分能力由运行时目录或供应商目录动态发现；部分来自配置 flags。P4 需收敛为平台 model/version 能力目录。
- 当前 `/verify` 读取模型/账号信息，不应生成付费内容；`/test` 只检查所选模型是否在目录。无免费验证接口时目标行为应是“配置已保存，未验证”。
- `create_job_record()` 当前对 `audio` 明确只允许 `volcengine_speech`。表中“是/依模型”表示本项目已接通能力；ComfyUI 或 Replicate 上游可能支持但未接通的能力只记为未来扩展，不能展示给用户。

## 目标平台目录

普通用户只看到：`platform_model_id`、展示名、用途、启用状态、允许参数、能力（参考图数量、首尾帧、音频、时长/分辨率等）。提交只能引用 `platform_model_id` 和允许参数。

平台管理员维护：Provider 类型、受控 base URL、认证加密 credential version、上游模型标识、能力、默认值/范围、启停状态。服务端拒绝客户端覆盖 `provider`、`base_url`、`api_key`、upstream model id、headers 和模板字段。

任务冻结：platform model version、非秘密 Provider 配置版本、credential version 引用和允许参数。明文密钥只在执行时由受控服务解密，不进入 job、API、SSE、日志、历史或导出。

## 必须保留的协议回归

1. 双遍分镜文本结构与一次有限修复。
2. Film Bible 引用顺序和稳定视觉绑定。
3. 方舟/RunningHub/幻场的模型目录与能力校验。
4. 首帧、尾帧、参考图限制和不支持组合的明确拒绝。
5. 远端 task id 在轮询前持久化，恢复只查询原任务。
6. 豆包固定音色对白进入项目 voice 资产。
7. 幻场素材组创建、远端素材登记、审核等待、持久映射、同幂等键重试与账户隔离。
8. Replicate 模板替换和 prediction 恢复/取消。

## P0 测试边界与 Fake Provider 计划

当前协议测试已广泛使用 `httpx.MockTransport` 和 monkeypatch，覆盖文本、图片、视频、语音、task id、超时/错误及下载登记，但尚未形成一个统一、可启动的 test-profile Provider。

P1 最小骨架建议提供独立测试适配器/进程，只有测试 profile 可启用，具备：同步文本、结构化双遍输出、图片/视频/语音测试媒体、异步 task id、可控 429/timeout/已接单丢响应/重复终态/取消不支持、请求计数和安全下载。生产配置不能通过万能环境变量启用它。P0 不改业务调用链。
