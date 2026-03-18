# 彩票数据管理分发平台

一个基于Flask的彩票数据管理和分发系统，支持管理员上传彩票数据文件，用户通过A/B两种模式接单出票，并自动计算中奖结果。

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

## ✨ 功能特性

### 管理员功能
- 📤 **文件上传**：上传TXT格式彩票数据文件，系统自动解析
- 📊 **实时监控**：查看在线用户、票池状态、出票进度
- 👥 **用户管理**：创建用户、设置接单模式、设备数量限制
- 🎯 **中奖管理**：上传赛果文件，自动计算中奖金额
- 🔄 **文件撤回**：支持撤回已上传的文件
- ⚙️ **系统设置**：配置B模式批量选项、公告等

### 用户功能
- 🎫 **A模式接单**：逐张接单，浮层显示，支持上一张/下一张导航
- 📦 **B模式批量下载**：按彩种和截止时间批量获取彩票
- 📱 **手机端优化**：全屏铺满、大字体大按钮、防误触设计
- 🏆 **中奖查询**：查看个人中奖记录，按日期分类
- 📈 **统计信息**：今日出票张数、金额、票池剩余等
- 🔧 **设备管理**：注册设备、自定义设备名称

### 系统功能
- 🔐 **多设备管理**：支持设备注册、命名、数量限制
- 💓 **心跳机制**：30秒心跳，2分钟在线检测
- 🔄 **会话管理**：3小时无活动自动清理，每日12点重置
- 📡 **实时推送**：WebSocket推送票池状态、文件上传等事件
- 🗄️ **数据归档**：每周一凌晨6点自动归档，30天保留期
- ⏰ **定时任务**：超时票检测、会话清理、每日重置

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

### 支持的彩票玩法
- **SPF** - 胜平负
- **CBF** - 比分
- **JQS** - 总进球
- **BQC** - 半全场
- **SXP** - 上下盘（0=上单，1=上双，2=下单，3=下双）
- **SF** - 胜负

---

## 🚀 快速开始

### 环境要求
- Python 3.9+
- pip

### 安装步骤

1. **克隆项目**
```bash
git clone https://github.com/qiaosheng125/lottery-platform.git
cd lottery-platform
```

2. **创建虚拟环境**
```bash
python -m venv venv
# Windows
venv\Scripts\activate
# Linux/Mac
source venv/bin/activate
```

3. **安装依赖**
```bash
pip install -r requirements.txt
```

4. **配置环境变量**
```bash
# 复制示例配置文件
cp .env.example .env

# 编辑.env文件，设置必要的配置
# SECRET_KEY=your-secret-key-here
# DATABASE_URL=sqlite:///lottery.db
```

5. **初始化数据库**
```bash
python init_db.py
```

6. **运行应用**
```bash
python run.py
```

7. **访问应用**
- 打开浏览器访问：http://localhost:5000
- 默认管理员账号：admin / admin123（首次运行后请修改密码）

---

## 📁 项目结构

```
lottery-platform/
├── app.py                      # Flask应用工厂
├── config.py                   # 配置文件
├── extensions.py               # Flask扩展初始化
├── run.py                      # 应用启动入口
├── init_db.py                  # 数据库初始化脚本
├── requirements.txt            # Python依赖
├── .env.example                # 环境变量示例
├── .gitignore                  # Git忽略文件
│
├── models/                     # 数据模型
│   ├── user.py                 # 用户、会话模型
│   ├── device.py               # 设备注册模型
│   ├── file.py                 # 上传文件模型
│   ├── ticket.py               # 彩票数据模型
│   ├── result.py               # 赛果模型
│   ├── winning.py              # 中奖记录模型
│   ├── settings.py             # 系统设置模型
│   └── audit.py                # 审计日志模型
│
├── routes/                     # 路由控制器
│   ├── auth.py                 # 认证路由
│   ├── admin.py                # 管理员路由
│   ├── user.py                 # 用户路由
│   ├── mode_a.py               # A模式路由
│   ├── mode_b.py               # B模式路由
│   ├── pool.py                 # 票池路由
│   ├── device.py               # 设备管理路由
│   └── winning.py              # 中奖路由
│
├── services/                   # 业务逻辑服务
│   ├── file_parser.py          # 文件解析服务
│   ├── ticket_pool.py          # 票池管理服务
│   ├── mode_a_service.py       # A模式服务
│   ├── mode_b_service.py       # B模式服务
│   ├── result_parser.py        # 赛果解析服务
│   ├── winning_calc_service.py # 中奖计算服务
│   ├── session_service.py      # 会话管理服务
│   ├── notify_service.py       # 通知推送服务
│   └── oss_service.py          # OSS服务（预留）
│
├── tasks/                      # 定时任务
│   ├── scheduler.py            # 调度器初始化
│   ├── expire_tickets.py       # 超时票检测
│   ├── clean_sessions.py       # 会话清理
│   ├── daily_reset.py          # 每日重置
│   └── archive.py              # 数据归档
│
├── sockets/                    # WebSocket事件
│   ├── pool_events.py          # 票池事件
│   └── admin_events.py         # 管理员事件
│
├── utils/                      # 工具函数
│   ├── filename_parser.py      # 文件名解析
│   ├── amount_parser.py        # 金额计算
│   ├── winning_calculator.py   # 中奖计算
│   ├── time_utils.py           # 时间工具
│   └── decorators.py           # 装饰器
│
├── templates/                  # HTML模板
│   ├── base.html               # 基础模板
│   ├── login.html              # 登录页
│   ├── admin/                  # 管理员页面
│   │   ├── dashboard.html      # 管理员主页
│   │   ├── upload.html         # 文件上传
│   │   ├── users.html          # 用户管理
│   │   ├── winning.html        # 中奖管理
│   │   └── settings.html       # 系统设置
│   └── client/                 # 用户页面
│       └── dashboard.html      # 用户主页
│
├── static/                     # 静态资源
│   ├── css/
│   │   └── style.css           # 样式文件
│   └── js/
│       ├── app.js              # 公共JS
│       ├── ticket_renderer.js  # 票面渲染
│       ├── mode_a.js           # A模式JS
│       ├── mode_b.js           # B模式JS
│       ├── admin.js            # 管理员JS
│       └── socket_client.js    # WebSocket客户端
│
└── uploads/                    # 上传文件目录（自动创建）
```

---

## 🎯 核心功能

### 1. 文件上传和解析

**文件名格式**：
```
标识_内部代码+彩种+倍投_金额XXX元_XX张_HH.MM_期号.txt
示例: 军_V58比分2倍投_金额240元_11张_23.55_26034.txt
```

**文件内容格式**：
```
SPF|1=0,2=1,3=0/1/3,4=3,5=0/1/3,6=0|6*1|3
CBF|1=20,2=90/42/41/40/31/30|2*1|2
```

**解析规则**：
- 自动提取彩种、倍投、金额、截止时间、期号
- 计算每行金额：`2 × ∏(各场次选项数量) × 最终倍数`
- 生成唯一票据ID，写入数据库

### 2. A模式接单

**特点**：
- 逐张接单，浮层显示
- 支持上一张/下一张导航（客户端历史记录）
- 实时倒计时显示
- 手机端全屏铺满优化
- 防误触设计（接单时页面锁定）

**操作流程**：
1. 打开接单开关
2. 系统自动分配一张票
3. 查看票面内容
4. 点击"下一张"继续，或"停止"结束

### 3. B模式批量下载

**特点**：
- 按彩种批量获取
- 服务器自动按最早截止时间分配
- 支持自定义张数（50/100/200/300/400/500）
- 自动分组打包（按彩种分文件）

**文件名格式**：
```
{彩种}_{倍数}倍_{金额}元_{截止HH.MM}_{时间戳}.txt
示例: 比分_2倍_96元_21.55_2026-0318-081715.txt
```

### 4. 中奖计算

**计算逻辑**：
- 支持6种玩法的中奖判断
- 串关组合计算（笛卡尔积）
- 延期场次处理（任何选项都算中，SP=1.0）
- 奖金计算：`SP值之积 × 2元 × 倍投数 × 1.3系数`
- 扣税规则：>10000元扣税20%

**赛果文件格式**：
```
序号  让球胜平负彩果  让球胜平负SP值  比分彩果  比分SP值  ...
1     3              4.918           1-3       17.454    ...
```

---

## 📖 使用说明

### 管理员操作

#### 1. 上传彩票数据
1. 登录管理员账号
2. 进入"文件上传"页面
3. 选择TXT文件（支持批量上传）
4. 系统自动解析并写入票池

#### 2. 上传赛果文件
1. 进入"中奖管理"页面
2. 点击"上传赛果"
3. 选择赛果TXT文件
4. 输入期号（如：26034）
5. 系统自动计算所有已完成票的中奖情况

#### 3. 用户管理
1. 进入"用户管理"页面
2. 创建新用户，设置：
   - 用户名和密码
   - 接单模式（A模式/B模式）
   - 最大设备数（默认1）
3. 可随时修改用户设置、强制下线

### 用户操作

#### A模式接单
1. 登录用户账号
2. 打开"A模式接单"开关
3. 系统自动显示票面
4. 操作：
   - **下一张**：完成当前票，获取下一张
   - **上一张**：查看历史票（最多3张）
   - **停止**：结束接单

#### B模式批量下载
1. 登录用户账号
2. 选择彩种（自动加载截止时间）
3. 选择张数（50/100/200/300/400/500）
4. 点击"预览"查看可用数量
5. 点击"下载"获取TXT文件
6. 系统自动标记为已完成

---

## ⚙️ 配置说明

### 环境变量（.env）

```bash
# Flask配置
SECRET_KEY=your-secret-key-here
FLASK_ENV=development

# 数据库
DATABASE_URL=sqlite:///lottery.db

# Redis（可选，用于票池缓存）
REDIS_URL=redis://localhost:6379/0

# 上传目录
UPLOAD_FOLDER=uploads

# 会话配置
SESSION_LIFETIME_HOURS=3
DAILY_RESET_HOUR=12

# OSS配置（可选）
OSS_BUCKET_NAME=
OSS_ENDPOINT=
OSS_ACCESS_KEY_ID=
OSS_ACCESS_KEY_SECRET=
```

### 系统设置（管理员界面）

- **注册开关**：是否允许新用户注册
- **票池开关**：是否允许用户接单
- **B模式张数选项**：自定义批量下载张数
- **公告**：系统公告内容

---

## 🚢 部署指南

### 开发环境

```bash
python run.py
```

访问：http://localhost:5000

### 生产环境（Linux）

#### 1. 使用Gunicorn

```bash
# 安装Gunicorn
pip install gunicorn gevent-websocket

# 启动应用
gunicorn -c gunicorn_config.py run:app
```

#### 2. 使用Supervisor守护进程

创建配置文件 `/etc/supervisor/conf.d/lottery-platform.conf`：

```ini
[program:lottery-platform]
directory=/path/to/lottery-platform
command=/path/to/venv/bin/gunicorn -c gunicorn_config.py run:app
user=www-data
autostart=true
autorestart=true
stderr_logfile=/var/log/lottery-platform.err.log
stdout_logfile=/var/log/lottery-platform.out.log
```

启动服务：
```bash
sudo supervisorctl reread
sudo supervisorctl update
sudo supervisorctl start lottery-platform
```

#### 3. Nginx反向代理

```nginx
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
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
- **lottery_tickets** - 彩票数据表（核心）
- **match_results** - 赛果表
- **result_files** - 赛果文件表
- **winning_records** - 中奖记录表
- **system_settings** - 系统设置表
- **audit_logs** - 审计日志表

### 数据归档

- 每周一凌晨6点自动归档
- 归档30天前的数据
- 归档后数据移至 `lottery_tickets_archive` 表

---

## 🧪 测试

### 运行测试脚本

```bash
# 彩果解析测试
python test_result_parser.py

# 中奖计算测试
python test_winning_calc.py

# 延期和扣税测试
python test_postponed_tax.py

# 完整兑奖流程测试
python run_26034_winning_calc.py

# 查询中奖详情
python query_26034_winning.py
```

### 手机端测试

打开浏览器访问：
- `test_mobile_mode_a.html` - A模式测试页面
- `test_mobile_mode_a_v2.html` - A模式测试页面v2（全屏铺满）

---

## 📝 开发说明

### 添加新的彩票玩法

1. 在 `utils/amount_parser.py` 中添加解析逻辑
2. 在 `utils/winning_calculator.py` 中添加中奖判断逻辑
3. 在 `services/result_parser.py` 中添加赛果解析
4. 在 `static/js/ticket_renderer.js` 中添加票面渲染

### 自定义定时任务

在 `tasks/scheduler.py` 中添加：

```python
from apscheduler.triggers.cron import CronTrigger

scheduler.add_job(
    func=your_function,
    trigger=CronTrigger(hour=0, minute=0),
    id='your_task_id',
    replace_existing=True
)
```

---

## 🔒 安全建议

1. **修改默认密码**：首次部署后立即修改admin密码
2. **使用HTTPS**：生产环境必须使用HTTPS
3. **定期备份**：定期备份数据库文件
4. **限制访问**：使用防火墙限制访问IP
5. **环境变量**：不要将.env文件提交到git
6. **Token管理**：定期更换GitHub Token等敏感信息

---

## 📄 许可证

本项目仅供学习和研究使用。

---

## 👥 贡献者

- 开发：Claude Sonnet 4.6
- 需求：项目所有者

---

## 📞 联系方式

如有问题或建议，请通过GitHub Issues反馈。

---

## 🎉 致谢

感谢使用本系统！
