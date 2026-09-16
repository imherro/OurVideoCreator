# 审核包使用

先读 REVIEW.md 和 MATRIX.md；下一单一开发任务使用 P5_R1_CODEX_PROMPT.md。

checks/environment.json 是审核容器实查。repro/structural_guard_probe.py 和输出是已运行的限定逻辑实验；repro/test_p5_review_child_identity.py 是未运行、仅语法检查的真实PG/API回归草案，不能混作审核端实测。

所有代码仅适用于自行新建的隔离测试环境。不要执行任何涉及用户现有服务或保留证据库的清理。
