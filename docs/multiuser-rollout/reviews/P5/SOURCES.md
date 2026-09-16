# 审核来源索引

只使用协作仓库；运行代码固定业务SHA，证据固定最终HEAD。部分大文件按函数或行范围读取，不声称逐字读取所有文件或自行核算全部校验和。

|编号|材料|固定链接|对话证据标识|
|---|---|---|---|
|S01|branches/master|https://api.github.com/repos/imherro/OurVideoCreator/branches/master|turn486file0|
|S02|P5 full commit|https://github.com/imherro/OurVideoCreator/commit/f4773f0075325625c6cf2e6236c5d2014d416d3f|turn488file0; turn528file0|
|S03|frontend followup commit|https://github.com/imherro/OurVideoCreator/commit/0851dce02e0f22e87f6247b029fd3faedd39e7dd|turn500file0; turn514file0|
|S04|commands implementation|https://github.com/imherro/OurVideoCreator/blob/0851dce02e0f22e87f6247b029fd3faedd39e7dd/backend/collaboration.py|turn491file0; turn492file0; turn521file0; turn522file0|
|S05|graph validation|https://github.com/imherro/OurVideoCreator/blob/0851dce02e0f22e87f6247b029fd3faedd39e7dd/backend/collaboration_validation.py|turn493file0|
|S06|object HTTP routes|https://github.com/imherro/OurVideoCreator/blob/0851dce02e0f22e87f6247b029fd3faedd39e7dd/backend/collaboration_routes.py|turn494file0|
|S07|readonly aggregate|https://github.com/imherro/OurVideoCreator/blob/0851dce02e0f22e87f6247b029fd3faedd39e7dd/backend/collaboration_document.py|turn512file0|
|S08|topology validation|https://github.com/imherro/OurVideoCreator/blob/0851dce02e0f22e87f6247b029fd3faedd39e7dd/backend/workflows.py|turn519file0|
|S09|canonical integration tests|https://github.com/imherro/OurVideoCreator/blob/0851dce02e0f22e87f6247b029fd3faedd39e7dd/tests/test_p5_canonical_integration.py|turn499file0|
|S10|object transactions tests|https://github.com/imherro/OurVideoCreator/blob/0851dce02e0f22e87f6247b029fd3faedd39e7dd/tests/test_p5_object_transactions.py|turn513file0|
|S11|object candidate|https://github.com/imherro/OurVideoCreator/blob/0851dce02e0f22e87f6247b029fd3faedd39e7dd/backend/object_job_candidates.py|turn495file0|
|S12|relation candidate|https://github.com/imherro/OurVideoCreator/blob/0851dce02e0f22e87f6247b029fd3faedd39e7dd/backend/job_candidates.py|turn496file0|
|S13|storyboard candidate|https://github.com/imherro/OurVideoCreator/blob/0851dce02e0f22e87f6247b029fd3faedd39e7dd/backend/storyboard_candidates.py|turn505file0|
|S14|owned relational content|https://github.com/imherro/OurVideoCreator/blob/0851dce02e0f22e87f6247b029fd3faedd39e7dd/backend/owned_content.py|turn497file0|
|S15|relation routes|https://github.com/imherro/OurVideoCreator/blob/0851dce02e0f22e87f6247b029fd3faedd39e7dd/backend/owned_content_routes.py|turn503file0|
|S16|director and promotion|https://github.com/imherro/OurVideoCreator/blob/0851dce02e0f22e87f6247b029fd3faedd39e7dd/backend/collaboration_actions.py|turn498file0|
|S17|frontend save client|https://github.com/imherro/OurVideoCreator/blob/0851dce02e0f22e87f6247b029fd3faedd39e7dd/src/collaborationClient.ts|turn501file0|
|S18|frontend drafts|https://github.com/imherro/OurVideoCreator/blob/0851dce02e0f22e87f6247b029fd3faedd39e7dd/src/objectDrafts.ts|turn502file0|
|S19|P5 contract|https://github.com/imherro/OurVideoCreator/blob/0851dce02e0f22e87f6247b029fd3faedd39e7dd/docs/multiuser-rollout/design/P5_OBJECT_COLLABORATION.md|turn489file0|
|S20|REPORT.md|https://github.com/imherro/OurVideoCreator/blob/5143ee36f55ab783f203832558cfedd4efce4936/docs/multiuser-rollout/evidence/P5/REPORT.md|turn487file0|
|S21|MATRIX.md|https://github.com/imherro/OurVideoCreator/blob/5143ee36f55ab783f203832558cfedd4efce4936/docs/multiuser-rollout/evidence/P5/MATRIX.md|turn490file0|
|S22|PROVENANCE.md|https://github.com/imherro/OurVideoCreator/blob/5143ee36f55ab783f203832558cfedd4efce4936/docs/multiuser-rollout/evidence/P5/PROVENANCE.md|turn510file0|
|S23|ATTEMPT_HISTORY.md|https://github.com/imherro/OurVideoCreator/blob/5143ee36f55ab783f203832558cfedd4efce4936/docs/multiuser-rollout/evidence/P5/ATTEMPT_HISTORY.md|turn511file0|
|S24|commands-f4773f0/backend-full.txt|https://github.com/imherro/OurVideoCreator/blob/5143ee36f55ab783f203832558cfedd4efce4936/docs/multiuser-rollout/evidence/P5/commands-f4773f0/backend-full.txt|turn508file0|
|S25|commands-f4773f0/concurrency-traces.txt|https://github.com/imherro/OurVideoCreator/blob/5143ee36f55ab783f203832558cfedd4efce4936/docs/multiuser-rollout/evidence/P5/commands-f4773f0/concurrency-traces.txt|turn509file0|
|S26|commands-f4773f0/runs.json|https://github.com/imherro/OurVideoCreator/blob/5143ee36f55ab783f203832558cfedd4efce4936/docs/multiuser-rollout/evidence/P5/commands-f4773f0/runs.json|turn506file0|
|S27|commands-0851dce/runs.json|https://github.com/imherro/OurVideoCreator/blob/5143ee36f55ab783f203832558cfedd4efce4936/docs/multiuser-rollout/evidence/P5/commands-0851dce/runs.json|turn520file0|
|S28|commands-0851dce/frontend.txt|https://github.com/imherro/OurVideoCreator/blob/5143ee36f55ab783f203832558cfedd4efce4936/docs/multiuser-rollout/evidence/P5/commands-0851dce/frontend.txt|turn523file0|
|S29|commands-0851dce/build.txt|https://github.com/imherro/OurVideoCreator/blob/5143ee36f55ab783f203832558cfedd4efce4936/docs/multiuser-rollout/evidence/P5/commands-0851dce/build.txt|turn524file0|
|S30|commands-0851dce/editor-renderer.txt|https://github.com/imherro/OurVideoCreator/blob/5143ee36f55ab783f203832558cfedd4efce4936/docs/multiuser-rollout/evidence/P5/commands-0851dce/editor-renderer.txt|turn525file0|
|S31|commands-f4773f0/routes.txt|https://github.com/imherro/OurVideoCreator/blob/5143ee36f55ab783f203832558cfedd4efce4936/docs/multiuser-rollout/evidence/P5/commands-f4773f0/routes.txt|turn527file0|
|S32|browser-f4773f0-tools-complete.json|https://github.com/imherro/OurVideoCreator/blob/5143ee36f55ab783f203832558cfedd4efce4936/docs/multiuser-rollout/evidence/P5/browser-f4773f0-tools-complete.json|turn518file0|
|S33|browser-0851dce-tools.json|https://github.com/imherro/OurVideoCreator/blob/5143ee36f55ab783f203832558cfedd4efce4936/docs/multiuser-rollout/evidence/P5/browser-0851dce-tools.json|turn517file0|
|S34|browser-followup-db.json|https://github.com/imherro/OurVideoCreator/blob/5143ee36f55ab783f203832558cfedd4efce4936/docs/multiuser-rollout/evidence/P5/browser-followup-db.json|turn526file0|

根树核对：业务9b2b16b5aee9fa8eec21d3842daafd33b7ab21b7、证据a17fdf43ef9a613c2777a16c33f60fa3334307b6，对应 turn515file0/turn516file0；只有docs不同。
