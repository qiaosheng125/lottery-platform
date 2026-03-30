# 数据文件管理分发平台

一个基于Flask的数据文件管理和分发系统，支持管理员上传数据文件，用户通过A/B两种模式接单处理，并自动计算结果。

## 📋 目录

- [功能特性](#功能特性)
- [技术栈](#技术栈)
- [快速开始](#快速开始)
- [项目结构](#项目结构)
- [核心功能](#核心功能)
- [使用说明](#使用说明)
- [配置说明](#配置说明)
- [部署指南](#部署指南)

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
- 🗄️ **数据归档**：每周一凌晨6点自动归档，30天保留期
- ⏰ **定时任务**：超时检测、会话清理、每日重置

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

## 🔧 使用说明

### 管理员操作

1. 登录管理员账号
2. 进入"文件管理"上传TXT数据文件
3. 在"管理后台"查看实时处理状态
4. 在"结果管理"上传结果文件触发中签计算

### 用户操作

#### A模式接单
1. 登录用户账号
2. 打开"A模式接单"开关
3. 系统自动显示数据内容
4. 操作：
   - **下一条**：完成当前条目，获取下一条
   - **上一条**：查看历史记录（最多3条）
   - **停止**：结束接单

#### B模式批量下载
1. 登录用户账号
2. 选择类型（自动加载截止时间）
3. 选择张数（50/100/200/300/400/500）
4. 点击"下载"获取TXT文件
5. 系统自动标记为已完成

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
