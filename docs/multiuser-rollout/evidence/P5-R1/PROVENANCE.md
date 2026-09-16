# P5-R1 来源与取证边界

## 审核原件

- 主会话：用户指定的 `https://chatgpt.com/c/6aa9f86d-5420-83ea-96c0-06f199b7a0c8`。
- 浏览器“完整审核包”下载 `OurVideoCreator_P5_Audit_5143ee3.zip`，SHA256 `5cd00bbec53779f93268ff0abf65fd03ff0a28cdd28dbf2c073577ece28cfc25`；解包10个文件逐个与 `reviews/P5/` 比较哈希一致。该目录保留外部原始措辞、审核者环境边界及未运行测试草案，不改写为Codex结果。
- 浏览器“完整补充包”下载 `OurVideoCreator_P5_Supplement_OVC-P5-02.zip`，SHA256 `9bf091cdde64c08ebb800174c985fa4cfbb36d533879e19721fe146327b5dc9f`；3个原件与 `reviews/P5-Supplement/` 比较哈希一致。补充结论确认OVC-P5-02并授权R1独立交付准备完成后执行R2，不代表R1/P5已通过。
- 两份完整提示词分别复制到 prompts/P5_R1_CODEX_PROMPT.md 和 P5_R2_CODEX_PROMPT.md，未改变外部范围。

## 代码绑定

- 缺陷基线HEAD：`5143ee36f55ab783f203832558cfedd4efce4936`，继承0851dce运行时。
- 修复业务SHA：`34d646d5c17d5ba12fdc56d4948ab513703731ff`。相对5143，运行时仅 backend/collaboration.py 4增3删；三个测试文件修改/新增，无src运行时变化。
- 基线审核草案复制为 tests/test_p5_review_child_identity.py 后运行，文件SHA256为 `b6ec2c42d0f833cdc3b5af3c00e6b5eaa150a89beb1dde9518378a2eb976cf35`，见红日志头；其原件仍在reviews/P5/repro。
- 正式capture每一步验证HEAD固定且backend/src/tests/scripts/migrations/依赖文件无未提交改动。期间仅编辑docs；不把晚于测试的业务变更塞进evidence提交。

## 运行来源

- baseline-red.txt：真实完整API权限、事务和PG，未mock collaboration。控制请求A删B依赖403，原始三个更新入口200，原断言失败。
- development-green.txt：开发工作区专项，不冒称固定SHA执行。
- targeted-green.txt：固定34d646d执行同样15专项，含实际pg_stat_activity阻塞链和结果；只做入站TestClient，不冒称远端HTTP供应商。
- 完整capture源目录为本任务新建 `ovc-p5-evidence-nmwspojl`，生成脚本 scripts/capture_p5_evidence.py；正式全部日志完成后复制到commands-34d646d。保留其stdout/stderr、命令、UTC与退出码，capture已完成exit0。
- deferred/frontend-late-ack-red.txt：独立实际前端状态机+mock CAS，严格标为红测，未计入默认前端回归，未把模拟service Map写成PostgreSQL。后续R2须加强另一客户端合法CAS/epoch及宿主传播覆盖，不篡改本条早期记录。

## 发布处理

原始日志保留于本轮明确临时目录。prepare_public_evidence.py只在本证据目录的JSON/TXT副本脱敏本机用户路径、检查已知测试密码/登录名/DSN模式；它不删失败行、不改变响应码、计数、时间或SHA。

SHA256SUMS采用Git规范化LF内容，不包含自身及__pycache__。最终追加全部日志之后重建并核对Git staged blobs；取证未结束前的校验表不代表最终交付清单。

不扫描/导出用户数据库、浏览器凭据或无关项目内容，不使用真实付费Provider。历史环境未清理，旧浏览器证据继续归属原P5 SHA。
