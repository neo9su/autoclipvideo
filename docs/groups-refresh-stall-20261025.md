# 发布刷新间歇失败：后端主事件循环阻塞

不是仅直播间接口不稳定。现场并发请求/health、/api/rooms、/api/products、/api/codex/publish-groups全部超过20秒无响应。已安装py-spy以--nonblocking只读抓取PID12760：MainThread停在pathlib.stat → is_file → resolve_artifact_path → _artifact_statuses → main.list_groups。日志同段出现约75秒空档；ConnectionResetError是客户端放弃连接后的现象，不能当成唯一根因。

此前只将发布专用/api/codex/publish-groups移到线程，遗漏了公共/api/groups的同步网络文件检查。其它页面/客户端查询公共接口仍阻塞唯一API事件循环，导致发布窗口的直播间、商品、账号和分组一起超时。标签重试补丁只能缓解空白，不能修复服务阻塞。

修复使用现有GroupArtifactSnapshot在线程中完成真实文件校验与发型显示属性计算，保留完整接口数据和权限校验。公共分组接口增加asyncio.Lock合并并发刷新；缓存有效期从计算完成时计时，避免检查本身超过5秒后缓存立即失效。没有增加后台服务或放宽文件存在条件。

依赖依据：[FastAPI官方异步说明](https://fastapi.tiangolo.com/async/)明确阻塞I/O不能直接在异步路径操作的事件循环执行。本次使用项目已采用的asyncio.to_thread，不引入新依赖。

针对性测试4项通过：人为慢文件检查期间事件循环仍可处理请求、并发刷新只进行一次检查、文件可用性/显示字段保留、完成时缓存时间、重复补丁拒绝、底层去重与失败文件回退。部署仅替换备份后的main.py对应函数，由susun交互任务重启后端；不重启GPU，不写数据库，不删除媒体，保留哈希保护回退脚本。
