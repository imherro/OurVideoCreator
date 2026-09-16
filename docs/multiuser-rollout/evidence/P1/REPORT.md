# P1 交付报告

## 1. 身份、范围与状态

- 阶段：P1 — 移除内置推理，分离 Web 与任务进程。
- 前置外部通过：P0-R1，`b957e39405522baf8ae7e3052b2938941e75b00b`。
- 本次 base SHA：`4fe7735e1b0abf0085c1e408bdee6ea0b3458542`。
- 被测试业务代码 SHA：`249b5d0176971c0d6eca510cc72ae0df91b75e1f`。
- 分支：`master`。
- 唯一审核仓库：`https://github.com/imherro/OurVideoCreator`（不是单机版仓库）。
- 交付状态：**READY_FOR_REVIEW**；未自行填写外部通过，未开始 P2。

本阶段继续使用 SQLite 和单 Worker 进程，只用于内部开发，不具备公网多用户安全条件。没有调用真实付费 API，也没有迁移旧数据。

## 2. 实施结果

| P1 要求 | 实现 | 关键定位 |
|---|---|---|
| 移除内置推理 | 删除 `backend/runtime.py`、整个 `inference/`（1,918 个文件）及内置导入/冒烟脚本；移除 GPU/CUDA、模型扫描/下载/加载/卸载和 llama/Maestro 自启动依赖 | `backend/app.py`、`backend/worker.py`、`backend/media.py` |
| 外部 API-only | 保留 OpenAI-compatible、Ark、语音、RunningHub、幻场、Replicate、MiniMax、ComfyUI、Maestro API adapter；Maestro 不再读取服务端本机输出目录 | `backend/worker.py`、`backend/providers/` |
| 无静默回退 | 未选 Provider、已删 `local` 或 Provider 不存在时，在建任务/批量运行/Worker 出站前明确失败；不自动选首个付费模型 | `backend/generation_policy.py`、`src/generationPolicy.ts`、`backend/app.py` |
| Web/Worker 分离 | lifespan 只初始化持久层；Web 不创建 Worker、不持有 `worker.lock`；新增独立 Worker CLI | `backend/app.py`、`backend/worker_cli.py` |
| 单 Worker 边界 | 第二个 Worker 明确拒绝并以退出码 2 结束；P6 前不声称多 Worker 安全 | `backend/worker.py`、`backend/process_lock.py` |
| 启停行为 | 启动脚本分别启动 Web/Worker，支持 `-WebOnly`/`-WorkerOnly`；停止脚本核对命令行后才按 PID 停止，避免陈旧 PID 误杀 | `Start-Studio.ps1`、`Stop-Studio.ps1` |
| FFmpeg 保留 | 继续从配置、系统 PATH 或 `imageio_ffmpeg` 寻找 FFmpeg；实际导出并解码测试保留 | `backend/media.py`、`tests/test_export.py` |
| UI 清理 | 移除本地模型目录、llama、硬件/runtime、加载/卸载和 Maestro 启动控件；页面标明 external API-only 和独立 Worker | `src/main.tsx`、`src/ModelSelector.tsx`、`tests/p1_surface.test.mjs` |
| 测试禁付费出站 | pytest 自动阻断所有非 loopback socket；进程测试只使用本机 fake Provider；缺 Provider 请求计数为零 | `tests/conftest.py`、`tests/fake_provider_server.py`、`tests/test_p1_processes.py` |
| P0-R1 文档同步 | 导演台保持 `COLLAB-11`、前端私有状态 `COLLAB-12`；Twick lease/review 为 `COLLAB-06/07`；提示词模板为 `P4-TPL-01`；路由审计 P1 仍只读报告，P3 `ACL-09` 才升级守卫 | `design/DATA_OWNERSHIP.md`、`design/FEATURE_MATRIX.md`、`design/ROUTE_AUTH_MAP.md` |

## 3. 必须验证与实测证据

| 验证项 | 实际结果 | 原始证据 |
|---|---|---|
| 无模型/GPU/推理环境时 Web 可启动 | 两个真实 uvicorn Web 在已删除 `inference/` 和 runtime 的提交上健康响应；均未创建 `worker.lock` | `06-process-boundary.log`、`11-removed-surface.json` |
| 两个 Web 不争 Worker 锁 | 两个 Web 同时运行并共享独立临时数据目录，任务保持 queued，直到独立 Worker 启动 | `06-process-boundary.log` |
| Web 重启不影响任务 | 提交假文本任务后停止 Web-1，Worker 保持运行；同端口启动新 Web，Web-2 观察任务成功 | `06-process-boundary.log` |
| 单 Worker 显式限制 | Worker PID `25024` 成功处理任务；第二 Worker 退出码 2 | `06-process-boundary.log` |
| fake Provider 精确出站 | 成功任务请求数为 1；缺失/旧 local Provider 测试在构造 HTTP client 前失败，请求数为 0 | `06-process-boundary.log`、`08-zero-upstream-on-missing-provider.log` |
| FFmpeg 实际导出 | 5 个导出测试实际合成并用 FFmpeg/ffprobe 解码，5/5 通过 | `07-ffmpeg-export.log` |
| 默认 UI 无本地模型入口 | 源码约束检查旧目录、llama、runtime 路由及卸载控件不存在；前端生产构建成功 | `02-npm-test.log`、`03-npm-build.log` |
| Provider/素材/剪辑回归 | Python 全量 251/251；前端全量 125/125 | `05-pytest.log`、`02-npm-test.log` |
| 路由地图同步 | 实际 69 个注册入口，其中 67 个 API decorator，67/67 已分类、0 未分类；当前明确 report-only | `09-route-audit.log` |

进程证据中的 PID 是该次隔离测试的瞬时 PID，测试结束已清理所有子进程。测试临时目录由 pytest 管理，不使用用户正式 `data/`。

## 4. 最终证据运行

所有命令在业务 SHA `249b5d0176971c0d6eca510cc72ae0df91b75e1f` 上重新运行，UTC 时间、耗时、退出码和未编辑合并输出保存在相应日志；汇总见 `SUMMARY.json`。

| 命令 | 结果 | 耗时 |
|---|---:|---:|
| `npm ci` | exit 0 | 73.780s |
| `npm test` | 125/125，exit 0 | 1.490s |
| `npm run build` | 1825 modules，exit 0 | 14.640s |
| `python -m pytest --collect-only -q` | 251 collected，exit 0 | 1.700s |
| `python -m pytest -q` | 251/251，exit 0 | 30.315s |
| `python -m pytest -q tests/test_p1_processes.py -s` | 1/1，exit 0 | 5.874s |
| `python -m pytest -q tests/test_export.py -s` | 5/5，exit 0 | 7.730s |
| 缺 Provider 零出站定向测试 | 1/1，exit 0 | 1.540s |
| `python scripts/audit_routes.py` | 67/67 classified，exit 0 | 0.580s |
| `git diff --check` | exit 0 | 0.040s |

环境：Windows 11 `10.0.26200`、Python `3.14.2`、Node `24.13.0`、npm `11.8.0`。Vite 仍报告既有大 chunk 警告；构建成功，性能拆分不属于 P1。

开发期间的首次失败、原因和修正见 `ATTEMPT_HISTORY.md`。最终证据运行没有失败或重试。

## 5. 保留、删除与阶段边界

- 保留：项目/作品/剧集、原著资料库、改编与剧本、Film Bible、分镜、生成队列、素材登记、参考图/首尾帧/对白链路、Twick 编辑与 FFmpeg 导出、所有外部 Provider adapter。
- 删除：仅内置推理目录、runtime 桥、模型扫描/下载/硬件探测、内置引擎安装和本地默认/回退。
- P1 不做：PostgreSQL、团队身份/ACL、凭证加密与轮换、多 Worker lease/fencing/quota、对象级协作 API、公网发布；对应 P2–P8。
- 路由审计仍是只读报告工具，不能把 P3 `ACL-09` 的未来约束冒充本阶段已实现。

## 6. 外部审核入口

- 审核仓库：`https://github.com/imherro/OurVideoCreator`
- 分支：`master`
- 被测试业务代码：`249b5d0176971c0d6eca510cc72ae0df91b75e1f`
- 最终 evidence-only head：见本报告提交后的 Git SHA 和审核消息；该提交只增加证据并更新阶段状态。
- 推荐先读：本报告、`SUMMARY.json`、`06-process-boundary.log`、`FEATURE_MATRIX.md`，再核对 `backend/app.py`、`backend/worker_cli.py`、`backend/worker.py`、启动脚本和 P1 测试。
- 最小复跑：`npm ci && npm test && npm run build`；`python -m pytest -q`。
- 真实付费 API：未运行且未授权。
- 真实公网部署：未运行且 P1 明确禁止。

请外部验收人读取新仓库实际代码、提交 diff 和原始日志，不根据本报告自述直接判通过。P1 审核完成前不进入 P2。
