-- Menambahkan kolom 'context' yang hilang pada tabel bot_logs agar sesuai dengan logger Python

ALTER TABLE public.bot_logs ADD COLUMN IF NOT EXISTS context text;
