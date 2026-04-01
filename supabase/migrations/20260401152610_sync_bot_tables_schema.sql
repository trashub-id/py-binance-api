-- Sinkronisasi seluruh kolom yang dibutuhkan Python bot_logger
-- Menambahkan kolom-kolom baru jika sebelumnya Anda tidak membuatnya di dashboard.

ALTER TABLE public.bot_logs 
ADD COLUMN IF NOT EXISTS message TEXT,
ADD COLUMN IF NOT EXISTS error_trace TEXT,
ADD COLUMN IF NOT EXISTS payload JSONB;

ALTER TABLE public.trades 
ADD COLUMN IF NOT EXISTS entry_order_id TEXT,
ADD COLUMN IF NOT EXISTS symbol TEXT,
ADD COLUMN IF NOT EXISTS side TEXT,
ADD COLUMN IF NOT EXISTS quantity NUMERIC,
ADD COLUMN IF NOT EXISTS entry_price NUMERIC,
ADD COLUMN IF NOT EXISTS status TEXT,
ADD COLUMN IF NOT EXISTS tp_order_id TEXT,
ADD COLUMN IF NOT EXISTS sl_order_id TEXT,
ADD COLUMN IF NOT EXISTS payload JSONB;
