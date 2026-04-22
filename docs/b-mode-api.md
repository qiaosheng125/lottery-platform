# B 模式接口文档（客户对接版）

本文档用于给 B 模式客户端对接方直接接入。

## 1. 基本说明

- 基础地址：`https://zdj8.fun`
- 鉴权方式：`Session Cookie`
- 登录接口：`POST /auth/login`
- 请求体格式：`application/json`
- 字符编码：`UTF-8`
- 时间字段：服务端返回 `ISO 8601` 风格字符串，例如 `2026-04-22T14:30:00`
  - 当前实现按北京时间生成
  - 返回值通常不带时区后缀，客户端按北京时间处理即可

## 2. 推荐接入流程

1. 调用 `POST /auth/login` 登录，并保存服务端返回的 Cookie。
2. 建议首次登录后调用 `POST /api/device/register` 注册设备。
3. 定时调用 `POST /auth/heartbeat` 维持会话。
4. 调用 `GET /api/user/daily-stats` 获取账号状态和 B 模式可选张数。
5. 调用 `GET /api/mode-b/pool-status` 或 `GET /api/mode-b/preview` 查看当前可接数据。
6. 调用 `POST /api/mode-b/download` 下载一批票。
7. 客户端处理完成后，调用 `POST /api/mode-b/confirm` 确认完成。
8. 如客户端重启或掉线，可调用 `GET /api/mode-b/processing` 恢复当前设备未确认批次。

## 3. 设备号规则

`device_id` 是 B 模式的重要字段，建议一个设备固定一个值。

- 长度：`1-20`
- 允许字符：字母、数字、`-`、`_`
- 建议示例：`pc-01`、`client_a_01`

注意：

- 同一个登录会话一旦绑定了 `device_id`，后续不能切换为别的 `device_id`，否则会返回 `403`
- B 模式以下接口必须带 `device_id`
  - `POST /api/mode-b/download`
  - `GET /api/mode-b/processing`
  - `POST /api/mode-b/confirm`
- 登录时可以直接带 `device_id`；如果登录时没带，第一次访问上述 B 模式接口时，服务端会把当前会话绑定到该设备号

## 4. 通用返回格式

成功示例：

```json
{
  "success": true
}
```

失败示例：

```json
{
  "success": false,
  "error": "错误说明"
}
```

建议客户端主要依据以下字段判断：

- HTTP 状态码
- `success`
- 业务数据字段

不建议依赖错误文案全文匹配，因为当前部分错误文案是中文，部分是英文。

常见状态码：

- `200`：成功
- `400`：参数错误或当前业务不允许
- `401`：未登录或会话失效
- `403`：无权限、账号停用、设备不匹配、桌面端限制等
- `409`：设备注册冲突

## 5. 接口明细

### 5.1 登录

`POST /auth/login`

请求体：

```json
{
  "username": "demo_user",
  "password": "secret123",
  "device_id": "pc-01"
}
```

说明：

- `device_id` 可选，但 B 模式强烈建议登录时就传
- 登录成功后请保存响应 Cookie，后续接口都要携带

成功返回：

```json
{
  "success": true,
  "redirect": "/api/user/dashboard",
  "is_admin": false,
  "client_mode": "mode_b"
}
```

失败场景：

- `401` 用户名或密码错误
- `403` 账号禁用
- `403` 超过最大设备数限制
- `400` 参数类型不合法

`curl` 示例：

```bash
curl -X POST "https://zdj8.fun/auth/login" \
  -H "Content-Type: application/json" \
  -c cookies.txt \
  -d "{\"username\":\"demo_user\",\"password\":\"secret123\",\"device_id\":\"pc-01\"}"
```

### 5.2 注册设备

`POST /api/device/register`

说明：

- 该接口不是 B 模式强制前置条件
- 但建议客户端登录后调用，用于记录设备信息

请求体：

```json
{
  "device_id": "pc-01",
  "client_info": {
    "client_type": "desktop",
    "device_name": "Windows-PC-01",
    "version": "1.0.0"
  }
}
```

成功返回：

```json
{
  "success": true,
  "device": {
    "id": 1,
    "device_id": "pc-01",
    "user_id": 12,
    "client_info": {
      "client_type": "desktop",
      "device_name": "Windows-PC-01",
      "version": "1.0.0"
    },
    "first_seen": "2026-04-22T10:00:00",
    "last_active": "2026-04-22T10:00:00",
    "is_authorized": true
  }
}
```

失败场景：

- `400` 缺少或非法 `device_id`
- `409` 该 `device_id` 已被其他用户占用

### 5.3 心跳保活

`POST /auth/heartbeat`

请求体：

```json
{
  "device_id": "pc-01"
}
```

成功返回：

```json
{
  "success": true
}
```

说明：

- 用于刷新会话过期时间
- 当前系统默认会话时长为 3 小时，实际值以服务端配置为准
- 建议客户端每 5 到 10 分钟调用一次

### 5.4 获取账号与今日统计

`GET /api/user/daily-stats`

作用：

- 获取账号今日完成情况
- 获取 B 模式前端建议张数 `mode_b_options`
- 获取当前账号是否允许接单

成功返回示例：

```json
{
  "success": true,
  "today": "2026-04-22",
  "ticket_count": 18,
  "total_amount": 360.0,
  "active_count": 6,
  "can_receive": true,
  "pool_total_pending": 120,
  "announcement": "",
  "mode_b_options": [50, 100, 200, 300, 400, 500],
  "device_stats": [
    {
      "device_id": "pc-01",
      "count": 12,
      "amount": 240.0
    }
  ]
}
```

说明：

- `pool_total_pending` 对 B 模式账号来说，已经扣除了系统给 A 模式预留的张数
- `mode_b_options` 是前端推荐选择项，客户端可以直接展示给用户
- 服务端对 `download.count` 的硬性校验是“正整数”，不是必须落在 `mode_b_options` 内

### 5.5 B 模式池状态

`GET /api/mode-b/pool-status`

作用：

- 查看当前 B 模式可见票池状态
- 返回值已经扣除了系统预留给 A 模式的保留张数

成功返回示例：

```json
{
  "success": true,
  "total_pending": 35,
  "by_type": [
    {
      "lottery_type": "胜平负",
      "deadline_time": "2026-04-22T14:00:00",
      "count": 20
    },
    {
      "lottery_type": "让球胜平负",
      "deadline_time": "2026-04-22T16:00:00",
      "count": 15
    }
  ],
  "assigned": 10,
  "completed_today": 86
}
```

说明：

- `total_pending` 是当前 B 模式实际可见总数
- `by_type` 是按彩种和截止时间拆分后的可见数量
- 若系统关闭 B 模式或关闭票池，该接口仍返回 `200`，但数量为 `0`
- 若账号已停止接单，该接口仍返回 `200`，但数量为 `0`

### 5.6 B 模式预估可下载数量

`GET /api/mode-b/preview?count=100`

参数：

- `count`：期望下载张数，正整数，默认 `100`

成功返回示例：

```json
{
  "success": true,
  "available": 30,
  "requested": 100,
  "sufficient": false
}
```

字段说明：

- `requested`：客户端请求张数
- `available`：当前这一批最多能拿到多少张
- `sufficient`：是否足够满足 `requested`

重要说明：

- 该接口返回的 `available` 不是简单的“票池总数”
- 它会综合以下因素计算当前这一批最多能下发多少张
  - A 模式预留张数
  - 用户禁止彩种
  - 用户 B 模式处理中上限
  - 用户每日处理上限
  - B 模式单批次选票规则

失败场景：

- `400` `count` 不是正整数

### 5.7 B 模式批量下载

`POST /api/mode-b/download`

请求体：

```json
{
  "count": 100,
  "device_id": "pc-01",
  "client_type": "desktop"
}
```

参数说明：

- `count`：正整数，默认 `100`
- `device_id`：必填
- `client_type`：可选，建议桌面客户端固定传 `desktop`
  - 当账号开启“B 模式仅桌面端接单”时，浏览器或 `web` 会被拒绝

成功返回示例：

```json
{
  "success": true,
  "files": [
    {
      "filename": "胜平负_2倍_100张_200元_14.00_2026-0422-103000.txt",
      "content": "第1行票内容\n第2行票内容\n第3行票内容",
      "ticket_ids": [101, 102, 103],
      "count": 3,
      "amount": 6.0,
      "deadline_time": "2026-04-22T14:00:00"
    }
  ],
  "ticket_ids": [101, 102, 103],
  "actual_count": 3,
  "total_amount": 6.0,
  "adjustment_message": "已自动调整为 3 张"
}
```

说明：

- 当前接口直接把文件内容放在 JSON 的 `files[0].content` 中返回，不需要再调单独下载文件接口
- `files` 当前实现只返回一个文件
- 一次下载只会分配一个彩种、一个批次
- 客户端通常按 `filename` 保存本地文件，文件内容使用 `content`
- `adjustment_message` 只有在服务端自动缩减数量时才会出现

常见失败场景：

- `400` `count` 不是正整数
- `400` 缺少 `device_id`
- `400` `device_id` 非法
- `401` 会话无效
- `403` 当前账号停止接单
- `403` `device_id` 与当前会话绑定设备不一致
- `403` 该账号仅允许桌面端接单
- `400` 当前票池无可用票

### 5.8 查询当前设备处理中批次

`GET /api/mode-b/processing?device_id=pc-01`

作用：

- 查询当前设备尚未确认完成的批次
- 适合客户端重启后恢复任务

成功返回示例：

```json
{
  "success": true,
  "batches": [
    {
      "filename": "胜平负_2倍_100张_200元_14.00_（已接单）.txt",
      "ticket_ids": [101, 102, 103],
      "count": 3,
      "amount": 6.0,
      "downloaded_at": "10:30:00",
      "deadline_time": "2026-04-22T14:00:00"
    }
  ]
}
```

失败场景：

- `400` 缺少 `device_id`
- `400` `device_id` 非法
- `401` 会话无效
- `403` `device_id` 与当前会话绑定设备不一致

### 5.9 确认批次完成

`POST /api/mode-b/confirm`

请求体：

```json
{
  "ticket_ids": [101, 102, 103],
  "completed_count": 2,
  "device_id": "pc-01"
}
```

参数说明：

- `ticket_ids`：必填，整数数组
- `completed_count`：可选，整数
  - 不传时，默认全部完成
  - 传了以后，服务端会按 `ticket_ids` 当前顺序，将前 `completed_count` 张记为完成，其余记为过期
- `device_id`：必填

成功返回示例：

```json
{
  "success": true,
  "completed_count": 2,
  "expired_count": 1
}
```

业务规则：

- 若 `ticket_ids=[101,102,103]` 且 `completed_count=2`
  - `101`、`102` 会被记为 `completed`
  - `103` 会被记为 `expired`
- 同一个设备只能确认自己设备上的票

失败场景：

- `400` 缺少 `ticket_ids`
- `400` `ticket_ids` 不是整数数组
- `400` `completed_count` 不是整数
- `400` `completed_count` 超出当前去重后的票数范围
- `400` 没有可确认的票
- `403` `device_id` 与当前会话绑定设备不一致

## 6. 对接注意事项

1. 登录后一定要保存 Cookie。当前接口体系不是 Bearer Token。
2. B 模式建议客户端全程使用同一个 `device_id`。
3. 建议登录时就传 `device_id`，避免后续接口第一次调用时再自动绑定。
4. `download` 返回的是 JSON 内嵌文件内容，不是二进制文件流。
5. `preview.available` 是“当前单批次最多可拿数量”，不等于池子总库存。
6. 如果账号被设置为“仅桌面端接单”，客户端请传 `client_type=desktop`，并避免用浏览器 UA 调用下载接口。
7. 建议所有 POST 请求都显式带 `Content-Type: application/json`。

## 7. 最小调用链示例

### 7.1 登录

```bash
curl -X POST "https://zdj8.fun/auth/login" \
  -H "Content-Type: application/json" \
  -c cookies.txt \
  -d "{\"username\":\"demo_user\",\"password\":\"secret123\",\"device_id\":\"pc-01\"}"
```

### 7.2 查看可下载数量

```bash
curl "https://zdj8.fun/api/mode-b/preview?count=100" \
  -b cookies.txt
```

### 7.3 下载一批

```bash
curl -X POST "https://zdj8.fun/api/mode-b/download" \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  -d "{\"count\":100,\"device_id\":\"pc-01\",\"client_type\":\"desktop\"}"
```

### 7.4 确认完成

```bash
curl -X POST "https://zdj8.fun/api/mode-b/confirm" \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  -d "{\"ticket_ids\":[101,102,103],\"completed_count\":3,\"device_id\":\"pc-01\"}"
```
