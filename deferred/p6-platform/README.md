# 延期的旧 P6 实验

P6-SINGLE-01 明确暂缓多 Worker、租约接管、checkpoint/输出恢复和完整配额。
此处保留暂停时专用测试，不在默认 tests/ 回归范围，不计通过或普通 skip。
它们曾有真实失败，当前不作为可运行承诺；尤其配额日期 SQL 尚未修复，
运行时 attempt 防护已撤接。P0–P5 测试没有移出或跳过。

原始模块 backend/job_execution.py、backend/job_quota.py 和 0007 未启用字段/表
保留，但产品运行路径不导入这些模块。新的提交幂等继续在 tests/test_p6_admission.py。
单 Worker 句柄保护及 FFmpeg 收尾在活动测试中独立验证。
完整整理前快照在仓库外保留；旧开发日志亦保留，不重标为新版本证据。
