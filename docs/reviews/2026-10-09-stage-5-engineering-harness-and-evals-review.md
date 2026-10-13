# 阶段五：工程质量与评测（收口校正版）

当前状态以 [交付收口记录](2026-10-09-delivery-closeout.md) 和原始执行证据为准；[修订前正文](archive/2026-10-09-before-closeout/2026-10-09-stage-5-engineering-harness-and-evals-review.md) 保留用于追溯。

## 本次验证

- 后端：595 passed、0 failed、1 条第三方弃用告警，9.70s；日志与 JUnit 已归档。
- 前端：68 个 Vitest 用例与 4 个 TSX 专项脚本通过；lint 的编码、契约和类型检查通过；当次编码扫描 397 个文件。
- 构建成功：index 158.71 kB（gzip 49.14 kB）、Cesium 3593.75 kB、OpenLayers 328.26 kB、vendor 1249.54 kB、lucide 17.58 kB。
- 入口仍预加载 vendor/Cesium/OpenLayers；分块体积不能证明首屏资源量下降 97%，未测量首屏时间。
- GitHub Actions workflow 已配置并纠正名称与触发范围；未查询远程运行与分支保护，不称强制门禁已验收。

## E2E 与检索评测

- 历史 handoff-final-full：2026-09-26 的 36/36 结果可重新汇总，有 36 张截图文件；不是本次重构后的全量回归。
- 当次 2026-10-09-closeout：按用户要求中断，4 条结果中 3 完成、K02 引用断言失败，32 未执行。没有最终冻结版本的完整 E2E 通过证据。
- 检索脚本根据黄金标签构造候选，8 条查询的 MRR/Recall/HitRate 是合成排序消融结果，已在报告标注 synthetic_ablation 与 live_retrieval=false；不作为实际数据库检索质量。

本阶段已完成当前范围的自动化回归与证据归档。端到端能力验收仍按收口记录中的后续事项推进，不宣称零回归或全部基线闭环。
