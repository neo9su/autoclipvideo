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

## 本轮实际结果与中断

完成batch-000至batch-007共8批，归档并移除1,792个未引用的失败作业片段，共32,476,700,208字节（约30.25 GiB）。全部8个220归档在主机重启后重新完整计算SHA256，均与最初记录一致。录像源文件、现用剪辑和成片未删除。

第9批复制时203连接超时。恢复连接后确认203刚发生重启，系统记录Kernel-Power 41及EventLog 6008；batch-008刚写的manifest.json与archive-info.json内容为全零。该批尚未生成removed.jsonl，源目录均在。停止剩余三批，保留损坏元数据为*.interrupted-nul，清除3.705 GiB本轮临时clips.tar，并记录stopped-after-host-reboot.json。未为了完成计划而绕过完整性检查。

复查生产SQLite quick_check=ok，平台接口HTTP 200。最终C盘约31.21 GiB、F盘约45.62 GiB可用（后台持续写入，测量过程中有波动）。清理本身未发出任何重启或服务停止指令。未判定硬件故障的具体原因；异常关机仍需另行排查。

恢复/保护测试现共5项通过，包括传输中断后复用已有归档而非重复生成。为降低异常关机时的元数据风险，后续脚本改用临时文件+fsync+原子替换写入清单。协调脚本保持停止，未再次启动清理。
