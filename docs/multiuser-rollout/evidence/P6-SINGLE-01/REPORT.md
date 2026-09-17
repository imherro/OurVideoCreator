# P6-SINGLE-01 — 单 Worker 主链及提交幂等

状态：**READY_FOR_REVIEW**。请求按 P6-SINGLE-01 外部验收，不是整个旧 P6 平台通过。

## 版本与边界

- 协作仓库：imherro/OurVideoCreator；分支 master。
- base：afd1eb0d3eed36b3dcd818ed0c29aec2989c2259。
- 固定业务 SHA：c1b1695b6a2ef907647284bf1474a8d08537432f。
- evidence HEAD：本报告与日志将另作 docs-only 提交；最终完整 SHA 在送审消息中提供。
- 任务依据：已在指定会话打开并完整读取同名附件；正文 Markdown 转录见 ../../prompts/P6_SINGLE_01_CODEX_PROMPT.md。浏览器下载按钮已点击，但未取得可核实的下载文件，不声称字节级原件归档。
- 整理前在仓库外 OurVideoCreator-snapshots/P6-SINGLE-01-20260917-restore 保存 27 个变更文件、tracked.patch 和 MANIFEST.md，每个副本与源文件 SHA256 核对相同。没有复制用户数据库、媒体或秘密；没有 reset/revert/clean。

## 本次实际启用

1. Web 提交与 Worker 完成路径不再调用未完成的 quota reserve/release，运行时不再导入 job_execution/job_quota；没有假成功 reserve 或吞掉配额异常。
2. PostgreSQL admission 短事务、用户/团队/入口作用域唯一索引、规范请求指纹和当前对象权限验证。回放复用原模型/配置/凭证版本；编译准备读取原有安全模型规则，不解密凭证。目标、版本或有效输入不同返回冲突，不因回放建第二任务。
3. 六类入口：POST /api/projects/{pid}/jobs；/audio-jobs；/run；POST /api/productions/{id}/source-extractions；/adaptation/generate；/script-generations。audio-jobs 原 API 无批次总键，以成员提交键进行幂等；其余有批次总键的入口记录成员，阻止同键扩批/缩批。无新增业务入口或后台页面。
4. 保留数据库全局 WorkerAdvisoryLock、失锁停止、Web/Worker 进程隔离、P3/P4/P5 权限及候选明确采纳。仍不支持同库双 Worker。
5. 保留单调远端句柄：迟到空值不清除 ID，冲突 ID 拒绝；取消之后仍可保存已受理的 ID，但不能用迟到成功结果覆盖取消。
6. 每次 FFmpeg 导出独立临时目录；finally 只回收自身 Popen 子进程和临时目录，已登记输出保留。素材登记末次状态检查使用行锁，防止与取消写入交错。

## 保留但未启用

- backend/job_execution.py、backend/job_quota.py 为旧实验代码，无产品运行路径导入。已知旧配额日期 SQL 错误保留在延期模块中，并未伪装修复或计量生效。
- deferred/p6-platform/ 保存原 lease/checkpoint/配额/双 Worker 专用测试，不属于默认 tests/ 的本次后端套件，不计为通过或 skip。句柄及 FFmpeg 的当前要求在活动测试中另行验证；P0–P5 测试没有移走。
- 0007 保留 jobs 的旧未启用 attempt/lease/执行阶段字段，以及六张实验表 job_attempts、job_steps、job_outputs、job_limit_settings、job_reservations、job_step_usage。只有作用域幂等字段/索引和新增 job_submission_batches 批次成员记录启用。后者与任务同事务回滚，是防止同键改批次所需的最小记录，不是任务调度平台。
- 不启用多 Worker、完整日额度、分层并发、公平调度、队列年龄、远端槽位、逐步自动恢复、人工对账或新管理页面。不存在端到端 exactly-once 声明。
- 无依赖包、前端、发布/部署文件变更；未调用真实付费 API，未公网部署。

## 验证方式与结果

环境：Windows、Python 3.14、PostgreSQL 18.6；本任务新建回环端口 55437 实例。每次 pytest 由现有夹具创建全新 ovc_test_* 数据库并正常 Alembic upgrade head；仅该次测试库按夹具收尾。用户服务、历史测试库及指定保留端口未操作。

统一前提：OVC_TEST_ADMIN_URL 由进程环境指向本任务隔离 PG；不在公开材料输出完整连接串。PYTHONUTF8=1。

固定业务版本执行：

```text
python -m pytest -q
python -m pytest tests/test_p6_admission.py tests/test_p6_single_chain.py tests/test_p6_single_resources.py -q -s
```

固定版本完整后端：退出码 0，**490 passed，2 warnings，1126.57 秒**，见 full-backend-c1b1695.txt。两条是 websockets/uvicorn 的弃用提示，未以更换依赖扩大任务。无失败、无 skip；明确延期区不属于此 490 项集合，不算通过。

固定版本专项：退出码 0，**17 passed，86.24 秒**，见 specialized-c1b1695.txt；与完整后端重叠，不能相加。日志中的专项账本证明普通 editor 通过 TestClient 入站、独立真实 Worker 调用自有 loopback fake，文本/异步图片分别只生成一次，查询 1 次、下载 1 次；候选与真实 FFmpeg 导出均有断言。不是浏览器入站，也不是真实供应商验收。两连接等待同一 PG advisory gate 的轨迹及唯一任务断言见同一日志。

最终业务代码、迁移、测试及延期区与固定 SHA 的 diff 为空；证据提交只改文档及脱敏日志。公开日志替换本机用户目录为 <USER> 并规范换行/尾空白，不改断言、异常、计数、退出结果。开发失败及修正日志分别见 development-fixture-failure.txt、development-regressions.txt、development-corrections.txt；原始未处理日志保留本地。

P1/P2 原测试继续覆盖第二 Worker 拒绝、Web 重启不影响在途 Worker、空库显式迁移与数据库排他。P4/Provider 原测试覆盖已知句柄恢复查询与冻结凭证，不重新生成。P5 原权限/批量事务测试全部保留。

未运行：真实付费调用、多 Worker/完整配额/自动恢复矩阵、公网部署。本次未改前端和用户可见操作/状态，继承 P5-R2 的前端证据，不声称重跑 TypeScript、前端构建或浏览器。

## 开发历史，不与固定版本结果相加

- 旧 P6 暂停时 admission/quota 为 5 failed / 30 passed、quota 为 7 failed / 1 passed（同一日期 SQL 阻断）。较大旧回归中断，无通过结论；原始日志本地保留。
- 恢复主链后首批 24 passed。
- 新专项初次 1 failed / 14 passed：改编生成测试夹具未准备已采纳事件；补正前置条件，没有放宽业务校验。
- 扩展专项 2 failed / 33 passed：新批次记录外键锁在对象准备屏障前写入，阻塞原元数据竞争测试；已把记录写入放到原对象校验后。另一项旧故障注入包装未转发新增 entrypoint 参数；仅补 **kwargs 转发，第二项故障与事务回滚断言不变。
- 修正后定向 27 passed；真实 FFmpeg 失败与精确子进程收尾专项 5 passed。
- 不累计以上重叠批次，不将它们写成固定 SHA 验证。compileall 和 diff --check 在固定提交前通过。

交付后只请求外部按 P6-SINGLE-01 验收；不预写 PASS，不自动恢复旧计划或进入 P7。
