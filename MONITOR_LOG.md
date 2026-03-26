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
