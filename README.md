# 安影 · OurVideoCreator

安影协作版 AI 视频创作工作室。P0–P2 已通过外部验收，当前处于 P3 身份与团队权限返修阶段：浏览器 Web 与持久任务 Worker 已分离，PostgreSQL 是唯一业务数据库，所有生成只调用显式配置的外部 Provider API。已改为邀请制个人账号、团队及作品授权；P3 尚未通过外部验收，不得公网部署。阶段状态见 [多用户改造索引](docs/multiuser-rollout/README.md)。

## 运行

Windows，Python 3.11+ 与 Node.js 20+：

```powershell
.\Install-Studio.ps1
$env:OVC_DATABASE_URL='postgresql+psycopg://用户名:密码@127.0.0.1:5432/our_video_creator'
.\.venv\Scripts\python.exe -m alembic upgrade head
.\Start-Studio.cmd
```

`OVC_DATABASE_URL` 必须通过进程环境注入，仓库只展示占位示例，不保存真实密码。只接受 PostgreSQL DSN；缺失配置、SQLite DSN、数据库不可达或 Alembic 版本不匹配都会明确停止启动。Web 和 Worker 启动只检查数据库就绪状态，不会自动建表、升级、清空或覆盖数据。空数据库必须由运维显式执行 `python -m alembic upgrade head`。

`Start-Studio` 会启动两个独立进程：Web 和单实例 Worker。每个进程在实际数据目录写入带实例 ID、PID、创建时间、可执行文件和完整命令行的生命周期记录；实例 ID 同时绑定脚本所属工程根目录、实际媒体目录和不含凭证的 PostgreSQL 数据库标识。脚本从任何当前目录调用时都会在自身工程根加载后端，并核对返回的工程根；相对 `MVC_DATA_DIR` 也统一相对脚本工程根解析为绝对路径。启动与停止期间会把规范化后的绝对数据目录传给身份查询和新建子进程，完成或失败后再把调用者 PowerShell 中原有的 `MVC_DATA_DIR`、`PYTHONUTF8`、`OVC_DATABASE_URL` 及工作目录原样恢复。脚本只会复用或停止能够完整证明属于当前实例的进程，端口上若是另一个实例会明确拒绝启动。也可以分别执行：

```powershell
.\Start-Studio.ps1 -WebOnly
.\Start-Studio.ps1 -WorkerOnly
.\Stop-Studio.ps1
```

开发时可直接运行 `python -m uvicorn backend.app:app --host 127.0.0.1 --port 7868` 和 `python -m backend.worker_cli`。关闭浏览器或重启 Web 不会停止 Worker，也不会重置已持久化任务。`-WebOnly` 停止和重启 Web 时不会触碰 Worker。第二个 Worker 会因同一 PostgreSQL 队列上的 session advisory lock 明确拒绝启动；改变 `MVC_DATA_DIR` 不能绕过该锁，多 Worker 要等 P6。

首次部署必须由运维使用 `python -m backend.admin_cli bootstrap-admin --phone <管理员手机号> --nickname <昵称>` 初始化平台管理员，并通过进程环境 `OVC_BOOTSTRAP_PASSWORD` 提供密码；没有默认密码，浏览器公共初始化入口已退役。后续用户通过管理员邀请注册，入组及作品授权后才能访问对应内容。P3 完成前只能在受控开发网络使用，不得公网部署。

当前主机的局域网地址在首次开发检查时为 `192.168.2.100`，可能随网络改变。程序不会自行修改防火墙。允许 Python 入站访问时限定到需要的私人网络。

前后端同源，所有浏览器请求均使用相对 `/api` 地址。媒体文件通过认证后的 HTTP 接口读取，支持视频范围请求。

## 创作

1. 在设置中连接外部文本 Provider，并为作品显式选择默认模型。
2. 点击“继续拆解分镜”，生成后导入分镜表。
3. 按镜头建立图像和视频节点，连接参考图，选择对应外部 Provider。
4. 生成结果自动关联到节点；历史生成可切换版本。
5. 点击“剪辑”进入 Twick 多轨工作区，生成初剪后继续精剪并导出 MP4。

## 多轨剪辑与导出

剪辑工作区直接使用当前项目的素材库，不复制媒体文件。视频、图片和音频片段始终保存原项目 `assetId`；重新打开项目或更换访问主机后会用该 ID 恢复当前素材 URL。

- 支持多轨视频、图片叠加和多轨音频，以及拖动、trim、split、片段重叠、吸附、撤销和重做。
- 工具栏可增加视频轨、音频轨和标题，并将项目中的 SRT 导入为可逐条编辑的字幕轨。
- 右侧属性可设置时间、素材入点、速度、音量、音量关键帧、音画淡入淡出、位置、尺寸、旋转、透明度、滤镜、转场和同类型素材替换。
- 快捷键：`S` 在播放头切分，`Ctrl/Cmd+D` 复制；Twick 原生支持 `Delete`、`Ctrl/Cmd+Z` 与重做。
- “生成初剪”按分镜顺序建立 V1，并保留镜头、节点和素材关联；已有背景音乐会进入独立音轨。
- 左侧素材点 `+` 或双击会顺序追加到对应轨道；拖到轨道则从当前播放头加入。`V` 是视频/图片轨，`A` 是音频轨，`T` 是标题轨，画面轨越靠上越覆盖下层。
- “空视频轨”只用于新建叠加层，不会自动加入素材；误建的空轨可用“清理空轨”一次删除。

剪辑工程保存在 `Project.document.editor.timeline`。编辑器中的“导出工程”和导出面板都会优先提交该工程；没有编辑工程时继续使用原 `Clip[]` 导出。高级导出由 `backend/editor_renderer.py` 编译为 native FFmpeg filter graph，支持多轨合成、图片 overlay、交叉淡化、标题/字幕、静态 transform、滤镜、多路音频、音量关键帧及淡入淡出。导出仍运行在原持久化任务队列中，保留进度、取消、服务重启恢复和成片素材登记。

## 构图工具

- 宫格：按分镜排列镜头图，支持两列/三列、分页和带描述的 PNG 图板导出。
- 全景：素材库中的全景构图可浏览等距柱状全景图，保存指定视角为普通参考图。
- 3D 导演台：添加角色与物体占位，调整位置、大小、朝向，保存多个机位；截图后创建带构图参考的图像节点。场景随项目保存，截图隐藏辅助网格与选中高亮。

## 外部 API-only

仓库不再包含模型权重、CUDA/GPU 探测、模型下载、本地推理虚拟环境或 llama/Maestro 自动启动逻辑。Web 启动不需要模型文件；Worker 只消费持久任务并调用已冻结的外部 Provider 配置或 FFmpeg。没有显式 Provider 时请求会在出站前失败，系统不会回退到其他付费模型。

保留 ComfyUI API 工作流、OpenAI 兼容图文、Maestro/WanGP 兼容 HTTP API 和异步 JSON 视频网关。Maestro 在这里是已连接的独立服务，不由本仓库启动，也不读取其服务器文件系统。MiniMax Hailuo 2.3 已有原生视频适配器：支持 768P 的 6/10 秒文生视频或单首帧图生视频，以及 1080P 的 6 秒模式；首帧为 JPEG、PNG 或 WebP，短边大于 300px、文件小于 20MB。该适配器在任务提交后保存供应商任务编号，服务中断可恢复查询而不重复提交；供应商实际账号验收仍需使用者配置密钥后完成。

Replicate 模型平台也可作为云端服务添加。它能运行平台提供的官方模型，例如 Seedance、Kling、Veo、Flux、Imagen，以及填写 `owner/model:版本 ID` 的社区模型。每个服务配置选择一种用途并填写该模型的输入 JSON；`{{prompt}}`、`{{system_prompt}}`、`{{target_duration}}`、`{{image}}` 和 `{{images}}` 会在提交时替换。参考素材会作为 data URI 发送给该云端服务。Replicate 的输入和输出字段随模型而异，请在模型 API 页面核对输入模板与计费；取消按钮会同时请求取消远端 prediction。真实账号调用尚未在本机验收。

火山方舟作为统一 Provider 接入：在“模型与服务”中点击“添加火山方舟”，保存一次 ARK API Key，再点击“保存并验证 Key”。服务端通过方舟 `/models` 验证 Key 并读取模型目录，不提交生成任务；验证成功后，文本、图片和视频模型均可从目录选择，也可手动填写自定义接入点 ID。每类模型旁的“检测”用于确认所选 ID 是否出现在方舟目录中，不产生图片或视频费用；目录存在不代表账号已经开通该模型，实际权限以首次生成结果为准。默认地址为 `https://ark.cn-beijing.volces.com/api/v3`。文本与分镜复用 OpenAI-compatible `/chat/completions`；Seedream 文生图及单张/多张参考图调用 `/images/generations`，参考图由服务端从当前项目素材库读取并转换为 data URI；视频统一使用 `doubao-seedance-2-5-260628` 调用 `/contents/generations/tasks`。首尾帧分别以 `first_frame` / `last_frame` 角色发送，task id 会立即持久化，服务中断后只恢复查询原任务。P2 不在应用启动时执行任何旧库数据迁移；媒体结果仍下载并登记到当前项目素材库。浏览器读取配置时只获得 `api_key_set`，不会取得完整 Key。当前尚不向 Seedance 发送一般参考图、参考音频或参考视频。

RunningHub 也作为统一 Provider 接入：在“模型与服务”中点击“添加 RunningHub”，填写 Enterprise-Shared API Key 后保存并验证。验证读取账号类型和实时 LLM 目录，不发起付费生成；文本默认使用 RunningHub 的 OpenAI-compatible LLM 接口。图片配置 `seedream-v5-pro` 时会按有无参考图自动选择文生图或图生图端点，最多上传 10 张参考图；视频配置 Seedance 2.5 Token 时会按无参考、首帧、首尾帧、多图或固定对白音频参考自动选择对应端点。所有媒体任务在取得 taskId 后持久化并轮询 `/openapi/v2/query`，结果下载到项目素材库。RunningHub 当前未提供这些 Model API 任务的统一取消端点，因此取消只会停止本地等待，远端任务可能继续计费。

角色跨镜头音色通过 Film Bible 的“角色固定音色”管理。先在“设置 → 模型服务”添加“豆包语音”，填写独立的 Speech API Key、Resource ID 和默认音色 ID；配置检查只验证字段，不产生费用。随后在角色资产卡保存声音设定、生成试听并锁定版本，再批量生成本集结构化对白。对白音频保存为项目人声素材，初始剪辑会建立 `A1 · 角色对白` 轨；镜头已有固定对白时会关闭该视频片段的原始音轨，避免双重人声。豆包语音凭证与火山方舟 ARK API Key 分开管理，默认 V3 SSE 地址为 `https://openspeech.bytedance.com/api/v3/tts/unidirectional/sse`。

## 项目 Schema 与默认模型策略

项目文档现在带有 `schemaVersion`。旧项目和历史版本在读取时通过纯函数迁移到当前内存结构；历史 JSON 不会被后台改写，只有用户正常保存当前项目时才持久化当前 Schema。Schema v2 为旧分镜补充稳定的系统 `uid`、顺序、视觉版本绑定和节点管线字段，同时保留原来的显示 `id` 与其他数据。

分镜规划默认执行两次文本调用：第一遍从剧本提取角色、角色持续状态、场景、场景持续状态和道具，建立 `VisualCard` 及不可变的草稿 `VisualVersion`；第二遍只引用第一遍产生的视觉语义键拆分镜头。服务端把语义键转换为系统 ID，校验悬空引用和类型错误，并将每个镜头绑定到明确的视觉版本后再返回。导入分镜表时，`filmBible.visual`、镜头 `uid`、`assetBindings` 和 `pipeline` 一起保存到 `Project.document`。这一阶段只调用文本模型，不生成视觉参考图，也不创建 Film Bible 画布节点。

已锁定的视觉版本不会原地修改。用户可从它派生新版本；视觉卡会指向新版，但已有分镜继续绑定旧版，直到用户按镜头、场景或段落明确升级。升级只把现有生成结果标记为待更新，不删除素材、不自动重新生成。分镜图片任务会保存确定性的 Generation Fingerprint，覆盖镜头变量、绑定版本、风格版本、提示词编译器版本和最终 Provider/模型，用于判断当前结果是否陈旧。详细证据见 [PHASE_5_ACCEPTANCE.md](PHASE_5_ACCEPTANCE.md)。

“我的项目”面板可分别设置项目默认文本、图片和视频 Provider/Model。解析顺序为“节点显式覆盖 → 项目默认”；继承结果不会被写回成节点覆盖。新建项目在已经配置火山方舟时默认选择该服务的三类模型；迁移后的旧项目保持三个空策略，生成前必须显式配置。Provider 被删除后配置会保留并显示失效，生成解析不会静默切换到其他收费服务。项目文档只保存 Provider ID 和 Model ID，不保存 API Key。

## 数据与队列

PostgreSQL 保存项目、历史版本、任务、业务事件和模型服务设置；`data/assets` 保存原始素材和生成结果。素材由最小 `StorageBackend` 边界管理，稳定 `assetId` 不随数据库连接或媒体目录变化。备份必须同时包含 PostgreSQL 数据库和私有媒体目录。P2 从空 PostgreSQL 数据库开始，不导入旧测试库、不复制旧 Key，也不提供 SQLite 双写或运行时切换。API Key 仅在服务端保存，设置接口不回传密钥内容。

素材同时具有两个独立维度：`kind` 表示图片、视频、音频或字幕，`category` 表示角色、场景、道具、分镜、音乐、音效、人声、参考或其他；`source` 记录上传或系统生成。新素材文件保持 `data/assets/asset-uuid.ext`，分类变化不会移动或修改文件。素材库可组合筛选媒体类型与业务分类，上传时可指定分类，已有素材可直接重新归类。系统生成器可以通过任务上下文指定分类，为 Film Bible 的角色、场景和道具参考图预留接口。

生成任务固化输入及服务配置；提交 ID 防止重复提交。当前只允许一个独立 Worker 进程；少量已验证 Provider 可在线程内并发，其他执行保持串行。取消状态不能被迟到的成功结果覆盖。Worker 重启将原运行任务标记为“待恢复”，Web 重启不修改任务状态。已取得 Maestro、ComfyUI 或视频网关任务编号时，可点击“恢复查询已有任务”，沿用提交时的服务配置查询和取回结果；没有编号时必须先核对上游状态，不自动重新提交。

画布、分镜表和宫格顶部提供“全部资产”“全部分镜图”“全部视频”三个智能批量入口，数字表示当前可提交项。批量生成跳过已有有效结果和正在执行的任务，只重试缺失、失败或过期结果；分镜图和视频使用精确节点模式，不会重新生成剧本或分镜规划。视频必须先有当前有效的分镜图，并通过适用的首帧状态核验。资产状态版本仍要求先人工确认并锁定父版本；任务按项目或节点已经选定的 Provider 直接提交。原“高级运行”保留完整画布和分支重跑能力。

FFmpeg 优先使用配置路径或系统 PATH，也可使用已安装的 `imageio-ffmpeg` 包。合成统一为 24fps、H.264/AAC。legacy 时间线和新的 Twick 多轨工程均可导出；素材范围会在渲染前校验，跨项目素材 ID 会被拒绝。

## 开发与验证

```powershell
python -m uvicorn backend.app:app --host 127.0.0.1 --port 7868
python -m backend.worker_cli
npm run dev
npm run build
npm test
$env:OVC_TEST_ADMIN_URL='postgresql+psycopg://测试管理员@127.0.0.1:5432/postgres'
python -m pytest -q
```

开发浏览器使用 Vite 的 5178 端口，其 `/api` 代理到 7868；生产使用后端直接服务 `dist`。每次 pytest 会创建名称受限的独立 `ovc_test_*` PostgreSQL 数据库，预先执行 Alembic 迁移，并只允许删除当前活动的该测试目标；测试网络仅允许回环地址。

完整设计与研究边界见 [DESIGN_RESEARCH.md](DESIGN_RESEARCH.md)。开发中状态与未验收项见 [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md)。
