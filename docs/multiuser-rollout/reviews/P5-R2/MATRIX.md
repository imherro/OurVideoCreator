# P5-R2 复验矩阵与 P5 结论

固定业务 aebffe364313601aceb611fbcd0ca2b01a42e29d；evidence afd1eb0d3eed36b3dcd818ed0c29aec2989c2259。

| 原要求 | 核查依据 | 结论 |
|---|---|---|
| r2迟到回执后不能用r3 revision保存未接受的v2正文 | acknowledge保留成对r2基线；host full/only及final-note红绿 | 通过 |
| 保存期间输入不丢 | serial保护；4个组合保留note+remote r3 | 通过 |
| 较旧读取不替换缓存的新快照 | remote比较entry.remote.revision；older echo回归 | 通过 |
| 自身回显及正常顺序仍工作 | own echo无重复请求；随后r3正常应用 | 通过 |
| X保存不抹掉或回声写Y | 第二客户端合法更新Y；host接收、baseline同步 | 通过 |
| X冲突仍可saveOnly(Y) | 只检查本次tickets；真实saveObject回调断言 | 通过 |
| 明确discard/keep仍受控 | discard先采用r3再改note；keep后r4竞争使r3 CAS失败 | 通过 |
| epoch及作用域安全 | owner/epoch反例、full/only与same/different ID generation测试 | 通过 |
| 真实host传播 | AST读取三个实际函数并执行；非手写替代分支 | 通过，refs/setters/transport为夹具 |
| 共有章节状态机 | 保留r2/比较r3/禁重试/明确discard的加强断言 | 通过 |
| P5-R1结构修复 | backend树未改变，继承已通过473/10等证据 | 保持关闭 |

## P5 COLLAB-01…12

01不同对象双用户保存、02版本竞争、04旧PUT退役、05分配/撤权、06租约、07审核历史、08固定视觉引用、09候选采纳：沿用已核验实现与此前证据，无本轮新发现阻塞。

10批量原子与11附属结构：P5-R1已修，本轮保持关闭。

03客户端冲突不静默覆盖、12私有状态/共享更新：此前主链及本轮晚回执分支共同支持通过。原浏览器证据不冒称R2重跑。

**P5整体通过。没有声称每个交错已穷举或完成生产部署验收。**
