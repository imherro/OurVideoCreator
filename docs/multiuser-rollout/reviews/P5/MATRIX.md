# P5 外部验收矩阵

绑定最终业务 `0851dce02e0f22e87f6247b029fd3faedd39e7dd`，证据 `5143ee36f55ab783f203832558cfedd4efce4936`。总体不通过，仅 OVC-P5-01（S2）。

|编号|状态|依据与边界|位置/证据|
|---|---|---|---|
|COLLAB-01|通过（已核验场景）|不同负责人各自镜头保存、刷新／重登；服务端拒绝修改他人普通对象。|test_p5_object_transactions；browser-f477完整轨迹|
|COLLAB-02|通过（已核验场景）|同revision真实PG竞争一成功一409，独立镜头不因另一个行锁而无法保存。|并发日志；test_p5_object_transactions|
|COLLAB-03|通过（已核验场景）|旧页草稿真实409，比较保留且不自动重发；scope/flight隔离。|objectDrafts/collaborationClient；实际browser409|
|COLLAB-04|通过（已核验场景）|聚合GET与主源分离；旧整份PUT包括owner为410。|test_p5_canonical_integration；collaboration_document|
|COLLAB-05|通过（已核验场景）|分配代际、ABA、成员撤权保留内容并清lease。|collaboration/owned_content；tests及全量记录|
|COLLAB-06|通过（已核验场景）|短租约、锁后时钟、旧token、接管；浏览器双页竞争。|test_p5_object_transactions；并发日志；browser|
|COLLAB-07|通过（已核验场景）|审核精确revision，编辑回进行中，恢复追加；viewer评论无正文写。|review/restore；owned_content；tests/browser|
|COLLAB-08|通过（已核验场景）|锁定视觉/音色版本不原改，派生不漂移已有镜头绑定。|test_p5_canonical_integration；film_bible验证|
|COLLAB-09|通过（已核验场景）|生成先候选；当前权限/版本及必要引用校验，显式采纳和收据同事务。|object_job_candidates/job_candidates/storyboard；真实fake/browser|
|COLLAB-10|部分通过；阻塞OVC-P5-01|既有混合权限／引用失败回滚有效；附属节点身份变化遗漏结构要求。|collaboration.commands:413–419、463–467|
|COLLAB-11|部分通过；阻塞OVC-P5-01|章节/导演台/自由节点路径已接通；镜头子节点身份改变可留下悬空graph。|collaboration_routes/validation；workflows.topological|
|COLLAB-12|通过（已核验场景）|Twick清洁远端同步不回声，脏草稿保留，私人播放头/选择独立。|0851diff；178前端测试；17/17浏览器补跑|

“通过（已核验场景）”不代表所有组合已形式化证明或审核者独立全量复跑。P1–P4保留能力的正式回归记录有效，无本轮新发现需重开其历史关口的问题；未授权项目不纳入通过要求。
