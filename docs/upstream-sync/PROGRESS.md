# 选择性上游同步执行记录

上游冻结 `13939a82fb23ea7659cc079e575c521c104789d8`；原协作功能基线 `4fba7892daeafff017eae43b7295ac0054b99391`；分类清单 `eeb7a4f96df58dfae97a25e2af93249095d6c2be`。

用户已取消ChatGPT审核，Codex独立研究、复现、实现和验证。不能复制的按实际需求适配；不存在或已有等效修复的bug不重复改动。历史外部验收保持原绑定，本记录只报告本次自测结果，不签发新的外部PASS。清单不是全部功能已迁移的声明。

## UPSTREAM-SYNC-01：HC素材组跨实例重名

源提交：`81ec32e59150e2d12092a38ddaeced07387f7fbe`。

协作实现提交：`48d28ac36f1d1cbdf8a4611a72b1ee01b02b519d`。

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

## UPSTREAM-SYNC-02：错误响应读取一次

源提交：`83055bb5d7d0d5560782ca1aed17ea2995e22fe6`。

需求：服务端返回JSON、文本、HTML或空错误响应时，用户看到真实错误或明确HTTP状态，而不是“响应体已消费”；客户端依然保留status/url以及原403/409处理依据。

复现：从协作版 `src/main.tsx` 读取实际API包装函数，在隔离Node测试中注入本地Response，不启动页面或网络。旧实现先调用json、失败后再读text，返回纯文本502实际报 `Body is unusable: Body has already been read`，且未附带status。初次命令复现exit1；正式测试接入后旧包装器再次 **9 passed / 1 failed**，失败项是实际包装函数保留错误及状态的断言，不是缺少待创建文件造成的失败。

实现：新增11行 `src/apiResponse.ts`，先读取一次text再尝试JSON.parse；包装器仅改错误解析和导入。未改变fetch配置、CSRF头、认证、成功JSON返回、status/url/kind及协作冲突处理。

测试：新增10项，包含真实包装器片段执行（Node stripTypeScriptTypes；测试出现其experimental warning）、文本/HTML/空/JSON422、403、409及成功返回；使用模拟fetch，无真实HTTP或外部调用。保留原协作草稿/回执等测试，不新增请求层框架。

- 首次 `npm test` 因新worktree尚无node_modules：179 passed / 4文件加载失败（缺Twick/Three依赖），exit1；不是产品测试通过。原始失败日志保留。
- 在新worktree执行已有锁文件的 `npm ci --no-audit --no-fund`，383 packages，exit0；package.json和lockfile均未变化，只有既有传递依赖弃用提示。
- 随后 `npm test` → **205 passed / 0 failed，1358.34ms，exit0**（原195项＋新增10项；包括协作草稿/晚回执/租约边界）。
- `npm run build` → **tsc及Vite exit0，1838 modules，Vite 10.59秒**；既有大chunk警告保留。
- `git diff --check` → exit0。后端未变，本批不重跑79项或后端全量。
- 未运行浏览器端到端，不宣称页面链路复验；实际API包装器测试不等于浏览器测试。构建仅在独立worktree，未部署/替换原服务。

本批结论：已复现且修复、前端自测及构建完成。无新依赖、迁移、配置、后台页面，无真实付费调用。

## UPSTREAM-SYNC-03：编辑器连续播放、切分和完整初剪

需求来源：`edf241f`、`bba17a0`、`032dc96`、`7464df2` 的多片段播放、时间线工作区、切分、完整素材及显式目标时长需求。按协作版接口适配，不整批复制这些提交；其中素材标签、EP素材范围、额外预览提示等尚留在后续清单，不宣称上述提交每一行都已导入。

实际红测：`node --test tests/upstream_editor_regressions.test.mjs` 初次 **3 failed / exit1**：两段4秒视频被规划时长截成3+2秒；真实安装的Twick对带已知时长的受保护URL视频切分失败后剩余片段数0；真实安装的播放回调在旧4秒/当前8秒状态下于第6秒提前归零。不是仅由上游bug名称推断。

实现与协作适配：

- 新建/读取的画面轨使用Twick `element` 类型，避开旧video轨对后续片段重复叠加绝对起点。保留一个主画面轨，未复制上游“一镜一轨”；前后端旧简剪投影同步兼容，跳过纯标题轨。读取转换不直接写库；原 `TimelineInputSync` 不变。
- 初剪默认保留真实素材完整长度；用户明确选择“匹配目标”才变速。画面与**已明确采纳且版本匹配**的对白同步变速，BGM按输出长度循环。未采纳的对白不自动加入，已有音色版本绑定检查保留；未复制上游删除对白轨的实现。
- 目标速度限制为本项目预览/导出已有的0.25–4倍；超出明确报错，不用静默裁切或后端限幅假装满足目标。旧简剪投影增加可选 `playbackRate`，调音量/长度以及旧预览不再把速度丢掉。
- 工作区时长独立于内容/导出长度；至少覆盖目标时长、内容及5秒。只有主动修改输入框才持久化metadata；远端刷新可以缩短显示范围，不回写加载得到的规范化数据。
- 安装后补丁只修改锁定Twick发行文件的播放总时长、末端刻度对齐及已知视频时长时跳过重复元数据请求。四个ESM/CJS文件全部预检查再写，重复执行幂等，遇到未知构建报错。新增postinstall及lockfile的hasInstallScript标记，**没有新增/升级依赖**。

实际验证：

- 三项红测修复后3 passed。最终 `npm test` → **215 passed / 0 failed / 0 skipped，1192.50ms，exit0**，含10项本组新增回归、既有对白采纳及草稿同步回归。旧初剪“按规划截短”断言按新需求调整，缺素材/stale拒绝断言继续保留。
- 真实PG专项：`python -m pytest tests/test_p5_document_projection.py tests/test_p5_object_transactions.py tests/test_p5_canonical_integration.py tests/test_editor_renderer.py -q` → **60 passed，85.60秒，exit0**。覆盖generic轨/速度/工作区metadata经对象接口保存和新GET投影、无租约409、非负责人403、既有竞争/指派/版本边界。
- 上述60项包含3项真实FFmpeg双视频导出（0.5/1/2倍速）；抽取前段红色、后段蓝色像素验证片段存在。工作区设60秒时导出计划仍为实际内容长度。其余已有滤镜也实际调用FFmpeg。
- 后端首次60项为56 passed / 4 failed：新增测试插入时误归属一段旧测试尾部断言；新媒体probe桩返回ffprobe原始结构而非本项目扁平结构。修正断言位置、改用真实media.probe后完整60项重跑通过；没有为通过而改变产品权限/渲染校验。
- `npm run postinstall` 重复执行exit0；测试验证全部四个构建幂等、未知末文件时不部分修改前文件。
- 最终 `npm run build` → **tsc及Vite exit0，1839 modules，Vite 7.03秒**；既有大chunk警告仍在。`git diff --check` 无空白错误。
- 浏览器真实组件检查：新增仅测试使用的 `tests/editor_browser.{mjs,html,tsx}`，合成两段4秒红/蓝视频，独立Vite、无API代理/用户数据/Provider。页面初次加载本地修改次数0；连续播放见第二段蓝色视频至约8秒末尾；再点击回到0秒红色；工作区8→12秒保留原两段；2秒剪刀切分得到两个红片段且后段蓝片段仍在；空时间线选择匹配4秒得到2倍速初剪，3秒处显示蓝色。浏览器不是登录后端的完整E2E，权限/存储由以上真实PG HTTP专项证明，不混称全链路浏览器通过。

无数据库迁移、后台页面、付费调用；未修改认证、对象保存、租约或任务平台。只在独立worktree生成构建和合成测试媒体，未替换用户运行实例。PG夹具仍仅自动删除本次创建的临时测试库，保留历史服务/数据；本轮合成媒体和测试日志保留。开发交付状态：`READY_FOR_REVIEW`（用户已取消外部ChatGPT审核，此标识不代表新的外部PASS）。

## 后续队列

前三组完成自测，其余仍未全部移植。下一组研究编译后错误stale标记，以及当前EP素材范围/标签等创作界面需求，再处理媒体参数、多模态/音色、直接剧本。必须继续保留timeline单主源、租约与草稿。单机免审核/覆盖冲突草稿不照搬；运维、付费和延期平台不恢复。整体同步目标仍在进行，尚未合并master或更新用户运行实例。
