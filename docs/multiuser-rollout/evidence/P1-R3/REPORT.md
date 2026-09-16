# P1-R3 复验报告

状态：**READY_FOR_REVIEW**。本报告只登记开发侧证据，不自行宣称外部验收通过。

仓库：`https://github.com/imherro/OurVideoCreator`

被测试业务 SHA：`7283fc513cdc8bd296b54e340875ead9431055e4`

前次不通过审查 HEAD：`e4c61feba12765a6b70ecc9ee1e9db8e223372b1`

## OVC-P1-R2-01 闭环

- `Studio-Process.ps1` 增加进程级环境快照与恢复函数，分别保留变量是否存在及原始字符串值；未定义恢复为未定义，相对值和绝对值逐字恢复。
- `Start-Studio.ps1` 与 `Stop-Studio.ps1` 在第一次改写前保存 `MVC_DATA_DIR`、`PYTHONUTF8`，并用最外层 `finally` 覆盖成功、异常和 `exit 2` 非零出口。身份查询与新启动子进程仍在恢复前继承同一个规范绝对数据目录。
- `Get-StudioIdentity()` 原有的目标工程根执行、返回路径核对与 `finally { Pop-Location }` 保持不变；没有放宽进程归属校验，也没有通过删除对方记录规避问题。
- `06-same-session-powershell.log` 的三个模式均由单个 PowerShell 驱动进程连续调用真实 Start/Stop，并记录相同 `$PID`。未设置状态恢复为未设置；相对、绝对配置恢复原字符串；`PYTHONUTF8` 与工作目录也恢复。
- 未设置和相对模式先启动 B Worker，再调用 A Stop；B 的 PID 仍存活，生命周期记录逐字节不变，最后由 B Stop 正常停止。绝对模式验证调用者绝对配置不被规范化值替换。
- 同一驱动还覆盖“临时环境设置完成后因缺少前端构建而抛错”的 Start 失败分支；独立的非零出口测试用无效记录触发 Stop `exit 2`，调用者 `finally` 证明环境、工作目录与 PowerShell PID 均保持原样。

## 完整回归

- `npm ci`：通过。
- 前端：126/126 通过。
- `npm run build`：通过，保留大 chunk 警告。
- Python 收集：259 项。
- 首轮全量 Python：258 通过，1 项在本机 HTTP 请求处发生 5 秒超时；失败原始日志保留在 `05-pytest.log`。
- 同一业务 SHA 的完整补跑：259/259 通过，见 `15-pytest-rerun.log`；包含该失败点的专门在途重启测试也在 `09-inflight-web-restart.log` 单独通过。
- 同会话 PowerShell：4/4 通过；跨工程 PowerShell：3/3 通过；全部 PowerShell 生命周期：8/8 通过。
- 确定性在途 Web 重启、Worker PID/started 不变、单请求屏障和第二 Worker 拒绝：通过。
- FFmpeg 实际导出：通过。
- 缺失/旧 local Provider 零上游请求：通过。
- 路由审计：67/67 API 已分类，0 未分类，69 个总注册入口。
- `git diff --check`：通过。
- 内置推理目录、运行模块及历史导入/冒烟脚本均不存在且未被跟踪。

首轮 13 个命令的 UTC 时间、耗时和退出码见 `SUMMARY.json`；补跑元数据见 `RERUN_SUMMARY.json`，完整尝试史见 `ATTEMPT_HISTORY.md`。测试未配置真实凭证，也未发起付费调用。

## 阶段边界

P1-R3 只修复 Start/Stop 对调用者 PowerShell 环境的副作用并补同会话回归。External API-only、SQLite、单 Worker 约束保持不变；没有实施 PostgreSQL、账号/团队 ACL、凭证后台、多 Worker、对象级协作或公网部署。P2 仍未授权，直到外部验收人明确通过 P1-R3。
