# P5-R1 / OVC-P5-01 逐项复验

绑定业务34d646d5c17d5ba12fdc56d4948ab513703731ff，证据78fd14f40339e0b71908a685efb2354a0c1045ce。

| 原通过标准 | 已检查实现和证据 | 结论 |
|---|---|---|
| 原三入口不得留下悬空依赖 | 公共node_identity_changed检查；应用/PG三入口422；完整对象及三类记录计数不变 | 通过 |
| add/remove/rename合法操作可完成 | 含graph原子提交200；topological通过 | 通过 |
| graph存在不能代替有效性 | 边/positions/nodeOrder/shotOrder负例422；旧版本409；混合create无半写 | 通过 |
| 他人依赖不能自动移除或接管 | 目标B时即使完整清理仍403且状态不变 | 通过 |
| 恢复和复用入口不出现旁路 | restore走commands；改变子节点身份的单独恢复422；候选/导入既有回归保留 | 通过，限已审范围 |
| 真PG图竞争精确提交 | 记录数据库waiter；[409,200]；shot/graph内容版本和记录数匹配胜者 | 通过 |
| 普通正文继续独立 | 未改变node_ids不新增graph要求；原独立对象PG测试及前端请求测试通过 | 通过 |
| 前端合法命令不回归 | 实际CollaborationClient+mock transport验证shot/graph同请求；src未变 | 通过，不冒称浏览器重跑 |
| 正式SHA证据对应 | 根Git树仅docs不同；红/绿和开发/正式分开 | 通过 |

本表不是COLLAB全项或P5整体通过：OVC-P5-02仍未修复，继续P5-R2。
