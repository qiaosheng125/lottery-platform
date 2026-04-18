# Ubuntu 云服务器部署说明

> 文档状态：`历史参考（部署）`
>  
> 使用边界：仅在 Linux 生产部署或回滚排障时按需阅读；不属于日常接手必读文档。  
> 回归口径：默认执行主计划里的定向回归，**不做全量回归**；只有明确做部署验收时才结合本文。

## 推荐的生产形态

- `gunicorn workers=2`
- `PostgreSQL`
- `Redis`
- `DB_POOL_SIZE=5`
- `DB_MAX_OVERFLOW=5`

这是当前项目在你这个流量级别下，推荐的第一版生产配置。

## 一键部署

在一台全新的 Ubuntu 服务器上执行：

```bash
git clone -b main https://github.com/qiaosheng125/file-hub.git
cd file-hub
chmod +x scripts/deploy_production_ubuntu.sh
APP_DB_PASSWORD='替换成你的数据库密码' \
SECRET_KEY_VALUE='替换成长随机密钥' \
./scripts/deploy_production_ubuntu.sh
```

这个脚本会完成：

1. 安装 Python、PostgreSQL、Redis 和 nginx。
2. 创建 `.venv`。
3. 安装 Python 依赖。
4. 创建 PostgreSQL 用户和数据库。
5. 按生产默认值写入 `.env`。
6. 在禁用 scheduler 的情况下完成数据库初始化。
7. 创建并启动 `systemd` 服务。

## 服务管理

```bash
sudo systemctl status file-hub
sudo systemctl restart file-hub
sudo journalctl -u file-hub -n 200 --no-pager
```

## 说明

- `init_db.py` 现在会基于当前 `DATABASE_URL` 初始化数据库，并在初始化阶段自动禁用 scheduler，所以全新的 PostgreSQL 空库也能正常启动。
- `.env.example` 现在已经和部署脚本对齐，不再使用旧的 `user:password@localhost` 占位配置。
