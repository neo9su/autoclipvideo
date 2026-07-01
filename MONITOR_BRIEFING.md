# 监控简报 — 2026-06-25 09:05

本文档由 health_monitor.py 在 09:00 本地时间自动生成。

## 监控日志摘要

# 系统监控日志 — 2026-03-26

监控开始时间: 2026-03-26T03:07 UTC (11:07 本地时间)
监控间隔: 每5分钟
监控人: Claude (自动)

---

## 事件记录

### 03:07 UTC — 监控启动 & 队列修复

**问题发现**: 17条录像（16条>200MB大文件）全部卡在"待上传"状态，长达数小时。

**根本原因**: `segment_merger.py` 中 `_split_and_register()` 函数在插入分块DB记录时未包含 `start_time` 字段，但该字段有 `NOT NULL` 约束。每次轮询时：
1. ffmpeg分块成功（文件已在磁盘）
2. DB INSERT抛出约束异常
3. 整个轮询迭代中止
4. `last_submit_at` 永远不更新

**修复操作**:
1. 修复 `segment_merger.py`: INSERT语句加入 `start_time` 字段
2. 手动修复DB: 为16条录像注册59个分块记录，更新原始行指向chunk000，删除原始大文件
3. 调用 `/api/transcribe/flush` 唤醒轮询

**修复后状态**:
- `gpu_busy: true`
- `queue_depth: 23`
- `pending_transcribe: 25`
- `active_job_id: 1_20260325_215333_002_chunk001`
- `last_submit_at: 2026-03-26T03:07:08Z`

---

| UTC时间 | pending | gpu_busy | queue_depth | active_job | 操作 |
|---------|---------|----------|-------------|------------|------|
| 03:07 | 25 | true | 23 | 1_20260325_215333_002_chunk001 | 队列修复完成，开始上传 |
| 03:10 | 58 | true | 53 | 2_20260326_022708_006_chunk001 | 正常，持续上传中 |
| 03:15 | 34 | true | 31 | (全部已提交) | 正常。34=33个GPU在处理+1个文件尚未到达。无需操作 |
| 03:21 | 17 | true | 13 | (全部已提交) | 正常，进展顺利。⚠️ ComfyUI自动重启(restart_count=2, 24s前)，现已恢复healthy |
| 03:25 | 0 | false | 0 | - | GPU队列清空。但发现65个chunk全部transcribed=-1 (OOM错误) |
| 03:26-04:11 | - | - | - | - | 问题排查：OOM原因=第一批提交时GPU并发，chunk重传失败原因=GPU jobs.db存有旧记录(UNIQUE冲突) |
| 04:11 | 33 | true | 2+ | 1_20260325_210333_000_chunk000 | ✅ 已修复：SSH删除GPU jobs.db中65条chunk错误记录，重启GPU服务，重新上传成功 |
| 04:20 | 0 | false | 0 | - | GPU服务再次崩溃(restart_count=4)。仅完成6/65个chunk。原因: 内存泄漏 |
| 04:26-04:39 | - | - | - | - | 问题排查+修复: 向_do_transcribe添加finally块(gc.collect+torch.cuda.empty_cache) |
| 04:39 | 12 | true | 1 | - | ✅ 应用内存清理补丁，重启服务，重置59个chunk，重新开始转录 |
| 04:45 | 15 | true | 14 | 1_20260325_210333_000_chunk003 | ✅ 内存补丁有效！ram_free=11.2GB(之前4GB)，无新崩溃，队列正常推进 |
| 04:51 | 34 | true | 33 | 2_20260325_232612_000_chunk003 | 正常。chunk_done=6, in-flight=51, queue_depth=33, ram_free=11.1GB稳定 |
| 04:56 | 0 | false | 0 | - | ⚠️ GPU再次崩溃(restart_count=5)。chunk_done=10, 55个失败"service restarted"。剪辑作业正在收尾(thumbnail阶段) |
| 04:57 | - | - | - | - | 等待ComfyUI clip渲染结束(GPU ram_free 3.1GB→9GB)，重试55个chunk |
| 04:58 | 8 | true | 1 | - | ✅ GPU重启+DB清理，55个chunk重置，重新上传中，ram_free=9GB |
| 05:03 | 0 | true | 0 | - | GPU服务再次崩溃(restart_count=5)，chunk_done=10, err=12。剪辑作业thumbnail收尾中 |
| 05:06 | 8 | true | 3 | 1_20260325_234647_001_chunk000 | ✅ 新补丁：每次转录后 _model=None (卸载Whisper)，彻底释放VRAM+RAM。重置55chunk重试 |
| 05:07 | 53 | true | 24 | - | ⚠️ GPU再次崩溃(restart_count=4)，53个chunk→"service restarted"。修复：GPU DB清54条错误记录，重置53个chunk，修复46个end_time=NULL，重启GPU服务，flush。队列恢复 |
| 05:12 | 52 | true | 38 | 2_20260326_001824_000_chunk002 | ✅ 正常推进。restart_count=4(未新增崩溃)，ram_free=9.2GB稳定，_model=None补丁疑似生效 |
| 05:17 | 0 | false | 0 | - | ⚠️ GPU崩溃(restart_count=5)，49chunk→service restarted。chunk_done=12。排查根因：CTranslate2 GIL在模型加载时阻塞event loop→watchdog 5s超时→重启 |
| 05:37 | 46 | false | 0 | - | ⚠️ 连续崩溃 restart_count=7。两次失败尝试：startup pre-warm(OOM)、model reload latency。当前状态：restart_count=7 healthy=True chunk(done=12 in-queue=19 pending=25 error=7) |
| 05:42 | 42 | true | 41 | 2_20260326_022708_006_chunk001 | ✅ 稳定运行中！restart_count=7(无新崩溃)，uptime=166s，队列正常推进 |

| 07:25 UTC | gpu=True pending=0 busy=False | - | - | 前端已重建v1.2.0，发布页商品筛选+分组刷新修复，GPU service编码损坏修复+int8_float16，后端已重启 |
| 07:33 UTC | pending=0 | gpu_busy=false | queue_depth=0 | - | ✅ 系统正常。GPU在线(uptime=17min,restart_count=10)，队列清空，enhance无错误，clip队列空 |
| 07:50 UTC | pending=0 | gpu_busy=false | queue_depth=0 | - | ✅ 正常。GPU在线(uptime=33min,restart=10)，队列空，enhance无任务，clip空，ram_free=4GB |
| 07:58 UTC | pending=0 | gpu_busy=false | queue_depth=0 | - | ✅ 正常。GPU在线(uptime=44min,restart=10稳定)，所有队列空，ram=4GB |
| 08:00 UTC | pending=0 | gpu_busy=false | queue_depth=0 | - | ✅ 正常(整点快照已写PROJECT_SUMMARY)。GPU uptime=47min restart=10稳定，全队列空 |
| 03:21 UTC | pending=49 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 03:26 UTC | pending=49 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 03:31 UTC | pending=49 gpu_busy=False queue=0 | 队列卡住(pending=49, 10min无提交); Watchdog不可达 | flush成功 |
| 03:36 UTC | pending=49 gpu_busy=False queue=0 | 队列卡住(pending=49, 15min无提交); Watchdog不可达 | flush成功 |
| 03:41 UTC | pending=49 gpu_busy=False queue=0 | 队列卡住(pending=49, 20min无提交); Watchdog不可达 | flush成功 |
| 03:46 UTC | pending=47 gpu_busy=False queue=0 | 队列卡住(pending=47, 25min无提交); Watchdog不可达 | flush成功 |
| 03:51 UTC | pending=47 gpu_busy=False queue=0 | 队列卡住(pending=47, 30min无提交); Watchdog不可达 | flush成功 |
| 03:56 UTC | pending=46 gpu_busy=False queue=0 | 队列卡住(pending=46, 35min无提交); Watchdog不可达 | flush成功 |
| 04:01 UTC | pending=46 gpu_busy=False queue=0 | 队列卡住(pending=46, 40min无提交); Watchdog不可达 | flush成功 |
| 04:06 UTC | pending=46 gpu_busy=False queue=0 | 队列卡住(pending=46, 45min无提交); Watchdog不可达 | flush成功 |
| 04:11 UTC | pending=46 gpu_busy=False queue=0 | 队列卡住(pending=46, 50min无提交); Watchdog不可达 | flush成功 |
| 04:16 UTC | pending=46 gpu_busy=False queue=0 | 队列卡住(pending=46, 55min无提交); Watchdog不可达 | flush成功 |
| 04:21 UTC | pending=44 gpu_busy=False queue=0 | 队列卡住(pending=44, 60min无提交); Watchdog不可达 | flush成功 |
| 04:26 UTC | pending=44 gpu_busy=False queue=0 | 队列卡住(pending=44, 65min无提交); Watchdog不可达 | flush成功 |
| 04:31 UTC | pending=44 gpu_busy=False queue=0 | 队列卡住(pending=44, 70min无提交); Watchdog不可达 | flush成功 |
| 04:36 UTC | pending=44 gpu_busy=False queue=0 | 队列卡住(pending=44, 75min无提交); Watchdog不可达 | flush成功 |
| 04:41 UTC | pending=44 gpu_busy=False queue=0 | 队列卡住(pending=44, 80min无提交); Watchdog不可达 | flush成功 |
| 04:46 UTC | pending=44 gpu_busy=False queue=0 | 队列卡住(pending=44, 85min无提交); Watchdog不可达 | flush成功 |
| 04:51 UTC | pending=44 gpu_busy=False queue=0 | 队列卡住(pending=44, 90min无提交); Watchdog不可达 | flush成功 |
| 04:56 UTC | pending=44 gpu_busy=False queue=0 | 队列卡住(pending=44, 95min无提交); Watchdog不可达 | flush成功 |
| 05:01 UTC | pending=44 gpu_busy=False queue=0 | 队列卡住(pending=44, 100min无提交); Watchdog不可达 | flush成功 |
| 05:06 UTC | pending=44 gpu_busy=False queue=0 | 队列卡住(pending=44, 105min无提交); Watchdog不可达 | flush成功 |
| 05:11 UTC | pending=35 gpu_busy=False queue=0 | 队列卡住(pending=35, 110min无提交); Watchdog不可达 | flush成功 |
| 05:16 UTC | pending=35 gpu_busy=False queue=0 | 队列卡住(pending=35, 115min无提交); Watchdog不可达 | flush成功 |
| 05:21 UTC | pending=10 gpu_busy=False queue=0 | 队列卡住(pending=10, 120min无提交); Watchdog不可达 | flush成功 |
| 05:26 UTC | pending=10 gpu_busy=False queue=0 | 队列卡住(pending=10, 125min无提交); Watchdog不可达 | flush成功 |
| 05:31 UTC | pending=6 gpu_busy=False queue=0 | 队列卡住(pending=6, 130min无提交); Watchdog不可达 | flush成功 |
| 05:36 UTC | pending=5 gpu_busy=False queue=0 | 队列卡住(pending=5, 135min无提交); Watchdog不可达 | flush成功 |
| 05:41 UTC | pending=3 gpu_busy=False queue=0 | 队列卡住(pending=3, 140min无提交); Watchdog不可达 | flush成功 |
| 05:46 UTC | pending=2 gpu_busy=False queue=0 | 队列卡住(pending=2, 145min无提交); Watchdog不可达 | flush成功 |
| 05:51 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 05:56 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 06:01 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 06:06 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 06:11 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 06:16 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 06:21 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 06:26 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 06:31 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 06:36 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 06:41 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 06:46 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 06:51 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 06:56 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 07:01 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 07:06 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 07:11 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 07:16 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 07:21 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 07:26 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 07:31 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 07:36 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 07:41 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 07:46 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 07:51 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 07:56 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 08:01 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 08:06 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 08:11 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 08:16 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 08:21 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 08:26 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 08:31 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 08:36 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 08:41 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 08:46 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 08:51 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 08:56 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 09:01 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 09:06 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 09:11 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 09:16 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 09:21 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 09:26 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 09:31 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 09:36 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 09:41 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 09:46 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 09:51 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 09:56 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 10:01 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 10:06 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 10:11 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 10:16 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 10:21 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 10:26 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 10:31 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 10:36 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 10:41 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 10:46 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 10:51 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 10:56 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 11:01 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 11:07 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 11:12 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 11:17 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 11:22 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 11:27 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 11:32 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 11:37 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 11:42 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 11:47 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 11:52 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 11:57 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 12:02 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 12:07 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 12:12 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 12:17 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 12:22 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 12:27 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 12:32 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 12:37 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 12:42 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 12:47 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 12:52 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 12:57 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 13:02 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 13:07 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 13:12 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 13:17 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 13:22 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 13:27 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 13:32 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 13:37 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 13:42 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 13:47 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 13:52 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 13:57 UTC | pending=3 gpu_busy=False queue=0 | 队列卡住(pending=3, 636min无提交); Watchdog不可达 | flush成功 |
| 14:02 UTC | pending=3 gpu_busy=False queue=0 | 队列卡住(pending=3, 641min无提交); Watchdog不可达 | flush成功 |
| 14:07 UTC | pending=3 gpu_busy=False queue=0 | 队列卡住(pending=3, 646min无提交); Watchdog不可达 | flush成功 |
| 14:12 UTC | pending=3 gpu_busy=False queue=0 | 队列卡住(pending=3, 651min无提交); Watchdog不可达 | flush成功 |
| 14:17 UTC | pending=3 gpu_busy=False queue=0 | 队列卡住(pending=3, 656min无提交); Watchdog不可达 | flush成功 |
| 14:22 UTC | pending=6 gpu_busy=False queue=0 | 队列卡住(pending=6, 661min无提交); Watchdog不可达 | flush成功 |
| 14:27 UTC | pending=7 gpu_busy=False queue=0 | 队列卡住(pending=7, 666min无提交); Watchdog不可达 | flush成功 |
| 14:32 UTC | pending=7 gpu_busy=False queue=0 | 队列卡住(pending=7, 671min无提交); Watchdog不可达 | flush成功 |
| 14:37 UTC | pending=7 gpu_busy=False queue=0 | 队列卡住(pending=7, 676min无提交); Watchdog不可达 | flush成功 |
| 14:42 UTC | pending=7 gpu_busy=False queue=0 | 队列卡住(pending=7, 681min无提交); Watchdog不可达 | flush成功 |
| 14:47 UTC | pending=7 gpu_busy=False queue=0 | 队列卡住(pending=7, 686min无提交); Watchdog不可达 | flush成功 |
| 14:52 UTC | pending=10 gpu_busy=False queue=0 | 队列卡住(pending=10, 691min无提交); Watchdog不可达 | flush成功 |
| 14:57 UTC | pending=10 gpu_busy=False queue=0 | 队列卡住(pending=10, 696min无提交); Watchdog不可达 | flush成功 |
| 15:02 UTC | pending=10 gpu_busy=False queue=0 | 队列卡住(pending=10, 701min无提交); Watchdog不可达 | flush成功 |
| 15:07 UTC | pending=10 gpu_busy=False queue=0 | 队列卡住(pending=10, 706min无提交); Watchdog不可达 | flush成功 |
| 15:12 UTC | pending=10 gpu_busy=False queue=0 | 队列卡住(pending=10, 711min无提交); Watchdog不可达 | flush成功 |
| 15:17 UTC | pending=14 gpu_busy=False queue=0 | 队列卡住(pending=14, 716min无提交); Watchdog不可达 | flush成功 |
| 15:22 UTC | pending=14 gpu_busy=False queue=0 | 队列卡住(pending=14, 721min无提交); Watchdog不可达 | flush成功 |
| 15:27 UTC | pending=14 gpu_busy=False queue=0 | 队列卡住(pending=14, 726min无提交); Watchdog不可达 | flush成功 |
| 15:32 UTC | pending=14 gpu_busy=False queue=0 | 队列卡住(pending=14, 731min无提交); Watchdog不可达 | flush成功 |
| 15:37 UTC | pending=14 gpu_busy=False queue=0 | 队列卡住(pending=14, 736min无提交); Watchdog不可达 | flush成功 |
| 15:42 UTC | pending=23 gpu_busy=False queue=0 | 队列卡住(pending=23, 741min无提交); Watchdog不可达 | flush成功 |
| 15:47 UTC | pending=23 gpu_busy=False queue=0 | 队列卡住(pending=23, 746min无提交); Watchdog不可达 | flush成功 |
| 15:52 UTC | pending=23 gpu_busy=False queue=0 | 队列卡住(pending=23, 751min无提交); Watchdog不可达 | flush成功 |
| 15:57 UTC | pending=23 gpu_busy=False queue=0 | 队列卡住(pending=23, 756min无提交); Watchdog不可达 | flush成功 |
| 16:02 UTC | pending=23 gpu_busy=False queue=0 | 队列卡住(pending=23, 761min无提交); Watchdog不可达 | flush成功 |
| 16:07 UTC | pending=26 gpu_busy=False queue=0 | 队列卡住(pending=26, 766min无提交); Watchdog不可达 | flush成功 |
| 16:12 UTC | pending=26 gpu_busy=False queue=0 | 队列卡住(pending=26, 771min无提交); Watchdog不可达 | flush成功 |
| 16:17 UTC | pending=27 gpu_busy=False queue=0 | 队列卡住(pending=27, 776min无提交); Watchdog不可达 | flush成功 |
| 16:27 UTC | pending=30 gpu_busy=False queue=0 | 队列卡住(pending=30, 786min无提交); Watchdog不可达 | flush成功 |
| 16:32 UTC | pending=32 gpu_busy=False queue=0 | 队列卡住(pending=32, 791min无提交) | flush成功 |
| 16:37 UTC | pending=28 gpu_busy=False queue=0 | 队列卡住(pending=28, 797min无提交) | flush成功 |
| 16:42 UTC | pending=24 gpu_busy=False queue=0 | 队列卡住(pending=24, 802min无提交) | flush成功 |
| 16:47 UTC | pending=22 gpu_busy=False queue=0 | 队列卡住(pending=22, 807min无提交) | flush成功 |
| 16:52 UTC | pending=23 gpu_busy=False queue=0 | 队列卡住(pending=23, 812min无提交) | flush成功 |
| 16:57 UTC | pending=29 gpu_busy=False queue=0 | 队列卡住(pending=29, 817min无提交); Watchdog不可达 | flush成功 |
| 17:02 UTC | pending=29 gpu_busy=False queue=0 | 队列卡住(pending=29, 822min无提交) | flush成功 |
| 17:07 UTC | pending=28 gpu_busy=False queue=0 | 队列卡住(pending=28, 827min无提交) | flush成功 |
| 17:13 UTC | pending=27 gpu_busy=False queue=0 | 队列卡住(pending=27, 832min无提交) | flush成功 |
| 17:23 UTC | pending=25 gpu_busy=False queue=0 | 队列卡住(pending=25, 842min无提交) | flush成功 |
| 17:28 UTC | pending=23 gpu_busy=False queue=0 | 队列卡住(pending=23, 847min无提交) | flush成功 |
| 17:33 UTC | pending=20 gpu_busy=False queue=0 | 队列卡住(pending=20, 852min无提交) | flush成功 |
| 17:38 UTC | pending=18 gpu_busy=False queue=0 | 队列卡住(pending=18, 857min无提交) | flush成功 |
| 17:43 UTC | pending=18 gpu_busy=False queue=0 | 队列卡住(pending=18, 862min无提交) | flush成功 |
| 17:48 UTC | pending=22 gpu_busy=False queue=0 | 队列卡住(pending=22, 867min无提交) | flush成功 |
| 17:53 UTC | pending=21 gpu_busy=False queue=0 | 队列卡住(pending=21, 872min无提交) | flush成功 |
| 17:58 UTC | pending=21 gpu_busy=False queue=0 | 队列卡住(pending=21, 877min无提交); Watchdog不可达 | flush成功 |
| 18:03 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 18:08 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 18:13 UTC | pending=5 gpu_busy=False queue=0 | 队列卡住(pending=5, 892min无提交); Watchdog不可达 | flush成功 |
| 18:18 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 18:23 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 18:28 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 18:33 UTC | pending=0 gpu_busy=False queue=0 | Watchdog不可达 | - |
| 18:38 UTC | pending=5 gpu_busy=False queue=0 | 队列卡住(pending=5, 917min无提交); Watchdog不可达 | flush成功 |
| 18:43 UTC | pending=5 gpu_busy=False queue=0 | 队列卡住(pending=5, 922min无提交); Watchdog不可达 | flush成功 |
| 18:48 UTC | pending=5 gpu_busy=False queue=0 | 队列卡住(pending=5, 927min无提交); Watchdog不可达 | flush成功 |
| 18:53 UTC | pending=5 gpu_busy=False queue=0 | 队列卡住(pending=5, 932min无提交); Watchdog不可达 | flush成功 |
| 18:58 UTC | pending=5 gpu_busy=False queue=0 | 队列卡住(pending=5, 937min无提交); Watchdog不可达 | flush成功 |
| 19:03 UTC | pending=10 gpu_busy=False queue=0 | 队列卡住(pending=10, 942min无提交); Watchdog不可达 | flush成功 |
| 19:08 UTC | pending=10 gpu_busy=False queue=0 | 队列卡住(pending=10, 947min无提交) | flush成功 |
| 19:13 UTC | pending=7 gpu_busy=False queue=0 | 队列卡住(pending=7, 952min无提交) | flush成功 |
| 19:18 UTC | pending=3 gpu_busy=False queue=0 | 队列卡住(pending=3, 957min无提交) | flush成功 |
| 19:23 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 19:28 UTC | pending=2 gpu_busy=False queue=0 | 队列卡住(pending=2, 967min无提交) | flush成功 |
| 19:33 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 19:38 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 19:43 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 19:48 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 19:53 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 19:58 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 20:03 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 20:08 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 20:13 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 20:18 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 20:23 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 20:28 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 20:33 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 20:38 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 20:43 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 20:48 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 20:53 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 20:58 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 21:03 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 21:08 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 21:13 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 21:19 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 21:24 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 21:29 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 21:34 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 21:39 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 21:44 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 21:49 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 21:54 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 21:59 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 22:04 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 22:09 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 22:14 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 22:19 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 22:24 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 22:29 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 22:34 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 22:39 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 22:44 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 22:49 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 22:54 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 22:59 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 23:04 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 23:09 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 23:14 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 23:19 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 23:24 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 23:29 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 23:34 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 23:39 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 23:44 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 23:49 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 23:54 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 23:59 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 00:04 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 00:09 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 00:14 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 00:19 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 00:24 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 00:30 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 00:35 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 00:40 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 00:45 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 00:50 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 00:55 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 01:00 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |
| 01:05 UTC | pending=0 gpu_busy=False queue=0 | 正常 | - |

