# 项目说明

## 基本信息
- 项目名称：file-hub（原 lottery-platform）
- 技术栈：Flask + SQLite + Redis + Gunicorn + Gevent
- 功能：数据文件管理分发平台，管理员上传TXT文件，用户A/B两种模式接单处理

## 服务器
- 云服务商：阿里云
- 公网IP：121.196.170.150
- 系统：Ubuntu 22.04
- 部署路径：~/file-hub
- Python虚拟环境：.venv

## 常用命令
```bash
# 连接服务器
ssh root@121.196.170.150

# 启动服务
cd ~/file-hub
source .venv/bin/activate
gunicorn -c gunicorn_config.py run:app

# 后台常驻
systemctl start lottery
systemctl status lottery

# 更新代码
git pull origin main
pkill -f gunicorn
gunicorn -c gunicorn_config.py run:app
```

## 账号信息
- 管理员用户名：zucaixu
- 数据库文件：/root/file-hub/lottery.db
- 访问地址：http://121.196.170.150:5000

## 环境变量（.env）
```
SECRET_KEY=abc123xyz456def789ghi
DATABASE_URL=sqlite:////root/file-hub/lottery.db
REDIS_URL=redis://localhost:6379/0
UPLOAD_FOLDER=/root/file-hub/uploads
FLASK_ENV=production
```

## 项目结构
- `routes/` — 路由蓝图（admin, auth, mode_a, mode_b, winning, user, pool, device）
- `services/` — 业务逻辑（ticket_pool, mode_a_service, mode_b_service, file_parser, winning_calc_service）
- `models/` — 数据模型（user, device, file, ticket, winning, settings）
- `tasks/` — 定时任务（scheduler, expire_tickets, clean_sessions, daily_reset）
- `templates/` — 前端模板（base, login, admin/, client/）
- `utils/` — 工具函数（time_utils, filename_parser, winning_calculator, amount_parser）

## 关键设计
- 并发安全：Redis LPOP 原子弹出 + SQLite 单worker，100用户并发无问题
- 基注：1元（utils/winning_calculator.py BASE_STAKE）
- 业务日期分割线：每天12点
- 会话有效期：3小时无活动自动清理
- Gunicorn：单worker + gevent协程模式

## GitHub
- 仓库：https://github.com/qiaosheng125/file-hub
- 分支：main

## ⭐ 并发安全（最高优先级，绝不能破坏）

**核心要求：同一张票永远只分配给一个设备，任意数量设备并发接单均不会重复分票（20设备只是测试用例，实际不限数量）。**

### 实现层
- **SQLite（开发）**：`services/ticket_pool.py` 模块级 `_sqlite_assign_lock = BoundedSemaphore(1)`（gevent 协程锁），所有分票操作在锁内串行执行，UPDATE 带 `WHERE status='pending'` 原子条件；持锁期间其他无关请求仍可正常响应
- **PostgreSQL（生产）**：`SELECT FOR UPDATE SKIP LOCKED` 行锁 + 条件 UPDATE

### 关键约束
- Gunicorn **必须** `workers = 1`，多 worker 会破坏 SQLite 进程锁
- B 模式始终保留 20 张给 A 模式缓冲（`RESERVE = 20`，`ticket_pool.py`）
- A 模式每台设备同时只持有 1 张票（点"下一张"才自动完成当前票）

## 本次会话完成的功能（2026-03-24）

1. **每日处理票数上限** — 用户管理新增 `daily_ticket_limit` 字段，限制用户每个业务日期（12点分割）可处理的总票数，A/B模式均生效
   - `models/user.py` — 添加 `daily_ticket_limit` 字段（整型，可为空，默认 None 表示不限制），`to_dict()` 同步返回
   - `routes/admin.py` — 创建和更新用户 API 支持该字段，范围验证 1-100000
   - `services/ticket_pool.py` — 新增 `_count_today_completed()` 辅助函数；`assign_ticket_atomic()`（A模式）和 `assign_tickets_batch()`（B模式）均在分配前检查每日上限，SQLite 路径在锁内原子检查，PostgreSQL 路径在循环前检查
   - `services/mode_a_service.py` — `get_next_ticket()` 读取用户 `daily_ticket_limit` 并传入 `assign_ticket_atomic()`
   - `services/mode_b_service.py` — `download_batch()` 读取用户 `daily_ticket_limit` 并传入 `assign_tickets_batch()`
   - `templates/admin/users.html` — 表头"B模式上限"改为"B模式同时处理上限"；新增"每日处理上限"列（行内编辑）；新建用户弹窗新增每日上限输入框

## 上次会话完成的功能（2026-03-23）

### 上午会话

1. **管理后台统计设备处理速度** — `routes/admin.py` `dashboard_data()` 添加设备速度统计，计算每个设备最近180分钟（3小时）的实际出票速度（每分钟张数）；使用实际出票时间跨度（第一张到最后一张的时间差）而非固定时间窗口，排除空闲时间；至少需要2张票才能计算速度；返回 `device_speed_stats` 数组（包含用户名、设备ID、设备名、速度、时间跨度）
2. **管理后台预估完成时间** — 基于所有在线设备的总速度计算预估完成时间（剩余票数 / 当前在线总设备速度 = 预估分钟数）；添加除零保护（速度>0.01）和上限保护（超过7天显示"超过7天"）；返回格式化时间字符串（如"2小时30分钟"）
3. **禁止接单用户隐藏票数** — `routes/user.py` `daily_stats()` 和 `routes/mode_b.py` `pool_status()` 检查 `current_user.can_receive`，为 False 时返回 `pool_total_pending=0`，B模式还隐藏彩种列表（`by_type=[]`）
4. **B模式单彩种单文件优化** — `services/ticket_pool.py` `assign_tickets_batch()` 实现智能彩种选择逻辑：优先选择截止时间最早的彩种，如果该彩种票数不足且有其他截止时间相同的彩种，则选择票数最多的；确认实际可用票数防止票数不足；`services/mode_b_service.py` `download_batch()` 每次只返回一个文件（单彩种）
5. **客户页面设备维度统计** — 确认 `routes/user.py` `daily_stats()` 已有完整的设备统计功能（按设备ID分组统计张数和金额），前端已显示设备统计表
6. **客户页面中签记录增强查询** — `routes/winning.py` `my_winning()` 支持最近3天查询（基于业务日期）和日期+彩种类型的组合筛选；添加日期格式验证（返回400错误）；返回可用的筛选选项供前端使用

**技术改进**：
- 优化N+1查询问题（设备速度统计改为一次性查询所有在线用户的最近完成票）
- 速度计算逻辑优化（使用实际出票时间跨度，排除空闲时间，时间窗口扩大到180分钟）
- 完善异常处理（日期格式验证、除零保护、上限保护）
- 确认实际可用票数（防止B模式票数不足）

### 下午会话

7. **B模式处理中票数上限** — 在用户管理中增加 `max_processing_b_mode` 字段，限制B模式客户同时处理的票数上限（A模式不受限制）
   - `models/user.py` — 添加 `max_processing_b_mode` 字段（整型，可为空，默认 None 表示不限制）
   - `routes/admin.py` — 用户管理API支持创建和更新该字段，添加输入验证（1-10000范围）
   - `services/ticket_pool.py` — `assign_tickets_batch()` 在锁内进行并发安全的检查和分配，支持 `max_processing` 参数
   - `services/mode_b_service.py` — `download_batch()` 传递用户上限给 `assign_tickets_batch()`
   - `templates/admin/users.html` — 用户管理界面添加"B模式上限"列，支持在线编辑
   - `migrations/add_max_processing_b_mode.sql` — 数据库迁移脚本
   - `instance/lottery_dev.db` — 数据库已迁移，添加 `max_processing_b_mode` 列

**智能调整逻辑**：
- 如果用户已达上限（如 100/100），完全拒绝，提示"已达到处理中票数上限"
- 如果请求数量会超过上限（如当前100张，上限150张，请求100张），自动调整为剩余额度（50张），并返回调整提示消息
- 如果请求数量在额度内，正常分配，无调整提示
- 如果用户没有设置上限（`max_processing_b_mode = None`），不做任何限制

**并发安全保证**：
- 检查和分配操作在 `_sqlite_assign_lock` 锁内原子执行，防止竞态条件
- 多个请求同时进入时，锁保证串行处理，确保不会超过上限
- 返回值改为 `(tickets, adjustment_message)` 元组，支持调整提示

**输入验证**：
- 管理员API添加类型转换异常处理，防止500错误
- 范围验证：1-10000之间，超出范围返回400错误
- 空值处理：空字符串或 None 表示不限制

8. **前端界面完善** — 补充用户管理和管理后台Dashboard的前端界面
   - `templates/admin/users.html` — 添加"B模式上限"列，只在B模式时启用输入框，创建用户时可设置上限
   - `templates/admin/dashboard.html` — 添加"总速度(张/分)"和"预估完成时间"统计卡片，添加"设备处理速度统计"表格
   - 设备速度统计按用户名排序，同一用户的设备显示在相邻行
   - 所有数据实时更新（每5秒刷新）

## 本次会话完成的功能（2026-03-30）

### 核心 Bug 修复（12个）

1. **会话验证增强** — `app.py` 在 `before_request` 钩子中强制校验 `session_token`，缺失/过期/不存在的会话立即失效并返回 401，修复会话过期、强制下线、每日重置后仍可继续访问的问题
2. **停池状态统一** — `routes/pool.py` 和 `routes/mode_b.py` 停池时统一返回空池状态（`total_pending=0`），修复停池后仍显示待处理票数的问题
3. **A模式显式确认机制** — `services/mode_a_service.py` 和 `routes/mode_a.py` 实现显式票ID确认，只有客户端传入正确的 `complete_current_ticket_id` 才完成当前票，防止重复请求/网络重试误完成票
4. **B模式批次查询修复** — `routes/mode_b.py` `/processing` 接口未传 `device_id` 时返回当前用户所有设备的处理中批次，修复页面刷新后非 Web 设备批次"消失"的问题
5. **中奖记录同步写入** — `routes/winning.py` 用户上传中奖图片时同步更新 `LotteryTicket.winning_image_url` 和 `WinningRecord`，修复前台"已上传"但后台查不到记录的问题
6. **文件计数同步** — `tasks/expire_tickets.py` 过期任务执行时同步更新 `UploadedFile` 的 `pending_count/assigned_count/completed_count`，修复管理端文件列表显示失真的问题
7. **pytest 配置优化** — 新增 `pytest.ini` 限制测试收集范围为 `tests/test_*.py`，修复 `test_progress.txt` 被误当测试文件导致收集阶段中断的问题
8. **修改密码路径修复** — `templates/client/dashboard.html` 修改密码请求路径从 `/user/change-password` 改为 `/api/user/change-password`，修复用户修改密码遇到 404 的问题
9. **关闭公开注册** — `routes/auth.py` 统一关闭公开注册入口，JSON 请求返回 403，页面访问重定向到登录页，删除 `templates/register.html`
10. **SQLite 自举逻辑** — `app.py` 启动时检测核心表缺失则自动执行 `db.create_all()`，补齐 `SystemSettings` 默认记录和默认管理员账号，修复空库登录报"网络错误"的问题
11. **数据库路径规范化** — `app.py` 对相对 SQLite 路径统一规范到 `instance/` 目录，启动时日志记录实际使用路径，修复多份数据库文件混乱的问题
12. **数据库信息可视化** — `routes/admin.py` 和 `templates/admin/dashboard.html` 后台首页新增"数据库信息"卡片，显示当前引擎类型和实际连接路径

### 测试增强

- **活体并发压测重写** — `tests/test_concurrent_20devices.py` 重写为完整的活体并发压测（40设备：4账号×10设备，A/B模式混合），验证核心分票流程无重复、无遗漏、无卡顿

### 文档完善

- **Bug 修复日志** — `docs/bug-fix-log-2026-03-30.md` 详细记录12个 bug 的问题、影响、修复方式、关键代码和测试方法

## 上次会话完成的功能（2026-03-20）

1. **并发安全优化** — `services/ticket_pool.py` 将 `threading.Lock` 改为 `gevent.lock.BoundedSemaphore(1)`，持锁期间其他协程可继续响应无关请求，互斥性不变
2. **README 更新** — 替换所有 `lottery-platform` 为 `file-hub`，追加本周开发周报
3. **生成周报文件** — `docs/weekly-report-2026-03-20.md`

1. **修复设备限制检查** — `routes/auth.py` 登录时统计活跃设备数改为过滤 `last_seen` 超时的会话，过期会话不再占用设备名额
2. **会话清理读取管理员设置** — `tasks/clean_sessions.py` 从 `SystemSettings.session_lifetime_hours` 读取超时时长，不再硬编码 3 小时
3. **今日处理清单下载优化** — `routes/user.py` `export_daily()` 空结果不再返回 404，改为 JSON 提示；同时统计未到截止时间的票数，通过 `X-Pending-Count` 响应头传给前端；`dashboard.html` `exportDaily()` 改用 fetch 下载文件，有未到期票时弹 toast 提示

## 上次会话完成的功能（2026-03-19）

1. **B模式保留20张** — `services/ticket_pool.py` `assign_tickets_batch()` 加 `RESERVE=20`，`get_pool_total_pending()` 返回 `max(0, total-20)`
2. **中签记录显示设备** — `routes/winning.py` `my_winning()` 返回 `assigned_device_id/name`，`templates/client/dashboard.html` 中签卡片显示设备 badge
3. **接单页显示设备名** — `dashboard.html` 标题区加 `device-name-badge`，JS 读取本地存储设备名填入
4. **今日各设备出票统计** — `routes/user.py` `daily_stats()` 按 `assigned_device_id` 分组，`dashboard.html` 展示设备统计表（设备数>1时显示）
5. **上传成功自动清空队列** — `templates/admin/upload.html` `doUpload()` 全部成功则清空，有失败则只保留失败项
6. **20设备并发压力测试** — `tests/setup_test_env.py`（初始化测试账号）、`tests/test_concurrent_20devices.py`（10个A模式+10个B模式并发）
