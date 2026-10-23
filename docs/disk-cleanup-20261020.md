# 203磁盘清理（2026-10-20）

清理前C盘约38.01 GiB可用，F盘约12.15 GiB可用。生产录像源文件、clips、director_outputs、模型、数据库、账号配置均未清理。现有剪辑片段和成片未发现修改时间超过92天的文件。

本次仅迁移明确的安装残留、独立测试预览、旧音频恢复备份：

- C:\Users\neo\AppData\Local\Temp\pip-unpack-limr2yyp
- C:\douyin_login\_test_preview
- F:\douyin_recordings\_opening_fix_audio_backup

共383文件，4,980,742,600字节。清理前检查生产数据库和作业数据库未引用测试/备份目录，没有进程打开这些文件，没有pip安装进程。归档后再次逐文件验证摘要，源文件变化则停止清理。

## 回退

归档保存在220：`/Users/claw/douyin-cleanup-archive/disk-cleanup-20261020/artifacts.tar`。
归档SHA256：`0b3cb18c4f58216aee8ec884817eacc7c3565388ec70408176bcb537bbfaae1a`。
220已独立计算摘要确认与203生成的归档一致。恢复脚本、manifest.json和archive-info.json同时保存在220。

203日志及恢复脚本：`C:\Users\neo\douyin_backend\codex_rollbacks\disk-cleanup-20261020`。
需要恢复时，将220归档复制回203有足够空间的位置，使用该目录restore.py并传入归档路径。脚本验证整包和逐文件摘要，按清单恢复原路径，不覆盖已存在的不同内容。

## 验证

针对清理与恢复的2项测试通过：外部备份可完整恢复，源文件变动会在删除前中止。无生产代码/配置/数据库修改，无服务重启。

## 执行结果

383条移除记录全部写入，203临时归档包也已移除，220校验后的归档保留。清理结束瞬间C盘40.987 GiB、F盘12.145 GiB；稍后运行中复测C盘40.629 GiB、F盘12.145 GiB。逻辑移除4.64 GiB不等于物理释放4.64 GiB：C盘净增约3 GiB，F盘基本未增，不能把备份文件大小误报为F盘释放量。后台持续写入也会影响测量。

平台确认接口HTTP 200，录像源文件、生产片段和成片均未改动。F盘仍然紧张，进一步扩容需要迁移保留中的素材或经引用核对后处理废弃片段。
