# Bug Fix Log - 2026-04-07

## 本轮修复记录

### 1. A/B 模式超时完成缺少二次确认，容易把未完成票误记为完成

### 问题

原先客户端在“点击完成”的时点即使已经超过截止时间，也仍按普通完成流程提交。

- A 模式：点击“下一张”或“停止接单”时，超时票会直接完成。
- B 模式：点击“已完成”时，超时批次会整批完成。

这不符合当前业务规则：超过截止时间后，必须先确认是否真的完成；未完成部分应标记为 `expired`。

### 修复方式

- 更新 [dashboard.html](/C:/Users/徐逸飞/Desktop/file-hub/templates/client/dashboard.html)，只在“点击完成时刻 > 截止时间”时弹窗。
- 更新 [mode_a.py](/C:/Users/徐逸飞/Desktop/file-hub/routes/mode_a.py) 和 [mode_a_service.py](/C:/Users/徐逸飞/Desktop/file-hub/services/mode_a_service.py)，支持 A 模式将当前票按 `completed/expired` 分支落库。
- 更新 [mode_b.py](/C:/Users/徐逸飞/Desktop/file-hub/routes/mode_b.py)、[mode_b_service.py](/C:/Users/徐逸飞/Desktop/file-hub/services/mode_b_service.py) 和 [ticket_pool.py](/C:/Users/徐逸飞/Desktop/file-hub/services/ticket_pool.py)，支持 B 模式按“前 N 张完成，其余过期”原子提交。

### 当前行为

- A 模式：
  - 未超时：直接完成，不弹窗。
  - 已超时：弹窗确认是否完成；未完成则标记为 `expired`。
- B 模式：
  - 未超时：整批直接完成，不弹窗。
  - 已超时：先确认是否全部完成；若不是，则输入已完成张数，前 N 张完成，其余标记为 `expired`。

### 验证

- `pytest -q tests\test_bug_fixes.py -k "mode_a_next_can_expire_overdue_current_ticket or mode_b_confirm_can_complete_prefix_and_expire_rest or client_dashboard_handles_mode_b_confirm_failure"`

### 2. 桌面端会话可能以空 `device_id` 登录，导致管理员设备速度统计漏掉该设备

### 问题

桌面端 B 模式客户端首次登录时，如果本地配置里还没有 `device_id`，会先用空 `device_id` 请求 `/auth/login`，然后才在登录成功后提示录入设备号。

管理员“设备处理速度统计”依赖在线会话中的 `UserSession.device_id`。因此：

- 桌面端虽然在线，但当前会话可能没有设备号。
- 管理员页会漏掉该设备的速度统计。

### 修复方式

- 服务端在 [auth.py](/C:/Users/徐逸飞/Desktop/file-hub/routes/auth.py) 的 `/auth/heartbeat` 中支持回填 `device_id`，避免只依赖首次登录。
- 网页端在 [dashboard.html](/C:/Users/徐逸飞/Desktop/file-hub/templates/client/dashboard.html) 的心跳请求中显式携带 `device_id`。
- 仓库外的桌面端文件 `C:\Users\徐逸飞\Desktop\外部使用\客户端自动导入机器人-北京.py` 已同步修复：
  - 登录前先确认并保存 `device_id`
  - 登录请求携带 `device_id`
  - 心跳持续携带 `device_id`
  - 保留 B 模式超时确认逻辑

### 验证

- `pytest -q tests\test_bug_fixes.py -k heartbeat_can_backfill_session_device_id`
- 外部桌面端 `py_compile` 通过

### 3. “今日统计”业务日窗口在中午 12 点前计算错误

### 问题

正确口径应为：

- 若当前时间在 `4/7 12:00` 之前
- “今日统计”应统计 `4/6 12:00` 到 `4/7 12:00`

但原实现中部分接口在 12 点前会错误算成再往前一天的窗口，导致：

- 管理员“今日处理统计”无数据显示或少数据
- 用户“今日统计”无数据显示或少数据
- 导出和池状态统计与业务口径不一致

### 修复方式

- 统一把“当前业务日窗口”改为 `get_today_noon()` 到 `get_today_noon() + 1 day`。
- 修复以下主路径：
  - [user.py](/C:/Users/徐逸飞/Desktop/file-hub/routes/user.py)
  - [admin.py](/C:/Users/徐逸飞/Desktop/file-hub/routes/admin.py)
  - [ticket_pool.py](/C:/Users/徐逸飞/Desktop/file-hub/services/ticket_pool.py)
- 顺手修复同类边界：
  - [file_parser.py](/C:/Users/徐逸飞/Desktop/file-hub/services/file_parser.py) 的 `display_id` 日期和计数窗口统一按业务日计算

### 验证

- `pytest -q tests\test_bug_fixes.py -k "daily_stats_uses_current_business_window_before_noon or file_display_id_uses_business_date_before_noon"`

### 4. 桌面端客户端仅允许 B 模式账号使用

### 问题

桌面端文件 `C:\Users\徐逸飞\Desktop\外部使用\客户端自动导入机器人-北京.py` 是 B 模式批量处理客户端，但原先没有明确阻止 A 模式账号登录和调用 B 模式接口。

### 影响

- A 模式账号可能误登录桌面端。
- 如果只靠前端界面区分模式，仍存在被桌面端误用 B 模式接口的风险。

### 修复方式

- 更新 [auth.py](/C:/Users/徐逸飞/Desktop/file-hub/routes/auth.py)，登录 JSON 响应补充 `client_mode`。
- 新增 [decorators.py](/C:/Users/徐逸飞/Desktop/file-hub/utils/decorators.py) 中的 `mode_b_required`。
- 更新 [mode_b.py](/C:/Users/徐逸飞/Desktop/file-hub/routes/mode_b.py)，对 `/api/mode-b/*` 全部加上 `mode_b_required`，后端统一拒绝非 B 模式用户。
- 更新桌面端文件 `C:\Users\徐逸飞\Desktop\外部使用\客户端自动导入机器人-北京.py`：
  - 登录成功后检查 `client_mode`
  - 若不是 `mode_b`，立即提示失败并退出当前会话

### 验证

- `pytest -q tests\test_bug_fixes.py -k "login_json_returns_client_mode or mode_b_endpoints_reject_mode_a_user"`

## 本次新增回归测试

- [test_bug_fixes.py](/C:/Users/徐逸飞/Desktop/file-hub/tests/test_bug_fixes.py)
  - `test_login_json_returns_client_mode`
  - `test_mode_a_next_can_expire_overdue_current_ticket`
  - `test_mode_b_endpoints_reject_mode_a_user`
  - `test_mode_b_confirm_can_complete_prefix_and_expire_rest`
  - `test_heartbeat_can_backfill_session_device_id`
  - `test_user_daily_stats_uses_current_business_window_before_noon`
  - `test_file_display_id_uses_business_date_before_noon`

## 本次验证结论

- 仓库内相关 Python 文件 `py_compile` 通过
- 相关回归测试通过：`5 passed`
- 外部桌面端脚本已按 UTF-8 从共享盘原始文件重建并通过 `py_compile`
