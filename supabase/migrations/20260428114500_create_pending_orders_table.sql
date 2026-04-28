-- Create pending_orders table for persistent TP/SL state
CREATE TABLE pending_orders (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  entry_order_id TEXT NOT NULL,
  symbol TEXT NOT NULL,
  position_side TEXT,
  close_side TEXT NOT NULL,
  quantity TEXT NOT NULL,
  tp_price TEXT,
  sl_price TEXT,
  tp_type TEXT DEFAULT 'LIMIT',
  sl_type TEXT DEFAULT 'STOP_MARKET',
  -- Fields for algo flow (place-stop-auto)
  algo_id TEXT,
  tp_percent FLOAT,
  sl_percent FLOAT,
  is_long BOOLEAN,
  -- Tracking
  flow_type TEXT NOT NULL DEFAULT 'regular',  -- 'regular' or 'algo'
  status TEXT NOT NULL DEFAULT 'PENDING',      -- PENDING, FILLED, CANCELLED, EXPIRED
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_pending_entry_order_id ON pending_orders(entry_order_id);
CREATE INDEX idx_pending_symbol_ps ON pending_orders(symbol, position_side);
CREATE INDEX idx_pending_status ON pending_orders(status);
