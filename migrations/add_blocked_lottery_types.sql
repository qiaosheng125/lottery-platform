-- 添加用户禁止彩种字段
-- 用于限制某些用户不能接收特定彩种的票

-- SQLite 语法
ALTER TABLE users ADD COLUMN blocked_lottery_types TEXT;

-- PostgreSQL 语法（如果使用 PostgreSQL，请使用以下语句）
-- ALTER TABLE users ADD COLUMN blocked_lottery_types TEXT;
