# P0-R1 设计修正与证据补齐报告

## 范围与状态

- 审核仓库：`https://github.com/imherro/OurVideoCreator`，分支 `master`。
- 外部不通过绑定 SHA：`3c0e5ca1269d25b2d8db2323b057ac4d05ea00e2`。
- 被测业务代码仍为：`ade703cf20b66cfccc4520730747c0abf07c2158`；P0/P0-R1 未修改业务代码或测试。
- 本次只修正 P0 文档、增加只读路由审计和原始证据采集；未开始 P1、未迁数据库、未实现账号权限、未删除推理、未调用真实付费 API。
- 交付状态：**READY_FOR_REVIEW**；P1 仍未授权。

## 外部问题逐项处理

| 问题 | 修复位置 | 结果/复验点 |
|---|---|---|
| OVC-P0-01 | `PERMISSIONS.md`、`ROUTE_AUTH_MAP.md`、`API_CONTRACT.md` | 明确旧 `POST /api/projects` 实际创建 Production+首集，只能 WO 使用并退役；PM 仅能在已有 Production 内创建 Episode；加入正反边界 |
| OVC-P0-02 | `DATA_OWNERSHIP.md`、`API_CONTRACT.md`、`FEATURE_MATRIX.md` | 补齐导演台、固定音色、提示词库、旧简剪、Twick、audio、graph、visual、policy 的当前字段→唯一对象→归属→权限→revision/lease→API→退役→验收映射 |
| OVC-P0-03 | `scripts/audit_routes.py`、`ROUTE_AUTH_MAP.md`、`11-route-audit-classification.log` | 在临时 `MVC_DATA_DIR` 导出实际 `app.routes` 并逐项比对安全分类；确认 build 后 71 项=69 API+OpenAPI+Mount，69 API 无漏项，说明无 dist 时仅少 Mount；统一计数与公开策略 |
| OVC-P0-04 | 本目录全部 `.log`、`SUMMARY.json`、`scripts/capture_p0_evidence.py` | P0-R1 补跑并保存原始 stdout/stderr、退出码、UTC 时间、耗时、版本、Git 状态和依赖清单；明确不是冒充首次 P0 原始日志 |
| OVC-P0-05 | `CODE_MAP.md`、`PROVIDER_CAPABILITIES.md` | Worker 改为“单进程默认四领取线程，部分并发/部分串行”；ComfyUI/Replicate audio 标为项目未接通，不修改业务代码迎合旧文档 |

## P3 正反验收案例（OVC-P0-01）

1. WO 调用 Workspace-scoped Production 创建命令成功并可指定 Workspace 内 manager。
2. PA 只通过显式后台入口跨租户创建，产生审计；普通业务入口无万能 bypass。
3. 仅为 Production A manager 的用户调用旧 `POST /api/projects` 创建 Production B 返回 403/404，不产生半写数据。
4. 同一 manager 在有管理权的 Production A 调用 Episode 创建命令成功；对 Production B 失败。
5. 旧兼容入口与规范创建入口使用同一服务端授权函数，不能因直接请求绕过。

## 补跑证据索引

`SUMMARY.json` 是机器可读索引。所有输出未经摘要替换：

| 文件 | 结果 |
|---|---|
| `01-npm-ci.log` | exit 0；包含安装与 deprecated 警告 |
| `02-npm-test.log` | exit 0；123/123 通过 |
| `03-npm-build.log` | exit 0；build 成功并保留大 chunk warning |
| `04-pytest-collect.log` | exit 0；251 collected，保留完整节点清单 |
| `05-pytest.log` | exit 0；251 passed |
| `06-route-audit.log` | exit 1；首次脚本模块路径失败，未隐藏 |
| `07-route-audit-retry.log` | exit 0；修复后仅重跑路由审计，71 个实际注册项 |
| `08-python-dependencies.log` | 实际 Python 包版本 |
| `09-node-dependencies.log` | 实际顶层 Node 包版本 |
| `10-git-snapshot.log` | 提交前 Git 状态、diff stat/name-status 与 `diff --check` |
| `11-route-audit-classification.log` | 最终路由审计：69 API 全部分类、OpenAPI/Mount 已登记 |

测试数据由 `tests/conftest.py` 设置临时 `MVC_DATA_DIR`。Provider 测试使用 MockTransport、monkeypatch 或本地测试地址；本次未提供真实凭证，未调用付费 API。首次补跑的五个基线命令均未重试；路由审计唯一一次失败及重试均保留。

## 未验证项

浏览器 E2E、PostgreSQL、多 Worker 进程、部署/恢复/负载仍属于后续阶段，不作为 P0-R1 冒充验证。最终 P0-R1 Git SHA 在提交、推送及复验消息中给出。
