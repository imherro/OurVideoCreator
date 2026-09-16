# P4-R1 最小返修交付

状态：**READY_FOR_REVIEW**，未获得外部通过。审核仓库 **https://github.com/imherro/OurVideoCreator**，分支 `master`；不是单机版 MyVideoCreator。只处理 P4-R1，P5、真实付费 API 和公网部署未授权。

## 版本与范围

- P3 已通过：`de5ef13d6c772e62ec8a0e40be7be8abf1eb25d6`。
- 开发 base / 首轮 P4 evidence HEAD：`c7d6a88a06a01035fd44e45309414c05e061ab64`；其业务为 `3a73165f74520d0c15ec6f0750d7b2c105108744`。
- 本轮固定业务 SHA：`e6c3edd95830d4c778fee357b8807d1443920a04`。后续交付提交只改 docs；最终 evidence HEAD 见交付提交本身和审核消息，避免自引用 SHA。
- 原始外部 REVIEW/MATRIX/GATE_DECISION 在 `../../reviews/P4/`，完整授权在 `../../prompts/P4_R1_CODEX_PROMPT.md`。未改写原始结论，原 P4 证据完整保留。
- 本轮不新增依赖、迁移、认证协议或媒体供应商；不删除旧数据。只在既有验证/装载边界统一拒绝未实现组合和缺失受限参数。

## 三项缺陷的红绿闭环

| 外部问题 | 修复与实际证据 |
| --- | --- |
| OVC-P4-01 | `model_validation.parameters/shot_parameters` 在入队前要求所有已声明受限参数来自合法默认、显式值或规范分镜计算；`platform_models._load_binding` 对新出站再验证冻结快照，不偷偷补默认。红测在真实管理 API/普通用户 API/PG/Worker/guarded HTTP 下记录上限 200、冻结 `{}`、实际 wire 4096。绿测：省略 400 零 HTTP，201 为 400 零 HTTP，100 成功且冻结=wire=100。temperature=0、图片 n=2 也验证真实 wire 一致；voice_type 缺失拒绝、合法默认冻结，空/带首尾空白音色枚举拒绝发布。 |
| OVC-P4-02 | `supported_protocol` 统一服务端保存/发布/目录/提交/Worker/恢复校验；Maestro/Comfy 只允许显式 none，不引入未经定义的 Key 协议。红测实际原生调用没有认证却接受 Key；绿测 Key 保存 400 零 HTTP，无认证各自真实 Worker 完成图片并由普通用户读取资产。旧不支持版本用隔离 fixture 表示，目录隐藏，发布/提交/Worker/恢复全部拒绝，零 HTTP，不自动迁移数据。管理 UI 禁用 Key 选项并给出明确说明。 |
| OVC-P4-03 | `PROVIDER_KINDS` 移除未实现的 Replicate audio，保留 text/image/video 和既有豆包语音。红测真实 Worker 下载有效 WAV 后触发 `UnidentifiedImageError`；绿测发布 400 零 HTTP，旧组合目录/提交/Worker/恢复一致拒绝。UI 提示未接通并显示真实服务端错误，不将失败伪装成功。 |

红测不是源码摘录探针，也没有 mock resolve、参数验证或 Worker。`baseline-red.txt` 基于 c7 运行时代码及新增测试：4 failed / 2 passed / exit 1；失败断言表达期望修复行为。`targeted-green.txt` 在 e6c3edd：17 passed / 43.87s / exit 0，保留安全 HTTP 方法、路径、参数和认证布尔值，不导出 Key 或 header 原文。

所有规则字段现在都必须完整，这是明确的产品契约变化；未声明限制的固定协议常量仍可保留。例如仅限制 temperature 的用例仍使用不受该模型规则限制的 max_tokens=4096，不冒称所有模型一律上限 200。显式非法值不夹紧。旧排队空快照拒绝，已有远端 handle 查询不重新生成控制参数。

## 正式验证

所有本轮正式验证绑定 e6c3edd；开发期日志单列，不挪用旧 SHA。

- 新增真实 PG/API/Worker/HTTP 定向：17 passed，见 `targeted-green.txt`。
- 完整后端：**368 passed / 0 failed / 0 skipped / 2 warnings / 568.06s / exit 0**，UTC 2026-09-16T17:51:00.1323846Z–18:00:31.1632704Z；见 `backend-full.txt`、`SUMMARY.json`。工作区开发期另为 368 passed / 578.47s / exit 0，见 `development-full.txt`，不混淆运行起点。
- 前端：128 passed / 0 failed / 0 skipped；TypeScript/Vite build exit 0，**1827 modules**，8.79s；原大 chunk warning 保留。见 `frontend-test-build.txt`。
- `python -m compileall -q backend tests scripts` exit 0；实际 app.routes 守卫 99 registered / 96 API / 96 classified / 0 unclassified，exit 0，见 `routes-compile.txt`。
- 回归范围保留 P4 foundation/submission/rotation、秘密 canary、相关供应商协议/幻场映射、分镜参数、后项非法批次原子拒绝、独立 Worker 文本/异步图片/FFmpeg，以及 P1–P3 既有用例。没有用放宽权限、SQLite 或禁用断言换绿。

## 改动部分的真实浏览器验证

使用新建隔离实例 **7028**，fake **6955**；PG `ovc_test_30648_e2d41809730f`；harness/Web/独立 Worker PID 为 30648/16764/28788。启动 UTC 2026-09-16T17:51:25Z；浏览器操作窗口 17:51:30–17:54:40Z。预置仅合成账号/团队/作品/节点，**没有提前写入 Provider/模型**。

1. 管理员实际表单选择 Maestro、Comfy：认证切为 none，API Key 选项 disabled，显示只支持原生无认证及精确出站例外说明。两次保存均 200；保存不执行生成。
2. 表单创建 Replicate 并尝试发布 audio：页面明确提示未接通，POST `/api/admin/models` 400，显示“Provider 不支持该模型用途”。
3. 表单发布文本模型：max_tokens 上限 200、defaults `{}`。普通用户登录后 /admin 无权访问，转入画布，选择模型后不填写参数点击生成：jobs 400，页面显示“缺少平台受限参数…max_tokens”。本机 fake 当时 text/submit/poll/download/wrong_auth 全部零。
4. 填写 100 后再次点击生成：独立 Worker 执行成功，页面显示“已完成”和 `P4 浏览器文本闭环成功。[REDACTED]`；DB 冻结 max_tokens=100，任务 `job-edb894a5420447378a1320fa36a53f11` succeeded。最终 fake text=1，其他生成计数=0，wrong_auth=0。

普通浏览器账号为 platform user / workspace member / production manager，遵循既有 P3 整份文档保存门槛，不冒称每种角色都做了 UI 测试。定向 API 用例另使用普通 editor。

- `browser-tool-trace.json`：26 次实际浏览器调用和 26 次返回，包含填写/点击、AX、请求状态与检查计数；不是事后编写的 UI 日志。提取脚本同目录，只精确脱敏测试密码和合成 Key。
- `browser-web-access.txt`：该实例真实请求日志，含方法/路径/状态，无 header/body。
- `browser-db-audit.json`：复用只读采集器关联任务、版本、审计和角色；37 张表共 49 行、4 份 Web/Worker 日志 canary 零命中。
- 浏览器共观察 110 条 API 响应，**99 份 JSON body 实际检查，零 canary**；9 份跳转后无法读取，不记为通过；2 条 SSE response 本轮未做 body 扫描。旧 P4 的 13 条 SSE 扫描证据保留其原 SHA，不冒称本轮重跑。正文脱敏、数据库/日志及完整后端 canary 回归提供独立佐证；零命中不是形式化安全证明。

浏览器不是命令行程序，没有总 exit code。其 UI 结果与 Web 日志、PG、安全 fake 计数交叉关联。浏览器内核版本工具不支持，沿用 unavailable；未更换取证框架，没有让用户代点。

## 资源与限制

- 保留新的 7028 隔离实例、媒体、DB 和日志待查；没有停止/重启/改写 7868 用户服务、7895 P3 或旧 P4 6313/6185。
- 真实 PostgreSQL 18.6，独立每轮 pytest 白名单 DB；仅 pytest 自己清理其拥有的临时数据库。其他版本沿用旧 P4 环境并以本轮日志/当前 provenance 为准。
- 未调用真实供应商或付费 API，未测试公网/大并发；没有新增 Maestro/Comfy 认证协议，没有实现 Replicate 音频。voice_type 本轮新增用例仅验证解析/冻结，真实语音适配器保留原协议回归；最少一个相关媒体真实生成由 n=2 图片及两个原生无认证图片用例完成。
- 既有 websockets 弃用和 Vite chunk warning 保留，历史连接超时未重新归因。
- 请外部审核关注这三项实际功能缺陷及现有安全边界；若需要返修，给出最小必要改动，不扩展架构或提前进入 P5。
