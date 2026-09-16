# P5 证据来源与精确边界

## 命令

`scripts/capture_p5_evidence.py` 在 f4773f0 clean runtime 上执行完整命令链，临时源目录 basename 为 ovc-p5-evidence-f7iykkti，原件本机保留。归档在 commands-f4773f0。`capture_followup.py` 固定0851dce并验证未改变 backend/migrations/scripts/package文件；输出commands-0851dce。UTC和退出码由执行脚本写入，不由手工构造。

## 浏览器

浏览器实际工具调用从本任务 session JSONL 的限定UTC区间导出，源文件 basename `rollout-2026-09-16T11-11-38-01a0a832-d396-7a61-99cd-80a69762a975.jsonl`。export_browser_trace.py 只选 name=js 且引用 p5formal 的调用，再配对 call_id 输出，未重建返回文本。测试密码/登录名替换为明确 REDACTED 标记。本机用户路径脱敏不改变业务字段。

- f4773f0：第一快照46/46，完整快照61/61；完整窗口截止UTC22:00:00。两份保留为各时间点原始投影，不将其相加为独立用例。
- 0851dce：17/17，窗口UTC22:13:38到22:21:00，最后变更操作释放租约，随后只读确认两页bundle及稳定播放头。hash为index-DuioqIPf.js。混合读取审核会话的调用明确排除，避免导出不相关会话内容。
- 期间测试服务器仍为 f4773f0 启动的相同后端进程，前端静态目录由0851dce构建更新。服务代码在两SHA之间零diff；不是把旧页面冒称新SHA页面。测试tab禁用HTTP缓存后加载并核对脚本URL。

## DB / fake / 网络投影

`scripts/collect_p5_browser_evidence.py` 用 PostgreSQL READ ONLY 事务、明确 project_id/production_id 和列清单；JSON保留SQL文本和参数。f477初始/最终分别7对象24/25历史，followup为7对象31历史。business_sha是原manifest的**后端启动SHA**；followup的前端业务SHA为0851dce，二者关系特此明确，不篡改原collector字段。

两份 fake 请求逐次原件嵌入DB投影；只含合成请求，不含供应商密钥。访问日志只保留含目标project/production的行，原stdout还留在自有环境ovc-p5-browser-kl5p_ken。不是所有服务请求、不是HAR或SSE正文。没有读取credentials/provider binding/session/phone/cookie/无关项目/素材文件字节。

## 公开脱敏和完整性

prepare_public_evidence.py只把公开证据中的本机用户目录替换为`[LOCAL_USER]`，并检查已知隔离测试密码/登录名/DSN未泄漏。SHA256SUMS.json记录除它本身之外每个文件的SHA-256（文本换行统一为LF，与Git blob一致），便于下载校验；它不是外部验收签名。源临时日志与会话原件未改动。

所有结论限于实际轨迹和明确测试范围。没有真实Provider费用、没有公网发布或容量验收；新旧阶段状态以外部结论为准。
