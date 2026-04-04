-- Create table for single wallet tracking
CREATE TABLE public.daily_portfolio (
    date text NOT NULL PRIMARY KEY,
    wallet_balance numeric,
    wallet_balance_percent numeric,
    wallet_balance_usd_pair numeric,
    wallet_balance_usd numeric,
    wallet_balance_bnb numeric,
    unrealized_pnl numeric,
    created_at timestamp with time zone DEFAULT now()
);

-- Create table for tracking order signals
CREATE TABLE public.signals (
    symbol text NOT NULL PRIMARY KEY,
    "positionSide" text,
    entry text,
    tp text,
    sl text,
    tp_percent text,
    sl_percent text,
    tp_cancel_percent text,
    created_at timestamp with time zone DEFAULT now()
);

-- Ensure service_role can interact freely
ALTER TABLE public.daily_portfolio DISABLE ROW LEVEL SECURITY;
ALTER TABLE public.signals DISABLE ROW LEVEL SECURITY;
