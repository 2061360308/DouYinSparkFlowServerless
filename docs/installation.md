# 云端安装联调说明

安装向导现在调用真实后端接口，后端通过已有 ROS 客户端提交模板。管理员完成首次改密后，如果云模式配置不完整，会跳转到 `/install`。设置 `DouyinSparkDocker=true` 的本地模式跳过云安装。

## 上线前准备

系统设置密钥也已改为加密存储。升级前请阅读[系统凭据与调度排查](system-settings-security.md)，使用原加密密钥初始化 `system_secrets` 表并迁移旧值。

执行器现已升级到协议 v3。发布前请先阅读[执行可靠性与升级步骤](execution-reliability.md)，初始化新增表并同步更新任务执行器镜像；旧执行器会被后端拒绝。后台调度重试需按[调度队列](schedule-queue.md)部署持续唤醒入口。

1. 安装根目录 `requirements.txt`，前端在 `panel` 中运行 `npm ci`、`npm run build`。单独打包 API 时也需安装 `server/requirements.txt`，并保留仓库内的 `aliyunFC/install/ros-template.yaml`。
2. 配置共享的持久数据库 `DATABASE_URL`。Serverless 环境不能用临时 SQLite 文件保存安装状态。
3. 在目标数据库上运行 `python -m core.db`，创建新增的 `installation`、`task_schedule_sync` 表及缺失的系统配置项。该命令不会覆盖已有配置；它不是通用的字段迁移工具。发布前备份数据库，在单独的初始化步骤执行，不要让每个请求执行建表。
4. 配置固定的 `SPARK_COOKIE_KEY_B64`（32 字节的 Base64）和 `SPARK_SESSION_KEY_B64`（至少 32 字节的 Base64），关闭 `SPARK_DEV_INSECURE`。
5. 设置 `SPARK_PUBLIC_BASE_URL` 为云函数能访问的控制台 HTTPS 地址，以及至少 32 字符的 `SPARK_SERVICE_TOKEN`。后端将这两项注入任务函数模板，不从浏览器接受覆盖值。
6. 创建管理员并完成首次改密。进入安装页输入具备目标资源权限的阿里云 AK/SK，确认规格后点击部署。此操作会创建可能计费的云资源。

当前模板固定使用杭州地域 `cn-hangzhou`、资源栈名 `DouyinSpark` 及模板默认镜像和资源名称。前后端都会校验函数 CPU、内存、磁盘和超时；更换地域或镜像需要先调整模板与两端参数约束。

## 状态与凭据的归属

- `GET /api/install/status`：仅管理员可读，返回是否需要安装、环境缺项、已有部署摘要。
- `POST /api/install/deploy`：管理员会话及 CSRF 校验；先持久化请求，再提交 ROS。相同请求复用已保存的 ClientToken、模板和参数。
- `POST /api/install/refresh`：管理员会话及 CSRF 校验；查询一次 ROS，并保存状态。尚未获得资源栈 ID 时重放原创建请求。页面每次查询结束后等待 5 秒再查询，离开页面停止后续轮询。

数据库记录是本系统安装状态的依据，ROS 是云资源实际状态的依据。前端不再使用 localStorage 判断是否安装，也不模拟完成百分比。一次安装对应数据库中 ID 为 1 的记录。部署完成后，仅当五项关键输出齐全且函数地址合法，才在同一事务中写入浏览器函数、任务函数、事件总线配置和完成状态。

AK/SK、服务令牌及完整提交内容使用 AES-GCM 加密存储；安装接口与系统设置接口不会返回这份加密记录中的凭据。浏览器管理器在服务端读取解密凭据，云模式后续请求会重新读取配置，因此安装完成后不需要靠进程重启生效。旧系统设置中的手工凭据仍兼容，但新安装不会把凭据写回这些明文字段。

数据库备份应和原加密密钥一同保管。更换 cookie 加密密钥会导致安装凭据无法解密；修改控制台地址或服务令牌也不会自动更新已创建的云函数。

## 恢复与当前边界

创建响应丢失、查询网络失败时，刷新页面或点击“恢复查询”，继续处理原记录。重复提交不同配置会返回 409，不会自动再建一套资源。

失败恢复区支持三步操作，均需管理员会话和 CSRF：

1. `/api/install/credentials` 更新同一云账号的 AK/SK。已知资源栈 ID 时先验证新凭据可访问原栈；未取得 ID 时仍保留原 ClientToken、模板和参数，用户必须确认继续原部署，不能借此切换云账号。
2. `/api/install/cleanup` 需输入完整资源栈 ID。仅允许失败、回滚结束或删除失败的栈；调用前重新查询 ROS，正常运行和创建中的栈不删除。先持久化 `DELETE_REQUESTED`，再请求删除全部栈内资源。响应丢失时恢复查询，先判断云端是否已在删除。
3. `/api/install/reset` 仅在 `DELETE_COMPLETE` 后清除本次安装记录，回到配置页。新部署才生成新的 ClientToken。不要手工删记录绕过检查。已安装系统的迁移、卸载和正常凭据轮换不属于此失败恢复入口。
4. `/api/install/discard` 仅对**从未取得资源栈 ID** 的记录有效（创建请求被 ROS 确定性拒绝，如模板校验失败，重试无法成功且记录卡死在清理/重置之间）。后端会先按原记录幂等重放一次 CreateStack：若当时其实已创建成功则取回 stack_id 拒绝丢弃、改走正常恢复；确认未创建后删除记录允许重新部署。有资源栈 ID 的记录只能走上面的 2/3 步，不能丢弃。

安装成功表示资源栈输出已保存，不表示浏览器及任务业务已经经过真实云环境验证。本次没有创建真实阿里云资源，也没有完成 Vercel 部署验证。已完成记录用于恢复配置，不用于持续监测云资源被外部删除的情况。

## 任务调度

`TaskService` 的创建、编辑、启停会同步一条与业务任务同 ID 的 `ScheduledTask`，使用 `douyin_spark` 处理器及 `params.spark_task_id` 映射。云模式从系统配置读取地域和 EventBridge 总线，并从安装记录解密凭据；不修改进程环境变量。每日时间固定按上海时区生成 cron。

EventBridge 表达式使用“秒 + 标准五段 cron”，保留星期编号；不套用 Quartz 的星期转换。[官方格式与事件示例](https://www.alibabacloud.com/help/en/eventbridge/user-guide/create-a-custom-event-source-of-the-time-trigger-type)。执行器兼容顶层 task_id、data 内 task_id 以及 data.UserData 的 JSON 包装。本次修改了 `aliyunFC/taskrunner/invoke_server.py`，云端应用这些更改前需要重新构建并发布任务执行器镜像，更新对应函数或模板镜像引用；仅更新控制台代码不会更新已发布的容器镜像。

调度器先调用 UpdateEventSource，仅 `EventSourceNotExist` 才创建；权限错误、网络错误及响应体 `Success=false` 都视为失败。更新不会先删掉现有事件源。[接口约定](https://www.alibabacloud.com/help/en/eventbridge/developer-reference/api-eventbridge-2020-04-01-updateeventsource)。

`task_schedule_sync` 记录同步结果并串行化同一任务的外部调度写入。业务任务是启停与时间的依据，ScheduledTask 是执行器读取的映射，EventBridge 是外部触发器。同步失败时仍保存业务任务，接口返回 `schedule_state=error`；前端显示“待同步”，通过带用户权限与 CSRF 的 `POST /api/tasks/{id}/sync` 重试。旧任务也可用该入口补建映射，不会在普通列表读取时批量创建云事件源。

任务删除先持久化暂停，再清理触发器；失败时保留暂停任务，返回 409，用户重试删除。执行接口还会核对业务任务是否存在、启用、账号是否保留、用户是否有效及同步状态，阻止旧触发器继续启动已暂停任务。账号删除和额度自动暂停会尝试移除调度；用户删除必须先完成各任务调度清理。已经进入业务执行的请求不支持强制中断。

同步在请求内完成，数据库锁覆盖一次调度调用；SDK 设置连接和读取超时。没有后台巡检或自动重试队列，断网或进程终止后由页面重试对齐。生产 PostgreSQL 并发、云端重试投递和真实发送链路仍需部署后验证。Docker 本地模式沿用现有 crontab/Windows 计划任务实现，宿主机需具备相应命令和执行器回调环境。

## 本地验证

```powershell
python -m unittest discover -s tests -v
cd panel
npm test
npm run build
```

安装 API 回归使用临时 SQLite 和模拟 ROS，覆盖权限、CSRF、非法规格、创建响应丢失后的请求重放、失败原因脱敏、输出缺失、事务保存、刷新恢复和浏览器配置更新。模拟测试不能证明真实云账号权限、镜像可用性、ROS 模板资源依赖及云函数回调可达性。

扩展场景还覆盖失败资源清理、删除响应丢失、重新安装、任务 CRUD、EventBridge 错误响应、调度重试、暂停执行拦截及删除失败恢复。可在 Vite 的 5175 端口运行时执行 `python tests/ui_scheduling_smoke.py`，使用已安装的 Microsoft Edge 和 Playwright 检查桌面/手机尺寸的搜索、同步与安装恢复；API 全部使用隔离测试数据，截图保存到忽略的 `.local-dev`。
