# P1-R3 尝试记录

仓库：`https://github.com/imherro/OurVideoCreator`

被测试业务 SHA：`7283fc513cdc8bd296b54e340875ead9431055e4`

## 首轮完整采集

- `SUMMARY.json` 记录 13 个顺序执行的验收命令。
- 其中 12 项退出码为 0；`05-pytest.log` 的全量 Python 测试在创建在途任务时发生一次 5 秒本机 HTTP 超时，结果为 258 通过、1 失败。
- 首轮失败原始日志完整保留，没有删除或覆盖。
- 同一首轮稍后的 `09-inflight-web-restart.log` 单独执行包含该失败点的 `tests/test_p1_processes.py`，1/1 通过，证明 Web 重启、Worker 保持、单请求与第二 Worker 拒绝仍成立。

## 同 SHA 补跑

- 未修改业务代码，也未生成新业务提交。
- `15-pytest-rerun.log` 在同一 SHA 上重新执行完整 `python -m pytest -q`，259/259 通过，退出码为 0。
- `RERUN_SUMMARY.json` 单独登记补跑原因与元数据，避免把首轮失败改写成成功。

## 证据隔离

- P1、P1-R1、P1-R2 历史证据目录均未改写；本轮新证据只写入 `evidence/P1-R3/`。
- PowerShell 测试只操作临时工程副本、隔离数据目录、loopback 端口和自身记录的测试 PID；没有停止用户现有服务。
- 未配置真实 Provider 凭证，未发起真实付费调用。
