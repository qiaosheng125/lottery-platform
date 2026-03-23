-- 添加 B 模式处理中票数上限字段
-- 执行方式：sqlite3 lottery.db < migrations/add_max_processing_b_mode.sql

-- 添加新列（SQLite 不支持 IF NOT EXISTS，如果列已存在会报错，可忽略）
ALTER TABLE users ADD COLUMN max_processing_b_mode INTEGER DEFAULT NULL;

-- 说明：
-- max_processing_b_mode: B模式用户处理中票数上限
--   - NULL 表示不限制
--   - 整数值表示最多可同时处理的票数
--   - 只对 client_mode='mode_b' 的用户生效
--   - A模式用户不受此限制
