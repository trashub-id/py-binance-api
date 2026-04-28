-- Enable Row Level Security (RLS) for pending_orders table
-- By NOT creating any policies, we are implicitly denying all access from anon / authenticated roles.
-- The Python bot backend will bypass this completely because it uses the 'service_role' key.

ALTER TABLE public.pending_orders ENABLE ROW LEVEL SECURITY;
