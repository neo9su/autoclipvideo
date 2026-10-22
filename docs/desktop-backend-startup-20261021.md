# 发布后端固定使用交互式桌面启动

## 根因

旧的Wd8899Sys看门狗连续检查失败后强杀8899，并启动SYSTEM身份的Uvicorn8899。成功检查没有清零旧miss计数。同时多套历史启动任务保持启用，包含开机、定时和SYSTEM入口，导致桌面监督程序尚未取得监听端口时服务会话先启动。

## 修改

保留DouyinBackend8899SusunInteractive为唯一后端启动任务（susun，InteractiveToken）；Wd8899Sys仅负责请求该任务。禁用8个历史竞争入口：Uvicorn8899、DouyinBackend8899System、DouyinRemoteBackend8899、DouyinRemoteBackend8899Interactive、Diag8899Susun、Douyin8899User、DouyinBe8899B、Restart8899Interactive。

新看门狗遇到监听端口忙、HTTP暂时无响应或现有Session 0时仅报告，不强杀、不重复启动。健康恢复清零计数；无监听时达到阈值才调用桌面任务，不设SYSTEM回退。

桌面启动器用自身进程的SessionId判断，而非解析quser的Active状态；断开RDP后仍能监督子进程。启动任务无执行时限，失败后每分钟重试、最多3次，控制台隐藏。未修改账号凭证、自动登录设置或GPU服务。

## 备份与回退

203目录：`C:\Users\neo\douyin_backend\codex_rollbacks\desktop-startup-20261022-131449`。
包含10个相关任务的原始XML、启用/运行状态、两个原始脚本、前后摘要、rollback.py、recovery-verification.json。备份在修改之前持久化保存。原启动脚本包含本机配置，仅保存在203私有备份，不写入GitHub。

必要时在没有运行中发布任务时执行该目录rollback.py，按摘要校验恢复原始脚本及任务配置/启用状态。回退会恢复旧入口，需明确评估后执行；不自动启动SYSTEM后端，不回滚数据库。

## 验证

- 5项针对性单元测试通过：健康清零、忙碌监听保护、Session 0保护、无监听只启动桌面任务、无登录无SYSTEM回退。
- Windows PowerShell解析新启动脚本成功，部署摘要一致。
- 受控停止空闲后端后，由新看门狗恢复：PID8660 Session2 → PID13188 Session2；持续观察后重复检查healthy，仅一个后端实例。
- 实际运行Wd8899Sys计划任务，核对最终结果。
- 健康接口HTTP200；8个旧入口全部Disabled，主任务Running且Interactive，执行时限PT0S、失败重试PT1M/3次。

没有重启整机、上传视频或提交作品。完整的开机→登录链路尚未实测。Windows必须已有susun登录的交互会话才能启动可见发布浏览器；无桌面登录时不会退回Session0。此前的异常关机问题独立存在，本轮未排查其硬件原因。
