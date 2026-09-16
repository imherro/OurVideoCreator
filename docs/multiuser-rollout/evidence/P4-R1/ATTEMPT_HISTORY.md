# P4-R1 实际尝试记录

## 红测和修复

- 读取原始审核包和 R1 提示词；只下载、阅读、归档，没有执行外部提供的探针脚本。
- c7 运行时代码完整 API/PG/Worker/loopback 红测：UTC 17:42:22.4783384–17:42:51.8878269，4 failed / 2 passed / 26.88s / exit 1。完整 stdout/stderr/退出码在 `baseline-red.txt`。max_tokens 实际 4096、两种原生协议没有认证、Replicate WAV 被当 PNG 登记均由真实适配器复现。
- 第一轮最小修复定向 6 passed / 10.42s。随后原 P4 定向 47 passed / 1 failed / 85.99s：该进程收集了修改前的 Maestro helper，默认 api_key 不再受支持。夹具改为原生 none、空 Key，保留原业务断言，单项复跑 1 passed / 3.08s。
- 扩展旧版本拒绝、匿名正例、关联参数检查后 15 passed / 39.76s；再加空/空白音色枚举拒绝两项，17 passed / 46.99s。
- 开发期完整回归 UTC 17:47:09.7763199–17:56:51.6772569（c7 HEAD + 工作区改动），368 passed / 2 warnings / 578.47s / exit 0，不冒充固定 SHA 验证；日志 `development-full.txt`。
- 新业务固定 e6c3edd 后重新执行完整后端、17 项定向、前端/构建、编译和实际路由审计。原有 P4 首轮 351 和前端证据没有改 SHA 或覆盖。
- 固定 e6c3edd 的正式全量 UTC 17:51:00.1323846–18:00:31.1632704：368 passed / 2 warnings / 568.06s / exit 0；未发生新的失败。前端 128 passed，build 1827 modules，编译/路由审计均 exit 0。

## 浏览器和证据整理

- 新实例 7028 启动前未发布 Provider/模型；通过 UI 实际创建 4 个 Provider、一个文本模型，Replicate audio 尝试 400。仅测试自己新建的资源。
- 初次空平台显示主密钥尚未就绪：此时还没有 keyring 行；首次 Provider 保存按现有初始化规则成功，提示消失。未更换主密钥或绕过保护。
- 缺少 max_tokens 的普通生成 400 是预期拒绝；填写 100 后独立 Worker 成功不是重试真实付费 API。
- CDP 9 份 JSON body 因页面跳转已不可读取，保留 `body_checked=false`，不删除或计入零泄漏证明。2 条 SSE 本轮未扫描 body。导出的对象最后一次打印有 `... 10 more items` 展示裁剪；完整证据以先前各调用输出、精确汇总、真实访问日志和数据库交叉核对，不声称该最后展示是无裁剪完整数组。
- 第一次只读 PowerShell 查看会话结构，对没有 output 的消息调用 GetType 报空值错误；未影响产品/浏览器状态。改为只打印存在的结构字段后，实际提取 26 calls + 26 results 成功。
- 原始外部 Markdown 保留 4 处行末双空格硬换行，默认 git diff --check 报 trailing whitespace；未改写原件，使用 `core.whitespace=-blank-at-eol` 检查其余空白。业务代码无空白错误。

没有清理或停止旧实例；没有把未运行的真实供应商鉴权、公网或性能测试记为通过。
