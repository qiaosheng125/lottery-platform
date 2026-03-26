-- 添加中签记录审核标记字段
-- 2026-03-26

ALTER TABLE winning_records ADD COLUMN is_checked BOOLEAN DEFAULT 0 NOT NULL;
ALTER TABLE winning_records ADD COLUMN checked_at DATETIME NULL;
ALTER TABLE winning_records ADD COLUMN checked_by INTEGER NULL;

-- 添加外键约束
-- SQLite 不支持 ADD CONSTRAINT，需要在应用层处理

-- 为已有记录设置默认值（未检查）
UPDATE winning_records SET is_checked = 0 WHERE is_checked IS NULL;
