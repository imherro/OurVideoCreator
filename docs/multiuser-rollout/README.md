# 多用户改造执行索引

本目录记录协作版 `imherro/OurVideoCreator` 的分阶段实施产物。冻结需求、P0–P8 提示词、验收矩阵和证据模板的完整原文在 [`../MyVideoCreator_Codex_Full_Playbook_v1.md`](../MyVideoCreator_Codex_Full_Playbook_v1.md)。

已通过阶段：**P0、P1、P2**

状态：**P3-R2 返修中**

当前阶段：**P3-ID-01 — 邀请制账号、团队/作品隔离与基础页面闭环**

P1 首次被审查 HEAD：`5ed0afa361b0e86590cd05b9ac285d9285854635`（业务 SHA `249b5d0176971c0d6eca510cc72ae0df91b75e1f`）

P1-R1 被测试业务 SHA：`f27439fc9fcabd706e2772d5cd7212d76a9f4706`

P1-R2 被测试业务 SHA：`16a56194c7a15e71142696b283934ea1b7a2e3b5`

P1-R2 外部复验 HEAD：`e4c61feba12765a6b70ecc9ee1e9db8e223372b1`（不通过；唯一阻塞 `OVC-P1-R2-01`）

P1-R3 被测试业务 SHA：`7283fc513cdc8bd296b54e340875ead9431055e4`

P1-R3 外部通过 HEAD：`6358c76f238a680dc9bd27b44968d5fe82db29d0`（`OVC-P1-R2-01` 已关闭；非阻塞观察 `OVC-P1-R3-N01`）

P2 外部通过 HEAD：`a70341bad5c0da23153ad6cd44b67f2cd863dde1`（业务 SHA `fc8feee3d9c3bfaffb39c55ab10d41e0fff7050f`）

P3 首轮最终 HEAD：`dc1b0083db90ac1960b1f88117fa673e878c7baf`（外部不通过；阻塞 `OVC-P3-01…06`）

P3-R1 被测试业务 SHA：`a8cd59e8247b915737084383f5b53df1f831f4fe`（六项阻塞已提交待外部复验）

P3-R1 外部复验 HEAD：`5e0c5e36d37415d4867d380f4e86dd47c87eebce`（关闭 `OVC-P3-01/02/04`；剩余 `OVC-P3-R1-01…03`）

下一阶段：**P4 未授权；当前只实施 P3-R2**

参考单机版基线：`464914c553f4c1856ca77da4a07e9d5fffb7f71e`

P0 实际 base：`ade703cf20b66cfccc4520730747c0abf07c2158`

## 阶段产物

- [`design/BASELINE.md`](design/BASELINE.md)
- [`design/CODE_MAP.md`](design/CODE_MAP.md)
- [`design/FEATURE_MATRIX.md`](design/FEATURE_MATRIX.md)
- [`design/ROUTE_AUTH_MAP.md`](design/ROUTE_AUTH_MAP.md)
- [`design/DATA_OWNERSHIP.md`](design/DATA_OWNERSHIP.md)
- [`design/PERMISSIONS.md`](design/PERMISSIONS.md)
- [`design/API_CONTRACT.md`](design/API_CONTRACT.md)
- [`design/JOB_STATE_MACHINE.md`](design/JOB_STATE_MACHINE.md)
- [`design/PROVIDER_CAPABILITIES.md`](design/PROVIDER_CAPABILITIES.md)
- [`design/P2_STORAGE_CHANGELOG.md`](design/P2_STORAGE_CHANGELOG.md)（PostgreSQL schema、事务、Worker lock 与存储边界）
- [`evidence/P0/REPORT.md`](evidence/P0/REPORT.md)
- [`evidence/P0-R1/REPORT.md`](evidence/P0-R1/REPORT.md)（外部不通过后的逐项修正与原始补跑证据）
- [`evidence/P1/REPORT.md`](evidence/P1/REPORT.md)（内置推理移除、Web/Worker 分离及首次原始验收日志；保留不覆盖）
- [`evidence/P1-R1/REPORT.md`](evidence/P1-R1/REPORT.md)（实例所有权、确定性在途任务屏障及 P1-R1 完整回归）
- [`evidence/P1-R2/REPORT.md`](evidence/P1-R2/REPORT.md)（脚本工程根绑定、三种数据目录模式的跨工程真实脚本回归）
- [`evidence/P1-R3/REPORT.md`](evidence/P1-R3/REPORT.md)（调用者环境恢复、同一 PowerShell PID 连续调用及非零出口回归）
- [`evidence/P2/REPORT.md`](evidence/P2/REPORT.md)（PostgreSQL 唯一主库、空库迁移、完整业务与 Web/Worker 证据）
- [`evidence/P3/REPORT.md`](evidence/P3/REPORT.md)（邀请制身份、团队/作品 ACL、SSE 撤权和基础页面闭环）
- [`evidence/P3-R1/REPORT.md`](evidence/P3-R1/REPORT.md)（六项外部阻塞返修、并发不变量、真实浏览器与重新取证）

## 阶段边界

P1 已完成内置推理移除并建立独立 Web/Worker 进程边界；P2 已把保留业务切换到 PostgreSQL 唯一主库。P3-R2 只补首次限流并发入场、重置令牌签发/消费一致性与真实浏览器原始证据，继续保持单 Worker、内部试用且不调用真实付费 API；P4 的平台统一 Provider/Key/模型后台、多 Worker 与公网发布尚未实施。

P0 首次外部验收在 `3c0e5ca` 给出 OVC-P0-01 至 OVC-P0-05；P0-R1 在 `b957e39` 复验通过。P1 经 P1-R1 至 P1-R3 最终在 `6358c76` 通过。P2 经 P2-R1、P2-R2 最终在 `a70341b` 通过，阻塞项全部关闭；保留非阻塞观察 `OVC-P2-R2-N01`。P3 是否通过仍由外部验收人基于协作版仓库和证据决定，开发侧不自行宣称通过或进入 P4。
