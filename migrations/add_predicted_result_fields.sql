ALTER TABLE result_files
ADD COLUMN upload_kind VARCHAR(20) NOT NULL DEFAULT 'final';

ALTER TABLE match_results
ADD COLUMN predicted_total_winning_amount NUMERIC(14, 2) NOT NULL DEFAULT 0;

ALTER TABLE lottery_tickets
ADD COLUMN predicted_winning_gross NUMERIC(12, 2);

ALTER TABLE lottery_tickets
ADD COLUMN predicted_winning_amount NUMERIC(12, 2);

ALTER TABLE lottery_tickets
ADD COLUMN predicted_winning_tax NUMERIC(12, 2);
