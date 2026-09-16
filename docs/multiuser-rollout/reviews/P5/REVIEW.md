# OurVideoCreator P5-COLLAB-01 外部验收

## 结论

**不通过。当前仅确认一项 S2 阻塞：OVC-P5-01。P6 未授权。**

仅审核协作仓库 `imherro/OurVideoCreator`。P0–P4 历史通过不变；本结论不要求重做此前阶段，不要求真实付费联调或公网／容量验收。

| 绑定 | SHA |
|---|---|
| P4 通过 base | `c0152ffcfb5623fcc0b723dbdf450acec9f17f73` |
| P5 完整后端／初版前端 | `f4773f0075325625c6cf2e6236c5d2014d416d3f` |
| P5 最终业务 | `0851dce02e0f22e87f6247b029fd3faedd39e7dd` |
| 本次 evidence HEAD | `5143ee36f55ab783f203832558cfedd4efce4936` |

审核日期：2026-09-17。本文是审核者的关口结论，不是 Codex 自测报告。

## 核查范围和提交证据

已读取新仓库 master、两次业务提交差异、根 Git tree、阶段报告、实现契约、验收矩阵、尝试记录及原始测试／浏览器材料。实际链为 base → f4773f0 → 0851dce → 5143ee3。

0851dce 只修改四个 editor 源文件、三个前端测试：远端时间线同步、规范化不回声保存、标题轨 text→element。最终业务到 evidence HEAD 根树只有 docs 不同。因此，f477 的后端全量与 0851 的受影响前端／renderer 补跑可组合核验；不要求仅因前端变化再跑全部后端。

实际读取的关键实现：collaboration/validation/routes/document、owned_content/routes、actions、object/relation/storyboard candidates、工作流校验、对象草稿与实际前端保存适配器。核对了相应真实 PostgreSQL 测试实现，而不是仅以458或178个绿测作为通过条件。

## 已认可的实现

- 普通对象写入检查当前会话、作品成员、负责人、revision、assignment epoch；manager／owner 也不能静默改写他人对象。旧整份 PUT 在测试中对 owner 返回410。
- 成员撤权保留成果并推进代际；同对象竞争、ABA分配、时间线租约锁后过期检查、有权审核和历史追加均有实现与测试。
- 对象主源只读聚合，不以旧 projects.document 作为镜头／节点／时间线第二写主源。
- Worker 的生成结果作为候选；采纳使用服务器保存的结果，复核当前目标、必要引用、权限和版本，收据与写入同事务。
- 前端409保留草稿，不自动提高revision覆盖；作用域隔离及Twick远端清洁输入同步已有对应测试和真实浏览器补证。
- P4平台唯一模型治理、单Worker、素材和FFmpeg/Twick等保留能力有全量回归记录；未发现本轮需要重开P1–P4历史关口的具体问题。

完整逐项状态见 MATRIX.md。COLLAB-10/11 因以下结构缺口暂不能关闭，其余已核验场景不要求重新设计。

## OVC-P5-01｜S2：附属节点身份变更绕过图结构版本／完整性检查

### 位置

以 `0851dce02e0f22e87f6247b029fd3faedd39e7dd` 为准：

1. `backend/collaboration.py:413–419`，`commands()`：识别 shot/node 的节点ID集合变化为 structural，并取得结构锁。
2. 同文件 `463–467`：只有创建 shot/node 或顶层 deletes 才强制要求 graph update；只有出现在 updates 的对象才执行 graph_transition。
3. `backend/collaboration_validation.py::graph_transition`：非 graph 对象立即返回；节点存在性和依赖目标负责人校验均在此函数。
4. `backend/collaboration_routes.py::save_object/save_batch/object_commands`：单对象PATCH和批量入口共同调用上述commands；单对象PATCH不会自动附带graph。
5. `backend/collaboration_document.py::compose`：保留 graph 中的 edges；`backend/workflows.py::topological/execution_plan` 随后拒绝悬空边。

关键逻辑：

```python
# 这里能识别更新中的 child IDs 改动。
structural = bool(creates or deletes) or any(node_ids(new) != node_ids(old) ...)

# 这里却只覆盖 top-level creates/deletes。
if structural and (any(item['kind'] in {'shot','node'} for item in creates) or deletes):
    if not any(updated_object.kind == 'graph' ...):
        raise HTTPException(422, ...)

for item in updates:
    graph_transition(...)  # shot/node 会直接返回
```

上面省略号仅解释控制流，完整代码以 SOURCES 中 S04/S05/S06 为准。

### 最小触发场景

全部使用临时测试库和两个普通editor，无需任何模型生成：

1. A创建镜头X，含 `image-x` 子节点，shot的 `imageNode`／`pipeline.imageNodeId` 与 nodes 一致。
2. B创建自己的目标节点Y，并合法建立 `image-x → node-y` 依赖。B拥有目标，正常结构权限允许建立此边。
3. 对照：A直接删除这条边应因B的目标权限被拒绝。
4. A仅PATCH自己镜头X：将引用和子节点ID一起改为 `image-x-new`，镜头uid不变，使用当前revision/epoch，不提交graph。
5. 当前实现的结构锁会取得，但图版本要求被跳过；新shot内容可进入写入路径，旧graph的边、位置和排序未同步改变。
6. 聚合结果仍含 `image-x → node-y`，却已没有 `image-x`。工作流拓扑检查报“连线引用了不存在的节点”，而且它在按选中节点筛选前校验整个图。

影响是可持久化的悬空结构以及其他成员合法依赖被破坏。不是跨团队数据泄漏，不是已证明B正文被覆盖，也没有实际付费事故。所属是当前P5对象／结构一致性，不属于未来P6调度。

### 证据强度

实际检查了完整commands和相关验证／聚合／执行实现，以及现有测试。既有测试涵盖顶层增删、伪造他人节点和直接边目标授权，但没有覆盖仅在shot更新中改子节点集合且不携带graph。

审核端独立执行 `repro/structural_guard_probe.py`，观察到：structural=true、当前分支不要求graph、无graph被校验，随后真实摘录的topological对合成结果报悬空节点。该实验的对象行是测试输入，不是数据库读出；**不是完整HTTP／PostgreSQL复现，未观察实际应用HTTP状态码**。

另附 `repro/test_p5_review_child_identity.py`，是可复制进协作仓库的拟议PG/API回归。审核端只做了语法检查，没有运行或收集。其断言表达修复后应拒绝；实施端应先保存基线红测，不能把它标成审核端已执行。

### 最小修复和通过标准

- 把shot附属节点新增／移除／改名等实际身份变化纳入同一结构命令。缺少当前graph版本时明确拒绝；不修改图也不能遗留无效引用。
- 在同一短事务中校验拟提交图和保留引用，依赖边移除／替换继续核验目标对象当前编辑权。不要后台自动删掉B的依赖来让图“看起来有效”。
- 沿用现有排序锁、负责人、revision/epoch、原子历史／事件。修复集中在公共commands校验层，覆盖PATCH/batch/commands及共用的恢复／导入路径。
- 允许明确禁止不需要的既有节点重命名；产品已有附属节点创建／删除仍须有合法的结构命令，不得无声删除功能。
- 基线场景修复后409/422，shot/graph内容及版本、history/audit/event均不变；有权的完整结构变更能够成功并且聚合图可执行；旧graph版本拒绝，混合失败整批回滚。
- 普通镜头正文／提示词编辑不应被迫提交graph，也不应重新争用整份项目revision。保持两个独立镜头保存的已通过能力。

不要求新增数据库、图服务、全局工程锁或P6功能。

## 原始运行证据

| 固定SHA | 项目 | 已读日志结果 |
|---|---|---|
| f4773f0 | backend-full | 458 passed，2既有warning，1114.26秒，exit0 |
| f4773f0 | concurrency-traces | 10 passed，43.50秒，含PG等待链，exit0 |
| f4773f0 | routes | 125总注册项，122/122 API分类，0未分类 |
| 0851dce | frontend | 178 passed，0失败／跳过，exit0 |
| 0851dce | build | 1837 modules，8.69秒，exit0；chunk warning保留 |
| 0851dce | editor-renderer | 30 passed，3.43秒，exit0 |

runs.json记录包含进程启动在内的总耗时，pytest/Vite结果行是命令内耗时，两者不混写。

浏览器完整基线61调用+61返回、受影响补跑17+17；实际409请求、版本比较、租约及候选／历史操作、只读方同步与保留私人状态有轨迹。接受其为所声明范围的实际浏览器验证，不把它说成覆盖所有权限／并发组合。DB followup的business_sha是f477启动后端，前端为0851构建，PROVENANCE明确且代码等同，不能因此要求篡改collector字段。

已有浏览器证据不构成新的补证阻塞。9/13等历史阶段扫描不计入P5新扫描；本轮只按声明的项目级投影理解，并不声称完整HAR或秘密/SSE正文重扫。

## 审核端执行边界

GitHub连接器正常读取代码和证据。审核容器实际只读git ls-remote仍返回DNS解析失败，PATH没有PG/PowerShell工具。没有独立重跑完整PG/pytest/npm、工程浏览器或新API红测。实际独立运行的是上述限定逻辑探针；拟议pytest只解析语法。checks/environment.json与探针输出附包。

没有修改远端仓库，也没有访问、停止或清理用户7868、历史测试实例或新P5实例。测试资源继续按交付方说明保留，不把“保留待查”写成已清理。

## 下一单一任务

**P5-R1：补齐附属节点身份变化的原子结构校验及最小回归。**

完整提示词见 P5_R1_CODEX_PROMPT.md。新证据进入 evidence/P5-R1/，原P5证据保留。P6、付费API和公网部署未授权。已核验的其他场景只做必要回归，不重新开展整套协作重构。
