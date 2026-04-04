-- Enable Row Level Security (RLS) for daily_portfolio and signals table
-- By NOT creating any policies, we are implicitly denying all access from anon / authenticated roles.
-- The Python bot backend will bypass this completely because it uses the 'service_role' key.

ALTER TABLE public.daily_portfolio ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.signals ENABLE ROW LEVEL SECURITY;
