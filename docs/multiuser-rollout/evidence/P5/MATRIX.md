# P5 验证映射（READY_FOR_REVIEW，不是外部验收结论）

完整基线 f4773f0：458 后端、10 并发轨迹、172 前端及 TS/build/routes/compile 均 exit 0。最终业务 0851dce：后端/依赖不变，前端 178、renderer 30、TS/build/diff 均 exit 0。日志见 commands-*，逐次修正见 ATTEMPT_HISTORY。下列不是外部通过结论。

| 项 | 自动验证入口 | 真实页面 / 取证范围 |
|---|---|---|
| COLLAB-01 | test_p5_object_transactions: two_editors_independent_objects_and_no_management_bypass | 两独立 editor host 的 X/Y 实际保存、刷新、退出重登已观察 |
| COLLAB-02 | same_revision_real_pg_waiters_one_commit_one_conflict; locked_shot_does_not_lock_other_shot; owned_content same_version_wait_chain | 确定 PG waiter 轨迹由 concurrency-traces 命令输出 |
| COLLAB-03 | collaboration_client / object_drafts tests | 第二 A 页离线 r2 草稿、远端 r3、恢复联网明确保存 409、比较本地与远端、无自动重发观察 |
| COLLAB-04 | real_aggregate_reads_objects_and_legacy_put_is_gone_even_for_owner; metadata_whitelist; document_projection | 实际浏览器保存走 objects/commands，访问日志保留；直接旧 API 由接口测试覆盖 |
| COLLAB-05 | assign_a_b_a_invalidates_old_epoch; revocation_keeps_content; owned_content owner_only_and_aba; lifecycle | 包含团队/作品撤权与账号停用，未冒称所有撤权交错均由浏览器覆盖 |
| COLLAB-06 | timeline_lease_expiry_takeover_old_token_and_locked_clock; delayed lease/switch frontend cases | 两页竞争 lease_busy，续租、释放、第二页取得/释放；过期/接管/锁后时钟由真实 PG 测试覆盖 |
| COLLAB-07 | review_is_revision_bound_and_restore_adds_revision; chapter_review_exact_version | 实际页面恢复 r3 追加 r6，保留 r4 candidate.adopt/r5 save；管理审核并非全部浏览器覆盖 |
| COLLAB-08 | visual_version_and_voice_immutability_survive_new_card_version; storyboard two_pass_candidate_imports… | 固定版本、音色、已有素材和镜头绑定由接口及前端回归覆盖 |
| COLLAB-09 | object_candidates/relation_candidates/storyboard_candidates | 两真实 loopback 请求原件；人工 v2/v3 保留、过期 graph 采纳拒绝、B 只读比较、A 明确采纳 r4；重分配路径由接口测试覆盖 |
| COLLAB-10 | batch_rejection; nested_foreign_asset; mixed_structural_import; run_permissions; storyboard permissions | 同事务全失败和 job 无半批，真实 PG 等待/权限重查；未做百人性能测试 |
| COLLAB-11 | collaboration_actions; owned_content; lifecycle; resume_permissions | 实际自由节点/图结构、章节 A 保存 r2/B 只读、导演台 PNG 上传与新节点；包含截图目视检查 |
| COLLAB-12 | collaboration_document private-state tests; collaboration_client remote merge; timeline_input_sync / editor_document | f477 真实画布选择/视口独立；0851 修正后 A 0.5s/B 1.5s、A 有选择/B 无选择，标题共享更新后均保持；B 脏草稿保留，明确载入远端后同步；无回声写入。见 browser-0851dce-tools.json |

所有测试仅自有临时 PostgreSQL、loopback fake 和本地媒体。未调用真实付费 Provider；不对公网部署、性能容量、P6 多 Worker/配额/计费作结论。
