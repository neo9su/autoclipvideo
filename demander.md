# demander.md — 抖音录屏流水线 需求 & 进度

> 最后更新: 2026-06-17 20:55 CST

## 🔍 2026-06-17 20:55 CST — GPU 监控告警分析

**触发时间：** 2026-06-17 ~20:50 CST（约 170 分钟 GPU 空闲但有积压）

**根本原因分析：**
- GPU 服务本身健康（gpu_busy=false, queue_depth=0），是 idle 状态
- 后端 backfill 在 20:39 和 20:43 各跑了一次，触发了 405+ 个创意/导演版任务
- 但 141 个 director pending 组中，128 个 classic_status=0（经典版合并卡住），12 个 classic_status=-2（出错），只有 1 个 classic_status=2 真正符合 backfill 触发条件
- 275 个 creative pending 组同理：大部分 classic_status != 2，不在 backfill 扫描范围内

**积压分布：**
| 状态 | 导演版 | 自编版 |
|------|--------|--------|
| pending(0) | 141 | 275 |
| running(1) | 1 | 1 |
| done(2) | 1891 | 1470 |
| error(-1) | 640 | 1013 |
| crashed(-2) | 929 | 843 |

**卡住根源：** 128 个组 classic_status=0, merge_status=0（经典版合并未完成）；30 个组 merge_status=-1（合并出错）。这些组从 3 月起就卡住了，classic 未完成导致 director/creative 永远不会被 backfill 触发。

**建议修复：**
1. 对 classic_status=0 的 97 个组执行 merge 重试：`UPDATE clip_groups SET merge_status=0 WHERE classic_status=0 AND merge_status=0`（可能需检查原始 clip 文件）
2. 对 merge_status=-1 的 30 个组检查错误原因
3. backfill 逻辑只扫 classic_status=2 的组，但 3602 个组中只有 1 个 director_status=0 且 classic_status=2，说明大部分积压是经典版合并卡住导致的连锁反应
