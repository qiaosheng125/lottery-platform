# 2026-04-09 核心流程修复记录

本次修复聚焦 3 条最核心链路：

- 上传
- 分票
- 标记/回填中奖图片状态

## 1. PostgreSQL 分票上限并发穿透

### 问题

`A` 模式单张分票和 `B` 模式批量分票在 PostgreSQL 路径里，都会先读取：

- 今日已完成数量
- `B` 模式当前处理中数量

然后才真正执行分票更新。

在同一用户多设备并发请求时，这会出现典型的 `check-then-act` 竞争窗口：

- 不会把同一张票分给两台设备
- 但可能让同一个用户穿透每日上限
- 也可能让同一个用户穿透 `B` 模式处理中上限

### 修复

在 [services/ticket_pool.py](/C:/Users/徐逸飞/Desktop/file-hub/services/ticket_pool.py) 中新增 PostgreSQL 用户级事务锁：

- 使用 `pg_advisory_xact_lock`
- 以 `user_id` 作为锁粒度
- 在 PostgreSQL 分票前先加锁，再做上限检查和状态更新

这样同一用户的并发分票请求会在事务内串行化，避免上限被同时穿透。

另外顺手修正了两处分票兼容性问题：

- A 模式 PostgreSQL 文件计数更新改成 `GREATEST(pending_count - 1, 0)`，避免负数
- 分票成功后的取票改成优先 `db.session.get`，失败时再回退 `query.get`，兼容现有测试与 SQLAlchemy 2.x 路径

## 2. 中奖图回填接口允许跨票写入错误 `oss_key`

### 问题

用户端 `/api/winning/record` 和管理端 `/admin/api/winning/record` 之前只校验：

- 票是否存在
- 是否是中奖票
- 用户是否有权限
- 记录是否已被标记已检查

但没有校验 `oss_key` 是否真的属于当前 `ticket_id`。

结果是只要拿到任意可用的 `oss_key`，就可能把别的图片回填到当前票上，造成中奖图片串票。

### 修复

在以下文件中新增 `oss_key` 与 `ticket_id` 绑定校验：

- [routes/winning.py](/C:/Users/徐逸飞/Desktop/file-hub/routes/winning.py)
- [routes/admin.py](/C:/Users/徐逸飞/Desktop/file-hub/routes/admin.py)

校验规则：

- 只接受系统生成的 `winning/<yyyy>/<mm>/<dd>/<ticket_id>.<ext>`
- 或本地模式对应的 `winning_<yyyy>_<mm>_<dd>_<ticket_id>.<ext>`
- 扩展名限制为图片格式

同时保留原来的优先级：

- 如果记录已被管理员标记为“已检查”，仍然优先返回 `403`
- 未检查时再做 `oss_key` 绑定校验，非法则返回 `400`

## 3. 上传同名文件的并发重复导入风险

### 问题

TXT 上传原先只有应用层重复检查：

- 同业务日
- 同文件名（忽略大小写）

但检查和写入之间没有并发保护。

在并发上传同名文件时，两次请求都有机会通过检查，最终导入两份重复数据。

### 修复

在 [services/file_parser.py](/C:/Users/徐逸飞/Desktop/file-hub/services/file_parser.py) 中补了两层保护：

- PostgreSQL：使用业务日 + 小写文件名的事务级 advisory lock
- SQLite：增加进程内 pending guard，拦截同一业务日同名文件的并发重复上传

并在失败分支和成功提交后清理 SQLite guard，避免后续正常上传被误阻塞。

## 回归测试

本次重点验证了以下测试：

```bash
pytest -q tests\test_bug_fixes.py::test_mode_a_postgres_assignment_clamps_file_pending_count tests\test_bug_fixes.py::test_mode_a_sqlite_assignment_retries_after_guarded_update_miss
pytest -q tests\test_bug_fixes.py -k "record_winning_rejects_checked_record_replacement or record_winning_rejects_oss_key_for_other_ticket or admin_winning_record_rejects_oss_key_for_other_ticket or admin_winning_record_rejects_empty_oss_key or admin_winning_presign_rejects_checked_record or winning_presign_rejects_checked_record"
pytest -q tests\test_bug_fixes.py -k "process_uploaded_file_rejects_same_business_day_duplicate_filename or process_uploaded_file_rejects_case_only_duplicate_filename_same_business_day"
```

结果：

- 关键分票回归：通过
- 中奖图回填/已检查保护回归：通过
- 上传重名校验回归：通过

## 变更文件

- [services/ticket_pool.py](/C:/Users/徐逸飞/Desktop/file-hub/services/ticket_pool.py)
- [services/file_parser.py](/C:/Users/徐逸飞/Desktop/file-hub/services/file_parser.py)
- [routes/winning.py](/C:/Users/徐逸飞/Desktop/file-hub/routes/winning.py)
- [routes/admin.py](/C:/Users/徐逸飞/Desktop/file-hub/routes/admin.py)
- [tests/test_bug_fixes.py](/C:/Users/徐逸飞/Desktop/file-hub/tests/test_bug_fixes.py)
