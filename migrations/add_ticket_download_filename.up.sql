ALTER TABLE lottery_tickets ADD COLUMN IF NOT EXISTS download_filename VARCHAR(512);
ALTER TABLE archived_lottery_tickets ADD COLUMN IF NOT EXISTS download_filename VARCHAR(512);
