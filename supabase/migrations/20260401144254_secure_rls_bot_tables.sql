-- Enable Row Level Security (RLS) for bot_logs and trades table
-- By NOT creating any policies, we are implicitly denying all access from anon / authenticated roles.
-- The Python bot backend will bypass this completely because it uses the 'service_role' key.

ALTER TABLE public.bot_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.trades ENABLE ROW LEVEL SECURITY;
