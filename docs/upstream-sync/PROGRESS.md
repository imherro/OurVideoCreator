# 选择性上游同步执行记录

上游冻结 `13939a82fb23ea7659cc079e575c521c104789d8`；原协作功能基线 `4fba7892daeafff017eae43b7295ac0054b99391`；分类清单 `eeb7a4f96df58dfae97a25e2af93249095d6c2be`。

用户已取消ChatGPT审核，Codex独立研究、复现、实现和验证。不能复制的按实际需求适配；不存在或已有等效修复的bug不重复改动。历史外部验收保持原绑定，本记录只报告本次自测结果，不签发新的外部PASS。清单不是全部功能已迁移的声明。

## UPSTREAM-SYNC-01：HC素材组跨实例重名

源提交：`81ec32e59150e2d12092a38ddaeced07387f7fbe`。

需求：两个独立安装/数据库可共用同一HC账号，不因自动创建的素材组名称相同而使生成前置步骤失败；原分组与显式指定分组继续使用。

协作版实际红测：在原 `_asset_group` 实现上，用新建真实PG测试库和MockTransport模拟云端已有旧固定组名，实际报 `ValueError: 幻场 AI 返回业务错误：同名分组已存在`。命令 `python -m pytest tests/test_hc_atom.py -k asset_groups_are_unique -q`，1 failed / 13 deselected，3.90秒，exit1。不是仅凭上游存在bug推断本项目也需要改。

修改：仅缓存未命中时为新组名追加12位UUID十六进制后缀。保留PG SQL、缓存键、显式组ID优先、原HTTP检查、锁、供应商配置及旧云端分组。没有添加云端查找、重命名、删除或重试生成逻辑；未移植多模态协议/模型迁移。

测试适配：没有照搬上游SQLite夹具。使用项目现有帮助函数创建第二个已迁移的隔离PG数据库，与主测试库使用相同合成Provider ID和Key；一个MockTransport代表同云账号。验证两库创建不同组、原库反复复用，已有缓存/显式组ID零请求、旧云组保留、组名长度与不含Key、业务错误/缺groupId/HTTP503都不写成功缓存。夹具仅释放自己新建的 `ovc_test_*` 数据库，保留原有用户/历史库。

实际验证：

- HC专项：`python -m pytest tests/test_hc_atom.py -q` → **14 passed，11.35秒，exit0**。
- HC与P4平台模型/提交/轮换/回归联合专项：`python -m pytest tests/test_hc_atom.py tests/test_p4_submission_execution.py tests/test_p4_rotation_http.py tests/test_p4_model_foundation.py tests/test_p4_r1_regressions.py -q` → **79 passed，154.60秒，exit0**。包含上面的14项，不累计为93项。
- `python -m compileall -q backend/providers/hc_atom.py tests/test_hc_atom.py` → exit0。
- `git diff --check` → exit0。Git仅提示现有Windows行尾转换策略，无空白错误。
- 未跑前端build、浏览器和全量后端：没有前端、公共事务、认证、队列主链修改，不把历史测试改写为当前执行。
- 未调用真实供应商；Mock验证不代表真实账号或收费能力通过。

无新增依赖、迁移、配置或后台页面。唯一运行时文件为 `backend/providers/hc_atom.py`；测试为 `tests/test_hc_atom.py`。同步更新AGENTS/ChatGPTRules中的用户工作模式覆盖，避免后续继续等待已取消的外部审核。

开发在独立 `codex/upstream-sync-20260917` worktree；未合并master、未替换已运行实例、未停止历史服务。新测试PG仅绑定loopback端口55439；平台联合专项由既有夹具启动并收尾自己的隔离Worker/fake，不给原有实例增加Worker。只有本轮新建的临时测试数据库由既有夹具自动删除（不含用户或历史数据），不可恢复也不需要恢复；本轮专用PG集群和本地红/绿日志保留。

本批结论：缺陷已在本项目复现、最小修复及相关79项回归通过，独立自测完成；不代表真实供应商联调或新增外部验收。

## 后续队列

下一独立候选：`83055bb` 的错误响应读取问题，先在本项目复现，再决定最小修复。其余功能仍是分类清单中的待研究需求，不因本批测试通过就视为已完成。单机免审核/覆盖冲突草稿不照搬；运维、付费和延期平台不恢复。
