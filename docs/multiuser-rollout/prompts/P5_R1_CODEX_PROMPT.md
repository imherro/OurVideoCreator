# P5-R1 · 附属节点身份变化的最小结构修复

你负责协作仓库 **imherro/OurVideoCreator**，不要使用或修改单机版MyVideoCreator。本次只执行P5-R1，不开始P6。

## 关口与起点

- 上次P4通过：`c0152ffcfb5623fcc0b723dbdf450acec9f17f73`。
- P5后端基线：`f4773f0075325625c6cf2e6236c5d2014d416d3f`。
- P5最终业务：`0851dce02e0f22e87f6247b029fd3faedd39e7dd`。
- 本次外部不通过绑定HEAD：`5143ee36f55ab783f203832558cfedd4efce4936`。
- 唯一确认阻塞：**OVC-P5-01，S2**。P0–P4历史通过不变。

先读取适用AGENTS.md、现有P5完整提示词、design/P5_OBJECT_COLLABORATION.md、权限/API契约、本次REVIEW和MATRIX。核对工作区及HEAD；新提交或用户未提交改动不能回退/覆盖。不要为了返修重新拆分全部对象主源，也不要自行修改冻结验收目标。

## 唯一任务

修复 `backend/collaboration.py::commands` 对**shot附属节点身份集合变化**的结构校验遗漏。

当前结构计算已把更新中的 node_ids 变化设为structural，但463–467行的graph必带检查只考虑creates/deletes，graph_transition也只对updates内的graph生效。A可以仅PATCH自己的shot、同步改imageNode/pipeline与child.id，留下原graph中指向旧ID的连线及位置/排序。B的合法依赖因此损坏，后续workflow报悬空节点。

这不是要求P6依赖调度，只是当前P5命令提交后的持久状态必须自洽。

## 实施步骤（一个任务，可多个小提交）

1. 用现有team/普通editor夹具和独立PG库重现：A的shot子节点image-x；B的节点node-y；B合法建立image-x→node-y。A直接删边403作为对照；A不带graph仅把shot内child ID及对应引用改为image-x-new。保存修复前响应、shot/graph版本、实际聚合和topological失败轨迹。
2. 把新增／移除／改名等已存在对象内部节点身份变化纳入结构命令要求。客户端缺少当前graph版本则明确409/422；有graph时检查完整拟提交图，不能持久化悬空边、无效排序或位置引用。
3. 保持边目标负责人授权。A无权删除B依赖时不能由后端自动删边或自动接管来“修正”图。需要涉及他人对象的动作就明确拒绝，管理者照原规则显式取得所需权限。
4. 优先在公共commands/validation修一次，覆盖PATCH、batch、commands，以及复用它的restore/candidate/import路径。不要复制多套不同权限逻辑。保留原排序锁与身份屏障，避免新反向锁序；无须扩建锁平台。
5. 不变更普通文本保存粒度。节点ID集合未变化的镜头正文/提示词修改仍不要求graph，不争整份episode revision。两editor独立镜头保存保持通过。
6. 若实际UI会新增/移除附属节点，让它带当前graph revision做已有原子命令；若禁止既有编号重命名是最小方案，可明确拒绝该动作，但不能禁用原来合法的管线节点创建／结构更新。仅在必要处改UI。

## 必须验证（不要求真实供应商）

- 同一负例经单对象PATCH、batch、commands全部拒绝；shot/graph正文及revision、history/audit/event不变。
- 带合法graph版本和完整清理/替换且目标均获权的结构变更成功；实际聚合nodes/edges可通过现有topological；旧graph revision拒绝。
- 拒绝利用子节点身份变化间接绕过他人依赖目标权限。不要仅检查“有graph字段”，却仍允许未改图保留悬空边。
- 混合命令后一项非法整体回滚；graph与子节点竞争时不留下部分结果。用真实PG等待证明必要的提交/拒绝顺序，不靠固定sleep碰运气。
- 原COLLAB-01/02不同镜头正文并行、同对象409，COLLAB-03草稿，COLLAB-06租约，COLLAB-09候选，COLLAB-11导演台/图导入与历史恢复，COLLAB-12Twick同步均保留必要回归。
- API测试通过真实应用授权及PG；可使用现有TestClient作入站，但不能mock掉collaboration.commands、权限、事务或图完整性判断。无模型调用的这次结构复现也不应启动付费Provider。

附件repro/test_p5_review_child_identity.py是审核者提供的**未运行**红/绿测试草案，可复用但先核对当前fixture。repro/structural_guard_result.json只是已执行的逻辑摘录实验，不得作为你的PG/API运行结果。

## 证据与验收停止

- 新证据写到 `docs/multiuser-rollout/evidence/P5-R1/`，保留原P5完整证据和外部不通过记录。
- 保存最小基线红测和最终绿测原始stdout/stderr、命令、UTC、退出码、业务SHA及测试作用域；若基线行为与你观察不同，给出确切条件/原始输出，不硬改业务去配合报告。
- 固定新业务SHA后执行完整后端及受影响前端/构建/路由；若最终只补无关证据或测试，清楚说明代码等同性，不冒称某SHA重跑。真实PG tests保留隔离库防护。
- 浏览器只补实际受影响的结构编辑/保存流程；若只改服务端且现有UI不发该非法操作，不必重做61+17整套浏览器。至少保留原双用户正文/Twick证据及回归；若改UI，应跑变更页面并留下操作/响应/持久结果。
- 报告逐项说明OVC-P5-01的根因、最小修复、红绿轨迹、原有能力回归和未运行项。更新API说明里结构变更条件即可，不新增架构需求。
- 不访问/停止/重置用户7868、历史7895/6313/6185/7028或保留P5实例、库、租约和草稿。只操作自己新建且明确拥有的测试资源。旧保留资源需用户明确授权才能清理。
- 不新增队列、配额、多Worker、实时逐字共编、支付或公网部署，不调用真实付费API，不重新设计平台Key治理。
- 开发交付状态只能READY_FOR_REVIEW或BLOCKED。不要自签PASS、自动进入P6或覆盖历史通过。完成后提交新业务SHA、evidence HEAD和报告路径，停止等待外部复验。
