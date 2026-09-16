# P0 交付报告

## 1. 身份和范围

- 阶段：P0 — 建立基线与实施契约。
- 本轮指定范围：只建立实际代码/功能/路由/数据/权限/API/任务/Provider 地图，执行基线测试并整理证据；不开始 P1。
- 上个外部通过 SHA：无，P0 是首个阶段。
- 本次 base SHA：`ade703cf20b66cfccc4520730747c0abf07c2158`。
- 被测试的业务代码 SHA：`ade703cf20b66cfccc4520730747c0abf07c2158`。
- P0 设计与规则提交：`486ffdb8509e7493c99be454263a331aa077ebd5`。
- 最终交付 head：本报告是后续 evidence-only 提交，最终 SHA 由提交后 Git 值和审核消息给出；它相对 `486ffdb` 只增加/更新证据文档。
- 分支：`master`；审核仓库：`https://github.com/imherro/OurVideoCreator`。
- 工作区：提交本报告并推送后应为干净；提交前由命令复核。
- 交付状态：**READY_FOR_REVIEW**。

P0 没有修改业务代码，因此被测试业务 SHA 仍是 base。`486ffdb` 仅包含用户提供的总册、P0 设计产物和根规则；本报告提交只包含 evidence/GATE_LOG 变化。

## 2. 改动概览

| 需求/用例 | 文件/模块 | 完成行为 | 删除/替代旧路径 | 风险 |
|---|---|---|---|---|
| BASE-01 | `design/BASELINE.md` | 记录真实 HEAD、用户新增 docs、环境、测试和当前架构 | 未删除 | 无业务运行影响 |
| BASE-03 | `design/CODE_MAP.md` | 映射 app/store/worker/runtime/前端保存和测试 | 未删除 | P1/P2 必须按清单处理直接 SQL |
| BASE-03 | `design/FEATURE_MATRIX.md` | 逐项标记保留/移除/改造，包含幻场登记 | 未删除 | 后续删测试必须回填替代证据 |
| BASE-04 | `design/ROUTE_AUTH_MAP.md` | 分类全部 69 条 FastAPI 路由及目标权限/副作用 | 未改路由 | 当前全局 session 缺口仍存在，P3 修复 |
| BASE-05 | `design/DATA_OWNERSHIP.md` | 定义 Workspace/Production/Episode 语义、对象主源和退役顺序 | 未迁移数据 | P2/P5 不得形成双主源 |
| BASE-05 | `design/PERMISSIONS.md` | 冻结平台/团队/作品角色矩阵 | 未实现权限 | P3 前版本不可公网协作 |
| BASE-05 | `design/API_CONTRACT.md` | 定义 expected_revision、对象 API、旧 PUT 退役和任务/文件规则 | 未新增 API | 命名可调整，行为不可弱化 |
| BASE-03/05 | `design/JOB_STATE_MACHINE.md` | 定义付费边界、lease/fencing、幂等和配额口径 | 未改 Worker | P6 前仍是单 Worker 语义 |
| BASE-03 | `design/PROVIDER_CAPABILITIES.md` | 记录现有适配器能力、风险和 fake Provider 计划 | 未调用 Provider | P4/P6 按协议回归 |
| 阶段控制 | `AGENTS.md`、`multiuser-rollout/README.md`、`GATE_LOG.md` | 合并短规则、建立入口和待审关口 | 未覆盖原规则 | 未获外部通过不能进入 P1 |

未新增、修改或删除任何业务测试；本轮只执行现有测试。

## 3. 运行环境

| 项目 | 实际值 |
|---|---|
| OS/CPU/内存 | Windows 11 Pro 10.0.26200；i7-11700K 8C/16T；约 63.8 GiB |
| Python | 3.14.2；pip 25.3 |
| Node | 24.13.0；npm 11.8.0 |
| PostgreSQL | P0 未使用；真实 PG 从 P2 起强制 |
| 依赖 | `package-lock.json` + `npm ci`；Python 使用 `requirements.txt` 范围约束 |
| Web/Worker | 未启动服务进程；基线单元/集成测试在测试进程内运行 |
| 浏览器 | 没有仓库内 E2E 脚本，NOT_RUN |
| Provider | `httpx.MockTransport`、monkeypatch 和本地测试地址；无真实付费出站 |
| 测试数据 | `tests/conftest.py` 每次新建临时 `MVC_DATA_DIR` |

## 4. 实际命令与结果

| 测试层 | 完整命令 | 退出码 | 收集/通过/失败/跳过 | 证据摘要 |
|---|---|---:|---|---|
| 依赖安装 | `npm ci` | 0 | 383 packages | 有 deprecated 包警告，无安装失败 |
| Python 收集 | `python -m pytest --collect-only -q` | 0 | 251 collected | 完整列出测试节点 |
| 前端测试 | `npm test` | 0 | 123/123/0/0 | Node test runner，约 0.84s |
| 前端 build | `npm run build` | 0 | build success | 1825 modules；大 chunk 警告，最大约 3.9 MB |
| Python 测试 | `python -m pytest -q` | 0 | 251/251/0/0 | 26.00s |
| 路由枚举 | `rg "@app\.(get|post|put|patch|delete)" backend/app.py` | 0 | 69 route decorators | 已逐项写入授权地图 |
| 浏览器 E2E | NOT_RUN | — | — | 仓库没有配置 Playwright/Puppeteer E2E 命令；P0 不以源码断言冒充浏览器验证 |
| PostgreSQL/并发 | NOT_RUN | — | — | P2 交付范围 |
| 部署/性能/恢复 | NOT_RUN | — | — | P7/P8 交付范围 |

测试没有重试；上表均为第一次实际运行结果。

## 5. BASE 关键证据

| 用例 | 前置/操作 | 实际结果 | 定位 |
|---|---|---|---|
| BASE-01 | `git status --short --branch`、`git log -3` | base 为 `ade703c`；用户 `docs/` 未提交内容被保留；未回退 `464914c5` | `design/BASELINE.md` |
| BASE-02 | 执行 npm/Python 安装、收集、测试、build | 前端 123、Python 251 全通过；build 成功；未隐藏 warning/NOT_RUN | 本报告第 4 节 |
| BASE-03 | 对 key modules、provider adapters、tests 做路径/函数映射 | 保留矩阵覆盖双遍分镜、原著、Film Bible、指纹、恢复、首尾帧、对白、幻场登记、剪辑导出 | `CODE_MAP.md`、`FEATURE_MATRIX.md` |
| BASE-04 | 枚举 69 个 decorator 并按安全域逐项分类 | 发现当前除 public/signed 特例外只有共享 session；后续阶段与副作用已登记 | `ROUTE_AUTH_MAP.md` |
| BASE-05 | 对 SQLite schema、整份 PUT、独立 revision 对象和前端 autosave 定点阅读 | 定义唯一目标主源、对象负责人/revision、API 草案及旧 PUT 退役计划 | `DATA_OWNERSHIP.md`、`PERMISSIONS.md`、`API_CONTRACT.md` |

## 6. 已知问题与偏差

| ID | 严重性 | 影响 | 处理 |
|---|---|---|---|
| P0-RISK-01 | S1（未来公网阻塞） | 当前共享 session 下任意用户可改 Provider/Key 设置、读 job/asset/trash/event | 已完整登记；P3/P4 修复。P1/P2 明确只限内部开发 |
| P0-RISK-02 | S1（协作阻塞） | `main.tsx` 自动保存整份 document，同对象/不同对象都共享项目冲突域 | P5 对象 API 与 PUT 退役契约已冻结 |
| P0-RISK-03 | S1（多 Worker 阻塞） | 当前单机锁、无 lease/fencing/quota/unknown submission | P6 状态机与额度口径已冻结 |
| P0-RISK-04 | S1（秘密管理） | Provider 明文 Key 位于 settings 与 job_private | P4 加密/版本引用；本轮未输出真实 Key |
| P0-RISK-05 | S2 | 无浏览器 E2E 和仓库 CI | P0 如实 NOT_RUN；P3/P5/P7 补真实浏览器，后续补 CI |
| P0-RISK-06 | S3/性能 | Vite 报大 chunk，最大约 3.9 MB | 不在 P0 顺手优化；P7 性能阶段测量后处理 |
| P0-RISK-07 | S2/可复现性 | Python 依赖未 hash lock；本机为 3.14、Node 24，版本未固定 | P0 记录；P1/P7 选择并锁定受支持版本 |

无冻结契约偏差。源总册中的仓库名仍写旧单机库是历史来源；本轮开发与审核仓库明确为 `imherro/OurVideoCreator`。

## 7. 外部验收入口

- 审核仓库：`https://github.com/imherro/OurVideoCreator`
- 分支：`master`
- 被测试业务代码：`ade703cf20b66cfccc4520730747c0abf07c2158`
- P0 设计提交：`486ffdb8509e7493c99be454263a331aa077ebd5`
- 最终 evidence-only head：见 Git 提交及审核消息。
- 推荐先读：`BASELINE.md`、`CODE_MAP.md`、`FEATURE_MATRIX.md`、`ROUTE_AUTH_MAP.md`，再核对 `backend/app.py`、`store.py`、`worker.py`、`runtime.py`、`src/main.tsx` 和相关测试。
- 最小复跑：`npm ci && npm test && npm run build`；`python -m pytest -q`。
- 真实 API：未运行，且没有授权。
- 真实部署：未运行；P0 不声称部署通过。
- 本阶段结束，未进入下一阶段：**是**。

请外部验收人读取实际代码、提交 diff 和测试，不根据本报告自述直接判通过。Codex 不自行填写“外部通过”。
