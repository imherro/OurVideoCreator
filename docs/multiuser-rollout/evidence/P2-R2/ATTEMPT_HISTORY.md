# P2-R2 尝试记录

1. 在上轮 head `1ae1544...` 上先加入真实 PG/实际流测试，500 次 `_event()` 同事务 rollback 后保留 `[1,502]`。两个重连入口都只得到 heartbeat，测试按预期失败；原始输出保存在 `00-prefix-large-gap-failure.log`。
2. 实现按实际可见行统计后，P2-R2 与 cursor/retention 定向 8/8 通过。
3. 开发组合回归首次有两项失败：旧 P2-R1 helper 测试没有传入新统计参数；另一个普通 API GET 出现一次 5 秒 PostgreSQL connect timeout。前者更新断言后通过；两失败点立即复跑 2/2。timeout 未归因、未以重试改写业务。
4. 随后专项组合 25/25、开发全量 276/276；固定业务 SHA 后正式定向 8/8、正式全量 276/276、P2/进程回归 20/20、前端 126/126、构建通过。

没有删除或覆盖 P2、P2-R1 证据。正式成功日志全部绑定业务 SHA `fc8feee3d9c3bfaffb39c55ab10d41e0fff7050f`。
