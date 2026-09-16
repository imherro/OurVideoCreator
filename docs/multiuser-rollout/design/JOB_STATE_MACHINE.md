# P0 任务状态机与额度口径

## 当前实现

当前 `jobs.status` 主要使用 `queued`、`running`、`interrupted`、`succeeded`、`failed`、`cancelled`。`submission_id` 全局唯一并在同项目、同节点、同 kind、同冻结输入时返回旧任务；不同输入冲突。`provider_job_id` 在部分适配器取得后立即写入，恢复时有句柄则查询原任务，无句柄的 `interrupted` 任务会明确重新排队。

已有正确性基础：

- `store.job_update` 使取消优先于迟到完成。
- `attach_provider_job_id` 保存付费上游句柄并拒绝不同句柄覆盖。
- job input 冻结 prompt contract；`job_private` 冻结 Provider 配置。
- 生成结果登记为资产；Film Bible/指纹逻辑可识别部分迟到结果。
- `run_workflow` 在单事务内验证和创建批次任务。
- Provider 测试覆盖恢复只查询、取消竞态和幻场幂等键。

当前缺口：Worker 启动会处理旧 running 状态，领取依赖单机锁；没有 worker lease、heartbeat、attempt/fencing、quota ledger、公平调度或“提交结果未知”独立状态；`job_private` 复制明文 Key；submission_id 作用域不是 workspace+user+入口。

## 目标状态机

```text
accepted/queued
  -> claimed                         (短事务领取，worker lease + attempt token)
  -> preflight                       (重查权限、模型、凭证状态与配额)
  -> submitting                      (即将产生上游副作用)
       -> remote_running             (已持久化 provider_job_id)
       -> submission_unknown         (请求可能已送达但未获得可靠句柄；禁止自动 POST)
  -> finalizing                      (下载、探测、登记资产，可独立重试)
  -> succeeded

queued/claimed/preflight -> cancelled（确认未发送可释放预占）
remote_running/finalizing -> cancel_requested -> cancelled 或 completed_after_cancel
任意非终态 -> failed / needs_operator_review
lease 过期 -> reclaimable（只有安全步骤可领取；旧 attempt 写入被 fencing 拒绝）
```

终态必须明确：`succeeded`、`failed_before_submit`、`failed_after_submit`、`cancelled_before_submit`、`cancelled_remote_confirmed`、`completed_after_cancel`、`needs_operator_review`。实现可采用不同名称，但不能把不同费用语义折叠到无法对账的一个 `failed`。

## 转移约束

| 转移 | 必须原子检查/记录 |
|---|---|
| 接纳任务 | 身份/对象权限、model_version、规范化 input hash、幂等键、quota 预占、子调用计划 |
| Worker 领取 | `FOR UPDATE SKIP LOCKED` 或等价；worker_id、lease_expires_at、attempt/fencing token |
| 发起每个付费步骤 | 再检查账号/团队/作品权限、平台/Provider/model 开关、凭证可用、远端并发槽 |
| 获得上游 id | 在继续轮询前立即持久化 provider_job_id + credential_version |
| 上游响应不确定 | 转 `submission_unknown`，保守占用 quota/远端并发，等待人工/供应商查询 |
| 下载/登记失败 | 保留 provider_job_id 和结果位置；只重试 finalizing，不重新生成 |
| 完成回写 | `WHERE attempt_token=current`；结果绑定提交时 object revision/assignment epoch，过期则候选 |
| 取消 | 区分未发送、供应商确认取消、不支持取消和状态未知；UI 提示潜在费用 |

数据库 fencing 只能阻止本地迟到写，不能撤回已经送出的网络请求；系统不声明端到端 exactly-once。

## 幂等

- 客户端 key scope：`workspace_id + actor_user_id + endpoint_namespace + idempotency_key`。
- 存储规范化有效输入 hash；同 key 同 hash 返回同 job，不重复占额；同 key 不同 hash 返回 409。
- 批量任务有稳定 batch id 和稳定子任务 id；双遍分镜、对白批次、图片数量等按实际付费子调用展开。
- 供应商支持幂等键时使用稳定映射；不支持时在 `submitting` 崩溃后保守进入人工核对。

## 第一版额度口径

第一版是“每日提交额度”，不是金额预算。按后台时区（默认 UTC）记在任务成功接纳时所属日期。

| 维度 | 控制 |
|---|---|
| 平台/供应商账号 | 总远端并发、一键暂停新提交 |
| Workspace | 每类每日提交量、排队上限、远端并发 |
| User | 每类每日提交量、排队上限、远端并发 |
| Model | 参数范围、数量/时长/分辨率、并发 |
| FFmpeg | 独立 CPU slot，不与云端等待混用 |

预占和 job/子调用计划同事务；并发不能超卖。明确未发送的取消/失败释放预占；已发送、已受理或状态未知不自动返还。动态新增付费步骤必须先追加原子预占或暂停。排队最长寿命建议 24 小时，过期行为与原 quota 日均可追溯。人工调整记录操作者、原因和对账关联。

## 公平与恢复

- 调度至少按 Workspace 轮转，避免单租户积压饿死其他团队。
- 本地执行槽与远端在途计数分开；Worker 失联不能虚假释放远端槽位。
- 权限撤销后不发新付费步骤；已付费在途使用受限 SYS 身份继续查询/归档，结果不再向旧成员开放。
- 凭证轮换后新任务用新版本；旧 provider_job_id 仍用原账号/凭证版本查询。凭证已吊销则进入人工核对，不能换账号重发。
- 幻场素材登记以凭证身份 + workspace/production/local asset 唯一约束和状态机去重，不能只用 Python 锁。
