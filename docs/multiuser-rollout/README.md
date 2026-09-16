# 多用户改造执行索引

本目录记录协作版 `imherro/OurVideoCreator` 的分阶段实施产物。冻结需求、P0–P8 提示词、验收矩阵和证据模板的完整原文在 [`../MyVideoCreator_Codex_Full_Playbook_v1.md`](../MyVideoCreator_Codex_Full_Playbook_v1.md)。

已通过阶段：**P0 — 建立基线与实施契约；P1 — 外部 API-only 与独立 Web/Worker**

状态：**P2-PG-01 READY_FOR_REVIEW**（业务 SHA `a6820b045123ed73953cbe5667821225f8ceafb5`；尚未外部验收）

当前阶段：**P2-PG-01 已完成开发侧取证，等待外部验收**

P1 首次被审查 HEAD：`5ed0afa361b0e86590cd05b9ac285d9285854635`（业务 SHA `249b5d0176971c0d6eca510cc72ae0df91b75e1f`）

P1-R1 被测试业务 SHA：`f27439fc9fcabd706e2772d5cd7212d76a9f4706`

P1-R2 被测试业务 SHA：`16a56194c7a15e71142696b283934ea1b7a2e3b5`

P1-R2 外部复验 HEAD：`e4c61feba12765a6b70ecc9ee1e9db8e223372b1`（不通过；唯一阻塞 `OVC-P1-R2-01`）

P1-R3 被测试业务 SHA：`7283fc513cdc8bd296b54e340875ead9431055e4`

P1-R3 外部通过 HEAD：`6358c76f238a680dc9bd27b44968d5fe82db29d0`（`OVC-P1-R2-01` 已关闭；非阻塞观察 `OVC-P1-R3-N01`）

下一阶段：**P3 未授权，等待 P2 外部验收**

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

## 阶段边界

P1 已完成内置推理移除并建立独立 Web/Worker 进程边界。P2-PG-01 已把现有保留业务切换到 PostgreSQL 唯一主库并继续保持单 Worker，不提前实现 P3 之后的身份权限、凭证、多 Worker 或公网发布能力，也不调用真实付费 API。

P0 首次外部验收在 `3c0e5ca` 给出 OVC-P0-01 至 OVC-P0-05；P0-R1 在 `b957e39` 复验通过，五项全部关闭且无新增阻塞。P1 首次外部验收在 `5ed0afa` 给出阻塞项 OVC-P1-01、OVC-P1-02 及非阻塞项 OVC-P1-N01；P1-R1 至 P1-R3 逐项关闭，最终在 `6358c76` 通过。P2-PG-01 已在 `a6820b0` 完成开发侧全量取证，当前不自行宣称通过、不开始 P3。后续阶段仍以总册中的总控提示词、冻结契约、当前阶段提示词和相关验收矩阵为准。
