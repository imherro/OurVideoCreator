# P4-R1 开发侧验收映射

固定业务 `e6c3edd95830d4c778fee357b8807d1443920a04`；外部结论仍待签发。

| 范围 | 可复现测试 / 证据 | 边界 |
| --- | --- | --- |
| OVC-P4-01 / MODEL-04 | `test_effective_text_parameters_match_published_limit` 三项；baseline-red / targeted-green | 管理 API + 普通 editor jobs + PG + actual Worker + HTTP SSE |
| 关联温度/数量/音色 | `test_other_declared_controls_cannot_fall_back_when_omitted` 三项、音色枚举两项 | 温度/数量 actual wire；音色为缺失拒绝/合法冻结/发布校验，不冒称实际语音生成 |
| 旧排队快照 | `test_old_queued_missing_parameter_cannot_reach_adapter_fallback` | 实际 Worker 出站前拒绝，不补旧默认 |
| OVC-P4-02 | `test_unsupported_native_key_mode_rejected_before_publication` 两项 + anonymous 两项 | Key 配置 400 零 HTTP；none 两种原生适配器实际生成图片并读资产 |
| OVC-P4-03 | `test_replicate_audio_not_publishable_or_callable` | 红测有效 WAV 失败，绿测禁止发布；不新接音频协议 |
| 三种历史非法组合 | `test_legacy_unsupported_combinations_hidden_and_blocked_at_every_entry` 三项 | 测试夹具模拟旧版本；目录、发布、提交、Worker、恢复全部拒绝，零 HTTP |
| MODEL-01/02/05/06 UI | browser-tool-trace + web-access + db-audit | 原生认证提示、audio 发布 400、普通用户 admin 拒绝、缺失参数 400、100 成功；保存不冒称上游鉴权 |
| MODEL-03/04 批次及分镜 | 原 `test_p4_submission_execution.py` 随完整回归 | 后项 201 原子拒绝、音色后项非法原子拒绝、canonical 帧数与正常独立 Worker |
| MODEL-07/08、SECRET-01 | 原 foundation / rotation HTTP 随完整回归 | Key 轮换/吊销、原 handle 身份、加密失败关闭、跨源认证和 egress 不变 |
| SECRET-02 | 新浏览器 99 JSON、37 表 49 行、4 日志；完整后端 canary | 均零命中；9 JSON 未读、2 SSE body 未扫描明确排除；旧 SSE 证据只按旧 SHA 复用 |
| 保留业务与路由 | 完整后端、frontend-test-build、routes-compile | 既有 Provider/幻场、Film Bible、Twick、FFmpeg、P1–P3 不删测试；实际 96 API 全分类 |

原 P4 外部已认可的 UI 文本/异步图片、轮换和安全证据完整保留于 `../P4/`（业务 3a73165 / 浏览器 0e64bd0）；新结果以本目录 UTC 和 e6c3edd 为准。
