# P0 基线记录

## Git 与范围

- 协作仓库：`https://github.com/imherro/OurVideoCreator`
- 分支：`master`
- P0 base：`ade703cf20b66cfccc4520730747c0abf07c2158`
- 已知单机版参考基线：`464914c553f4c1856ca77da4a07e9d5fffb7f71e`
- base 比参考基线多一个文档提交 `ade703c`，没有回退代码。
- 开始 P0 时唯一未提交内容为用户提供的 `docs/MyVideoCreator_Codex_Full_Playbook_v1.md`；已保留并纳入交付。
- 仓库没有 `.github/workflows`，因此当前没有仓库内 CI 配置。

## 运行环境

| 项目 | 实际值 |
|---|---|
| OS | Windows 11 Pro 10.0.26200，64 位 |
| CPU | Intel Core i7-11700K，8 核 16 线程 |
| 内存 | 约 63.8 GiB 可见内存 |
| Python | 3.14.2 |
| pip | 25.3 |
| Node.js | 24.13.0 |
| npm | 11.8.0 |
| Git | 2.34.1.windows.1 |
| FFmpeg | 8.1.1 full build |
| PostgreSQL | P0 不需要；未用于本轮测试 |

README 声明 Python 3.11+、Node 20+；本机版本满足下限，但 Python 3.14 与 Node 24 尚未在仓库中锁定。P0 不升级依赖。

## 依赖、启动与数据隔离

- 前端依赖由 `package-lock.json` 和 `npm ci` 安装；脚本定义在 `package.json`。
- Python 依赖只有范围约束，见 `requirements.txt`，没有 hash lock。
- `pytest.ini` 仅指定 `testpaths = tests`。
- `tests/conftest.py` 在收集阶段把 `MVC_DATA_DIR` 设置为新建临时目录，因此测试不会读取或修改开发数据库和素材。
- `Install-Studio.ps1` 创建 `.venv`、安装依赖并构建；`Start-Studio.ps1` 启动当前单机架构。
- 测试中的供应商网络通过 `httpx.MockTransport`、monkeypatch 或本地不可达测试地址替代；本轮未配置或输出真实 Key，未调用真实付费 API。

## 实际命令与结果

| 命令 | 退出码 | 结果 |
|---|---:|---|
| `npm ci` | 0 | 安装 383 个包；存在上游 deprecated 警告 |
| `python -m pytest --collect-only -q` | 0 | 收集 251 个 Python 测试 |
| `npm test` | 0 | 123 通过，0 失败，0 跳过 |
| `npm run build` | 0 | TypeScript 与 Vite 构建成功；若干 bundle 超过 500 kB，最大约 3.9 MB |
| `python -m pytest -q` | 0 | 251 通过，0 失败，0 跳过，26.00 秒 |

没有配置浏览器 E2E 命令；现有 `.test.mjs` 是 Node 测试，不能声称完成真实双浏览器验证。P0 不要求 PostgreSQL、并发 Worker 或真实供应商测试。

## 当前架构结论

1. 运行时是单租户 SQLite：`backend/store.py` 打开 `data/studio.sqlite` 并在应用启动时建表、迁移和扫描数据。
2. 身份是一个共享工作室密码和全局 session cookie，不存在用户、团队、作品成员或角色。
3. FastAPI lifespan 同时初始化存储、本地推理 runtime 和内嵌 Worker；Web 与执行进程未分离。
4. `src/main.tsx` 以 2.5 秒自动保存整份项目 `document` 到 `PUT /api/projects/{pid}`；后端用项目 revision 和 Production revision 避免整份快照静默覆盖。
5. 章节、改编计划和逐集剧本已经是独立 revision 对象；Film Bible/镜头/画布/时间线仍主要位于聚合 document。
6. Provider 配置和明文 Key 保存在全局 `settings` JSON；普通认证用户可读脱敏配置并写整个设置。
7. 任务是 SQLite 持久队列，单 Worker 通过进程锁领取；已有提交 ID、远端任务 ID、取消优先和恢复查询逻辑，但没有多 Worker lease/fencing/配额。
8. 共有 69 条 FastAPI 业务路由；除 4 条公开认证路由和签名素材路由外，都只要求全局 session，不具备租户/作品/对象级授权。

## P0 停止状态

`READY_FOR_REVIEW`。没有修改业务代码、业务数据库或数据，没有开始 P1。
