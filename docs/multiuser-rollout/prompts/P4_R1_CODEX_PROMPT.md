# P4-R1 · 当前阶段最小必要返修

你负责协作仓库 **imherro/OurVideoCreator** 的 P4-R1。只操作协作仓库，不使用/修改原单机版 MyVideoCreator。

## 授权和版本

P3 已通过：`de5ef13d6c772e62ec8a0e40be7be8abf1eb25d6`  
本轮外部不通过的 P4 业务：`3a73165f74520d0c15ec6f0750d7b2c105108744`  
本轮外部不通过的 evidence HEAD：`c7d6a88a06a01035fd44e45309414c05e061ab64`

外部结论：P4 不通过。仅授权 **P4-R1**，修复下列三个 S2 实际问题并取证。P5/P6、公网部署、真实收费API仍未授权。

开始先核对 branch、HEAD、origin、工作区改动。上述HEAD是验收绑定，不是强制回退目标；保留用户新提交和未提交修改。阅读当前 AGENTS.md、已归档 P4_CODEX_PROMPT、P4_MODEL_CONFIG、MODEL/SECRET矩阵及此轮外部REVIEW/MATRIX。不覆盖旧日志、不自行签发通过。

不重做平台架构，不新增Redis/消息平台/微服务，不做对象协作、团队自带Key、支付/积分/配额。平台仍统一提供Provider/Key/模型。

## OVC-P4-01：实际协议缺省值绕过发布规则

### 已确认路径
- `model_validation.model_definition/parameters` 允许 `rules.max_tokens={"type":"integer","min":1,"max":200}`，同时 `defaults={}`。
- 正常用户省略max_tokens，冻结参数为空。
- `Worker._chat_text` 再加默认 `max_tokens=4096`。
- 外部审核的源码摘录loopback请求已收到4096；尚未代替完整API/PG的复现。

### 必须先补的红测
使用真实隔离PG，经平台管理API创建OpenAI-compatible文本模型与上述规则；用正常获权客户端通过 `/api/projects/{pid}/jobs` 提交不含max_tokens的请求；实际Worker调用你启动的loopback fake SSE，捕获真正HTTP JSON。不得mock掉resolve、参数验证或Worker。
记录模型规则、冻结参数、请求中max_tokens，不记录Key/Authorization原文。红测不能简单断言“现状4096是正确的”。

### 最小修复
允许选择现有实现中最小的方案：
1. 对需要协议缺省值的已声明受限参数要求有效平台默认；或
2. 在受控解析时归一化并验证最终有效值；或
3. 未提供必要有效值时，在出站前明确拒绝。
不允许冻结后由适配器悄悄补越界值。成功调用时，冻结和wire中受限参数应一致。
对当前已有的类似关键字段（温度/数量/voice_type等）做同根因的窄范围检查，只覆盖已支持适配器，不构造通用新规则引擎。
未定义平台限制的固定协议常量无需一律禁用；必须约束的是与已发布范围/枚举冲突的值。
非法显式值仍返回400，不自动夹紧到合法值；不靠UI强制填值代替后端。

### 通过证据
- 省略max_tokens：合法默认且<=200，或请求明确拒绝且fake零调用。
- 显式201：拒绝且零调用。
- 显式100：实际请求100并成功。
- 正常文本/分镜及最少一个相关媒体/音色规则回归不退步；batch后项不合法保持原子拒绝。
- 输出控制参数以冻结数据为准，无Worker阶段静默越界。

## OVC-P4-02：Maestro/Comfy接受API Key却不发送

### 已确认路径
`provider_config`接受两个类型的auth_mode=api_key和非空Key，`_load_binding`可取出明文，但Worker.maestro/Worker.comfy构造client及发请求不附认证；`provider_egress.client`不会从Provider对象自动取Key。
审核端实际loopback摘录观察到 `/api/v1/models` GET、`/prompt` POST均无Authorization并得到401。

### 最小修复：明确二选一，不必扩建协议
- 若当前适配器要支持某个已定义Key协议，按该协议在正确的请求上附加认证，上传/提交/状态/取消保持一致；不得对不属于该来源的下载或redirect透传。
- 若当前原生API只有无认证用法，服务端和UI明确拒绝该类型的api_key模式，保留auth_mode=none且仍需精确部署出站例外。不要接受无效模式再让作业失败。
不为了本条引入新认证框架、代理服务或所有未来厂商适配。

### 通过证据
对每个相关类型，通过真实平台API配置并用实际guarded transport连接自有fake：
- 支持模式：fake断言正确合成凭证（只输出正确/错误布尔或计数），至少首个请求和关键后续请求一致；401不被伪造成成功。
- 不支持模式：配置/发布时明确拒绝，普通目录不出现无法运行组合，不能入队或外呼。
- 无认证合法路径和现有其他Provider不退步；跨源认证禁止、canary日志扫描、Key轮换/吊销回归保留。

## OVC-P4-03：Replicate audio可发布，却当PNG登记

### 已确认路径
`PROVIDER_KINDS['replicate']`含audio，旧create_job_record音频限制造成的保护已移除，Worker.dispatch可直接进入Replicate。
`replicate_api.execute`对非video媒体统一传 `.png` 给download_result；register猜成image/png并用PIL打开，合法WAV/MP3失败。
这不是要求接通新的音频供应商。

### 最小修复
优先在平台定义、发布、目录及调用前校验中一致拒绝当前未接通的replicate/audio，不再向用户宣称可选；保留现有volcengine_speech音频，以及Replicate文本/图片/视频。
若选择继续提供audio，才实现最少的正确格式/输出类型登记并完整fake闭环。不要仅将异常忽略、把PNG改成固定WAV假设所有返回都相同，或直接标succeeded。
不需要迁入旧测试数据，不需新模型平台；旧未完成配置必须明确不可用而不是回退别的Provider。

### 通过证据
- API发布不支持用途即400且零HTTP，普通目录不提供该用途；直接提交也不能绕过。
- 或实际Worker将fake有效音频结果登记为audio、类型/格式一致，页面可用。
- 已支持豆包语音、Replicate文本/图像/视频保持回归。

## 修复组织

三个问题放在这一轮集中处理。先补最小红测，修代码，再执行定向/必要回归和最终全量。不要未经运行就写“已通过”。
评审文件中的源码摘录是定位参考，不能直接替代完整实现测试。全部网络限定自己创建的loopback服务和现有精确出站例外；真实主密钥和上游Key不要提交/打印。
不关停/重启7868用户服务、P3 7895或旧P4保留实例6313/6185。创建新的精确命名PG库、独立端口和媒体目录；清理只针对本轮有所有权记录的资源。

## 保持已认可内容

- PostgreSQL唯一主库与显式增量迁移；
- P3个人账号、CSRF、团队/作品ACL与路由守卫；
- Provider/config/credential/model不可变版本、认证加密、无主密钥失败关闭；
- 旧handle使用原账号/地址，正常轮换retired、显式revoked、disabled含义不变；
- 统一egress IP固定/域名检查/redirect/认证隔离；
- 既有Provider、幻场映射、素材、Film Bible、Twick、FFmpeg和文本/异步图片闭环；
- 提示词平台管理员写、普通读。
不要通过删除这些测试或放宽权限换绿。

## 验证和证据

1. 当前三个问题的真实PG/API/Worker/fake定向用例。外呼只输出安全方法/路径/参数与匿名认证计数，不含凭证。
2. P4 foundation、submission、rotation、相关Provider协议/映射、SECRET canary回归。
3. 完整后端pytest、前端npm test、TypeScript/Vite、实际app.routes守卫、compile；保留失败与warnings。
4. 如果修改表单/目录/错误状态，补对应真实浏览器操作证据即可；已认可的整套P3或未改P4流程不要求为取证工具换框架。新运行时变更的生成链至少有真实Worker成功证据。
5. 取证前固定新业务SHA，后续证据提交仅docs；如测试或代码又改，注明新SHA并重跑受影响项。不要将0e64或3a日志改成新SHA。
6. `evidence/P4-R1/`保存REPORT、SUMMARY、ATTEMPT_HISTORY、原始stdout/stderr/退出码/UTC、最小红绿轨迹和矩阵；写清未运行项、可复用证据与其SHA关系。
7. 构建模块数按实际日志写，旧P4正式为1827，不复制旧摘要1825。历史warnings/超时观察不编造解决原因。
8. canary扫描给实际范围和数量，不把合成密钥零命中宣传成形式化安全证明。敏感浏览器输入只做精确脱敏，保留操作/结果轨迹。

## 交付与停止

交付：
- 开发base、新业务SHA、最终evidence HEAD及远端状态；
- 按OVC-P4-01/02/03逐项列修改文件/函数、红绿测试、实际效果；
- 运行命令、环境、证据路径和warnings/失败/未验证项；
- 新增或移除的已支持组合/默认规则的明确说明；
- 按实际情况报告保留与清理资源。

状态仅`READY_FOR_REVIEW`或`BLOCKED`。更新GATE_LOG记录本次外部不通过以及P4-R1待审，保留历史通过，不自行授予P4通过/P5权限。完成后停止。
