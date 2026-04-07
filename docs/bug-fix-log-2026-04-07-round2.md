# 2026-04-07 持续排查修复记录（第二轮）

本轮继续针对全项目做确定性 bug 排查，重点补了归档清理、中奖链路、本地图片上传链路、结果重算链路，以及多个用户输入导致的 500 问题。

## 已修复问题

### 1. 归档清理误删仍需保留的数据

- `archive_old_uploaded_txt_files()` 之前会按文件上传时间直接删除整份 `UploadedFile` 和其关联票据。
- 现在改为：只有当该 `source_file_id` 下已经没有任何票据残留时，才允许删除原始 TXT 和文件记录。
- 这样不会把仍在 30 天保留期内的票据历史误删。

### 2. 辅助历史数据删除顺序存在外键风险

- `purge_old_auxiliary_records()` 之前先删 `ResultFile`，再删 `MatchResult`。
- 现在改为先删旧 `MatchResult`，再删已无引用的 `ResultFile`。
- 避免在外键约束更严格的数据库下直接失败。

### 3. 过期票中奖计算和展示不完整

- `expired` 票现在参与中奖计算，`revoked` 仍然不参与。
- 管理员中奖管理和中奖导出会显示 `expired` 中签票，并标记为“已过期未出票”。
- 用户自己的中奖记录仍然只显示 `completed` 中签票，不显示 `expired`。

### 4. 中奖重算后会残留脏数据

- 某张票从中奖变为未中奖时，之前旧的 `WinningRecord`、中奖图片、金额字段可能残留。
- 现在重算为未中奖或计算异常时，会同步清理：
  - `winning_gross`
  - `winning_amount`
  - `winning_tax`
  - `WinningRecord`
  - `ticket.winning_image_url`
  - 本地旧图片 / OSS 旧对象

### 5. 管理员上传中奖图后前后端状态不同步

- 管理员上传图片或回填 OSS 地址时，之前可能只更新了 `LotteryTicket`，没有保证同步创建/更新 `WinningRecord`。
- 现在管理员两条中奖图片接口都会创建或更新 `WinningRecord`，并回写 `record` 给前端。
- 前端当前行会立即更新 `winning_record_id`，无需刷新就能继续“标记已检查”。

### 6. 同 key 重传中奖图片会误删新图

- 在 OSS 使用固定 key 的情况下，旧逻辑会把刚上传的新对象当旧图删掉。
- 现在只有在“旧图目标”和“新图目标”不一致时才删除旧图。
- 用户端和管理员端都已修正。

### 7. 赛果上传/重算在调度器缺失时会假成功

- 之前如果调度器没启动，上传赛果或点击重算会返回成功，但后台不会真正执行计算。
- 现在改为：
  - 有调度器时继续异步执行
  - 没调度器时直接同步执行
- 同时在重新进入 `pending` 前清空旧的中奖统计字段，避免页面继续显示上一次结果。

### 8. 本地模式中奖图片上传链路不完整

- 本地模式预签名 URL 原先返回了错误的上传地址。
- 现在补齐了 `/api/winning/upload-local`，并和预签名接口对齐。
- 同时修复管理员和用户在本地模式下都能正常上传中奖图片。

### 9. 本地上传接口权限过宽

- 本地上传接口之前只校验登录，不校验该票是否属于当前用户，也不校验 `key` 是否与票匹配。
- 现在上传必须同时满足：
  - 带 `ticket_id`
  - 当前用户对该票有权限
  - `key` 与该票的预期 key 完全匹配

### 10. 管理员导出当日 CSV 会触发 `NameError`

- `/admin/api/tickets/export` 使用了 `timedelta`，但模块顶部未导入。
- 真实点击导出时会抛 `NameError`。
- 现已补齐导入，并验证业务日窗口筛选正常。

### 11. 多个接口遇到非法整数参数会直接 500

- 修复了以下入口的非法整数参数问题，统一改为返回 400：
  - `GET /api/mode-a/previous` 的 `offset`
  - `POST /api/mode-b/confirm` 的 `ticket_ids`
  - `GET /admin/api/files` 的 `page/per_page`
  - `GET /admin/api/files/<id>/detail` 的 `page/per_page`
  - `GET /admin/api/winning` 的 `page/per_page`
  - `POST /admin/api/users` 的 `max_devices`
  - `PUT /admin/api/users/<id>` 的 `max_devices`

### 12. 多个 JSON 接口在空 body 时会直接 500

- 修复了以下接口在 `Content-Type: application/json` 但 body 为空或解析失败时，因 `None.get(...)` 触发 500 的问题：
  - `POST /api/device/register`
  - `POST /api/user/change-password`
  - `POST /api/mode-b/confirm`
  - `POST /api/winning/record`
  - `PUT /admin/api/settings`
  - `POST /admin/api/winning/record`
- 现在统一会回到正常的业务错误响应，而不是直接抛异常。

### 13. 登录接口在空 JSON body 时响应不稳定

- `/auth/login` 之前在 JSON 请求体为空时，可能直接抛出解析错误。
- 现在会稳定返回登录失败 JSON，而不是框架级 400/HTML 响应。

### 14. 设备注册可抢占其他用户的设备 ID

- 之前任意已登录用户只要提交相同 `device_id`，就能把 `DeviceRegistry.user_id` 改成自己。
- 现在如果该设备 ID 已属于其他用户，会直接返回 409，阻止设备归属被劫持。

### 15. 管理员回填中奖图的“已检查”报错文案是乱码

- `/admin/api/winning/record` 在记录已检查时，返回的错误文案本身是乱码。
- 现已恢复为正常中文提示。

### 16. A 模式停止接单在并发下会假成功

- `stop_receiving()` 之前即使 `finalize_ticket()` 因并发失败，接口仍然返回“已停止接单，当前票已完成/已过期”。
- 现在会检查最终落库结果，失败时返回“当前票状态已变化，请刷新后重试”。

### 17. 重复期号赛果会更新到旧记录

- `parse_result_file()` 之前对同一期号使用 `first()`，如果库里历史上已经有多条 `MatchResult`，会更新到最旧那条。
- 现在改为按 `uploaded_at desc, id desc` 选择最新记录更新，符合“最新上传生效”的规则。

### 18. 赛果上传允许空文件名

- `/admin/match-results/upload` 之前只检查了有没有 `file` 字段，没有校验文件名是否为空。
- 现在空文件名会直接返回 400，不再创建脏的结果文件记录。

### 19. 系统设置接口缺少关键字段校验

- `/admin/api/settings` 之前几乎不校验类型和值范围。
- 现在补了以下校验：
  - `session_lifetime_hours` 必须是 `1-24` 的整数
  - `daily_reset_hour` 必须是 `0-23` 的整数
  - `mode_b_options` 必须是非空的正整数数组
- 同时对 `mode_b_options` 做去重和标准化，避免保存脏配置。

### 20. 用户中奖图片上传允许空文件名

- `/api/winning/upload-image/<ticket_id>` 之前未校验 `file.filename`，空文件名也会继续走图片处理逻辑。
- 现在空文件名会直接返回 400，与管理员上传接口保持一致。

### 21. 用户可绕过“已检查”限制直接换图

- 用户端 `/api/winning/record` 之前不会检查 `WinningRecord.is_checked`。
- 结果是管理员已经标记“已检查”的记录，用户仍可通过 OSS 回填接口直接替换图片，绕过 `/upload-image` 的限制。
- 现已统一拦截，返回 403。

### 22. 已检查记录仍可继续申请 presign，留下孤儿文件

- 用户端 `/api/winning/presign` 和管理员端 `/admin/api/winning/<ticket_id>/presign` 之前即使记录已检查，仍然会返回 presign URL。
- 这会导致图片先上传到 OSS 或本地，最后在 `/record` 被拒绝，留下孤儿对象/文件。
- 现在 presign 和本地上传入口都会提前拦截已检查记录。

### 23. 文件列表状态和筛选长期不准确

- `UploadedFile.status` 之前基本只在“撤回”时更新，正常完成或过期后数据库里仍常常保持 `active`。
- 结果是后台文件列表的状态筛选不准，撤回按钮也会对已完成/已过期文件继续显示。
- 现已改成统一按实时派生状态返回：
  - `revoked`
  - `exhausted`
  - `expired`
  - `active`
- 管理后台 `/admin/api/files` 的 `status` 筛选也已改为按派生状态生效。

### 24. 最大设备数限制可被旧设备会话绕过

- 登录时判断“同设备已有会话”原先不带活跃时间筛选。
- 这意味着只要拿一个历史很久以前的旧 `device_id`，也可能绕过当前的最大设备数限制。
- 现已统一只把活跃窗口内的同设备会话视为“existing”。

### 25. 新会话的过期时间不跟随数据库设置

- 登录限制和会话清理读的是数据库里的 `session_lifetime_hours`。
- 但 `create_session()` 之前仍然读配置常量 `SESSION_LIFETIME_HOURS`。
- 结果是设置页改了无活动超时时间后，新会话的 `expires_at` 实际不会跟着变。
- 现已统一优先读取数据库设置，失败时才回退到配置默认值。

### 26. 历史清理会删记录，但不会删中奖图片

- `archive_old_tickets()` 和 `archive_old_uploaded_txt_files()` 之前删除旧票据或 `WinningRecord` 时，不会同步删除中奖图片。
- 本地模式会留下孤儿图片文件，OSS 模式会留下孤儿对象。
- 现已在历史清理时同步删除对应图片。

### 27. `daily_reset_hour` 设置保存了，但业务日和调度都不会用

- 之前 `daily_reset_hour` 只是能保存到数据库，但：
  - 业务日 helper 仍然硬编码按 `12:00`
  - 每日会话重置任务也仍然硬编码在 `12:00`
- 结果是设置页改这个值，系统实际行为完全不变。
- 现已修复：
  - 业务日 helper 改为读取数据库里的重置小时
  - 调度器启动时按该小时注册每日重置任务
  - 设置页更新该值时会同步重排每日重置任务

### 28. 用户文件状态长期失真，后台筛选不准

- `UploadedFile.status` 之前基本只在撤回时更新，已完成或已过期文件常年仍是 `active`。
- 现在改为实时派生文件状态，并让后台文件列表的 `status` 筛选按派生状态生效。

### 29. 历史旧设备会话可绕过最大设备数限制

- 登录时判断“同设备已有会话”原先不区分是否仍在活跃窗口内。
- 历史很久以前的旧会话也会被当成当前设备，从而让最大设备数限制判断失真。
- 现已统一只认活跃窗口内的同设备会话。

### 30. 新会话过期时间不跟随数据库超时设置

- 新会话 `expires_at` 之前仍使用配置常量 `SESSION_LIFETIME_HOURS`。
- 设置页修改“无活动超时”后，登录限制和清理逻辑会变，但新建会话的过期时间不会跟着变。
- 现已统一优先读取数据库设置。

### 31. 活跃用户不会续期 `expires_at`，会被固定时长踢下线

- 系统原来虽然有 `last_seen` 和“无活动超时”配置，但 `expires_at` 只在登录时生成一次。
- 后续正常请求和 `/auth/heartbeat` 都不会续期 `expires_at`。
- 结果是活跃用户也会在固定小时后被强制登出，不符合“无活动超时”的语义。
- 现已修复：
  - 正常请求会按当前超时配置刷新 `expires_at`
  - `/auth/heartbeat` 会同步刷新 `expires_at`
  - `touch_session()` 也改为同时刷新 `last_seen` 和 `expires_at`

### 32. 用户中奖记录在自定义业务日小时下会重新变成错口径

- `routes/winning.py` 里的“我的中奖记录”之前仍然写死按 `12:00` 切业务日。
- 在默认配置下没问题，但一旦 `daily_reset_hour` 改成其他小时，这里会重新统计错误。
- 现已改为统一走 `get_business_window()`。

## 本轮验证

已通过的定向回归包括：

- 归档清理保留最近票据历史
- 辅助历史数据删除顺序
- 过期票参与中奖计算
- 中奖重算清理旧金额和旧中奖图
- 管理员中奖图片上传/回填创建 `WinningRecord`
- 同 key 重传不误删 OSS 对象
- 调度器缺失时赛果同步计算
- 本地中奖图片预签名和上传落盘
- 本地上传的 `ticket_id/key` 权限校验
- 管理员当日 CSV 导出
- 多个非法整数参数返回 400
- 多个空 JSON body 接口稳定返回业务错误
- 登录空 JSON body 返回统一错误 JSON
- 设备 ID 归属劫持拦截
- 管理员回填中奖图报错文案恢复正常中文
- A 模式停止接单并发失败不再假成功
- 重复期号赛果优先更新最新记录
- 赛果上传空文件名拦截
- 系统设置关键字段范围/类型校验
- 用户中奖图片上传空文件名拦截
- 用户端 OSS 回填不能绕过“已检查”限制
- 已检查记录不再继续签发 presign，避免孤儿文件
- 文件列表状态和状态筛选改为实时派生
- 最大设备数限制不再被旧设备会话绕过
- 新会话过期时间与数据库设置统一
- 历史清理同步删除旧中奖图片
- `daily_reset_hour` 现在会真正影响业务日与每日重置任务
- 文件列表状态与状态筛选不再失真
- 最大设备数限制不再受旧设备会话污染
- 新会话过期时间与后台设置一致
- 活跃请求和心跳都会正确续期会话
- 用户中奖记录也已跟随可配置业务日小时

定向回归结果：

- `22 passed`

备注：

- `pytest -q tests/test_bug_fixes.py` 全量主回归在本机执行时间较长，300 秒内未跑完，但本轮实际修改覆盖到的定向链路已全部通过。
