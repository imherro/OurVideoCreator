# 多用户改造执行索引

本目录记录协作版 `imherro/OurVideoCreator` 的分阶段实施产物。冻结需求、P0–P8 提示词、验收矩阵和证据模板的完整原文在 [`../MyVideoCreator_Codex_Full_Playbook_v1.md`](../MyVideoCreator_Codex_Full_Playbook_v1.md)。

已通过阶段：**P0 — 建立基线与实施契约**

状态：**PASSED**（外部复验绑定 `b957e39405522baf8ae7e3052b2938941e75b00b`）

下一阶段：**P1 已授权、尚未开始**

参考单机版基线：`464914c553f4c1856ca77da4a07e9d5fffb7f71e`

P0 实际 base：`ade703cf20b66cfccc4520730747c0abf07c2158`

## P0 产物

- [`design/BASELINE.md`](design/BASELINE.md)
- [`design/CODE_MAP.md`](design/CODE_MAP.md)
- [`design/FEATURE_MATRIX.md`](design/FEATURE_MATRIX.md)
- [`design/ROUTE_AUTH_MAP.md`](design/ROUTE_AUTH_MAP.md)
- [`design/DATA_OWNERSHIP.md`](design/DATA_OWNERSHIP.md)
- [`design/PERMISSIONS.md`](design/PERMISSIONS.md)
- [`design/API_CONTRACT.md`](design/API_CONTRACT.md)
- [`design/JOB_STATE_MACHINE.md`](design/JOB_STATE_MACHINE.md)
- [`design/PROVIDER_CAPABILITIES.md`](design/PROVIDER_CAPABILITIES.md)
- [`evidence/P0/REPORT.md`](evidence/P0/REPORT.md)
- [`evidence/P0-R1/REPORT.md`](evidence/P0-R1/REPORT.md)（外部不通过后的逐项修正与原始补跑证据）

## 阶段边界

本轮只产出代码/路由/数据/权限/任务/Provider 地图和真实基线测试证据。没有修改业务代码、数据库结构或运行数据；没有开始 P1；没有调用真实付费 API。

P0 首次外部验收在 `3c0e5ca` 给出 OVC-P0-01 至 OVC-P0-05；P0-R1 在 `b957e39` 复验通过，五项全部关闭且无新增阻塞。P1 已获授权，但本轮没有擅自开始。后续阶段仍以总册中的总控提示词、冻结契约、当前阶段提示词和相关验收矩阵为准。
