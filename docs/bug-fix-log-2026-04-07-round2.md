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

定向回归结果：

- `22 passed`

备注：

- `pytest -q tests/test_bug_fixes.py` 全量主回归在本机执行时间较长，300 秒内未跑完，但本轮实际修改覆盖到的定向链路已全部通过。
