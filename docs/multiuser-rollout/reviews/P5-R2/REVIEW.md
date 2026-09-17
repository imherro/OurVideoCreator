# OurVideoCreator P5-R2 外部复验及 P5 整体关口

## 结论

**P5-R2 通过；OVC-P5-02（原 S2）关闭。P5 整体通过，允许进入 P6。**

OVC-P5-01 已在上一轮独立关闭，本次保持关闭。P0–P4 历史通过不变。没有新增阻塞，不需要 P5-R3。

- 仓库：`imherro/OurVideoCreator`，只读审核，未使用单机版仓库。
- 本次 base：`78fd14f40339e0b71908a685efb2354a0c1045ce`。
- 固定业务：`aebffe364313601aceb611fbcd0ca2b01a42e29d`。
- 通过 evidence HEAD：`afd1eb0d3eed36b3dcd818ed0c29aec2989c2259`。
- 下一单一授权任务：**P6-JOBS-01，可靠任务执行、原子配额与管理操作闭环**。
- P7、公网部署、真实付费 Provider 调用：未授权。

本结论针对已冻结 P5 范围和当前两个问题的关闭，不是生产部署、容量、真实供应商可用性或形式化无缺陷证明。

## 1. 实际审查及提交绑定

GitHub 连接器读取时 master 指向指定 evidence HEAD。Git commit 父子关系为 base → aebffe3 → afd1eb0。业务提交只改三个运行时文件及两个测试文件：

- `src/objectDrafts.ts`：远端缓存单调性和旧回执后的显式冲突。
- `src/collaborationClient.ts`：先记录已提交基线，再把本次票据的冲突传给宿主。
- `src/main.tsx`：保存成功/失败和单对象保存 finally 的作用域检查。
- `tests/p5_receipt_host.test.mjs`：新增宿主回调集成。
- `tests/owned_content_drafts.test.mjs`：共享状态机的更强冲突断言。

业务根树 `e5a1018ffdfa17d4372b3a0946d559c065137efa` 与证据根树 `1e70e6b482d169393415a15a60db3f07abc32277` 除 docs 子树外一致。

两者 backend 子树均为 `e08a8a14606cae13a0696574e405b2a3302ff556`，与已通过 R1 业务相同；迁移、依赖及脚本也未被本次业务修改。实施端 `git diff --exit-code 34d646d... aebffe3... -- backend` 返回0。故保留 R1 的473项后端及10项并发证据，不将其重新署名为R2执行，也不为纯前端改动要求机械重跑。

已读取：实际业务 diff、三处修改及上下文、全部新增宿主测试、REPORT、MATRIX、ATTEMPT_HISTORY、命令索引，基线失败和正式绿测关键原始输出、构建输出、实际 Git 树。未独立重算实施端全部文件哈希，不将其SHA256清单视为审核端签名。

## 2. OVC-P5-02 的关闭依据

### 2.1 正文与版本继续成对，不静默接受较新版本号

`ObjectDrafts.acknowledge()`（当前约111–134行）把成功回执的正文与revision记为本地基线；若已观察到更高revision或assignment epoch，保留远端快照并置为conflict，而不是在状态机内部单独切换至r3。

`remote()` 拒绝低于已缓存远端版本的读取/回显。`edit()` 不清除conflict，`begin()` 不给conflict签发保存票据；保存期间新增输入按serial继续保留。

因此，r2提交后延迟回执、期间收到r3、最后释放r2的场景中，本地正文/r2基线一致，r3是明确比较对象。下一次只改note不会自动将r3 revision配给旧正文。

### 2.2 宿主确实得到冲突，而不是只有状态机测试变绿

`CollaborationClient.save()`（约157–182行）先记录服务器已成功提交的对象及基线，再检查本次tickets是否变为conflict；若是，则抛出带status=409的本地冲突，供既有宿主分支显示。

**这不是原HTTP响应409，也不是原r2写入失败。** 原写入已经提交；这里的含义是“本次保存之后已有较新内容，需要比较”。先记录成功基线，避免下一次重复创建或重放已成功对象。

`main.tsx::save/saveObject/acceptObjectDocument` 的真实代码参与测试：全局保存进入冲突分支；单对象保存传播错误并通过finally更新宿主冲突状态。检查对象范围只针对本次票据，因此X冲突不阻止单独保存Y。

新增project/client/generation判断防止旧作用域成功或失败处理改变新页面；同ID重新打开也不视为原作用域。未改变服务器CAS、对象协议或SSE推送行为。

### 2.3 红绿测试的证明范围

基线测试使用实际客户端、split/compose及状态机，通过TypeScript AST提取并转译`main.tsx`中三个真实函数声明。React refs/setters与传输为测试夹具，不是整个React渲染树。

内存CAS传输在任何修改前核查整个batch的revision、epoch和owner。第一次已经提交r2、复制回执后仅延迟交付；第二个实际客户端读取已提交r2再合法提交r3。该前提不是“服务器无条件接受写入”。

基线最终9例有6失败、3通过；原始最终note轨迹记录expected_revision=3携带v2正文，并将模拟服务端写成r4/v2。这是实际客户端/宿主回调集成红测，**不是HTTP、PG或浏览器红测**。

固定业务绿测包括16个宿主用例：full/only × 输入/无输入、note-only后续保存、较旧回显、仅自身回显、常规顺序、独立Y、X冲突时单存Y、明确discard、明确keep后再次CAS竞争、epoch变化、不同ID/同ID新generation。

在核心绿测中，rows与draft基线为r2，r3保留为remote，页面显示“保存冲突”；继续只改note不增加写请求，模拟服务端仍为r3/v3。明确discard后再改note，r4保留v3正文；明确keep后若另一个客户端已提交r4，旧r3 CAS再次拒绝，输入保留。

共享章节/剧本测试从“自动采用r3”改为“r2保留+r3比较+阻止重试+明确discard”，与授权B方案一致，并非删除回归以换绿。

## 3. 正式运行证据

UTC窗口：2026-09-16T23:24:05.614Z–23:24:22.138Z，固定业务aebffe3。退出码来自runs.json；stdout/stderr在相邻文件。

| 检查 | 核验结果 | 层级 |
|---|---|---|
| 基线最终红测 | 6 failed / 3 passed / 0 skipped；exit1按尝试记录/报告登记 | 旧运行时+新增测试；原始断言失败可读 |
| 16宿主用例及相关定向集 | 49 passed / 0 failed / 0 skipped；exit0 | 实际代码+React边界夹具+内存CAS |
| 全部默认前端 | 195 passed / 0 failed / 0 skipped；exit0 | 包括本轮16项及既有前端测试 |
| TypeScript tsc -b | exit0 | 固定业务构建检查 |
| Vite | 1837 modules；8.52秒；exit0 | 大chunk既有warning保留 |
| 后端等同性 | 无diff；exit0 | 不等于本轮重跑后端 |
| 业务diff whitespace | exit0 | 不将原始失败日志行尾格式改写成绿测 |

早期Array.map/structuredClone夹具错误、有效8例红测、作用域测试失败以及共享章节旧预期失败均在尝试记录中区分。缺少单独时间戳的开发运行明确披露，不倒填为固定SHA日志。本轮没有新增功能阻塞或要求清零既有警告。

## 4. P5整体关口

OVC-P5-01于34d646d/78fd14f通过，本次未修改其后端实现；COLLAB-10/11结构缺口保持关闭。OVC-P5-02本次关闭，补齐COLLAB-03/12涉及的客户端正文、版本及冲突状态一致性。

P5整体结论综合原P5实际双editor浏览器、候选/剪辑/FFmpeg、真实PG对象事务证据，P5-R1结构红绿和473后端/10并发证据，以及本次纯前端修复和正式回归。不是声称全部COLLAB场景在aebffe3重新做了浏览器/PG测试。

| 范围 | 最终关口 |
|---|---|
| OVC-P5-01 | 保持关闭，原S2 |
| OVC-P5-02 | 本次关闭，原S2 |
| P5-R2 | 通过 |
| P5整体 | 通过 |
| 新增阻塞 | 无 |
| 下一任务 | P6-JOBS-01 |

## 5. 审核端与实施端边界

本轮审核端未独立运行项目Node/React测试、PG、PowerShell或浏览器。实际完成的是连接器源码/证据审查、Git树一致性比对，以及本地环境/只读git ls-remote探测。

审核端有Node/npm，但没有完整本地工作区及项目依赖；直接只读Git连接本次返回DNS失败。环境没有psql/postgres/pg_ctl/pwsh等工具。不能将“有Node”写成完整工程已复跑，也不能说连接器无法访问仓库。详见checks/environment.json。

本轮未改远端仓库，未操作用户或保留实例/数据库/租约/草稿，也未调用真实Provider。无新浏览器/HTTP/PG测试是本次授权的有效边界，不构成追加验收门槛。

## 6. 下一单一任务

允许进入 **P6-JOBS-01：可靠任务执行、原子配额与管理操作闭环**。完整提示词见P6_CODEX_PROMPT.md，按原P6冻结范围执行。P7部署/备份/容量和真实付费联调不前移。

P5通过SHA即本报告指定evidence HEAD；开始P6时记录实际HEAD，不回退新提交、不覆盖未提交改动。阶段完成仍须独立外部验收，Codex不自行签发PASS。

来源定位见SOURCES.md。本文未用未执行的源码探针代替已声明的测试。
