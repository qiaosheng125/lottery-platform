# HTTPS 证书与自动续期说明

> 文档状态：`当前生产口径（2026-04-22）`
>
> 适用范围：`Ubuntu + nginx + gunicorn + acme.sh + 阿里云 DNS API`
>
> 当前生产目标：
> - 服务器：`121.196.170.150`
> - 主域名：`zdj8.fun`
> - 附加域名：`www.zdj8.fun`

## 当前统一口径

- 对外流量链路：`HTTPS :443 -> nginx -> gunicorn(127.0.0.1:5000) -> Flask`
- 当前证书来源：`Let's Encrypt`
- 当前签发方式：`acme.sh + dns_ali`
- 当前证书落盘路径：
  - `/etc/nginx/ssl/zdj8.fun/zdj8.fun.pem`
  - `/etc/nginx/ssl/zdj8.fun/zdj8.fun.key`
- 当前 nginx 站点文件：`/etc/nginx/sites-available/file-hub`
- 当前应用必须只监听本机：`GUNICORN_BIND=127.0.0.1:5000`
- 当前代理信任口径：`.env` 中必须设置 `TRUSTED_PROXY_IPS=127.0.0.1`

## 应用侧配置

生产 `.env` 至少需要包含以下两项：

```env
GUNICORN_BIND=127.0.0.1:5000
TRUSTED_PROXY_IPS=127.0.0.1
```

修改后执行：

```bash
systemctl restart file-hub
ss -ltnp | grep 5000
```

期望结果：只看到 `127.0.0.1:5000`，不能再监听 `0.0.0.0:5000`。

## nginx 统一配置

当前生产建议配置如下：

```nginx
server {
    listen 80 default_server;
    server_name zdj8.fun www.zdj8.fun;

    return 301 https://zdj8.fun$request_uri;
}

server {
    listen 443 ssl http2;
    server_name zdj8.fun;

    ssl_certificate /etc/nginx/ssl/zdj8.fun/zdj8.fun.pem;
    ssl_certificate_key /etc/nginx/ssl/zdj8.fun/zdj8.fun.key;

    client_max_body_size 32m;

    location /socket.io/ {
        proxy_pass http://127.0.0.1:5000/socket.io/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 120s;
        proxy_buffering off;
    }

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 120s;
    }
}
```

注意：

- `X-Forwarded-For` 当前统一写法是 `$remote_addr`，不要改回 `$proxy_add_x_forwarded_for`
- `/socket.io/` 必须单独保留 WebSocket 反代配置
- 改完后先执行 `nginx -t`，再执行 `systemctl reload nginx`

## acme.sh + 阿里云 DNS API 自动签发

### 1. 阿里云 RAM 最小权限

建议单独创建一个程序用户，例如 `acme-dns`，只开 `AccessKey`，不要开控制台登录。

策略建议如下：

```json
{
  "Version": "1",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "alidns:AddDomainRecord",
        "alidns:DescribeDomainRecords",
        "alidns:DeleteDomainRecord"
      ],
      "Resource": "acs:alidns:*:*:domain/zdj8.fun"
    }
  ]
}
```

### 2. 安装 acme.sh

正常网络可直接执行：

```bash
curl https://get.acme.sh | sh -s email=you@example.com
```

如果服务器拉 GitHub 很慢或卡住，当前已验证可用的替代路径是：

1. 在本地下载官方 ZIP 包
2. 上传到服务器 `/root/acme.sh-master.zip`
3. 在服务器解压并安装

```bash
cd /root
python3 -m zipfile -e /root/acme.sh-master.zip /root/
chmod +x /root/acme.sh-master/acme.sh
/root/acme.sh-master/acme.sh --install -m you@example.com
```

### 3. 设置 DNS API 凭证并切换 CA

不要把 AccessKey 写进仓库文件。只在当前 shell 会话中临时导出：

```bash
export Ali_Key="你的AccessKeyID"
export Ali_Secret="你的AccessKeySecret"
~/.acme.sh/acme.sh --set-default-ca --server letsencrypt
```

### 4. 申请证书

当前环境已验证可用的签发命令：

```bash
~/.acme.sh/acme.sh --issue --force --dns dns_ali --dnssleep 60 -d zdj8.fun -d www.zdj8.fun --debug 2
```

说明：

- `--dnssleep 60`：跳过 `acme.sh` 自己的公网 DNS 轮询卡顿问题，直接等待 60 秒
- `--force`：如果前一次尝试留下了域名状态，可强制重新签发

### 5. 安装到 nginx 并配置自动 reload

```bash
~/.acme.sh/acme.sh --install-cert -d zdj8.fun --ecc \
  --key-file /etc/nginx/ssl/zdj8.fun/zdj8.fun.key \
  --fullchain-file /etc/nginx/ssl/zdj8.fun/zdj8.fun.pem \
  --reloadcmd "systemctl reload nginx"
```

### 6. 清理当前 shell 中的密钥

```bash
unset Ali_Key Ali_Secret
```

## 自动续期口径

当前 `acme.sh` 安装后会写入 root 的 `crontab`。检查命令：

```bash
crontab -l
~/.acme.sh/acme.sh --info -d zdj8.fun --ecc
```

当前应至少看到：

- 使用 `dns_ali`
- `Le_RealKeyPath=/etc/nginx/ssl/zdj8.fun/zdj8.fun.key`
- `Le_RealFullChainPath=/etc/nginx/ssl/zdj8.fun/zdj8.fun.pem`
- `Le_ReloadCmd=systemctl reload nginx`

## 验证命令

```bash
curl -I https://zdj8.fun
curl -I http://zdj8.fun
echo | openssl s_client -connect zdj8.fun:443 -servername zdj8.fun 2>/dev/null | openssl x509 -noout -issuer -subject -dates
```

本地机器也建议补一轮：

```powershell
curl.exe -I https://zdj8.fun
curl.exe -I https://www.zdj8.fun
curl.exe -I http://zdj8.fun
```

期望结果：

- `https://zdj8.fun` 返回 `302` 到 `/auth/login`
- `https://www.zdj8.fun` 正常握手且返回应用响应
- `http://zdj8.fun` 返回 `301` 跳转到 `https://zdj8.fun/`

## 常见故障

### 1. `nginx -t` 报 duplicate default server

通常是把备份软链接也放进了 `/etc/nginx/sites-enabled/`。删除误放的备份链接即可。

### 2. `acme.sh --issue` 卡在 `Checking zdj8.fun for _acme-challenge...`

当前机器出现过该现象。统一处理方式是改用：

```bash
--dnssleep 60
```

### 3. `_acme-challenge.www.zdj8.fun` 返回 `NXDOMAIN`

说明子域名 TXT 记录没有成功写入公网 DNS。先去阿里云 DNS 控制台确认 `_acme-challenge.www` 是否存在，再重新执行签发。

### 4. `Skipping. Next renewal time is ...`

不是失败，是 `acme.sh` 认为当前无需重签。需要重跑时加：

```bash
--force
```

### 5. SSH 会话断开导致签发中断

重新登录服务器后直接重跑签发命令即可。必要时继续使用 `--force`。

## 安全注意事项

- 不要把 `Ali_Key` / `Ali_Secret`、数据库密码、OSS 密钥写进仓库
- 不要在聊天记录、截图、文档里贴出真实密钥
- 上传到 `/root` 的原始证书文件用完应删除，只保留 `/etc/nginx/ssl/zdj8.fun/` 中的正式文件
- 私钥权限应保持为 `600`

## 参考

- acme.sh：`https://github.com/acmesh-official/acme.sh`
- 阿里云 DNS API：`https://help.aliyun.com/zh/dns/`
