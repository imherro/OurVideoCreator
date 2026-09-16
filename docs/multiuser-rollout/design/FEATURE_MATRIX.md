# P0 功能保留、移除与改造矩阵

| 领域 | 当前证据 | 决策 | 目标阶段与回归 |
|---|---|---|---|
| 原著/章节导入与事件提取 | `backend/source_library.py`、`backend/adaptation.py`、`SourceLibraryPage.tsx`、`test_source_library.py` | 保留并改造 | P2 PG；P3 授权；P5 对象归属；REG-01 |
| 改编策划与逐集剧本 | `adaptation.py`、`AdaptationPage.tsx`、`ScriptRoomPage.tsx` | 保留；已有 revision 模型 | P2/P3/P5；REG-01 |
| 双遍分镜 | `backend/worker.py`、`test_storyboard.py::test_film_bible_storyboard_is_two_text_passes_with_deterministic_bindings` | 保留 | P1 外部 API；P4 平台模型；REG-02 |
| Film Bible 卡片/不可变视觉版本 | `backend/film_bible/`、`src/filmBible/`、`test_film_bible*.py` | 保留并关系化主源 | P5；COLLAB-08、REG-02 |
| 镜头稳定 uid 与视觉版本绑定 | `project_schema.py`、`reference_compiler.py`、`filmBible/versioning.py` | 保留 | P5 镜头对象；REG-02/03 |
| Generation Fingerprint/过期判断 | `generation_fingerprint.py`、`generation_staleness.py` 及对应测试 | 保留 | P5 对象版本，P6 任务回写；COLLAB-09 |
| 首帧、尾帧、多参考素材 | `reference_compiler.py`、`visual_references.py`、`test_end_frame.py`、`test_batch_references.py` | 保留 | P4 能力目录；REG-03 |
| 角色固定音色、对白音频 | `video_dialogue.py`、`volcengine_speech.py`、`src/filmBible/voices.ts` | 保留 | P4 平台模型；P5 对象；REG-04 |
| 素材库分类、Production 共享 | `assets` 表、`app.py:512-665`、`ProductionAssetCenter.tsx` | 保留并加租户/作品归属 | P2/P3/P7；MEDIA-* |
| 幻场素材组/素材登记 | `providers/hc_atom.py`、`provider_asset_groups`、`provider_asset_mappings`、`test_hc_atom.py` | 必须保留 | P2 关系化；P4 凭证作用域；P6 并发去重；JOB-12 |
| 方舟 Seedream/Seedance | `providers/volcengine_ark.py`、`test_volcengine_ark.py` | 保留 | P4/P6；REG-03 |
| RunningHub | `providers/runninghub.py`、`test_runninghub.py` | 保留 | P4/P6；REG-03 |
| Replicate | `replicate_api.py`、`test_replicate_api.py` | 保留 | P4/P6；REG-03 |
| MiniMax 原生视频 | `minimax_video.py`、`test_minimax_video.py` | 保留外部适配器 | P1 与 runtime 解耦；P4/P6 |
| ComfyUI/API 网关 | `worker.py::comfy/video_api` | 保留为外部 Provider | P1；P4 收敛到管理员配置 |
| 内置 llama 文本运行时 | `runtime.py::load`、`worker.py` local dispatch、模型目录 UI | 移除 | P1；无本地回退 |
| 内置 Maestro/WanGP 启动 | `runtime.py::start_maestro`、`inference/`、runtime API | 移除本仓库运行依赖 | P1；未来作为受控外部 API |
| GPU/CUDA/权重发现和模型安装 | `runtime.py`、`inference/`、`scripts/import_local_engine.py` | 移除 | P1；CLOUD-01/04 |
| FFmpeg/ffprobe/缩略图 | `media.py`、`editor_renderer.py`、`worker.py::export*` | 保留 | P1 不误删；P7 加固；CLOUD-05、MEDIA-06 |
| Twick 多轨剪辑/字幕/初剪 | `src/editor/`、`initialTimeline.ts`、`test_export.py` | 保留并改为 timeline 对象 | P5 租约；P7 E2E；REG-05 |
| 画布/节点/连线 | `src/main.tsx`、`graph.ts`、`shotNodes.ts` | 保留并拆主源 | P5 graph revision；COLLAB-11 |
| 宫格图板 | `contact_sheet.py`、`StoryboardGrid.tsx` | 保留 | P3 文件授权；REG-06 |
| 全景浏览/视角保存 | `panorama.ts`、`PanoramaViewer.tsx` | 保留 | P5 对象映射；REG-06 |
| 3D 导演台 | `directorScene.ts`、`DirectorStage.tsx` | 保留 | P5 对象映射；REG-06 |
| 当前共享密码/setup | `app.py:73-123` | 移除 | P3 CLI 初始管理员和个人会话；AUTH-01 |
| 当前全局 Provider settings | `settings` 表、`app.py:673-727`、`SettingsPanel` | 移除普通入口，迁为后台 | P4；MODEL/SECRET |
| 当前 SQLite 与启动迁移 | `store.py` | 完整替换，不保留运行兼容 | P2；DB-* |
| 整份 Project.document 写入 | `app.py:391`、`main.tsx:989` | 退役为只读聚合 | P5；COLLAB-04 |
| 旧数据/schema 兼容 | `store.init` 与 `project_schema` 历史迁移 | 新库不迁旧数据；保留必要纯函数直到聚合切换 | P1/P2/P5 后清理，删除需测试映射 |
| SQLite 任务队列/单 Worker 锁 | `worker.py`、`process_lock.py` | 分阶段替换 | P1 独立 Worker；P2 PG；P6 lease/fencing |
| SSE | `events` 表、`app.py:1849`、前端 EventSource | 保留机制并加权限/重连 | P3/P7；EVENT-* |

## 不在第一版范围

同段文字实时共编、CRDT、在线光标、复杂组织树、自定义权限编辑器、充值/积分/支付、跨作品公共素材库、Redis/Celery/Kubernetes 前置、自动切换付费模型、端到端 exactly-once。
