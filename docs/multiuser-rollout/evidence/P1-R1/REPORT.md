# P1-R1 复验报告

状态：**READY_FOR_REVIEW**。本报告只登记开发侧证据，不自行宣称外部验收通过。

仓库：`https://github.com/imherro/OurVideoCreator`

被测试业务 SHA：`f27439fc9fcabd706e2772d5cd7212d76a9f4706`

前次不通过审查 HEAD：`5ed0afa361b0e86590cd05b9ac285d9285854635`

## 问题闭环

| 问题 | 修复 | 独立证据 |
|---|---|---|
| `OVC-P1-01` | 由工程根目录与实际 `MVC_DATA_DIR` 生成实例 ID；Web 健康接口返回该 ID；Web/Worker 生命周期记录保存角色、PID、创建时间、可执行文件和完整命令行；复用及停止前逐项校验，不一致时拒绝停止；启动失败只清理由本次调用创建且能够证明所有权的进程。 | `07-powershell-lifecycle.log` 使用真实 `Start-Studio.ps1` / `Stop-Studio.ps1` 覆盖正常启停、重复启动、不同实例同端口拒绝、错误 PID 拒停、`WebOnly` 不影响 Worker。 |
| `OVC-P1-02` | loopback fake Provider 增加 received/release 文件屏障；请求抵达后保持未完成，待 Web 重启和持久任务断言完成后才放行。 | `06-inflight-web-restart.log` 保存重启前/后的完整任务快照、相同 `started`、不变 Worker PID、请求次数 1、最终成功状态和全部子进程日志。 |
| `OVC-P1-N01` | 视频网关尾帧报错改为“选择支持尾帧的外部 Provider”，并添加窄表面测试，禁止“使用内置引擎”回归。 | `02-npm-test.log`。 |

## 完整回归

- `npm ci`：通过。
- 前端：126/126 通过。
- `npm run build`：通过。
- Python：252/252 通过。
- FFmpeg 导出：通过；见 `08-ffmpeg-export.log`。
- 未配置/已移除 Provider 时零上游请求：通过；见 `09-zero-upstream-on-missing-provider.log`。
- 实际注册路由审计：69 条框架路由、67 条 API 装饰器路由、67 条全部分类、0 条未分类；见 `10-route-audit.log`。
- `git diff --check`：通过。
- 内置推理目录、运行模块和历史导入/冒烟脚本均不存在且未被跟踪；见 `12-removed-surface.json`。

所有命令、UTC 时间、耗时、退出码和环境版本见 `SUMMARY.json`。全部命令退出码为 0。测试只使用临时数据目录、loopback 端口和 fake Provider；未配置真实凭证，也未发起付费调用。

## 阶段边界

P1-R1 仍保留 SQLite、单 Worker 锁和外部 API-only 架构。没有实施 P2 的 PostgreSQL/对象化数据层，也没有提前实现 P3 之后的身份权限、凭证、多 Worker 或公网部署能力。P2 继续保持未授权，直到外部验收人明确通过 P1-R1。
