# Bug Fix Log - 2026-03-30

## 4. B 模式处理中批次恢复逻辑错误

### 问题
`/api/mode-b/processing` 在未传 `device_id` 时默认把请求强行绑定到 `Web` 设备，导致当前用户其他设备上处于 `assigned` 状态的批次无法被恢复。

### 影响
- 页面刷新后，非 `Web` 设备下载的批次会“消失”。
- 用户可能误以为没有处理中批次，继续重复下载新票。
- 后台会留下旧批次卡在 `assigned` 状态，直到过期或人工干预。

### 修复方式
- 调整 [`routes/mode_b.py`](/C:/Users/徐逸飞/Desktop/file-hub/routes/mode_b.py)，`processing` 接口在未传 `device_id` 时返回当前用户所有设备的处理中批次。
- 仅当显式传入 `device_id` 时才做单设备过滤。
- 补充回归测试，验证“未传设备 ID 返回全部批次”和“传设备 ID 只返回对应批次”。

### 关键代码
```python
device_id = (request.args.get('device_id') or '').strip()
...
batches = get_processing_batches(current_user.id, device_id or None)
```

### 测试
- `pytest -q tests/test_bug_fixes.py -k mode_b_processing_without_device_id_returns_all_batches`
- `pytest -q tests/test_bug_fixes.py -k mode_b_processing_with_device_id_filters_batches`

## 3. A 模式“下一张”会自动完成当前票

### 问题
`/api/mode-a/next` 只要发现当前设备上已有 `assigned` 票，就会直接把它标记为 `completed`，然后再分配下一张。重复点击、网络重试或前端重复请求都可能误完成一张并未真正处理完的票。

### 影响
- 用户误触“下一张”会直接把当前票记为已完成。
- 请求重放可能把刚分到的新票也错误完成。
- 处理统计会被高估，真实漏单风险升高。

### 修复方式
- 调整 [`services/mode_a_service.py`](/C:/Users/徐逸飞/Desktop/file-hub/services/mode_a_service.py)，只有客户端显式传入且匹配当前票的 `complete_current_ticket_id` 时，才允许完成当前票并分配下一张。
- 调整 [`routes/mode_a.py`](/C:/Users/徐逸飞/Desktop/file-hub/routes/mode_a.py)，接收 `complete_current_ticket_id`。
- 调整 [`templates/client/dashboard.html`](/C:/Users/徐逸飞/Desktop/file-hub/templates/client/dashboard.html)，前端点击“下一张”时显式带上当前票 ID。
- 如果收到的是过期/重复请求携带的旧票 ID，后端直接返回当前正在处理的票，不再误完成新票。

### 关键代码
```python
if requested_ticket_id != current_ticket.id:
    return {
        'success': True,
        'ticket': current_ticket.to_dict(),
        'completed_current': False,
    }
```

```javascript
body: JSON.stringify({
  device_id: deviceId,
  device_name: getDeviceName(),
  complete_current_ticket_id: this.currentTicket ? this.currentTicket.id : null,
})
```

### 测试
- `pytest -q tests/test_bug_fixes.py -k mode_a_next_does_not_complete_current_ticket_without_explicit_ticket_id`
- `pytest -q tests/test_bug_fixes.py -k mode_a_next_ignores_stale_completion_ticket_id`

## 2. 票池关闭后仍显示待处理票数

### 问题
停池后，普通用户仍可能从票池状态接口看到待处理票数。原逻辑只在 `pool_enabled=False` 且 `can_receive=False` 时才清空返回值，条件方向写反了，而且 B 模式接口也没有同步遵守停池状态。

### 影响
- 前端在停池状态下仍显示“有票可接”。
- 用户会误判系统还在派单。
- 管理员停池后的运营动作缺乏一致性。

### 修复方式
- 调整 [`routes/pool.py`](/C:/Users/徐逸飞/Desktop/file-hub/routes/pool.py)，只要系统停池就统一返回空池状态。
- 调整 [`routes/mode_b.py`](/C:/Users/徐逸飞/Desktop/file-hub/routes/mode_b.py) 的 `/pool-status`，B 模式接口也统一遵守停池状态。
- 保留“用户被禁接单时隐藏待处理数量”的行为，但前提是系统本身仍处于开池状态。

### 关键代码
```python
if not settings.pool_enabled:
    return jsonify({
        'total_pending': 0,
        'by_type': [],
        'assigned': 0,
        'completed_today': 0,
        'pool_enabled': False,
    })
```

### 测试
- `pytest -q tests/test_bug_fixes.py -k test_pool_status_returns_empty_when_pool_disabled`
- `pytest -q tests/test_bug_fixes.py -k test_mode_b_pool_status_returns_empty_when_pool_disabled`

## 1. 会话过期、强制下线、每日重置后仍可继续访问

### 问题
项目原先只依赖 Flask-Login 的 cookie 恢复 `current_user`，但不会在每次请求时校验 `session_token` 对应的 `UserSession` 是否还存在、是否已过期。会话表被删掉后，旧 cookie 仍然可以继续访问接口。

### 影响
- 管理员强制下线后，旧登录态仍可能继续可用。
- 每日会话重置和超时清理不能真正拦截后续请求。
- 设备数限制和会话生命周期失去约束力。

### 修复方式
- 调整 [`app.py`](/C:/Users/徐逸飞/Desktop/file-hub/app.py) 的 `before_request` 钩子。
- 对每个已认证请求强制校验 `session_token`：
  - 缺失 token：立即失效。
  - 找不到对应 `UserSession`：立即失效。
  - `expires_at` 已过期：删除会话记录并立即失效。
- 失效时同时清理 Flask session 并调用 `logout_user()`。
- API/心跳请求返回 `401` JSON，页面请求重定向到登录页。

### 关键代码
```python
if not sess:
    return invalidate_current_session()
if sess.is_expired():
    db.session.delete(sess)
    db.session.commit()
    return invalidate_current_session()
```

### 测试
- `pytest -q tests/test_bug_fixes.py -k test_deleted_user_session_invalidates_api_access`
- `pytest -q tests/test_bug_fixes.py -k test_expired_user_session_invalidates_api_access`

## 5. 用户端上传中奖图片只写 LotteryTicket，不写 WinningRecord

### 问题
用户通过 `/api/winning/upload-image/<ticket_id>` 上传图片时，原实现只更新 `LotteryTicket.winning_image_url`，不会补建或更新 `WinningRecord`。这会导致前台看起来上传成功，但后台审核列表缺记录或状态不一致。

### 影响
- 前台“已上传”，后台可能查不到对应中奖记录。
- 审核、统计、图片追踪出现数据对不上。
- 后续管理员校验可能误判为用户未提交图片。

### 修复方式
- 重写 [`routes/winning.py`](/C:/Users/徐逸飞/Desktop/file-hub/routes/winning.py) 中的用户上传图片逻辑。
- 上传成功后统一双写：
  - 更新 `LotteryTicket.winning_image_url`
  - 设置 `LotteryTicket.is_winning = True`
  - 补建或更新 `WinningRecord`
- OSS 模式下同步保存 `image_oss_key`，本地模式下保持为空。

### 关键代码
```python
if record:
    record.winning_image_url = image_url
    record.image_oss_key = image_oss_key
    record.uploaded_by = current_user.id
    record.uploaded_at = beijing_now()
else:
    record = WinningRecord(
        ticket_id=ticket_id,
        source_file_id=ticket.source_file_id,
        detail_period=ticket.detail_period,
        lottery_type=ticket.lottery_type,
        winning_image_url=image_url,
        image_oss_key=image_oss_key,
        uploaded_by=current_user.id,
    )
```

### 测试
- `pytest -q tests/test_bug_fixes.py -k test_upload_winning_image_creates_winning_record`

## 6. 过期任务只改票状态，不回写文件计数

### 问题
`expire_overdue_tickets()` 会把超时的 `pending/assigned` 票改成 `expired`，但不会同步更新 `uploaded_files.pending_count` 和 `uploaded_files.assigned_count`。

### 影响
- 管理端文件列表显示的待处理/处理中数量会长期失真。
- 票池进度和文件统计可能互相矛盾。
- 运营人员会误判票池剩余量。

### 修复方式
- 重写 [`tasks/expire_tickets.py`](/C:/Users/徐逸飞/Desktop/file-hub/tasks/expire_tickets.py)。
- 在过期任务执行时先收集受影响的 `source_file_id`，更新票状态后统一重算对应 `UploadedFile` 的 `pending_count / assigned_count / completed_count`。
- PostgreSQL 和 SQLite 两条路径都做同样的计数同步。

### 关键代码
```python
_sync_uploaded_file_counters(sorted(set(affected_file_ids)))
db.session.commit()
```

### 测试
- `pytest -q tests/test_bug_fixes.py -k test_expire_overdue_tickets_updates_file_counters`

## 7. pytest 收集阶段会把 `test_progress.txt` 当测试文件

### 问题
项目根目录下存在 [`test_progress.txt`](/C:/Users/徐逸飞/Desktop/file-hub/test_progress.txt)。在缺少 pytest 收集约束时，`pytest -q` 会尝试读取它并在收集阶段触发编码错误，中断全部测试。

### 影响
- 回归测试在真正执行前就中断。
- CI 或本地排查都会被无关文件阻塞。
- 依赖手工启动服务的并发压测脚本也会影响默认测试入口的稳定性。

### 修复方式
- 新增 [`pytest.ini`](/C:/Users/徐逸飞/Desktop/file-hub/pytest.ini)，把测试收集范围限制为 `tests/` 下的 `test_*.py`。
- 调整 [`tests/test_concurrent_20devices.py`](/C:/Users/徐逸飞/Desktop/file-hub/tests/test_concurrent_20devices.py)，默认跳过需要手工启动本地服务的活体并发压测，仅在显式设置 `RUN_LIVE_CONCURRENCY_TESTS=1` 时运行。

### 关键代码
```ini
[pytest]
testpaths = tests
python_files = test_*.py
```

```python
if os.environ.get("RUN_LIVE_CONCURRENCY_TESTS") != "1":
    pytest.skip(..., allow_module_level=True)
```

### 测试
- `pytest -q`
- 结果：`10 passed, 1 skipped`

## 8. 用户端修改密码请求路径错误

### 问题
客户端仪表盘里的“修改密码”调用了错误路径 `/user/change-password`，而后端真实接口是 `/api/user/change-password`。

### 影响
- 用户在页面里修改密码会直接遇到 404。
- 后端接口本身正常，但前端入口不可用。
- 这类路径拼接问题不容易被纯后端接口测试覆盖。

### 修复方式
- 更新 [`templates/client/dashboard.html`](/C:/Users/徐逸飞/Desktop/file-hub/templates/client/dashboard.html)，把请求路径改成 `/api/user/change-password`。
- 增加模板级回归测试，避免以后再改回错误路径。

### 关键代码
```javascript
fetch('/api/user/change-password', {
```

### 测试
- `pytest -q tests/test_bug_fixes.py -k change_password`

## 9. 公开注册入口未关闭且会落到缺失模板

### 问题
项目实际业务是“管理员后台创建账号”，但 `/auth/register` 公开路由仍然保留。此前浏览器访问时还会尝试渲染缺失模板 `register.html`，直接触发 500。

### 影响
- 对外暴露了不符合业务规则的注册入口。
- 访问该入口时得到的是 500，而不是明确的业务限制提示。
- 代码状态和真实注册流程不一致，后续维护容易误判。

### 修复方式
- 调整 [`routes/auth.py`](/C:/Users/徐逸飞/Desktop/file-hub/routes/auth.py)，统一关闭公开注册入口。
- JSON 请求返回 `403` 和明确错误信息。
- 页面访问 flash 提示后重定向到登录页。
- 删除 [`templates/register.html`](/C:/Users/徐逸飞/Desktop/file-hub/templates/register.html)，避免保留错误入口暗示。
- 更新回归测试，验证浏览器访问重定向、JSON 请求返回 403。

### 关键代码
```python
message = '公开注册已关闭，请联系管理员创建账号'
if request.is_json:
    return jsonify({'success': False, 'error': message}), 403
```

### 测试
- `pytest -q tests/test_bug_fixes.py -k register`
# Bug Fix Log - 2026-03-30

## 10. 登录显示“网络错误”，实际是空 SQLite 库未建表

### 问题
用户登录时报错“网络错误”，服务器日志显示 `/auth/login` 查询 `users` 表时抛出 `sqlite3.OperationalError: no such table: users`。原因不是登录逻辑本身，而是当前运行环境连到了一份空的 SQLite 数据库文件，核心表尚未创建。

### 影响
- 登录接口直接返回 500，前端表现为“网络错误”。
- 只要数据库文件是新的或空的，系统启动后几乎所有依赖数据库的功能都会不可用。
- 问题定位容易被误判为“账号错误”或“前端请求异常”。

### 修复方式
- 在 [`app.py`](/C:/Users/徐逸飞/Desktop/file-hub/app.py) 增加 SQLite 启动自举逻辑。
- 启动时如果检测到当前数据库缺少 `users` / `system_settings` 等核心表，就自动执行 `db.create_all()`。
- 自动补齐 `SystemSettings` 默认记录。
- 如果库里没有管理员账号，则自动补一个默认管理员 `zucaixu / zhongdajiang888`，保证空库至少可以登录后台。
- 对 SQLite `create_all()` 的重复建表边界做幂等兜底，避免偶发“table already exists”导致启动失败。

### 关键代码
```python
if required_tables.issubset(existing_tables):
    return

db.create_all()
SystemSettings.get()
```

### 测试
- `pytest -q tests/test_bug_fixes.py -k bootstrap`

## 11. SQLite 相对路径导致可能出现多份数据库文件

### 问题
项目原先使用相对 SQLite 路径 `sqlite:///lottery_dev.db`。这种写法在不同启动方式、不同工作目录或 Flask 实例目录处理下，容易让数据库实际落到不同位置，进而出现“明明是同一个项目，却连到了另一份库”的现象。

### 影响
- 容易产生多份 `*.db` 文件，用户误以为数据库被清空。
- 服务可能连到新生成的空库，而历史业务数据还留在旧库。
- 排查登录失败、数据丢失、初始化异常时会非常混乱。

### 修复方式
- 在 [`app.py`](/C:/Users/徐逸飞/Desktop/file-hub/app.py) 增加运行时数据库配置刷新逻辑，按当前环境变量重新读取 `DATABASE_URL`。
- 对相对 SQLite 路径统一规范到 `instance/` 目录下。
- 启动时把最终实际使用的 SQLite 路径写入日志，便于排查。
- 删除无效的空库文件，只保留当前实际使用的 [`instance/lottery_dev.db`](/C:/Users/徐逸飞/Desktop/file-hub/instance/lottery_dev.db)。

### 关键代码
```python
relative_path = db_uri[len('sqlite:///'):]
resolved_path = Path(app.instance_path) / relative_path
app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{resolved_path.as_posix()}"
```

### 测试
- `pytest -q tests/test_bug_fixes.py -k normalizes_relative_sqlite_path`

## 12. 管理后台缺少当前实际数据库路径可视化

### 问题
即使已经统一数据库路径，管理员在页面上仍然看不到系统当前到底连的是哪份数据库文件。出现“空库”“旧库”“多库”问题时，只能靠日志或手工排查。

### 影响
- 管理员无法快速确认当前环境是否连接了正确数据库。
- 一旦切库、重建库或误连空库，问题发现会滞后。
- 排查环境问题需要进命令行，操作门槛高。

### 修复方式
- 在 [`routes/admin.py`](/C:/Users/徐逸飞/Desktop/file-hub/routes/admin.py) 新增数据库信息组装逻辑。
- 在 [`templates/admin/dashboard.html`](/C:/Users/徐逸飞/Desktop/file-hub/templates/admin/dashboard.html) 后台首页增加“数据库信息”卡片。
- 显示当前数据库引擎类型和实际连接路径，管理员进入首页即可确认。

### 关键代码
```python
return render_template('admin/dashboard.html', database_info=_database_display_info())
```

```html
<div class="font-monospace small text-break">{{ database_info.path }}</div>
```

### 测试
- `pytest -q tests/test_bug_fixes.py -k database_display_info`
