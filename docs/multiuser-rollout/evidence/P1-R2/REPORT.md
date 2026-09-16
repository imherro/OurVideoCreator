# P1-R2 复验报告

状态：**READY_FOR_REVIEW**。本报告只登记开发侧证据，不自行宣称外部验收通过。

仓库：`https://github.com/imherro/OurVideoCreator`

被测试业务 SHA：`16a56194c7a15e71142696b283934ea1b7a2e3b5`

前次不通过审查 HEAD：`e698dcb2167cccd6c4797a49f2e4b1581b6c2b95`

## OVC-P1-R1-01 闭环

- `Resolve-StudioDataDirectory()` 以脚本 `$PSScriptRoot` 为固定根：未设置 `MVC_DATA_DIR` 时使用 `<root>/data`，绝对值保持绝对，相对值统一相对目标工程根解析；随后把绝对路径写回环境，保证身份查询及 Web/Worker 子进程使用同一数据目录。
- `Get-StudioIdentity()` 在 `Push-Location $Root` / `finally { Pop-Location }` 的受控上下文执行 `python -m backend.instance_identity`，不再从调用方当前目录加载模块。
- 返回后使用不区分大小写的规范路径比较 `project_root` 与目标根、`data_dir` 与规范数据目录；任一不匹配都会在读取、删除生命周期记录或操作进程前抛错。
- `06-cross-root-powershell.log` 使用两份临时完整后端副本 A/B，真实执行绝对路径 `Start-Studio.ps1` / `Stop-Studio.ps1`。三组分别覆盖未设置、绝对、相对 `MVC_DATA_DIR`，调用目录覆盖普通目录、A 根、B 根；每组都证明 B 才是启停目标，停止 B 后 A 的 Web/Worker PID 仍存活且两份生命周期记录逐字节不变。
- `07-all-powershell-lifecycle.log` 同时保留 P1-R1 的正常启停、重复启动、同数据根端口冲突、错误 PID 拒停和 `WebOnly` 不影响 Worker 全部回归。

## 完整回归

- `npm ci`：通过。
- 前端：126/126 通过。
- `npm run build`：通过，保留大 chunk 警告。
- Python：255/255 通过。
- 确定性在途 Web 重启、Worker PID/started 不变及单请求屏障：通过。
- FFmpeg 实际导出：通过。
- 缺失/旧 local Provider 零上游请求：通过。
- 路由审计：67/67 API 已分类，0 未分类，69 个总注册入口。
- `git diff --check`：通过。
- 内置推理目录、运行模块及历史导入/冒烟脚本均不存在且未被跟踪。

所有命令、UTC 时间、耗时、退出码和环境版本见 `SUMMARY.json`；12 个命令退出码全部为 0。测试只操作临时工程副本、隔离数据目录、loopback 端口和自身记录的测试 PID，未配置真实凭证，也未发起付费调用。

## 阶段边界

P1-R2 只修复工程根绑定和跨目录回归。External API-only、SQLite、单 Worker 约束保持不变；没有实施 PostgreSQL、账号/团队 ACL、凭证后台、多 Worker、对象级协作或公网部署。P2 仍未授权，直到外部验收人明确通过 P1-R2。
