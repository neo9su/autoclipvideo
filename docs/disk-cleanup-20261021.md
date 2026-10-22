# 203 F盘失败作业残留归档

清理前C盘约32.33 GiB可用、F盘约12.13 GiB可用。前次仅迁移测试文件不足以缓解F盘。

本轮对象：F:\douyin_recordings\clips 下201个超过7天的旧目录，共2,493文件、约41.737 GiB，历史clip_jobs均为error；生产业务数据库所有TEXT字段均未引用目录ID。当前无运行或排队的clip_jobs。清理前文件链接计数均为1。

每批重新核对生产引用、作业状态及文件时间，按约4 GiB归档，复制到220并验证整包SHA256，再次验证源文件SHA256后移除203副本；不改变数据库，不删除录像源文件、现用片段、成片、模型或账号信息。不重启服务。

## 回退和审计

203：`C:\Users\neo\douyin_backend\codex_rollbacks\disk-cleanup-20261021`。包含候选计划、batches.json、每批manifest.json、archive-info.json、external-copy.json、removed.jsonl、complete.json。

220：`/Users/claw/douyin-cleanup-archive/disk-cleanup-20261021/batch-NNN/`，每批保留clips.tar、manifest.json、archive-info.json、complete.json。

恢复时复制所需批次的clips.tar回203有足够空间的位置，使用restore_203_test_artifacts.py，参数为203该批次日志目录和归档路径；按清单恢复原clips路径，校验整包及逐文件摘要，不覆盖现有不同内容。历史失败作业的日志记录保留，归档位置可由审计目录查得。

清理脚本：scripts/archive_unreferenced_failed_clips.py；220协调脚本：scripts/run_failed_clip_archive.py。
测试：4项归档、摘要、恢复、源文件变更保护测试通过。
