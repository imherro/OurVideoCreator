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

## UPSTREAM-SYNC-04：无对白视频编译后误标过期（已完成）

来源 `cdf1dec`。协作版 `src/graph.ts` 的旧自动采纳函数仅剩导入、没有工作链路调用；实际写入位于服务端 `object_job_candidates.adopt`，故没有照搬前端自动修复/回写旧结果。通过真实PG、普通编辑者的提交和明确采纳API复现：正常无对白视频被时长编译追加提示词，采纳后 `stale=True`，专项 **1 failed / 2 passed，14.50秒**。生成媒体来自本地FFmpeg，没有Provider调用。

服务端编译器现在写入自己生成的 `shot_video_projection`，冻结原节点提示词。采纳比较源提示词与源提示词，不比较追加了时长要求的编译文本；仍检查generation_revision和原对象/依赖/权限版本。仅靠布尔编译标记跳过提示词检查会漏掉不更新generation_revision的API编辑，本项目没有采用该简化。调用者伪造的同名标记先被移除，未绑定镜头或非视频任务不能借标记绕过判断。生成成功不自动写回、修改后须显式accept_stale、依赖版本检查全部保持。

`python -m pytest tests/test_upstream_compiled_candidates.py tests/test_video_dialogue.py tests/test_p5_object_candidates.py tests/test_p4_submission_execution.py -q` → **31 passed，90.47秒，exit0**。含真实提交/采纳接口正常、改提示词但不改generation_revision、改generation_revision三种情况，及既有迟到候选/越权/依赖变化回归；编译器还验证伪造标记不会被保留。未重跑浏览器、前端或全量后端，本批没有前端代码变更；`git diff --check`通过。没有新依赖、迁移、页面或收费调用；不在GET中修复旧数据，不修改历史验收结论。`READY_FOR_REVIEW`，按用户指示无需外部ChatGPT审核。

## UPSTREAM-SYNC-05：EP 素材范围、易读标签与跨集剪辑导出

需求来源：`b2881e0` 及 `83b8657` 的素材面板部分。默认只显示当前 EP，其他 EP / 全部作品须显式选择；计数及搜索随范围变化。素材显示镜头、内容、实际/规划时长及版本；版本分组包含 EP 身份，同名节点不得串用描述或版本号。面板可拖动及键盘调整宽度。适配协作版平台 `model_id`，UUID 镜头编号回退到镜头顺序，不把 UUID 中数字误显示为镜号。没有修改原素材名、复制单机生成命名落库逻辑或本地模型配置；83b8657 的剩余命名/规格需求不算本批完成。

复现并修复同作品跨 EP 导出：原素材查询已允许同作品，但 `EditorRenderCompiler` 仍严格要求相同 project_id。真实 PG 普通编辑者先上传、持租约保存引用，再提交导出，原实现 **1 failed，5.89秒**，报素材属于其他项目。现在 Worker 从数据库解析目标作品，并把同作品范围显式传给编译器；未传可信作品时仍按原同项目检查。查询保留软删除素材过滤，不信任输入或时间线 metadata 的 production_id，不修改素材所属 EP。没有放宽跨作品授权。

验证记录：

- `npm test` → **221 passed / 0 failed / 0 skipped，1243.07ms，exit0**；新增6项包括范围筛选不修改原素材数组、跨EP描述/版本隔离、UUID编号和包含冒号的身份不能拼接碰撞。
- `npm run build` → **tsc及Vite exit0，1840 modules，Vite 6.90秒**；既有大chunk警告保留。
- 初始导出/渲染/功能回归 **39 passed，16.06秒**；后续新增负例首次断言误以为跨作品请求应在提交时422，第二次误以为接口会替换请求时间线，两次联合执行各 **53 passed / 1 failed**。检查实际代码和响应后修正测试而未改动接口行为：提交冻结目标对象版本及可信作品，导出内容仍来自请求；跨作品引用由执行阶段拒绝，保存的时间线不被提交覆盖。
- 修正后的真实 PG / FFmpeg 专项 **1 passed，8.09秒**：同作品跨EP确实产生成片并解码首帧；伪造输入作品、伪造任务作品、已排队的跨作品引用均由 Worker 拒绝；对象 GET 保持原保存素材。编译器另有4个空/缺失/不同可信作品的负例。
- 最终 `python -m pytest tests/test_upstream_shared_editor_export.py tests/test_editor_renderer.py tests/test_final_functional.py tests/test_p5_object_transactions.py -q` → **54 passed，69.04秒，exit0**；覆盖真实导出、跨作品拒绝、源EP回收后已有引用可用、ACL、租约及对象事务竞争。`git diff --check`通过。没有运行全量后端或真实付费Provider。
- computer-use 真实隔离组件页：默认EP01显示2项，EP02显示1项，全作品3项，按“第二集”搜索只剩1项；主动加入产生一次本地修改、内容时长8→12秒，切回当前EP后原红/蓝两段及跨EP第三段都保留，切换/搜索没有额外保存。面板键盘向右从360→384像素，页面布局及无障碍数值已检查。不是登录业务系统的完整E2E；权限/存储由PG专项验证。仅关闭本轮测试页和自建Vite，保留合成媒体、日志及原用户/历史服务。

无新依赖、数据库迁移、后台页面或收费请求。保留对象事务、租约、审查、草稿和显式采纳语义；不在加载时回写。隔离PG夹具只释放本轮自建临时测试库，未删除用户数据。`READY_FOR_REVIEW`（用户已取消外部审核，不代表外部PASS）。

## UPSTREAM-SYNC-06：生成素材名称与顶部制作规格

来源 `83b86572b3295f19ac88b81fc9a67b17ba7ddb29` 剩余命名/规格需求；素材面板部分已在05完成。原登记函数实际返回 `Seedream 生成图.png`，真实PG专项先运行 **1 failed / 8 deselected，1.76秒**，证明协作版尚未满足按镜头/任务上下文命名的需求。

实现：普通通用结果名按冻结的任务label显示“镜头 06 · 分镜图 · V1.png”；显式output_name/asset_name优先，保留有效后缀及固定角色音色等结果限定词，替换名称中的路径分隔及控制字符。具体自定义名称与无上下文旧名称保持。参考图提交带视觉卡名、主/状态参考图及视觉版本号；结果仍只登记候选，明确采纳前不写回视觉卡。只改新结果显示名，不回填历史素材，不改assetId、UUID物理路径、内容、类别或生成指纹。

协作适配：PG按项目/节点/媒体类型计数，同名节点跨EP互不累计；用一个该组的事务advisory lock保护现有单Worker内并发登记，锁在任务行锁之前，等待时取消可先提交，随后不发布结果。不是新版本表/任务平台，不扩展多Worker。显示V编号不替代协作对象revision或视觉版本，原删除/保留策略不变。

比例、风格、目标秒数从视图工具栏移到共享流程顶部，只读显示并保留完整title；小屏按上游收缩/隐藏，原设置、保存与对象协作入口不变。没有引入单机默认模型或免审核行为。

实际验证：

- 命名、取消与Provider联合专项 `tests/test_asset_naming.py tests/test_asset_registration.py tests/test_volcengine_speech.py tests/test_volcengine_ark.py tests/test_hc_atom.py` → **56 passed，52.87秒，exit0**。包含4个并发登记得到V1–V4、跨EP/节点分别V1、数据库锁等待时取消及媒体清理、注册返回与PG名称一致、文件字节和UUID路径保持。Provider只使用Mock/本地测试，不代表真实账号通过。
- `npm test` → **222 passed / 0 failed / 0 skipped，1268.29ms，exit0**。顶部规格是结构回归检查，不宣称浏览器像素布局验收。
- `npm run build` → **tsc与Vite exit0，1840 modules，Vite 7.49秒**；既有大chunk警告保留。
- 协作联合专项 `tests/test_asset_naming.py tests/test_asset_registration.py tests/test_p5_object_candidates.py tests/test_p4_submission_execution.py` → **31 passed，79.98秒，exit0**。实际普通编辑者参考图提交保留命名输入，登记后卡片不变，明确采纳后按assetId关联；原非负责人、迟到结果及平台提交保护通过。此31项与前面56项包含重复专项，不累计为87个独立测试。`git diff --check`通过；没有运行全量后端、浏览器或真实付费API。

无新依赖、迁移、配置项、后台页面；保留主工作区与运行服务。本轮PG夹具仅自动释放新建测试库，未动用户库、历史媒体或草稿。`READY_FOR_REVIEW`，用户已取消外部ChatGPT审核。

## UPSTREAM-SYNC-07：项目图片画幅与平台参数冻结

需求来源 `ac2414d`，也是 `9b55ccf` 图片设置需求的画幅基础部分；本批不宣称完整图片设置界面、只读规格预览或实际随机种子展示已迁入。旧协作版仅对绑定镜头的图片推导尺寸，独立图片仍冻结为方形；同时把resolution质量档与像素尺寸混为一个优先字段。先运行新增专项，实际 **10 failed / 1 passed，7.51秒**，包括真实PG提交后冻结值仍为1024x1024的失败，不是缺少待创建模块。

服务端按规范化项目画幅推导所有图片任务中已发布的size/resolution/ratio/aspect_ratio控制；前端镜头构造保持一致。resolution为2k等质量档时不把它改成像素字符串，同时独立处理size。推荐尺寸必须满足管理员已发布的枚举/限制；不能满足时保留已验证、同比例的合法替代尺寸，否则在入队前明确报错，不静默生成方图、不扩展管理员允许值。没有发布尺寸/比例控制的模型仍保持原配置行为，不凭空注入参数，因而不承诺此类模型强制遵循项目画幅。

保留全景功能：新建全景节点明确保存image_purpose=panorama，服务端只读取已保存节点用途，按2:1处理。单独伪造任务input的同名字段不能覆盖普通项目画幅；不根据提示词猜测用途，不批量修改历史未标记全景节点。原Worker已经用私有冻结参数覆盖Provider默认值，经真实提交与模拟出站验证后，不重复复制上游HC/RunningHub参数优先级改动。

实际验证：

- 首轮修复专项11 passed；扩充后端联合专项59 passed，109.42秒；最终 `python -m pytest tests/test_upstream_image_aspect.py tests/test_p4_submission_execution.py tests/test_p4_r1_regressions.py tests/test_runninghub.py tests/test_hc_atom.py -q` → **61 passed，116.91秒，exit0**。含真实PG普通编辑者HTTP提交、私有参数冻结、OpenAI/HC本地假服务收到1152x2048、RunningHub模拟请求同时收到竖图宽高和2k档、规则更新后原幂等回执仍使用旧版本、新提交拒绝且不新增任务。RunningHub媒体下载为桩，不算真实媒体下载；无真实付费调用。
- 前端首次225 passed / 1 failed：既有测试断言不兼容平台枚举时继续返回方图，与本次明确拒绝的需求冲突；改为断言画幅错误，未放宽平台参数规则。最终 `npm test` → **226 passed / 0 failed / 0 skipped，1359.19ms，exit0**。
- `npm run build` → **tsc与Vite exit0，Vite 7.45秒**，保留既有大chunk警告。未运行浏览器或全量后端；不宣称真实供应商输出像素已验证。

无新依赖、数据库迁移、配置项或后台页面；保持对象权限、候选采纳、平台模型版本与幂等流程。未部署、合并master或修改用户服务。`READY_FOR_REVIEW`，按用户授权独立自测，不提交ChatGPT审核。

## UPSTREAM-SYNC-08：统一图片设置、只读预览与实际参数展示

来源 `9b55ccf`，与07的画幅基础合并满足这组需求。按协作版平台模型、对象保存和冻结绑定适配，不复制单机SQLite设置或恢复本地推理部署。需求/行为说明见 `docs/image-generation-settings.md`。

- 分镜列表、宫格、高级画布共用折叠图片设置，编辑同一节点的model_id/parameters/imageSettings。切换模型保留当前参数，不兼容明确报错；恢复项目默认是显式操作。仍经原patchNode、对象revision/草稿及提交前保存，不绕过负责人权限，不自动采纳图片。
- 新增本地只读 `POST /projects/{pid}/image-spec`，viewer只能在有权作品内预览，保留登录/CSRF边界；不创建任务、不改项目、不查询外部模型目录或发起生成。不以预览代替提交时的对象/素材检查。支持未保存画幅、视频分辨率及旧节点顶层参数，旧顶层参数重复冲突在预览与实际提交均拒绝。
- 私有工作流支持且平台发布相应规则时，Maestro/Comfy外部API才开放自定义/视频像素及固定种子。尺寸/随机整数仍受管理员规则约束；云端固定种子未实现时拒绝，不把输入后被忽略当作支持。随机种子预览不抽取，创建时冻结，旧幂等回执沿用原模型/配置/种子。没有种子合法候选时预览与提交均拒绝。
- 新图片任务的image_spec是只读安全投影，与job_private参数一致；客户端伪造值不影响冻结和重试。任务详情区分原请求与冻结值。不回填历史任务、不改恢复查询、无迁移或依赖升级。
- 额外实际复现批量入口重复注入图片ratio与节点parameters冲突，红测 **1 failed / 13 deselected，3.24秒**；仅取消图片批量入口的第二处注入，沿用服务端统一推导。单次与绑定镜头的精确批量均保持显式尺寸和稳定重试。

验证记录：

- 首轮图片设置/画幅专项24 passed，36.45秒；扩大联合首次62 passed / 1 setup error，161.36秒：测试新导入team夹具但遗漏clients夹具，修正测试导入，未改变权限实现以绕过测试。
- 随后联合82 passed，189.64秒；加入规则更新后种子回执及随机域校验，`tests/test_image_settings.py tests/test_upstream_image_aspect.py tests/test_p4_submission_execution.py tests/test_p4_r1_regressions.py tests/test_p5_run_permissions.py tests/test_runninghub.py tests/test_hc_atom.py` → **83 passed，199.11秒，exit0**。之后补齐旧顶层参数预览，最终设置专项 **16 passed，45.65秒**。有重复覆盖，不相加声称独立测试数。
- 真实PG与普通编辑者提交/批量/重试均执行；Maestro/Comfy Worker通过真实冻结绑定向MockTransport发出自定义宽高及确定种子，取回2×2合成PNG并登记素材。此项验证请求与登记，不声称真实供应商输出1280×720或付费账号通过。viewer跨作品拒绝，预览的外部调用入口被测试桩禁止，业务文档/任务列表不变。
- 前端首次228 passed / 1 failed：新增“保留已有节点”夹具没有既有图像→视频边，ensureShotNodes正常补边时测试的禁止ID生成器抛错；补齐夹具既有边后通过。最终 `npm test` → **229 passed / 0 failed / 0 skipped，1537.27ms**；`npm run build` → **tsc与Vite exit0，Vite 8.29秒**，既有chunk警告保留。
- computer-use隔离真实组件页：展开预览修改次数0；设置1280×720与种子7后三次修改，旧assetId保留且generation_revision递增/stale=true；切换入口不增加修改且设置保持；换模型保留参数并出现不兼容错误；主动恢复默认才重置。截图检查收紧后的布局。页面使用模拟预览函数，不是登录业务系统完整E2E；服务端一致性由PG专项覆盖。已关闭本轮自建页与Vite，保留用户服务和日志。

最终候选回归 `tests/test_image_settings.py tests/test_p5_object_candidates.py tests/test_upstream_compiled_candidates.py` → **26 passed，93.47秒，exit0**，包括本轮最终16项设置测试及既有显式采纳/迟到结果边界。`git diff --check`通过。未运行全量后端、真实付费API或部署。无新依赖、数据库迁移或后台配置页面；原master工作区仍干净且HEAD为eeb7a4f。本批仅进入集成分支，不合并master，不发送ChatGPT审核。`READY_FOR_REVIEW`仅为开发交付标识，不代表新的外部验收PASS。

## UPSTREAM-SYNC-09：幻场使用已采纳的固定对白

来源 `4e86bac` / `77b99d7` 的固定对白分支与 `dcee553` 的HTTP音频引用需求。原协作版尚未接通HC参考音频，故本批是功能适配，不把上游Base64报错描述为本项目已复现的bug。动作视频、上传音色样本、状态独立音色和完整多模态预览仍未完成，不将这几个上游提交整体标记为已迁入。

- 管理员可为私有上游ID符合doubao/dreamina-seedance-2.0或2.5协议的HC视频模型发布audio_reference；默认不开启，未知别名及其他HC模型不得宣称支持。还需发布generate_audio规则，并在已有Provider配置中填写public_base_url；没有新增配置字段、迁移、依赖或后台页面，也没有修改现用模型配置。
- 开启后，单次与精确批量生成都从已保存镜头、锁定音色和明确采纳的对白素材编译轨道。未采纳拒绝入队，伪造输入不能替换轨道，无镜头归属的任意音频引用拒绝。视频工作区的准备状态使用同一公开能力标记；原HC未开启模型继续原行为。
- 复用本地FFmpeg编排为时序MP3，按正常作品素材登记为derived/voice；HC取得短期签名HTTP链接，不发送Base64。签名不写入任务输入、幂等摘要或素材metadata。链接是现有的限时Bearer能力，默认一小时、绑定素材/方法/用途，沿用软删除过滤；不宣称它随用户成员资格变动即时失效。衍生音频按现有素材机制保留，没有自动清理任务。
- 参考音频模式的单张图使用reference_image、保留项目比例，2.5增加omni_reference_task_type=reference；本批不扩展多图上限或尾帧。原方舟Base64协议不变。入队前验证公网地址与时长，已有15/30秒限制保持，新增音轨末尾不得超过提交时长；有远端ID时仅查询，不再次编排或提交。
- 原对象负责人/版本、平台冻结参数、候选生成及显式采纳均保留，不因完成生成自动写回镜头。

实际验证记录：首次新增专项8 passed / 3 failed（签名断言传字符串、误认批量返回jobs而非job_ids、预期错误文案不符），修正测试后初步联合 **62 passed，92.87秒**。扩展真实合成视频回路后的联合38 passed / 2 failed：两个超限请求已被原适配器提前拒绝，但测试错误要求新文案；改为断言超限，不改原限制。最终新增专项 **16 passed，46.06秒**。

最终联合 `tests/test_upstream_hc_dialogue.py tests/test_hc_atom.py tests/test_volcengine_ark.py tests/test_video_dialogue.py tests/test_p5_object_candidates.py tests/test_p5_run_permissions.py tests/test_p4_submission_execution.py tests/test_p3_identity_acl.py::test_media04_signed_capability_binds_asset_method_purpose_expiry_and_revocation` → **93 passed，215.56秒，exit0**。含新增16项、真实PG普通编辑者单次/批量提交、未采纳拒绝且不增任务、他人及viewer拒绝、冻结真实音轨覆盖伪造引用、真实FFmpeg四秒MP3、签名验证及原签名路由软删除/过期边界、Mock视频下载与登记、成功后对象不变、显式采纳后视频不误标stale、有远端ID不再次POST或生成衍生音频。图片与音频组合的角色/比例测试使用编排及图片登记桩，不混称该组合进行了真实上游审核。前述专项与本次联合有重复，不相加计算独立测试数。

前端 `npm run test:frontend` **232 passed / 0 failed / 0 skipped，1363.48ms**；`npm run build` **tsc与Vite exit0，Vite 7.61秒**，既有大chunk警告保留。未跑浏览器、全量后端或真实付费服务；本地合成MP3/MP4和MockTransport证明请求、下载登记与采纳，不代表供应商实际音色/口型质量已验收。`git diff --check`通过。PG夹具只释放各轮新建隔离测试库，保留用户库、历史媒体、草稿和服务；master工作区干净且仍为eeb7a4f。本批仅交付集成分支，不部署、不合并master。`READY_FOR_REVIEW`为开发交付标识，用户已取消外部ChatGPT审核，不代表外部PASS。

## UPSTREAM-SYNC-10：动作参考视频与显式多模态模式

来源 `67c9f5b` 及冻结上游动作参考文档、`4e86bac` / `77b99d7` 的多模态协议。协作版原来没有这一闭环，本批按需求适配，不将单机实现直接覆盖；相关上游提交还含音色样本、状态音色和后续参考缩略图等内容，不整体标记为全部完成。详细使用与约束见 [动作参考说明](../motion-reference.md)。

- 网页新作品默认多模态，本集默认/镜头覆盖；旧文档及省略新字段的旧创建 API 保持 legacy。镜头保存一段 MP4 动作引用、角色和运镜模式；保留素材、计划时长和明确采纳流程。切模式/模型不删除绑定，不自动降级。
- 只读 video-spec 与单次/精确批量共用服务端编译。图片（含全部已确认角色/场景/道具）、动作、已采纳对白统一清单和编号；超过公开能力报错而非截断。纯单图仍走显式参考协议，严格首/尾帧拒绝额外引用。待生成图片绑定 durable job ID；旧结果不混入，执行时多图结果明确拒绝，避免编号漂移。
- FFmpeg 实测合法性和完整解码，冻结原文件 hash；第一次执行生成可复用静音派生 MP4，不改源文件、不裁剪变速。HC/Ark 使用短期签名 URL，RunningHub 上传视频/时序 MP3；预览没有 DB 写入。远端 handle 仅查询不补发。
- 保留平台发布/冻结模型规则、服务端作品素材 ACL、对象负责人和 revision。引用/模式改变时在事务锁内只更新相关视频及下游的生成版本/stale，其他负责人正文/分配/租约不覆盖；旧编辑会冲突，晚到候选仍须明确采纳并保持 stale。
- 视频工作区及高级画布可展开/刷新最终预览；生成忙碌不禁止只读查看。原“实际发送”客户端摘要改为折叠摘要，避免与服务器实际清单混淆。任务详情展示冻结参数。本批没有依赖、迁移或新后台页面；新增的是已有模型定义中的公开能力字段，没有修改现用配置。

开发过程实际记录：初始专项修正只读路由、缺少导入以及预览完整参数对比后 9 passed；首次构建因混用 `||`/`??` 失败，修正括号后通过。随后专项 20 passed。新增单图测试初次 3 例未传单次请求的 asset_ids（批量/预览读取已保存字段），修正请求与实际 UI 一致；重复编译测试发现参考标签丢失，修复去重后合并标签，4 项复测通过。新增前端测试首次有一处括号笔误，修正后 236 passed。动态图片负例首次误用不可变终态的 job_update，改为仅在隔离测试库注入异常供应商结果；生产终态保护未放宽。

前端最终 `npm test`：**236 passed / 0 failed / 0 skipped，1577.39ms**。最终 `npm run build`：**tsc/Vite exit0，Vite 8.01秒**，保留既有大 chunk 警告。额外供应商组合专项 `test_motion_references.py -k 'motion_and_adopted or 2.0 or 2-0'`：**6 passed / 26 deselected，41.84秒**，其中包括本次追加的5项和1项重复的发布上限测试，不与联合回归简单相加。

浏览器实际组件隔离检查（无 API 代理、无业务库）：忙碌时生成按钮禁用但可展开预览，修改次数保持0；显示计划2秒/提交4秒/动作2秒；长中文 prompt 折行。切严格模式显示错误且保留绑定；切回后可继续使用；解绑时素材数仍1。浏览器技能用于实际交互/布局核对，不把 Mock 预览描述为登录后的业务 E2E。完成后只关闭本轮测试页及其 Vite 服务，没有停止用户实例。

最终联合后端回归：`tests/test_motion_references.py tests/test_upstream_hc_dialogue.py tests/test_hc_atom.py tests/test_volcengine_ark.py tests/test_runninghub.py tests/test_video_dialogue.py tests/test_p5_object_transactions.py tests/test_p5_object_candidates.py tests/test_p5_run_permissions.py tests/test_p5_canonical_integration.py tests/test_p4_model_foundation.py tests/test_p4_submission_execution.py tests/test_image_settings.py tests/test_project_setup.py` → **204 passed，506.83秒，exit0**。该次收集包含动作专项27项；运行期间追加的2个2.0请求和3个动作+对白组合已在上述6项独立专项中验证。测试共同使用真实隔离PG，商业网络套接字禁用。未运行真实付费 Provider、完整业务浏览器 E2E 或全量后端测试，不对口型/动作跟随质量签发验收结论。

`git diff --check` 通过；原 master 工作区干净，HEAD 仍为 `eeb7a4f`，不合并、不部署、不发送 ChatGPT 审核。仅提交/推送到 `origin/codex/upstream-sync-20260917`。`READY_FOR_REVIEW` 是开发交付标识，不代表新的外部 PASS。

## UPSTREAM-SYNC-11：音色试听身份与确认边界

对照冻结上游音色样本/声音版本需求（`10acb73`、`0866461` 及最终 voices.ts）时先验证其前置条件。本批修复协作版实际复现的旧试听错配，不将音色样本上传、独立参考音频协议、命名音色库或状态继承标记为完成。

- 修复前前端4项失败：改变试听文字、语速、情绪不提高版本且保留旧试听；旧客户端结果投影还可能改写 locked profile。后端真实PG3项失败：同版本修改上述字段后，旧试听通过 accept_stale=True 仍被采纳，均实际返回200。
- 前端把模型、音色ID、试听文字、语速和情绪共同视为试听身份；改变后提高声音版本、清除旧试听/生成关联，保持原音频素材不删除。空白规范化不制造新版本。已锁定版本不接受晚到客户端试听投影，正式路径仍是服务端候选明确采纳。
- 服务端采纳时使用原任务已绑定的 collaboration_history 快照与当前 profile 比较，不信任请求中 identity 字符串；文字/语速/情绪变化不能靠 accept_stale 绕过。纯卡片改名仍可显式采纳旧候选。
- 新试听入队后的实际平台冻结参数必须与保存的语速/情绪一致，不能只校验音色ID。已有提交的重试路径与旧任务输入/摘要不改写，追加幂等测试确认返回同一任务。
- 对带生成试听的 profile，锁定时须有对应本角色的明确采纳记录、匹配音频和原试听身份。修改文本后强行锁定旧样本会拒绝；恢复原设置后可以锁定。未保存的编辑会禁用UI锁定按钮。历史只有预设、没有试听素材的 profile 仍保持原兼容行为；本批不声称已建立上传样本确认流程。

初步候选联合回归10 passed；最终 `tests/test_voice_identity.py tests/test_p5_object_candidates.py tests/test_p5_object_transactions.py tests/test_p4_submission_execution.py tests/test_upstream_hc_dialogue.py` **54 passed，196.71秒，exit0**。前端 `npm test` **241 passed / 0 failed / 0 skipped，1346.52ms**；最终防御性文本归一化后新增前端专项 **5 passed，129.02ms**，最终 `npm run build` **tsc/Vite exit0，Vite 7.61秒**，既有大chunk警告保留。联合收集之后追加的真实PG重试专项 **1 passed，5.28秒**，前述中间测试不与最终结果简单相加。无新增依赖、数据库迁移、后台页面或配置，没有真实付费请求、部署、用户服务重启或用户数据库清理；PG夹具只释放自己生成的隔离测试库，未运行本批浏览器 E2E 或全量后端。

`git diff --check`通过。仅交付集成分支，原master仍为eeb7a4f且工作区干净；不发送ChatGPT审核。`READY_FOR_REVIEW`为开发交付标识，不代表外部验收PASS。

## UPSTREAM-SYNC-12：已确认角色音色样本用于视频生成

按冻结上游 `10acb73`、`4e86bac`、`77b99d7`、`dcee553` 的相关需求适配，不整体复制这些提交。早期上游说明仍将幻场标为不支持，但冻结代码已实现；本批以实际冻结协议为依据。命名音色库、状态继承和外部音频上传确认仍未完成，不能以本批代替这些后续需求。使用说明见 [音色样本](../voice-samples.md)。

- 形成“生成试听 → 任务中心明确采纳 → 锁定声音参考 → 视频生成”闭环；历史已锁定试听可一次性明确确认，不能借此改写其他锁定字段。派生音色版本清空引用，不删除原媒体。仍使用原对象负责人、revision、历史任务快照及采纳权限。
- 新网页作品显式选择音色样本；旧API省略字段与旧文档保持完整对白。支持本集默认和镜头覆盖。样本模式必须显式多模态且平台已发布能力，否则拒绝，不自动切模型或减少参考。
- 服务端预览、单次、精确批量共用规范编译：只取本镜说话角色、按首次出现编号、同素材去重但保留角色映射。只参考音色，不混音、不播放样本文字、不套用样本情绪、不延长镜头。真实8秒样本测试保持4秒提交。
- MP3/WAV、大小、时长、完整解码、作品归属及摘要检查；超限拒绝不截断。方舟数据URI、幻场短期签名URL、RunningHub上传，冻结引用与参数，远端handle恢复只查询。未调用付费服务，未改现用平台模型配置。
- 共享音色变化在同作品各EP分别计算依赖，只更新相关视频/下游生成版本；他人正文、分配和租约保留，旧保存409，跨EP请求仍404。额外真实PG复现：回收站中的EP引用导致确认声音404“项目不存在”。修复仅内部派生失效的锁定路径，保持回收站内容及恢复后的失效状态，不把该内部路径开放给用户写入。
- 已有前端编辑器显示对白模式、当前声音参考版本和缺失警示；任务详情显示冻结角色到音频映射。无新增依赖、迁移或后台页面，仅扩展既有JSON数据及平台公开能力定义。

实际测试过程：旧音色/动作回归38 passed；初次新增专项6 passed/4 failed，分别是单次测试漏传与已保存预览相同的prompt、样本排除断言误包含在测试台词中、错误码断言及误用公共素材返回的path，修正测试后10 passed/1 failed（无生成结果的节点应检查generation_revision而非stale=true）。扩展2.0及模式覆盖后15 passed。回收站分集专项先实际失败1项（404），修复后与生命周期联合23 passed。上述中间结果不相加为独立用例数。

联合回归：`tests/test_voice_samples.py tests/test_voice_identity.py tests/test_motion_references.py tests/test_p5_object_transactions.py tests/test_p5_object_candidates.py tests/test_p5_canonical_integration.py tests/test_p4_model_foundation.py tests/test_p4_submission_execution.py tests/test_project_setup.py tests/test_upstream_hc_dialogue.py tests/test_hc_atom.py tests/test_volcengine_ark.py tests/test_runninghub.py tests/test_video_dialogue.py` → **203 passed，533.41秒，exit0**。此收集使用音色专项最初11项及修复回收站前代码；回收站修复与追加2.0/默认模式边界由最终 `tests/test_voice_samples.py tests/test_p5_lifecycle.py` **23 passed，114.88秒，exit0** 覆盖（收集音色16项、生命周期7项）。真实PG夹具和本地FFmpeg，商业请求均Mock。

追加的最终边界/供应商复测 `tests/test_voice_samples.py -k 'protection_total or worker'` **6 passed / 11 deselected，44.07秒，exit0**；覆盖真实参考素材删除保护（409，未删除）、跨作品素材拒绝、两份各8秒样本超15秒总量拒绝、伪造时长元数据下真实损坏WAV仍拒绝解码，以及五组供应商提交/恢复（含2.0先拒绝仅音频、再加视频参考提交）。这些测试与前述联合有重叠，不累计为独立测试数。

前端 `npm test` **244 passed / 0 failed / 0 skipped，1443.37ms**。最终 `npm run build` **tsc/Vite exit0，Vite8.01秒**，既有大chunk警告保留。computer-use技能用于隔离实际组件检查：版本不匹配显示缺失，切完整对白/样本不丢台词和动作绑定，忙碌时可只读预览且不增加修改次数；截图确认控件可读、提示折行。此页无API代理/业务数据库，不冒充完整业务E2E。已关闭本轮测试页及其Vite进程，没有停止用户或历史实例。

未跑全量后端或真实付费供应商；不声明音色相似度/口型质量通过。原master仍为eeb7a4f且工作区干净；本批不合并master、不部署、不发送ChatGPT审核。`READY_FOR_REVIEW`为开发交付标识，不代表外部PASS。

## UPSTREAM-SYNC-13：命名音色库与角色状态继承

对照冻结上游 `0866461` 的使用需求实现。基础角色保存不可变的命名锁定版本及明确默认；新试听草稿保留旧默认。状态默认继承，需要时只保存父角色锁定版本指针，不复制上游的整份试听记录。状态选择由状态负责人保存，基础音色库仍由基础角色负责人维护，不扩大权限。使用说明见 [音色样本](../voice-samples.md)。外部上传音频及权利确认没有在本批实现。

- 前后端统一解析基础角色默认、明确状态及镜头隐式状态；多个状态无法确定说话者时拒绝。样本预览、单次/批量视频、完整对白、准备状态及明确采纳都使用有效版本，避免同版本号但不同来源的对白误用。
- 服务端拒绝伪造、覆盖或删除锁定历史；新版本仍须明确采纳试听再锁定。候选绑定状态和父角色对象revision，选择变化后的旧结果不能靠accept_stale越过校验。没有增加对象种类或复制可伪造的试听确认记录。
- 基础/状态族在原事务内锁定，跨EP只对实际声音签名变化的镜头做派生失效；固定旧版本的状态不受基础默认切换影响，新草稿不让旧默认失效。原负责人、分配、租约和正文保留，旧保存仍409。
- 实际面板提供版本名称、默认选择、状态继承/固定、当前参考试听与对白入口。未保存声音草稿禁止切默认，名称保存不强制重做相同参数的试听。生成按钮标明实际默认版本。

测试过程：初次联合因video_dialogue新增表达式漏括号出现18 failed / 12 passed，118.04秒；修正语法后compileall通过。初步库专项8 passed，50.42秒；扩展跨EP精准失效及完整对白采纳后，最终 `tests/test_voice_library.py` **10 passed，74.29秒，exit0**。

联合 `tests/test_voice_library.py tests/test_voice_identity.py tests/test_voice_samples.py tests/test_p5_object_candidates.py tests/test_p5_object_transactions.py tests/test_p5_canonical_integration.py tests/test_p5_lifecycle.py tests/test_video_dialogue.py tests/test_motion_references.py` → **109 passed，451.96秒，exit0**。该次收集库专项最初8项，追加2项已在上述最终10项运行中通过，不累加为独立测试数。使用真实隔离PostgreSQL、本地合成WAV/FFmpeg和假任务结果，无商业调用。

最终补齐历史null默认值与服务端一致的兼容检查后，`npm test` **250 passed / 0 failed / 0 skipped，1283.15ms，exit0**；`npm run build` **tsc/Vite exit0，Vite7.04秒**，既有大chunk警告保留。computer-use用于实际组件隔离交互：状态继承→固定V2，基础默认切V2再V1但状态不变，新草稿V3不改有效声音，未保存名称禁用默认选择，保存后恢复，状态重新继承回V1。页面无API代理/业务库，不等同登录业务E2E；已关闭本批自建浏览器页及Vite，未停用户服务。

无新增依赖、数据库迁移、配置或后台页面，只扩展既有JSON字段及编辑面板。未跑全量后端、真实付费供应商或完整业务浏览器E2E，不声明音色相似度/口型质量通过。仅交付集成分支，不合并master、部署或发送ChatGPT审核。`READY_FOR_REVIEW`为开发交付标识，不代表外部PASS。

## UPSTREAM-SYNC-14：上传声音与生成试听统一音色库

按冻结上游 `00f2640` 及 `docs/voice-reference-upload.md` 的需求适配。使用同一角色声音库与状态指针，不复制单机整份项目PUT、自动采纳或SQLite实现。协作版原本没有上传来源确认闭环，本批是功能补齐，不将其描述为上游bug在此复现。说明合并到 [音色样本](../voice-samples.md)，没有增加架构文档。

- 无语音模型时仍可选择上传声音。复用素材上传，支持本作品已有音频，用户明确声明使用权；系统上限30 MB/120秒、真实MP3/WAV纯音频和完整解码。视频提交另受模型15 MB/最少2秒/数量/总时长限制，不截断或训练声音。
- 独立素材确认只保存服务端时间、声明人、用户声明标记及文件摘要，不改变角色、不产生TTS任务、不自动锁定。已有声音确认记录重复使用不改时间或覆盖hash；文件变化要求重新上传。声明不是平台权利核验。
- 文件校验在事务外，落库前复核成员访问、作品归属和删除状态。上传来源必须先保存草稿，再明确锁定；沿用卡片负责人、revision、锁定历史、默认/状态选择、跨集派生失效及素材删除保护。锁定后文件被改动在视频预览/提交前拒绝，执行前仍沿用冻结摘要复核。
- 上传来源没有TTS音色注册，服务端与UI阻止逐句/批量合成和生成试听，不自动回退；视频样本通过已有方舟数据URI、幻场短期签名URL、RunningHub上传协议发送。现有远端任务仍只查询，不重传。预览/任务详情显示来源、角色、版本、编号与时长。
- 新增source/description JSON字段、上传校验参数与素材确认路由，不新增依赖、迁移、模型配置或后台页面。历史无source声音按生成试听解释，保留其原编译字段形状和幂等摘要，不回写旧任务。

实际验证：首轮上传专项 **9 passed，39.23秒**；扩展后联合 `tests/test_voice_uploads.py tests/test_voice_library.py tests/test_voice_identity.py tests/test_voice_samples.py tests/test_p5_object_candidates.py tests/test_p5_object_transactions.py tests/test_p5_canonical_integration.py tests/test_video_dialogue.py` → **85 passed，374.88秒，exit0**（当时收集上传13项）。包含真实隔离PostgreSQL、上传/已有素材、校验不写角色、负责人/跨作品边界、晚到TTS候选拒绝、状态跨EP引用、三供应商Mock请求及远端恢复不重传；模拟供应商返回有意设置为mock-terminal，仅证明协议和恢复，不冒充真实供应商生成成功。

追加撤权与真实MP3测试初次 **1 failed / 1 passed，11.25秒**：权限已按项目既有规则返回404，测试误预期403；修正断言后 **2 passed / 13 deselected，9.62秒**，确认撤权后不保存声明。之后补齐锁定后磁盘变化与不能跳过草稿，最终 `tests/test_voice_uploads.py tests/test_voice_samples.py` → **34 passed，187.57秒，exit0**（上传17项、样本17项）。最终来源字段兼容及幂等重试专项 **2 passed / 17 deselected，18.28秒**，断言原input/input_hash不变。上述运行有重叠，不相加声称独立测试总数。

最终前端 `npm test` **255 passed / 0 failed / 0 skipped，1581.39ms，exit0**；`npm run build` **tsc/Vite exit0，Vite8.59秒**，既有大chunk警告保留。computer-use用于实际组件隔离页面：无语音模型可选上传，声明初始未勾选时禁用提交，模拟失败不保存，有效校验后修改次数仍0，试听目标正确，保存后是草稿，明确锁定才进入默认，新草稿保留旧默认。检查截图后修正复选框布局、区分草稿与当前默认提示。浏览器使用模拟素材确认/试听回调，不等同真实文件选择器、音频播放或登录业务E2E；真实multipart上传、解码及落库由PG测试覆盖。已关闭自建测试页及Vite，未停用户或历史服务。

`git diff --check`通过，原master工作区干净且HEAD仍为eeb7a4f。未跑全量后端、真实付费API或完整业务浏览器E2E，不签发声音效果/口型质量结论。只提交推送协作版集成分支，不合并master、不部署、不发送ChatGPT审核。`READY_FOR_REVIEW`仅为开发交付标识，不代表外部PASS。

## UPSTREAM-SYNC-15：动作参考分类、可读预览与依赖刷新

对照冻结上游 `117f843`、`c3cad55`、`fd9a3da`、`47e0409`、`b21aa66`、`0a3beda`、`46752db`、`aa4e955` 的参考展示需求。`4f9faaa` 的忙碌时只读预览已有等效实现，继续验证并保留。没有移植单机供应商设置、任意素材回退或自动采纳；批量工具栏和批量审核弹窗属于后续交互，不计入本批。

- 新增“动作参考”素材分类，上传默认归类，素材库可重新分类；选择器只列原始动作参考视频，同时保留历史绑定和失效占位，排除去声衍生视频。剪辑素材适配器已有此标签，不重复修改。文件上传晚到且镜头/作品/绑定已改变时，保留原作品素材但不覆盖当前绑定。
- 区分电脑上传与已有素材，标明白模支持；视频工作区参考设置放到镜头描述区下方。最终预览默认折叠，可直接刷新打开，忙碌时仍可读取。移除编辑区重复成功声音提示，保留缺失样本警示，声音来源/版本/时长留在最终预览内。
- 提示词分段、换行和紧凑编号；图片缩略图及音视频编号按清单准确 assetId 打开居中预览，关闭恢复键盘焦点。只使用认证素材接口，未生成图片/未来混合对白不冒充已有媒体，原始提示词和完整参数仍保留。没有添加远端或任意当前素材回退。
- 修复前实际组件隔离页复现：切换样本版本为未确认，状态提示变化而预览仍是“编译次数1”。修复后共享声音、模型、素材目录、图和镜头等依赖纳入预览标识，变化立即隐藏旧结果，展开时重新请求。共享依赖仍使用服务端保存版本，不以客户端替代授权数据；折叠时不请求。

实际测试：`tests/test_motion_reference_assets.py tests/test_motion_references.py` 首轮 **1 failed / 32 passed，132.56秒**，失败为测试错误地从公开响应读取磁盘path（该字段本就不公开）。改为直接读取测试库后分类/ACL专项 **1 passed，8.11秒**。32项原动作参考回归已通过；分类专项验证上传、已有素材归类、只读预览等价、原字节和项目/任务不变、viewer禁止写、跨作品和撤权后拒绝。使用真实隔离PostgreSQL、本地合成MP4/FFmpeg及Mock，不调用商业API。

最终 `npm test` **260 passed / 0 failed / 0 skipped，1308.75ms，exit0**；`npm run build` **tsc/Vite exit0，Vite7.50秒**，既有大chunk警告保留。computer-use技能用于实际组件浏览器交互：运行中打开预览、依赖改变后编译1→2、素材移除后3且移除图片按钮、折叠改变依赖不编译、再次刷新为4，本地修改次数始终0。合成图片实际显示且居中；静音WAV播放器显示但没有声学/播放质量结论；历史绑定+专用分类可见，普通/衍生视频排除。页面没有业务API代理或数据库，不等同完整登录E2E。已关闭本批浏览器页及专用Vite，保留用户/历史服务。

无新增依赖、数据库迁移、配置或后台页面；只是扩展既有分类值、编辑组件与只读展示。未跑全量后端、真实供应商或完整业务浏览器E2E。原master工作区干净、HEAD仍eeb7a4f；仅提交/推送集成分支，不合并、部署或发送ChatGPT审核。`READY_FOR_REVIEW`为开发交付标识，不代表外部PASS。

## UPSTREAM-SYNC-16：直接编写正式剧本与原审核闭环

对照冻结上游 `13939a82` 与其 `docs/direct-script-workflow.md`，完成手工直接编写这一可独立使用的路径。该提交的 AI 辅助创作、前集上下文及统一新增集入口仍未全部完成，继续列入后续队列；不以手工路径替代完整需求。没有移植 `4b474aa` 单人免审核，也不恢复 Worker 自动回写。

- 新建网页默认 direct 并进入剧本，adaptation 仍显式可选；旧 API 未指定时保留改编语义。新增集继承最近未删除集的规格和起点。实际集与规划集联合列出，无规划集可读写。
- 正文仍使用 episode_scripts、原负责人/代际/revision与明确审核；批准前不能直接批准，非管理者不能批准他人成果，旧保存409。正文读取投影只有一个，没有创建第二份主源。直接正文的独立来源由服务端初始化，保存接口不允许客户端伪造元数据。
- 直接手写不随无关改编更新过期，真实引用的章节变化仍标过期；明确采纳改编结果后恢复 adaptation 来源及依赖。生成只产候选，采纳前原正文不变。
- 剧本室无需 plan 才渲染，正文前移、无已批准规划时不显示可用生成入口；空批量操作栏隐藏。沿用草稿存储与切集隔离。浏览器实际发现批准后侧栏仍显示旧草稿状态，改用最新已接收剧本状态；正文未保存时仍有明确未保存提示。

实际验证：功能缺口红测 `tests/test_direct_script_manual.py` **2 failed / 1 passed，5.29秒**，直接创作字段被既有严格接口422拒绝。实现后首轮 **3 passed，11.56秒**。联合 `tests/test_direct_script_manual.py tests/test_adaptation.py tests/test_p5_owned_content.py tests/test_p5_object_candidates.py` → **32 passed，115.72秒，exit0**。追加“直接→明确采纳改编”后，`tests/test_direct_script_manual.py tests/test_p5_relation_candidates.py` → **12 passed，62.71秒，exit0**（手工专项4项）。运行有重叠，不相加冒充独立总数。使用真实隔离PostgreSQL与无网络模拟文本输出，不调用商业模型。

前端 `npm test` **262 passed / 0 failed / 0 skipped，1403.13ms**；最终构建结果见本轮提交记录。computer-use用于实际组件隔离页：默认直接新建、无规划正文编辑、切EP02再返回保留EP01未保存文本、保存为草稿→提交审核→批准后出现正确本集分镜入口、再次编辑禁用入口。页面仅内存Mock，无业务库/Provider，不等同登录业务E2E；创建路由与权限由上述真实PG覆盖。已关闭专用测试页和本批Vite，未停止用户或历史服务。

最终 `npm run build` **tsc/Vite exit0，Vite7.02秒**，既有大chunk警告保留。无新增依赖、数据库迁移、后台页面或平台配置。未跑全量后端、真实付费模型、完整业务浏览器E2E或 AI 辅助创作专项。原master仍eeb7a4f且工作区干净，仅提交推送协作集成分支，不合并master、不部署、不发送ChatGPT审核。开发交付标识 `READY_FOR_REVIEW`，不代表外部PASS。用法与未完成范围见 [直接剧本](../direct-script-workflow.md)。

收尾补充：显式传入空创作起点不能静默继承；追加该校验后手工专项最终 **4 passed，15.25秒，exit0**。

## UPSTREAM-SYNC-17：直接剧本 AI 辅助、冻结依赖与明确采纳

接续上下文准备提交 eed9301，已接通 `/episode-scripts/{no}/assist`、原持久任务、原候选采纳和剧本室折叠入口。无需改编规划，仍限当前负责人和有效 revision/assignment_epoch；采用平台文本模型，不开放用户 Provider/Key。仅生成目标集，最近三集、当前正文、Bible/当前视觉版本及显式原著版本冻结为依赖。通用任务接口也重建服务端提示词；迟到结果不得覆盖变更后的正文，`accept_stale` 不绕过本路径依赖校验。已有采纳视频时保护剧本，采纳后仍为草稿并需审核。原改编生成分支的批准条件未放宽。

同集排队/运行任务防重复，覆盖改编与直接生成共用节点；相同提交 ID 同输入回放原任务。前端未知网络结果重试保留提交 ID，成功后的明确再次生成用新 ID。依赖只在提交/采纳短事务内锁定，正在保存的参考对象通过 NOWAIT 返回409，不在模型执行期间持锁。

实际测试：首次 AI 专项 4 passed / 1 failed（12.54秒），失败是成片夹具使用不存在的素材，被原素材归属校验422正确拒绝；改为隔离库规范对象夹具，不修改该安全校验。之后上下文/候选联合20 passed /66.96秒，扩展专项8 passed /22.42秒。最终联合首跑28 passed /1 failed（99.16秒），新增原著依赖SQL错误地直接读取章节的 production_id；已修正为关联 source_documents 并过滤回收站。修正后同一完整命令 `pytest tests/test_direct_script_assist.py tests/test_direct_script_context.py tests/test_direct_script_manual.py tests/test_p5_relation_candidates.py -q`：**29 passed /97.97秒**。包括真实PG两请求竞争仅一个入队、参考行锁冲突409且释放后采纳成功、负责人及接管、正文/前集/显式来源变化、通用入口伪造提示词、成片保护、无自动写入、明确采纳为草稿。模拟 Worker 文本输出，不声称真实供应商联调。

`npm test` **263 passed /0 failed /0 skipped，1544.61ms**；最终 `npm run build` tsc/Vite exit0，Vite **9.40秒**，原大chunk警告保留。computer-use 实测内存Mock组件页：未保存正文禁用AI；保存后提交1次，正文保持；EP02要求为空，切回EP01保留其正文和要求。真实组件测试不等同登录后的业务E2E。已关闭本批临时页和Vite，不动用户/历史实例。原master eeb7a4f工作区干净；协作版7878端口变更在集成分支，尚未部署或重启。

无新增依赖、数据库迁移、平台配置或后台页面。未运行全量后端、真实付费API、完整业务浏览器E2E。仅提交/推送 origin 集成分支，不合并master、不发送ChatGPT审核。开发交付 `READY_FOR_REVIEW`，不是外部PASS。统一新增集/可选原著导航及其他冻结需求仍未完成。

## 后续队列

UPSTREAM-SYNC-18（统一新增集入口）：对照冻结上游 EpisodeSetupDialog，新增共享原生模态对话框，作品列表和剧本室同入口；填写名称和创作起点后分别进入 script/source。保留 prepareProjectSwitch，不照搬上游先自动保存的行为；取消及空名称不提交，正在创建不能重复点击/退出，创建成功即关闭，刷新导航错误不保留重复创建按钮。集号提示取现有最大值加一，实际分配仍由服务端负责。没有后端规则、依赖、迁移或后台页面变化。

验证：npm test 265 passed /0 failed /0 skipped，1399.95ms；tsc/Vite build exit0（Vite7.36秒，原大chunk警告保留）；真实隔离PG手工/分集回归4 passed /16.00秒。computer-use 实际组件页验证新增EP03、默认direct、空名称错误、取消后未保存正文保持、选择adaptation并收到单次Mock新增请求；无业务库/AI调用，不冒充完整登录E2E。已关闭本批临时页和Vite。统一入口已完成，可选原著导航等后续项继续核对。

用户新增运行要求：阶段完成后即绑定协作版7878，不再无限延期。当前7878无监听，7868确认为单机版；当前进程/User/Machine均无 OVC/MVC 环境配置，原工作目录data未找到运行身份记录，55438只列出保留的ovc_test验收库。未擅用旧测试库，未停止单机或历史实例；已向用户询问独立本地使用库或已有配置文件位置，运行切换待此数据选择。端口配置已在1869b4d提交，不把配置已改等同服务已启动。

运行补充（用户授权全新开发数据自行决定后）：已建立独立本地 PostgreSQL 55440 / ourvideocreator_dev，应用现有0001–0007迁移并初始化新管理员；不复用或迁移验收库。Web运行910ae35集成版本，仅监听127.0.0.1:7878，媒体与凭据独立保存在本机OurVideoCreator-dev目录。受应用目录映射影响，实际路径为 `%LOCALAPPDATA%\Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\OurVideoCreator-dev`；Start-Local.ps1已规范化媒体路径，通过原实例身份校验。数据库密码、管理员初始密码和平台主密钥随机生成并用Windows用户加密存储，不进入Git；初始化密码临时文件已删除。只启动Web，没有Worker、Provider配置或付费调用；普通再次启动复用同一进程，后续阶段可用本机启动脚本的-RestartWeb仅更新Web。

实际检查：health status=ok且实例ID匹配、首页HTTP200、管理员登录成功（platform_admin）、作品列表为空、测试登录退出成功。浏览器已显示7878个人账号登录表单；未在浏览器输入密码。7868仍有单机服务监听，本轮未停止/重启它或任何历史测试数据库。初始化过程中只中止了本轮自身的冗余安装包复制、等待交互密码的initdb以及已完成pg_ctl但等待子树的启动包装进程；新数据库数据保留，没有清理历史资源。运行目录和本机启动脚本不提交到Git。

直接剧本 AI 辅助准备（尚未完整交付）：新增 `backend/direct_scripts.py` 内部只读上下文/指纹/提示词构造，沿用正式剧本与协作对象聚合读取。当前正文完整保留，前集按最近三个有效集排序并截取各自末尾 8000 字符；视觉描述从当前视觉版本读取，避免照搬上游卡片字段而漏掉协作主源。未接入 HTTP、队列、Worker 或候选采纳，不声称功能已可用。真实隔离 PostgreSQL：上下文专项首轮 6 passed / 5.23 秒；补充主源/过期卡验证后，与手工剧本联合 11 passed / 22.46 秒（上下文 7、手工 4）。测试禁止商业网络，无新增依赖或迁移；未运行全量后端或浏览器 AI E2E。后续继续接通任务准入、并发依赖校验、明确采纳与网页入口。

上方“AI辅助准备”段为 eed9301 的历史快照，已由 SYNC-17 完成接入；统一分集入口已由 SYNC-18 完成，7878运行状态以上方运行补充及后续批次为准。

## UPSTREAM-SYNC-19：直接创作的可选原著导航

直接创作时将原著资料/改编策划收进“原著改编（可选）”选择入口；改编创作保持完整阶段栏。采用原生选择框，避免横向滚动栏内展开菜单被裁剪；复用原导航回调，不删除URL或放宽剧本审核。无后端、依赖、数据库迁移或后台页面变化。

实际验证：npm test **266 passed /0 failed /0 skipped，1418.77ms**；tsc/Vite build exit0，Vite **7.47秒**，保留已有大chunk警告。computer-use在内存Mock实际组件页验证 source→adaptation→script 三次导航及入口选中状态；没有业务库/供应商调用，不等同登录业务E2E。已关闭本批临时页及Vite。本批纯前端未额外运行后端全量或PG测试。

前十九组已完成各自验证；整体同步仍未完成。后续还须核对章节/长篇扩展与连续性、视觉历史复用/恢复及剩余交互，并逐项核对冻结清单。必须保留timeline单主源、租约与草稿。单机免审核/覆盖冲突草稿不照搬；运维、付费和延期平台不恢复。未合并master，不发送ChatGPT审核。每批完成后仅更新独立7878 Web。

## UPSTREAM-SYNC-20：向当前原著追加章节

需求来源12b6608。现有协作接口红测返回405，确实没有追加导入能力。新增原著路径下 chapters/import，复用拆章逻辑；保留现有原著名称/类型/元数据、章节正文和归属，新增章节由操作者负责。原著行锁与手工新增共用，章号包含回收站占位，拒绝跨作品、已删除原著和只读成员写入。未引入上游 source_id 请求体别名，目标只取URL，避免两处目标歧义。

网页已有原著时默认追加，“更多原著操作”仍可创建/导入另一部；首个数据加载完成前禁止写入入口。选文件前冻结作品/原著/草稿代际，读文件及返回后校验作用域，用即时互斥避免重复点击提交。不自动保存旧章节；刷新通过既有OwnedContentDrafts保留本地草稿。未新增跨请求导入幂等协议；网络结果不明时不自动重试，用户再次导入同一文件仍会追加，不能将前端互斥称为服务端内容去重。

实际验证：红测1 failed（405，2.95秒）；实现后原著库6 passed（22.21秒）。协作扩展首轮2 passed /1 failed（夹具没有admin_id字段，11.74秒），改为原认证status读取测试管理员ID。最终真实隔离PG联合 tests/test_source_library.py + tests/test_source_append.py **9 passed，34.64秒**，覆盖并发追加/手工新增、旧章节不变、新归属、viewer拒绝、跨作品拒绝、回收站恢复章号、删除原著拒绝。npm test **268 passed /0 failed /0 skipped，1708.40ms**；tsc/Vite build exit0，Vite **7.58秒**，原大chunk警告保留。草稿保留动态测试及入口作用域静态测试通过；本批未运行浏览器上传E2E、全量后端或真实供应商。无新增依赖、迁移、配置或后台页面。

仅交付本批功能，不代表章节提取去重、长篇扩展或整批冻结上游全部完成。后续继续其余清单，保留master与历史实例；独立7878 Web按用户要求更新。

## UPSTREAM-SYNC-21：章节提取活跃任务去重

需求来源11bc482。真实PG红测确认：同一章节在另一EP用新submission_id可重复入队（应409，实际200；1 failed，4.27秒）。修复放在create_job_record的原子准入事务、原幂等回放之后，因此专用/通用入口及跨集均覆盖。新重复请求409，原同输入同标识仍回放；不照搬上游直接返回别次提交的任务，避免混淆模型、输入或负责人。批次冲突整事务回滚，取消/结束后可明确再次生成。

新增只读GET source-extractions，只返回获授权作品的活跃章节ID，不返回别人成本/提示词或凭据。原著页每5秒查询、卸载停止，未确认状态禁用提交、所选活跃章节显示正在提取；成功提交立即合并本地活动状态，忽略提交前发起的迟到查询。不改正文、不自动采纳或自动保存，不新增Worker或任务平台。

验证过程：初步原著库7 passed（22.40秒）；扩展联合首轮15 passed /1 failed（69.31秒），失败是旧并发采纳夹具同时排两个提取任务，被新规则正确拒绝。改为顺序完成生成但不采纳，再以两个同版本候选竞争采纳，保留200/409及单收据断言。读取权限专项1 passed（4.56秒）。npm test **269 passed /0 failed /0 skipped，1496.63ms**；tsc/Vite build exit0，Vite **6.93秒**，原大chunk警告保留。本批未运行浏览器E2E、全量后端或真实Provider；前端新增静态作用域/迟到查询保护断言，不冒充浏览器交互测试。无新依赖、迁移或后台页面。

最终联合 `tests/test_source_library.py tests/test_p5_relation_candidates.py` **16 passed，73.97秒**。覆盖跨EP/通用入口防重复、幂等回放、取消后重提、混合批次全回滚、两请求竞争仅一个入队及原候选版本/负责人/明确采纳回归。仅提交推送集成分支并更新7878，不合并master。长篇扩展/连续性及其余冻结清单仍待完成。

## UPSTREAM-SYNC-22：手工分集规划的失效范围

需求来自4dfb676的change-scope部分，对照冻结最终版本确认。真实PG红测证明追加EP03会将已批准的全局策划降为draft（1 failed，5.66秒）。新增adaptation_change_scope区分共享内容与具体集：纯增集/单集修改保留全局批准和未变集状态，新/变集强制draft；故事骨架、商业策划、全局画幅/时长/平台及减集仍使全局draft。状态字段不能由手工保存晋升或伪造降级。保留manager权限与production revision检查。

_stale_scripts增加episode_nos筛选，仅锁定并更新受影响的已审核关联剧本；chapter_ids来源失效、直接剧本adaptationLinked=false排除规则保持。没有新增主源、自动采纳或批量跨负责人正文写入。全局AI候选仍沿用保守整体失效，不在本批悄悄改变。

实际验证：`tests/test_adaptation_scope.py tests/test_adaptation.py tests/test_direct_script_manual.py` **13 passed，41.14秒**（当时scope专项1项）；随后扩展scope专项最终 **2 passed，8.18秒**。中间两次专项各1 failed/1 passed，分别因测试将API revision混入严格bundle、删除计划但未同步总集数，被既有校验拒绝；修正测试输入，不放宽业务校验。验证追加两集旧正文/状态/revision完全不变、只改EP02只使EP02过期、全局前提使EP01过期、状态伪造忽略、全局规格/减集识别。上述次数有重叠，不加总冒充独立覆盖。

本批纯后端，未额外运行前端构建/浏览器E2E、全量后端或真实供应商。无新增依赖、迁移、配置或后台页面。只提交推送集成分支，按要求更新独立7878 Web。**这只是长篇扩展的一部分**：已有成片的服务端保护、单集规划生成及候选采纳、单集审核入口、连续性上下文和相关UI尚需继续完成；不将4dfb676/87c470a整项标完成。

## 用户运行数据切换：复用旧验收数据

用户随后明确要求改为复用旧验收数据。只读核对55438两库：33184库与FINAL浏览器manifest、3个媒体文件匹配，含5账号/1作品/1集/3素材/4已成功任务；另一37772库仅1账号且没有素材和任务。选择较完整33184库，pg_dump快照恢复为独立55440/ourvideocreator_acceptance，并复制配套媒体到运行目录acceptance-media，逐文件SHA256一致；不修改旧验收原库，保留ourvideocreator_dev空开发库和原媒体目录。

本机Start-Local.ps1改用该副本，7878当前运行096c570代码、PID31552、实例ovc-a4e15bde7bcf478370d4a38ee4a341fe。切换前首次停止因未提供旧库身份配置而安全拒绝，端口冲突也安全拒绝；随后加载旧库身份并通过原停止脚本仅停止旧Web，成功启动新身份。health ok，原验收管理员密码与已知测试夹具离线验证一致后仅DPAPI保存本地，不改密码；HTTP登录成功、platform_admin、作品数1。Show-Login.ps1已指向验收账号凭据，不再显示空开发库账号。7868 PID34128未动。

旧供应商为验收配置，未证明旧加密主密钥可恢复或可真实调用；没有启动Worker或付费API，不宣称生成能力可用。账号/数据库密码/会话/密钥不进入Git。运行数据及本机辅助脚本不提交。后续批次继续以此验收副本更新7878。

## UPSTREAM-SYNC-23：已采纳视频的改编保护

接续4dfb676保护需求。protected_episode_nos从read_project_state协作正式投影判断视频assetId，不读取单机旧document作为主源。调用者持production锁；写路径对项目和协作对象使用SHARE NOWAIT，避免与对象保存的反向锁等待。手工修改受保护集/全局内容409，未完成兄弟集仍可修改；整体审核状态变更、整体生成（含通用入口）及迟到整体候选采纳也拒绝。没有视频绑定的生成候选不作为已完成成片。

真实隔离PG：scope+relation-candidates联合 **12 passed，62.93秒**；补充整体审核及项目行锁冲突后scope专项 **3 passed，13.15秒**。测试使用规范协作节点与隔离DB内合成已采纳assetId，验证正式投影而非真实视频生成。覆盖未保护原流程、管理权限、生成后出现视频再采纳的拒绝（含accept_stale）、全局/受保护集修改失败不写入、其他集可保存、NOWAIT409且版本不变。没有付费调用。最后权限检查顺序调整为先manager授权、再保护读取，保持授权优先。

本批无前端变化，未跑浏览器E2E、全量后端或额外前端构建；无新依赖、迁移或后台页面。仅集成分支交付，7878仍使用验收副本。长篇能力仍未全部完成：**单集规划审核/生成及候选采纳入口尚未接通**，已有成片时不能借整体审核代替；下一批必须继续补齐这一闭环，不能以保护开关代替完整需求。

## UPSTREAM-SYNC-24：单集规划独立审核

接续4dfb676。原transition_adaptation增加明确episode_no分支，复用manager授权/production revision/短事务及成片保护；单集提交校验正文要点和原著引用，批准必须先review。只改目标计划状态，其他分集和全局策划保持；不存在目标404、旧revision409、非manager403。全局审核原分支继续保留，不能绕过已采纳视频保护。

改编页增加本集提交审核/批准按钮，保存后才允许审核；使用已保存内容指纹阻止有本地修改时提交，忙碌期间fieldset禁用输入，避免请求回执覆盖同期输入。这不等于已经修复整个改编页跨作品/自动刷新草稿同步，后续仍需按62d4b09/44相关清单核对。没有加入免审核或AI自动回写。

初步scope真实PG **3 passed，13.87秒**。前端 **270 passed /0 failed /0 skipped，1568.63ms**；tsc/Vite build exit0，Vite **10.30秒**，保留既有chunk警告。前端新增静态入口/保存版本/忙碌保护断言，未运行浏览器完整E2E；未运行真实Provider或全量后端，无依赖/迁移/后台页面新增。独立单集AI规划生成及候选采纳仍未完成，下一步继续此闭环。

最终 `tests/test_adaptation_scope.py tests/test_adaptation.py` **12 passed，35.52秒**，包括新增manager/其他角色验证，以及已成片EP01保持、EP02独立review/approve、禁止直接批准/旧版批准、错误集404。只推送集成分支并更新7878验收副本。

## UPSTREAM-SYNC-25 准备：单集规划契约与连续性上下文

对照冻结最终13939a8中4dfb676/87c470a的合成要求，新增内部episode_plans模块：严格单集JSON Schema/结果校验、目标集号与固定时长、仅引用快照内章节，结果为draft、不写业务。continuity_context读取正式剧本与协作视觉投影：紧邻前集全文、更早集末1500字及截断标识；区分已成片/已批准/保存/仅规划证据，未成片过期正文不作为可靠来源；包含assignment_epoch，锁定视觉来自currentVersion spec，忽略废弃卡。兼容没有改编plan的已存在直接创作前集，不遗漏实际正文。

实际测试 `tests/test_episode_plan_contract.py`：首轮14 passed /1 failed（5.66秒，测试误用projectId而实际API为project_id）；修正后15 passed（4.78秒）；增加真实PG规范视觉对象对照旧document残留后最终 **16 passed，8.70秒**。覆盖不修改候选/数据库正文、集号bool/float、NaN/Inf/错时长、越界章节、未知status字段、空要点、前集全文/截断/过期证据、锁定正式视觉及废弃排除。

**本次仅内部准备，不是单集AI功能完成**。模块尚未接HTTP/准入、Worker、候选采纳或网页按钮；调用者未来必须在授权和依赖锁下读取、冻结指纹，不能仅凭当前只读helper声称已具备并发安全。没有新增依赖/迁移，没有付费调用，未运行前端构建/浏览器/全量后端。7878继续运行SYNC-24，待单集生成闭环完成再更新；整体同步目标保持进行中。

## UPSTREAM-SYNC-25 接通：单集规划生成与明确采纳

新增 /adaptation/episodes/{no}/generate，沿用既有adaptation任务命名空间和生产级候选，不创建新队列/对象主源。manager授权、生产锁下冻结全局规划/原著事件/前集连续性指纹，锁定项目和协作视觉、原著及前集正文；反向锁冲突NOWAIT409。只限制目标集已有视频，其他已完成集作为只读连续性证据。通用任务入口也重新构造提示词、Schema、允许章节列表；不能伪造。已存在本集活跃任务409，同请求幂等回放仍保留。

Worker复用原文本候选通道，按单集Schema严格验证并保存episodePlan候选，不自动写规划。明确采纳时再核对成片及全部依赖，accept_stale不绕过；只替换目标计划为draft、仅失效目标关联剧本，保留其他集/全局状态，沿用原采纳收据及事件。依赖校验当前保守包含整个规划与原著事件，不声称可在任何无关改动后自动采纳。

改编页新增“AI生成本集规划候选”，要求草稿已保存、引用非空、平台模型已选；明示可能费用和不自动采纳。未知网络结果重试复用标识，成功后清除；任务中心显示具体EP单集规划。现有比较/明确采纳组件兼容生产级目标，无自动跳过审核。

首轮真实PG专项4 passed（30.48秒），覆盖明确采纳/未自动写入、角色权限、同请求回放、重复任务、原著/前集/视频变化拒绝。前端最终 **272 passed /0 failed /0 skipped，1540.38ms**；tsc/Vite build exit0，Vite **7.79秒**，既有chunk警告保留。浏览器完整E2E、真实供应商、全量后端未运行，Worker仅模拟文本返回；没有新增依赖/迁移/后台页面。原验收副本尚无实际Worker，不能把本轮模拟验证称作真实生成部署完成。

最终联合 `test_episode_plan_jobs.py test_episode_plan_contract.py test_p5_relation_candidates.py` **29 passed，95.69秒**。额外覆盖通用入口重复拒绝、原任务完成后通用入口提示词/Schema重建、前集行锁冲突409，以及旧整体/关系候选回归。仅推送集成分支并更新7878验收副本；整份冻结清单仍未核对完成，后续继续分集连续性其余入口、源章节/页面同步及视觉历史等未完项。

## UPSTREAM-SYNC-26：正式剧本生成的前集连续性

接续87c470a的业务意图，将已经用于单集规划的前集/Bible连续性真正接入“已批准规划 → 正式剧本候选”路径。每个任务冻结前集正式正文证据、Film Bible故事/连续性和当前锁定视觉版本，并把紧邻前集全文放进服务端提示词；`episode-script/v2`明确要求承接前集结尾，不重复已完成剧情或无依据重置人物状态。通用任务入口会重建提示词、Schema、连续性上下文和允许的章节版本，客户端伪造字段无效。

提交与明确采纳都在production和目标剧本锁下，以NOWAIT短锁读取前集、原著章节、项目与协作视觉对象；前集、原著、规划或Film Bible变化后，旧候选即使请求`accept_stale`也不能写入。目标集已有采纳视频时禁止生成和采纳新正式剧本。仍保留原负责人、assignment_epoch、revision、人工审核与显式候选采纳；Worker只生成候选，不自动写正文。批量候选来自同一旧快照时，从后往前采纳仍可全部使用；先采纳较早集会使尚未采纳的后集候选按设计过期，避免后集遗漏新前集内容。

实际验证：新专项 `tests/test_script_generation_continuity.py` **4 passed，18.88秒**；修正批量回归采纳顺序后，新专项加原失败用例 **5 passed，22.01秒**。最终真实隔离PostgreSQL联合 `test_script_generation_continuity.py test_p5_relation_candidates.py test_adaptation.py test_p6_admission.py test_direct_script_assist.py` **42 passed，174.74秒**，覆盖前集/Bible变化、通用入口伪造、依赖行锁、成片保护、任务准入、直接剧本与原候选回归。前端 `npm test` **272 passed / 0 failed / 0 skipped，1600.28ms**；`npm run build` exit0，Vite **7.03秒**，保留既有大chunk警告。

本批无新增依赖、数据库迁移、后台页面或配置；未运行真实付费Provider、完整业务浏览器E2E或全量后端。测试使用模拟文本返回。整体同步仍未完成，后续继续核对原著/改编/剧本页面同步、视觉历史复用与恢复及其余冻结清单。

## UPSTREAM-SYNC-27：原著章节分配与改编/剧本选集同步

按冻结上游 `62d4b09` 与 `1cb7a94` 的业务意图适配，没有复制其单机页面状态。改编页新增作品内分集导航、原著章节分配索引、把未分配章节加入当前规划或建立下一集规划；新增规划只形成本地草稿，仍须通过原有 production revision 保存，不能直接建立 Episode、跳过审核或触发 AI。受成片保护的分集在导航中明确标识，加入当前集的快捷操作禁用，最终保护仍由服务端实施。

改编与剧本页共用作品级私有选集焦点，包括尚未建立 Episode 的规划；保存后从改编切到剧本仍进入同一集。切换真实 Episode 时同步焦点，不把选集写成共享数据。无首选项时优先未批准且未受保护的规划，而不是总回到 EP01。

协作草稿保护强于上游：后台刷新可以更新章节索引，但不能覆盖未保存策划；若服务器规划基线已变化则显示提示，只能保存并接受服务端版本检查，或点刷新明确确认放弃。改编草稿没有持久 Draft Store，因此未保存时阻止切换阶段、作品或分集，并纳入 beforeunload；保存后正常导航。刷新、保存、审核和生成的迟到响应均验证组件仍存活且仍属于同一作品，不能更新新页面的 revision、通知或继续第二段生成请求。原著页继续使用已有关系草稿和请求代际机制，没有换回上游较弱的页面布尔 dirty 状态。

前端最终 `npm test`：**276 passed / 0 failed / 0 skipped，1661.55ms**。最终 `npm run build`：tsc/Vite exit0，Vite **7.07秒**，产物 `assets/index-BjNoHSE2.js`，保留既有大 chunk 警告。真实隔离 PostgreSQL 定向回归 `test_adaptation_scope.py test_adaptation.py test_source_library.py test_source_append.py`：**24 passed，78.79秒**；测试服务只使用任务自建数据库，没有操作验收数据。

computer-use 隔离组件检查使用内存 Mock：初始焦点为 EP03；输入未保存核心前提后切剧本被阻止；模拟服务器规划变化后本地文字保持并显示远端更新提示；另一干净实例从未分配章节建立并保存 EP04，切到剧本室后仍为 EP04 且保留该章节引用。隔离页没有 API 代理、业务库或 Provider，不冒充登录后的完整业务 E2E；测试后已关闭页面与临时 Vite 服务。

`git diff --check`通过。本批无新增运行依赖、数据库迁移、平台配置或后台页面；未调用真实付费 Provider，未运行全量后端。整体同步仍未完成，后续继续视觉历史复用/恢复、分集切换反馈和剩余冻结清单审计。

## UPSTREAM-SYNC-28：跨集视觉历史与资产复用

按冻结上游 `eee2ebe` 的业务需求适配到协作对象主源，没有复制单机版浏览器合并整份 Film Bible 的写入方式。分镜任务提交时服务端丢弃调用方伪造的 `storyboard_visual_context`，在对象版本锁和 Production 视觉绑定锁下冻结全部共享视觉卡及版本；每张卡作为只读任务依赖，不要求生成者拥有其他负责人的视觉卡。提示词只列有效当前版本和确认别名，并要求按稳定 key、类型和父级复用，同名歧义不做模糊猜测。

Worker 两阶段输出保留已有全部版本、参考图和外观约束；第二阶段使用解析后的规范版本 ID。候选采纳改在服务端完成旧任务身份映射、状态父级版本、镜头角色/场景/道具绑定和对白基础角色映射，只创建真正新增的视觉卡，不更新已有视觉对象。现有对象 revision/assignment epoch 变化或任务后新增视觉卡都会使候选过期，`accept_stale` 不能绕过；无完整视觉目录快照的旧候选须重新生成。详细边界见 [跨集分镜复用作品视觉资产](../storyboard-asset-reuse.md)。

实际验证：纯规范化与分镜契约首轮 **13 passed，4.31秒**。首次联合 **20 passed / 3 failed，56.37秒**：一项是同批新状态引用同批新基础卡被废弃父级保护误判，修正为仅拒绝现有且不可用的父卡；另两项来自同一根因及旧测试恰好使用显式 `hero` key，新语义按 key 正确复用后将旧期望从新增4张调整为新增3张，没有放宽视觉版本校验。修正后同一组合 **23 passed，58.07秒**。

真实隔离 PostgreSQL 分镜专项最终 **11 passed，59.91秒**，包括EP02复用EP01由另一负责人维护的Production视觉卡、调用方伪造目录被替换、旧卡内容/revision逐项不变、新状态父级、镜头及对白ID映射、目录编辑/新增后无半写、镜头负责人/版本及真实图锁竞争。Film Bible、对象候选和主源联合 **49 passed，127.21秒**；任务准入、批量画布和平台模型冻结联合 **30 passed，145.83秒**。这些命令有重叠项时不相加冒充独立总数。

前端 `npm test` **276 passed / 0 failed / 0 skipped，1457.08ms**；`npm run build` tsc/Vite exit0，Vite **8.61秒**，产物主包仍为 `assets/index-BjNoHSE2.js`，保留既有大chunk警告。`compileall`与`git diff --check`通过。本批无新增依赖、数据库迁移、平台配置或后台页面；没有真实付费Provider调用，未运行登录业务浏览器E2E或全量后端。整体同步尚未完成，下一独立批次处理从协作历史恢复废弃视觉版本；不能用本批复用能力代替显式历史恢复。

## UPSTREAM-SYNC-29：从协作审计历史恢复废弃视觉版本

按冻结上游 `045853a` 的业务目标适配，没有复制单机版 Production 整份快照写回。新增对象范围恢复入口，要求当前负责人、精确 object revision 和 assignment epoch；manager 仍须先显式接管。在视觉绑定事务锁下按新到旧读取该对象不可变历史，只从最近非废弃快照恢复 `draft` / `pending_reference` / `locked` 状态。除状态外内容不一致、所属卡片未恢复、对象代际变化或非负责人操作均拒绝。

写入只改目标版本 `status`，不使用历史卡片、参考素材、声音、其他版本或分镜覆盖当前协作主源。成功追加 object revision、`visual.restore` 历史、审计及各分集SSE事件。网页只在废弃版本显示恢复按钮；目标对象有本地草稿时先拒绝，恢复回执仅合并该对象，不覆盖其他未保存内容。详见[跨集分镜复用作品视觉资产](../storyboard-asset-reuse.md#废弃版本恢复)。

实际验证：纯规则及真实隔离 PostgreSQL 恢复专项 **7 passed，14.58秒**；扩展到 Film Bible、视觉主源、普通对象历史/事务、分镜候选与采纳的真实PG联合回归 **64 passed，213.49秒**。覆盖locked/draft恢复、只改状态、跨集可见、负责人/manager/viewer、旧revision、缺失版本、两请求竞争只一次提交、历史/审计/事件，以及原整对象恢复与候选采纳回归。

前端协作客户端专项 **22 passed，173.42ms**；全量 `npm test` **278 passed / 0 failed / 0 skipped，1395.82ms**；`npm run build` tsc/Vite exit0，Vite **7.43秒**，保留既有大chunk警告。无新增依赖、数据库迁移、平台配置或后台页面；未调用真实付费Provider，未运行登录业务浏览器E2E或全量后端。整体上游同步仍未全部完成，下批继续分集切换反馈与剩余冻结清单审计。

## UPSTREAM-SYNC-30：分集切换渐隐反馈

按冻结上游 `a3b9e6b` 与 `fcbbe4c` 的交互目标适配。顶部作品/分集选择器切换到另一集时，页面显示固定视口的深色渐隐反馈和目标分集名称；工作区在切换期间设置 `inert` 与 `aria-busy`，状态层通过 Portal 挂到工作区之外并使用 `role=status` / `aria-live=polite`。最终遮罩深度为 **68%**，进入和退出动画分别为 140ms 与 160ms；系统启用减少动态效果时取消动画。

反馈层只包裹既有 `openProject` 调用，不直接设置项目、文档或脏状态，因而保留协作版已有的未保存草稿检查、对象保存、冲突拒绝、请求代际及作用域校验。重复点击在活动切换期间被忽略；当前分集和未知目标不触发切换；无论切换成功还是失败都会退出反馈并恢复仍存在的原焦点。组件卸载不会吞掉原 `openProject` 异常，原调用链继续交给既有错误报告处理。

定向 `episode_transition + workflow_shell + production_navigation + adaptation_frontend`：**20 passed / 0 failed**。全量 `npm test`：**281 passed / 0 failed / 0 skipped，1422.78ms**。`npm run build` tsc/Vite exit0，Vite **7.21秒**，主产物 `assets/index-Ca71Y38Z.js`，保留既有大 chunk 警告。`git diff --check`通过。本批纯前端，没有新增 API、后端逻辑、依赖、数据库迁移、配置或后台页面；未调用真实付费 Provider，也未运行登录业务浏览器 E2E。整体上游同步仍未完成，后续继续剩余冻结清单审计和未完成项。

## UPSTREAM-SYNC-31：紧凑任务中心筛选

按冻结上游 `8fe968d` 的界面目标适配。任务中心标题同行显示当前作品名，过长时省略并保留完整 title；只读说明独占下一行并同样保留完整 title。任务范围、类型、状态三个既有筛选器改为一行三列，作品范围列略宽，所有 label/select 都允许收缩并限制在面板宽度内，不再让第三项无条件换到下一行。

本批没有修改任务加载、作品授权、跨集/整部作品作用域、状态枚举、候选采纳、取消/恢复或刷新逻辑。现有筛选函数及六种持久任务状态回归继续通过；紧凑布局只改变标记结构和 CSS，不产生任务、自动重试或费用。

定向 `task_center + job_detail + episode_transition`：**10 passed / 0 failed**；新增契约断言验证作品名省略、说明 title、三列比例及 select 宽度边界。全量 `npm test`：**282 passed / 0 failed / 0 skipped，1619.59ms**。`npm run build` tsc/Vite exit0，Vite **7.29秒**，产物 `assets/index-CyImXyGr.js` / `assets/index-EH1HLD0z.css`，保留既有大 chunk 警告。本批纯前端，没有新增 API、依赖、迁移、配置或后台页面；未调用真实付费 Provider，也未运行登录业务浏览器 E2E。

## UPSTREAM-SYNC-32：简化当前作品标题

按冻结上游 `0e8ce1c` 的界面目标适配。顶栏作品按钮移除文件夹图标、“项目 ·”前缀和下拉箭头，只显示当前 Production 名称，为制作流程和分集选择释放横向空间。按钮仍打开 Production 设置页签，完整作品名保留在动态 `aria-label`，title 明确为查看和修改当前项目。

协作版团队切换、制作流程、当前分集选择、作品/分集设置、保存状态和对象协作入口全部保留；没有把作品名和 Episode 标题混为一个可写字段，也没有改变权限、草稿或保存逻辑。`FolderOpen` 仍用于引用类型、回收站原著/剧本等其他位置，只删除已无使用的主文件 `ChevronDown` 导入。

定向 `workflow_shell + production_navigation + episode_transition`：**12 passed / 0 failed**，新增契约断言验证按钮行为/无障碍名称及协作控件仍存在。全量 `npm test`：**283 passed / 0 failed / 0 skipped，1639.84ms**。`npm run build` tsc/Vite exit0，Vite **7.41秒**，主产物 `assets/index-iU3-9m7N.js`，保留既有大 chunk 警告。本批纯前端，没有新增 API、依赖、迁移、配置或后台页面；未调用真实付费 Provider，也未运行登录业务浏览器 E2E。

## UPSTREAM-SYNC-33：长镜头描述完整换行

按冻结上游 `247d314` 的界面缺陷修复。协作版视频工作区仍把镜头动作和右侧机位/时长摘要强制为单行并截断省略，长文本无法读全。现在摘要容器允许换行并顶端对齐；镜头动作保留作者换行且可在任意长词/连续文本处分行，机位与时长摘要也可收缩、换行，不能越出卡片。

本批只覆盖 `VideoProductionWorkspace` 已有 `video-shot-context` 的显示，不修改镜头动作、Video Prompt、机位、计划/提交时长数据，不改变保存、候选、任务提交或 Provider 参数。采用后置同等选择器覆盖旧单行规则，明确恢复 `overflow:visible` / `text-overflow:clip`，避免旧省略声明继续生效。

定向 `video_production + motion_reference + video_dialogue`：**21 passed / 0 failed**；新增契约断言验证组件实际使用目标选择器、动作文本 `pre-wrap/anywhere` 和摘要 `normal/anywhere`。全量 `npm test`：**284 passed / 0 failed / 0 skipped，1654.32ms**。`npm run build` tsc/Vite exit0，Vite **7.69秒**，产物 `assets/index-O6uBJ7K5.js` / `assets/index-DaU2Z3_n.css`，保留既有大 chunk 警告。本批纯前端，没有新增 API、依赖、迁移、配置或后台页面；未调用真实付费 Provider，也未运行登录业务浏览器 E2E。

## UPSTREAM-SYNC-34：折叠分镜图编辑详情

按冻结上游 `7afcf70` 的界面目标适配。分镜规划阶段继续直接展示时长、场景、角色、情绪、动作、机位/声音、视觉绑定与提示词；分镜图阶段改为结果优先：表格默认显示预览、场景、两行动作摘要和视觉引用，详细字段、视觉绑定、统一图片设置及提示词放入默认关闭的“镜头详情与设置”。宫格也将动作/角色/情绪/机位/声音和统一图片设置放入每卡 disclosure。

折叠使用原生 `details`，关闭时子控件仍挂载，不建立第二份草稿，也不触发保存、生成或 API。所有编辑继续调用原 `onPatch` / 绑定命令和共享 `ImageGenerationSettings`；两处图片设置入口数量保持，负责人、对象 revision、冲突和草稿保护仍由宿主原链路实施。分镜图卡继续在折叠外显示过期、待核对提示词、无视觉绑定或缺主参考图警告，生成/预览/尾帧/高级画布按钮不移入折叠区。

定向 `storyboard_workspace + image_settings + shot_sync + batch_generation`：**16 passed / 0 failed**；新增契约断言验证规划展开、图片 disclosure 默认关闭、两处图片设置仍挂载及摘要换行样式。全量 `npm test`：**285 passed / 0 failed / 0 skipped，1689.99ms**。`npm run build` tsc/Vite exit0，Vite **7.78秒**，产物 `assets/index-DWRuFsqu.js` / `assets/index-He3xw10A.css`，保留既有大 chunk 警告。本批纯前端，没有新增 API、依赖、迁移、配置或后台页面；未调用真实付费 Provider，也未运行登录业务浏览器 E2E。

## UPSTREAM-SYNC-35：分镜图批量操作浮动

按冻结上游 `b5ece03` 的界面目标适配。分镜图表格与宫格共用的批量栏固定在视口右下角，窄屏为其预留底部空间，宽屏为其预留右侧空间，滚动长分镜列表时无需回到顶部即可查看选择数量和提交批量生成。批量栏补充 `role=group` 与“批量生成分镜图”无障碍名称。

本批只改变批量栏布局与语义标记。全选仍写入当前镜头的稳定 UID，提交仍只调用 `generate(selected)`；未选择或工作区忙碌时继续禁用。没有扩大跨集选择、对象权限、任务准入或 Provider 调用范围，也没有自动提交任务。

定向 `storyboard_workspace`：**6 passed / 0 failed**；新增契约断言验证浮动布局、宽窄屏内容避让、显式 UID 选择提交及禁用条件。全量 `npm test`：**286 passed / 0 failed / 0 skipped，1610.39ms**。`npm run build` tsc/Vite exit0，Vite **7.68秒**，产物 `assets/index-CqhTs9qD.js` / `assets/index-CNbrRJBI.css`，保留既有大 chunk 警告。`git diff --check` 通过。本批纯前端，没有新增 API、依赖、数据库迁移、配置或后台页面；未调用真实付费 Provider，也未运行登录业务浏览器 E2E。

## UPSTREAM-SYNC-36：视频批量操作浮动

按冻结上游 `887f1da` 的批量操作需求适配。视频工作区批量栏固定在视口右下角，宽屏为其预留右侧空间，窄屏预留底部空间；滚动逐镜视频列表时仍能看到全选、已选数量和“生成所选视频”。批量栏增加 `role=group` 与“批量生成视频”无障碍名称。

本批保留协作版更严格的两段式流程：浮动按钮只打开提交前复核，复核继续显示任务数量、Provider、模型和公网 API 数量，并在存在未就绪或运行中镜头时禁止确认；最终只提交明确选中的稳定 UID。没有移动协作版动作参考编辑器，没有扩大跨集选择、对象权限或服务端任务准入，也没有自动提交或调用 Provider。

定向 `video_production`：**14 passed / 0 failed**；新增契约断言同时验证浮动布局、宽窄屏内容避让、显式选择、复核入口和阻断后的确认提交。全量 `npm test`：**287 passed / 0 failed / 0 skipped，1375.25ms**。`npm run build` tsc/Vite exit0，Vite **6.94秒**，产物 `assets/index-B1TiYTRo.js` / `assets/index-Cq0dIKPe.css`，保留既有大 chunk 警告。`git diff --check` 通过。本批纯前端，没有新增 API、依赖、数据库迁移、配置或后台页面；未调用真实付费 Provider，也未运行登录业务浏览器 E2E。
