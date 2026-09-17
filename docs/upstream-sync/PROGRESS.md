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

## 后续队列

前七组已完成自测，其余仍未全部移植。下一组继续处理9b55ccf的图片设置、只读规格预览与冻结实际参数展示，再处理多模态/音色、直接剧本及剩余交互。必须继续保留timeline单主源、租约与草稿。单机免审核/覆盖冲突草稿不照搬；运维、付费和延期平台不恢复。整体同步目标仍在进行，尚未合并master或更新用户运行实例。
