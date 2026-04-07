# 数据文件管理分发平台

一个基于Flask的数据文件管理和分发系统，支持管理员上传数据文件，用户通过A/B两种模式接单处理，并自动计算结果。

## 📋 目录

- [系统概览](#系统概览)
- [业务日口径](#业务日口径)
- [功能特性](#功能特性)
- [核心业务流](#核心业务流)
- [技术栈](#技术栈)
- [快速开始](#快速开始)
- [项目结构](#项目结构)
- [核心数据模型](#核心数据模型)
- [状态流转](#状态流转)
- [核心功能](#核心功能)
- [使用说明](#使用说明)
- [配置说明](#配置说明)
- [常见排查](#常见排查)
- [部署指南](#部署指南)

---

## 🧭 系统概览

这个项目本质上是在做一件事：把管理员上传的 TXT 投注文件，拆成一张张票，分发给用户设备处理，并在后续叠加中奖计算、图片上传、统计和导出能力。

系统里有三类主要角色：

- 管理员
  - 上传原始 TXT 文件
  - 管理用户、设备、系统设置
  - 查看实时处理进度
  - 上传赛果并查看中奖记录
- A 模式用户
  - 一次只处理 1 张票
  - 通过“下一张 / 上一张 / 停止”推进
  - 适合逐张确认的工作方式
- B 模式用户
  - 按批量下载 TXT
  - 处理完后批量确认
  - 支持网页端和桌面端客户端

系统里最核心的对象是：

- `UploadedFile`
  - 管理员上传的一份源文件
- `LotteryTicket`
  - 源文件拆出来的单张票
- `UserSession`
  - 用户当前在线会话，设备统计依赖它
- `MatchResult`
  - 开奖/赛果数据
- `WinningRecord`
  - 中奖图片和审核记录

如果只看业务主线，可以理解为：

1. 管理员上传文件
2. 文件被解析成很多 `LotteryTicket`
3. 用户按 A / B 模式领取并完成
4. 已完成的票进入统计、导出、中奖计算链路
5. 管理员查看中奖记录、审核图片和导出报表

---

## 🔑 核心保证：并发安全，绝不重复分票

> **这是本系统最重要的设计约束。**
>
> 无论多少设备同时接单，**同一张票永远只会分配给一个设备**，不会出现重复。（压力测试以20设备为例，实际支持任意数量并发）

### 实现机制

**SQLite 环境（开发/测试）**

```python
# services/ticket_pool.py
_sqlite_assign_lock = threading.Lock()   # 进程级互斥锁，强制串行化

with _sqlite_assign_lock:
    row = SELECT id FROM tickets WHERE status='pending' LIMIT 1
    updated = UPDATE tickets SET status='assigned'
              WHERE id=:id AND status='pending'   # 原子条件，防止重复
    if not updated:
        rollback(); return None   # 已被抢走，放弃
```

**PostgreSQL 环境（生产）**

```sql
SELECT id FROM tickets
WHERE status = 'pending'
FOR UPDATE SKIP LOCKED   -- 数据库行锁，天然防并发
LIMIT 1
```

### 关键约束

| 约束 | 说明 |
|------|------|
| Gunicorn 必须 `workers = 1` | 多 worker 会破坏 SQLite 进程锁 |
| B 模式保留 20 张 | 始终为 A 模式和管理员上传预留缓冲 |
| 每台设备同时只持有 1 张票 | A 模式点"下一张"才自动完成当前票 |

---

## 🕛 业务日口径

本系统所有“按天”统计和筛选，默认都不是自然日 `00:00 - 24:00`，而是统一使用**业务日**：

- 业务日开始：当天 `12:00`
- 业务日结束：次日 `12:00`
- `12:00` 之前的数据，归到**前一个业务日**
- `12:00` 及之后的数据，归到**当前业务日**

例如：

- `2026-04-07 11:30` 归属业务日 `2026-04-06`
- `2026-04-07 12:13` 归属业务日 `2026-04-07`

以下功能都按这个口径计算：

- 用户“今日处理张数 / 金额”
- 用户“今日处理清单”导出
- 管理后台“今日处理统计”
- 文件列表按日期筛选
- 按日期导出投注内容
- 用户中奖记录按日期分组与筛选
- 管理后台中奖记录筛选与导出
- 结果计算状态列表按日期筛选

如果要判断某条记录属于哪一天，请优先看“业务日归属”，不要按自然日理解。

---

## ✨ 功能特性

### 管理员功能
- 📤 **文件上传**：上传TXT格式数据文件，系统自动解析
- 📊 **实时监控**：查看在线用户、数据池状态、处理进度
- 👥 **用户管理**：创建用户、设置接单模式、设备数量限制
- 🎯 **结果管理**：上传结果文件，自动计算中签金额
- 🔄 **文件撤回**：支持撤回已上传的文件
- ⚙️ **系统设置**：配置B模式批量选项、公告等

### 用户功能
- 🎫 **A模式接单**：逐条接单，浮层显示，支持上一条/下一条导航
- 📦 **B模式批量下载**：按类型和截止时间批量获取数据
- 📱 **手机端优化**：全屏铺满、大字体大按钮、防误触设计
- 🏆 **中签查询**：查看个人中签记录，按日期分类
- 📈 **统计信息**：今日处理张数、金额、待处理剩余等
- 🔧 **设备管理**：注册设备、自定义设备名称

### 系统功能
- 🔐 **多设备管理**：支持设备注册、命名、数量限制
- 💓 **心跳机制**：30秒心跳，2分钟在线检测
- 🔄 **会话管理**：3小时无活动自动清理，每日12点重置
- 📡 **实时推送**：WebSocket推送数据池状态、文件上传等事件
- 🗄️ **历史清理**：每周清理 30 天外历史数据，控制数据库和磁盘体积
- ⏰ **定时任务**：超时检测、会话清理、每日重置

---

## 🔄 核心业务流

### 1. 文件上传到入池

管理员上传 TXT 文件后，系统会：

1. 解析文件名，得到彩种、倍数、金额、张数、截止时间、编号等信息
2. 逐行解析文件内容
3. 为每一行创建一条 `LotteryTicket`
4. 初始化 `UploadedFile` 的计数信息
5. 让这些票进入待分配池

这一段主要在：

- `services/file_parser.py`
- `models/file.py`
- `models/ticket.py`

补充说明：

- 原始 TXT 在上传时就会按**业务日**落到本地目录：
  - `uploads/txt/<业务日>/...`
- 不是先堆在根目录，再等后续归档时分类
- 这样可以从一开始就控制单目录文件数

### 2. A 模式处理流

A 模式每台设备同一时间只持有 1 张票。

典型流程：

1. 用户点击开始接单
2. 后端原子领取 1 张 `pending` 票，改为 `assigned`
3. 用户处理完成后点击“下一张”或“停止”
4. 未超时则直接完成
5. 已超时则先确认，未完成可标记为 `expired`

这一段主要在：

- `routes/mode_a.py`
- `services/mode_a_service.py`

### 3. B 模式处理流

B 模式按批量下载处理，服务端负责决定给哪一批票，不由客户端自行挑选。

典型流程：

1. 用户选择下载张数
2. 服务端按截止时间优先分配一批票
3. 用户处理完成后点击确认
4. 未超时则整批完成
5. 已超时则确认“全部完成”或“部分完成”
6. 部分完成时，前 N 张 `completed`，其余 `expired`

这一段主要在：

- `routes/mode_b.py`
- `services/mode_b_service.py`
- `services/ticket_pool.py`

### 4. 中奖与赛果流

中奖链路是独立叠加在“已完成票”之上的：

1. 管理员上传赛果文件
2. 系统生成 `MatchResult`
3. 异步计算每张票是否中奖
4. 用户或管理员上传中奖图片
5. 中奖记录进入审核和导出流程

这一段主要在：

- `routes/winning.py`
- `services/winning_calc_service.py`
- `models/result.py`
- `models/winning.py`

---

## 🛠 技术栈

### 后端
- **Flask 3.x** - Web框架
- **Flask-SocketIO** - WebSocket实时推送（threading模式）
- **SQLAlchemy 2.x** - ORM
- **SQLite** - 数据库（支持切换PostgreSQL）
- **APScheduler 3.x** - 定时任务调度
- **Flask-Login** - 用户认证
- **Flask-Bcrypt** - 密码加密

### 前端
- **Vue 3** (CDN) - 前端框架
- **Bootstrap 5** - UI框架
- **Socket.IO Client** - WebSocket客户端
- **Jinja2** - 模板引擎

---

## 🚀 快速开始

### 环境要求
- Python 3.9+
- pip

### 安装步骤

1. **克隆项目**
```bash
git clone https://github.com/qiaosheng125/file-hub.git
cd file-hub
```

2. **创建虚拟环境**
```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/Mac
source .venv/bin/activate
```

3. **安装依赖**
```bash
pip install -r requirements.txt
```

4. **配置环境变量**
```bash
# 创建 .env 文件
SECRET_KEY=your-secret-key-here
DATABASE_URL=sqlite:////path/to/data.db
REDIS_URL=redis://localhost:6379/0
UPLOAD_FOLDER=uploads
FLASK_ENV=production
```

5. **初始化数据库**
```bash
python init_db.py
```

6. **运行应用**
```bash
gunicorn -c gunicorn_config.py run:app
```

7. **访问应用**
- 打开浏览器访问：http://localhost:5000
- 首次运行后请立即修改默认密码

---

## 📁 项目结构

```
file-hub/
├── app.py                      # Flask应用工厂
├── config.py                   # 配置文件
├── extensions.py               # Flask扩展初始化
├── run.py                      # 应用启动入口
├── init_db.py                  # 数据库初始化脚本
├── requirements.txt            # Python依赖
├── gunicorn_config.py          # Gunicorn配置
│
├── models/                     # 数据模型
│   ├── user.py                 # 用户、会话模型
│   ├── device.py               # 设备注册模型
│   ├── file.py                 # 文件模型
│   ├── ticket.py               # 数据条目模型
│   ├── winning.py              # 结果记录模型
│   └── settings.py             # 系统设置模型
│
├── routes/                     # 路由蓝图
│   ├── auth.py                 # 认证路由
│   ├── admin.py                # 管理员路由
│   ├── mode_a.py               # A模式路由
│   ├── mode_b.py               # B模式路由
│   ├── winning.py              # 结果路由
│   └── user.py                 # 用户路由
│
├── services/                   # 业务逻辑
│   ├── file_parser.py          # 文件解析
│   ├── ticket_pool.py          # 数据池管理
│   ├── mode_a_service.py       # A模式服务
│   ├── mode_b_service.py       # B模式服务
│   └── winning_calc_service.py # 结果计算服务
│
├── tasks/                      # 定时任务
│   ├── scheduler.py            # 任务调度器
│   ├── expire_tickets.py       # 超时检测
│   ├── clean_sessions.py       # 会话清理
│   └── daily_reset.py          # 每日重置
│
├── templates/                  # Jinja2模板
│   ├── base.html
│   ├── login.html
│   ├── admin/
│   └── client/
│
└── static/                     # 静态资源
    ├── css/
    └── js/
```

---

## 🧱 核心数据模型

### `users`

表示账号本身，最重要字段：

- `client_mode`
  - `mode_a` 或 `mode_b`
- `max_devices`
  - 最大在线设备数
- `can_receive`
  - 是否允许接单
- `daily_ticket_limit`
  - 当前业务日内可处理的总票数上限

### `user_sessions`

表示当前在线会话，最重要字段：

- `session_token`
- `device_id`
- `last_seen`
- `expires_at`

管理员“设备处理速度统计”依赖这里的 `device_id`，不是只看票表。

### `uploaded_files`

表示一份原始上传文件，常用字段：

- `original_filename`
- `display_id`
- `uploaded_at`
- `stored_filename`
- `pending_count / assigned_count / completed_count`
- `deadline_time / detail_period`

说明：

- `stored_filename` 现在保存的是相对路径
- 原始 TXT 通常类似：
  - `txt/2026-04-07/20260407123000_abcd_xxx.txt`

### `lottery_tickets`

系统里的核心事实表，一张票就是一行。常用字段：

- `status`
  - `pending / assigned / completed / expired / revoked`
- `assigned_user_id / assigned_device_id`
- `assigned_at / completed_at`
- `deadline_time`
- `ticket_amount`
- `is_winning / winning_amount / winning_image_url`

### `match_results`

表示一条已上传的赛果/开奖结果，常用字段：

- `detail_period`
- `uploaded_at`
- `calc_status`
- `tickets_total / tickets_winning / total_winning_amount`

### `winning_records`

表示中奖图片与审核信息，常用字段：

- `ticket_id`
- `winning_image_url`
- `uploaded_by / uploaded_at`
- `is_checked / checked_at / checked_by`

---

## 🔁 状态流转

### 票据状态

```text
pending -> assigned -> completed
pending -> expired
assigned -> expired
pending/assigned -> revoked
```

说明：

- `pending`
  - 尚未被用户领取
- `assigned`
  - 已分配给某个用户/设备，正在处理
- `completed`
  - 已确认处理完成
- `expired`
  - 超过截止时间且确认未完成，或系统定时任务自动过期
- `revoked`
  - 来源文件被管理员撤回

### 文件状态理解

文件本身没有像票那样复杂的显式状态机，页面上看到的“处理中 / 已完成 / 已过期 / 已撤回”主要来自：

- 文件表自己的 `status`
- 文件下所有票的计数聚合
- 文件截止时间是否已过

也就是说，文件页展示状态本质上是“文件元数据 + 票据汇总”计算出来的结果。

---

## 🔧 使用说明

### 管理员操作

1. 登录管理员账号
2. 进入"文件管理"上传TXT数据文件
3. 在"管理后台"查看实时处理状态
4. 在"结果管理"上传结果文件触发中签计算

说明：
- 文件列表中的“日期筛选”按业务日计算，不按自然日计算
- 中奖管理和结果计算状态中的日期筛选，也都按业务日计算
- 如果某文件上传时间是当天中午 12 点前，它会显示在前一个业务日下
- 如果设备在线但后台速度统计没显示，优先检查该会话是否带了 `device_id`

### 用户操作

#### A模式接单
1. 登录用户账号
2. 打开"A模式接单"开关
3. 系统自动显示数据内容
4. 操作：
   - **下一条**：完成当前条目，获取下一条
   - **上一条**：查看历史记录（最多3条）
   - **停止**：结束接单

说明：
- 如果点击完成时已经超过截止时间，系统会先确认是否真的完成
- 未超时则直接按完成处理，不弹窗
- A 模式用户不能使用 B 模式桌面端客户端

#### B模式批量下载
1. 登录用户账号
2. 选择类型（自动加载截止时间）
3. 选择张数（50/100/200/300/400/500）
4. 点击"下载"获取TXT文件
5. 完成后点击确认，系统按业务规则落库

说明：
- B 模式桌面端客户端仅允许 `client_mode = mode_b` 的账号使用
- 如果确认完成时已经超过截止时间，系统会先确认是否全部完成
- 选择“部分完成”时，前 N 张记为完成，其余记为过期
- 用户“今日处理清单”导出按业务日统计，并且只导出当前业务日内已完成且已过截止时间的票

---

## ⚙️ 配置说明

### 环境变量（.env）

```bash
SECRET_KEY=your-secret-key-here
FLASK_ENV=production
DATABASE_URL=sqlite:////path/to/data.db
REDIS_URL=redis://localhost:6379/0
UPLOAD_FOLDER=uploads
SESSION_LIFETIME_HOURS=3
DAILY_RESET_HOUR=12
OSS_BUCKET_NAME=
OSS_ENDPOINT=
OSS_ACCESS_KEY_ID=
OSS_ACCESS_KEY_SECRET=
```

### 关键配置项说明

- `DATABASE_URL`
  - 开发默认通常使用 SQLite
  - 生产建议 PostgreSQL
- `REDIS_URL`
  - 用于缓存/推送；不可用时系统会退化到部分 DB-only 模式
- `SESSION_LIFETIME_HOURS`
  - 会话有效期
- `DAILY_RESET_HOUR`
  - 默认 `12`，与业务日切换保持一致
- `UPLOAD_FOLDER`
  - 本地文件和中奖图片落盘目录

---

## 🛠 常见排查

### 1. 统计数字不对

优先确认三件事：

1. 看的是否是业务日，而不是自然日
2. 票是否真的已经写成 `completed`
3. `completed_at` 是否落在当前业务日窗口内

### 2. 后台设备速度统计没显示某台设备

优先检查：

1. 设备是否真的在线
2. 当前 `UserSession.device_id` 是否为空
3. 该设备最近是否有 `completed` 票

### 3. 文件列表里日期看起来“差一天”

这通常不是 bug，而是业务日口径导致：

- 例如 `4/7 11:30` 上传的文件，会归到业务日 `4/6`

### 4. 用户导不出“今日处理清单”

通常有两种原因：

1. 当前业务日内还没有 `completed` 票
2. 虽然已完成，但这些票的 `deadline_time` 还没到，所以暂时不允许导出

### 5. 桌面端登录了但不能接单

优先检查：

1. 该用户是否为 `mode_b`
2. `can_receive` 是否被管理员关闭
3. `max_devices` 是否超限
4. 当前服务地址是否连到了正确实例

### 6. 上传目录里的 TXT 越来越多怎么办

当前策略已经做了两层控制：

1. 新上传的原始 TXT 会按业务日分目录落盘
2. 超过 30 天且已闭环的数据，会在定时任务里删除对应 TXT 和数据库记录

也就是说：

- 短期内每天新增上百个 TXT 没问题
- 长期不会无限累积在同一个目录
- 超过保留期的数据不会一直留在数据库和磁盘里

### 7. 历史数据会保留多久

当前策略是：

- 管理员和用户的业务历史数据原则上只保留最近 30 天
- 清理任务每周执行一次
- 因此允许存在最多不到 7 天的浮动窗口
- 用户中奖记录默认只看最近数据，最多支持最近 4 个业务日

---

## 🚢 部署指南

### 生产环境（Linux）

```bash
# 安装依赖
pip install -r requirements.txt

# 初始化数据库
python init_db.py

# 启动应用
gunicorn -c gunicorn_config.py run:app
```

### 开机自启（systemd）

```ini
[Unit]
Description=Data File Management Platform
After=network.target redis.service

[Service]
User=root
WorkingDirectory=/root/file-hub
Environment=PATH=/root/file-hub/.venv/bin
ExecStart=/root/file-hub/.venv/bin/gunicorn -c gunicorn_config.py run:app
Restart=always

[Install]
WantedBy=multi-user.target
```

### Nginx反向代理

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    location /socket.io {
        proxy_pass http://127.0.0.1:5000/socket.io;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

---

## 📊 数据库说明

### 主要数据表

- **users** - 用户表
- **user_sessions** - 会话表
- **device_registry** - 设备注册表
- **uploaded_files** - 上传文件表
- **lottery_tickets** - 数据条目表（核心）
- **match_results** - 结果表
- **winning_records** - 中签记录表
- **system_settings** - 系统设置表
- **audit_logs** - 审计日志表

---

## 🔒 安全建议

1. **修改默认密码**：首次部署后立即修改管理员密码
2. **使用HTTPS**：生产环境建议使用HTTPS
3. **定期备份**：定期备份数据库文件
4. **限制访问**：使用防火墙限制访问IP
5. **环境变量**：不要将.env文件提交到git

---

## 📝 更新日志

### 2026-03-30 - 前端模板修复与后端增强

**前端修复**：
- 修复了所有模板的 JavaScript 语法错误（字符串未闭合、注释损坏、变量声明缺失）
- 修正了多个 API 路径错误（如中奖页"标记已检查"按钮）
- 修复了状态管理问题（中奖记录分组、B模式处理中列表残留等）
- 为所有前端请求补充了网络异常处理和失败提示
- 统一了所有提示文案为中文

**后端增强**：
- 添加了参数校验，防止非法输入导致500错误
- 添加了管理员账号保护，禁止通过API误操作管理员
- 修复了B模式确认零完成时的返回值
- 重构了图片上传逻辑，支持无Pillow环境回退
- 补充了运行时依赖：Pillow、openpyxl

**测试增强**：
- 新增62个回归测试用例，全部通过

详见 `docs/bug-fix-log-2026-03-30.md`

### 2026-04-07 - 业务日口径统一与超时确认修复

- A / B 模式补充超时完成确认，避免超时后误整批记为完成
- 桌面端客户端补齐设备 ID 会话上报，并限制为 B 模式账号使用
- 用户统计、用户导出、后台统计、文件列表、中奖管理、结果计算状态统一改为业务日 `12:00 -> 次日12:00` 口径

详见 `docs/bug-fix-log-2026-04-07.md`

### 2026-03-24 - 每日处理票数上限

- 用户管理新增 `daily_ticket_limit` 字段
- 限制用户每个业务日期可处理的总票数
- A/B模式均生效

### 2026-03-23 - 设备速度统计与B模式优化

- 管理后台新增设备处理速度统计
- 管理后台新增预估完成时间
- B模式单彩种单文件优化
- 客户端新增设备维度统计
- 中奖记录增强查询功能

---

## 📄 许可证

本项目仅供内部使用。

---

## 📅 开发周报

### 2026-03-30 核心 Bug 修复（12个）

#### 安全与会话
1. **会话验证增强** — 每次请求强制校验 session_token，修复会话过期后仍可访问的问题
2. **关闭公开注册** — 统一注册流程，只允许管理员后台创建账号

#### 业务逻辑
3. **停池状态统一** — 停池时统一返回空池，修复停池后仍显示待处理票数
4. **A模式显式确认** — 实现显式票ID确认机制，防止重复请求误完成票
5. **B模式批次查询修复** — 未传 device_id 返回所有批次，修复页面刷新后批次"消失"
6. **中奖记录同步** — 上传图片时同步写入 WinningRecord，修复后台查不到记录
7. **文件计数同步** — 过期任务同步更新文件计数，修复管理端显示失真

#### 数据库与环境
8. **SQLite 自举** — 空库自动建表和创建默认管理员，修复登录"网络错误"
9. **数据库路径规范化** — 统一到 instance/ 目录，修复多份数据库混乱
10. **数据库信息可视化** — 后台显示当前连接路径，便于排查环境问题

#### 前端与测试
11. **修改密码路径修复** — 修复前端请求路径错误导致 404
12. **pytest 配置优化** — 限制测试收集范围，修复收集阶段中断

**详细记录：** `docs/bug-fix-log-2026-03-30.md`

### 2026-03-13 ~ 2026-03-20

#### 核心功能完善
1. **并发安全优化** — 将 SQLite 分票锁从 `threading.Lock` 改为 `gevent.lock.BoundedSemaphore`
2. **设备管理增强** — 修复设备限制检查逻辑，过滤过期会话不占用设备名额
3. **B 模式资源保留** — B 模式始终为 A 模式保留 20 张票缓冲
4. **数据导出优化** — 今日处理清单空结果返回友好提示
5. **统计功能增强** — 新增今日各设备出票统计

#### 文档与规范
- 创建 `CLAUDE.md` 项目上下文文件
- 更新 README，统一项目名称为 file-hub
- 补充并发安全说明和实现细节

**提交数：** 21 commits
