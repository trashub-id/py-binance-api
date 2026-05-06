import logging
from core.binance_client import rest_client, get_symbol_filters, new_algo_order
from core.precision import round_tick_size
from database.supabase_logger import log_error, update_trade, get_all_pending_orders, update_pending_order, claim_pending_order

logger = logging.getLogger(__name__)

# In-memory store mapping entry orderId → TP/SL config (for regular orders via place-order)
pending_entries = {}

# In-memory store mapping symbol → TP/SL config (for algo orders via place-stop-auto)
# Algo orders return algoId, but ORDER_TRADE_UPDATE fires with a NEW orderId,
# so we match by symbol + side instead.
pending_algo_entries = {}

def load_pending_orders_on_boot():
    """Load pending orders from Supabase into memory."""
    try:
        orders = get_all_pending_orders()
        for order in orders:
            flow_type = order.get("flow_type", "regular")
            if flow_type == "regular":
                pending_entries[order["entry_order_id"]] = {
                    "symbol": order["symbol"],
                    "position_side": order["position_side"],
                    "close_side": order["close_side"],
                    "quantity": order["quantity"],
                    "tp_price": order["tp_price"],
                    "tp_type": order.get("tp_type", "LIMIT"),
                }
            elif flow_type == "algo":
                algo_key = f"{order['symbol']}_{order['position_side']}"
                pending_algo_entries[algo_key] = {
                    "algo_id": order["entry_order_id"],
                    "symbol": order["symbol"],
                    "position_side": order["position_side"],
                    "close_side": order["close_side"],
                    "quantity": order["quantity"],
                    "tp_percent": order["tp_percent"],
                    "sl_percent": order["sl_percent"],
                    "is_long": order["is_long"],
                    "tp_type": order.get("tp_type", "LIMIT"),
                    "sl_type": order.get("sl_type", "STOP_MARKET"),
                }
        logger.info(f"Loaded {len(orders)} pending orders from DB.")
    except Exception as e:
        logger.error(f"Failed to load pending orders on boot: {str(e)}")

def _place_tp_sl(entry_id: str, config: dict):
    """
    Place TP and/or SL orders based on pending config.
    Extracted as helper to avoid duplication between orderId and symbol-based flows.
    """
    symbol = config["symbol"]
    # Defensive: ensure quantity/prices are strings for Binance API
    quantity_str = str(config["quantity"])

    # 1. Place TP (only if tp_price is configured)
    if config.get("tp_price"):
        tp_type = config.get("tp_type", "LIMIT")
        tp_price_str = str(config["tp_price"])

        if tp_type == "LIMIT":
            tp_params = {
                "symbol": symbol,
                "side": config["close_side"],
                "positionSide": config.get("position_side"),
                "type": "LIMIT",
                "quantity": quantity_str,
                "price": tp_price_str,
                "timeInForce": "GTX" # GTX ensures 100% Post Only (Maker) on Binance Futures
            }
        else:
            # E.g. TAKE_PROFIT_MARKET → via Algo Order API
            tp_params = {
                "symbol": symbol,
                "algoType": "CONDITIONAL",
                "side": config["close_side"],
                "positionSide": config.get("position_side"),
                "type": tp_type,
                "triggerPrice": tp_price_str,
                "quantity": quantity_str,
                "priceProtect": "TRUE"
            }

        try:
            if tp_type == "LIMIT":
                res_tp = rest_client.new_order(**tp_params)
            else:
                res_tp = new_algo_order(**tp_params)
            tp_id = str(res_tp.get("orderId", res_tp.get("algoId", "")))
            update_trade({"entry_order_id": entry_id}, {"tp_order_id": tp_id})
            logger.info(f"TP Placed Successfully: {res_tp}")
        except Exception as e:
            log_error("place_tp_order", e, tp_params)
            logger.error(f"Failed to place TP order: {str(e)}")

    # 2. Place SL (only if sl_price is configured)
    if config.get("sl_price"):
        sl_price_str = str(config["sl_price"])
        sl_params = {
            "symbol": symbol,
            "algoType": "CONDITIONAL",
            "side": config["close_side"],
            "positionSide": config.get("position_side"),
            "type": "STOP_MARKET",
            "quantity": quantity_str,
            "triggerPrice": sl_price_str,
            "priceProtect": "TRUE"
        }

        try:
            res_sl = new_algo_order(**sl_params)
            sl_id = str(res_sl.get("algoId", res_sl.get("orderId", "")))
            update_trade({"entry_order_id": entry_id}, {"sl_order_id": sl_id})
            logger.info(f"SL Placed Successfully: {res_sl}")
        except Exception as e:
            log_error("place_sl_order", e, sl_params)
            logger.error(f"Failed to place SL order: {str(e)}")



def handle_order_update(event: dict):
    """
    Called when WebSocket receives ORDER_TRADE_UPDATE.
    event is the full user data stream message.
    
    Supports two lookup strategies:
    1. By orderId → for regular orders (place-order flow)
    2. By symbol + side → for algo orders (place-stop-auto flow)
    """
    try:
        order = event.get("o", {})
        if not order:
            return
            
        order_id = str(order.get("i"))
        status = order.get("X")
        symbol = order.get("s")
        order_side = order.get("S")  # BUY or SELL
        position_side = order.get("ps", "")
        algo_key = f"{symbol}_{position_side}"
        
        logger.info(f"[ORDER_UPDATE] {symbol} orderId={order_id} side={order_side} ps={position_side} status={status}")
        
        # Check if this order relates to a pending algo entry, map its ID in DB
        if algo_key in pending_algo_entries:
            config = pending_algo_entries[algo_key]
            entry_side = "BUY" if config["close_side"] == "SELL" else "SELL"
            if order_side == entry_side:
                algo_id = config.get("algo_id")
                if algo_id:
                    logger.info(f"[MAPPING] Mapping algoId {algo_id} to real orderId {order_id} for {symbol}")
                    # Replace algo_id with true order_id so subsequent updates work properly
                    update_trade({"entry_order_id": algo_id}, {"entry_order_id": order_id})
                    # Nullify to prevent redundant mapping on next updates (e.g. PARTIALLY_FILLED -> FILLED)
                    config["algo_id"] = None

        # Update trade status in DB for visibility
        update_trade({"entry_order_id": order_id}, {"status": status})
        
        if status == "FILLED":
            # === Strategy 1: orderId-based lookup (place-order flow) ===
            if order_id in pending_entries:
                # Soft-guard: attempt to claim but ALWAYS proceed with TP/SL placement.
                # claim_pending_order returns False both when "already claimed" AND "no DB record".
                # We cannot distinguish the two, so we always place TP/SL from in-memory state.
                claimed = claim_pending_order({"entry_order_id": order_id})
                if not claimed:
                    logger.warning(f"[FILL] Could not claim {order_id} in DB (record may not exist or already claimed). Proceeding with TP/SL anyway.")
                
                config = pending_entries[order_id]
                logger.info(f"[FILL] Entry {order_id} FILLED (orderId match). Placing TP/SL for {config['symbol']}")
                _place_tp_sl(order_id, config)
                del pending_entries[order_id]
                update_pending_order({"entry_order_id": order_id}, {"status": "FILLED"})
                return

            # === Strategy 2: symbol-based lookup (place-stop-auto / algo flow) ===
            if algo_key in pending_algo_entries:
                config = pending_algo_entries[algo_key]
                # Derive expected entry side from close_side
                entry_side = "BUY" if config["close_side"] == "SELL" else "SELL"
                
                if order_side == entry_side:
                    # Soft-guard: attempt to claim but ALWAYS proceed with TP/SL placement.
                    # claim returns False both when "already claimed" AND "no DB record".
                    claimed = claim_pending_order({"entry_order_id": order_id})
                    if not claimed:
                        original_algo_id = config.get("algo_id")
                        if original_algo_id:
                            claimed = claim_pending_order({"entry_order_id": original_algo_id})
                        if not claimed:
                            logger.warning(f"[FILL] Could not claim algo entry for {symbol} in DB (record may not exist or already claimed). Proceeding with TP/SL anyway.")
                    
                    # Hitung TP/SL dari ACTUAL FILL PRICE, bukan entry signal
                    # Field 'ap' = average price (fill price) dari Binance ORDER_TRADE_UPDATE
                    fill_price = float(order.get("ap", 0))
                    if fill_price <= 0:
                        # Fallback: pakai last filled price jika ap tidak tersedia
                        fill_price = float(order.get("L", 0))
                    
                    if fill_price > 0:
                        is_long = config.get("is_long", True)
                        tp_pct = config.get("tp_percent", 0)
                        sl_pct = config.get("sl_percent", 0)
                        
                        tp_price_raw = fill_price * (1 + tp_pct / 100) if is_long else fill_price * (1 - tp_pct / 100)
                        sl_price_raw = fill_price * (1 - sl_pct / 100) if is_long else fill_price * (1 + sl_pct / 100)
                        
                        tick_size, _ = get_symbol_filters(symbol)
                        tp_price = round_tick_size(tp_price_raw, tick_size)
                        sl_price = round_tick_size(sl_price_raw, tick_size)
                        
                        logger.info(f"[FILL] Algo entry FILLED for {symbol} (orderId={order_id}, fillPrice={fill_price}). TP={tp_price}, SL={sl_price}")
                        
                        # Build resolved config with actual prices for _place_tp_sl
                        # Prices MUST be strings for Binance API
                        resolved_config = {
                            "symbol": symbol,
                            "position_side": config.get("position_side"),
                            "close_side": config["close_side"],
                            "quantity": config["quantity"],
                            "tp_price": str(tp_price),
                            "sl_price": str(sl_price),
                            "tp_type": config.get("tp_type", "LIMIT"),
                            "sl_type": config.get("sl_type", "STOP_MARKET"),
                        }
                        _place_tp_sl(order_id, resolved_config)
                    else:
                        logger.error(f"[FILL] Algo entry FILLED for {symbol} but fill price is 0. Cannot place TP/SL.")
                    
                    del pending_algo_entries[algo_key]
                    # Use entry_order_id instead of composite key to avoid ambiguous matching
                    update_pending_order({"entry_order_id": order_id}, {"status": "FILLED"})
                    return
                else:
                    logger.debug(f"[FILL] {symbol} FILLED but side={order_side} != entry_side={entry_side}. Skipping.")

        elif status in ["CANCELED", "EXPIRED"]:
            if order_id in pending_entries:
                logger.info(f"Entry {order_id} {status}. Removing from pending_entries.")
                del pending_entries[order_id]
                update_pending_order({"entry_order_id": order_id}, {"status": status})
            
    except Exception as e:
        log_error("handle_order_update", e, event)
        logger.error(f"Error handling order update: {str(e)}")


def handle_strategy_update(event: dict):
    """
    Called when WebSocket receives STRATEGY_ORDER_TRADE_UPDATE.
    This fires for algo/conditional order status changes (NEW, TRIGGERED, CANCELLED, EXPIRED).
    Used to clean up pending_algo_entries when algo orders are cancelled/expired before triggering.
    """
    try:
        strategy = event.get("so", {})
        if not strategy:
            return

        symbol = strategy.get("s", "")
        status = strategy.get("ss", "")
        algo_id = strategy.get("si", "")
        strategy_type = strategy.get("st", "")
        position_side = strategy.get("ps", "")
        algo_key = f"{symbol}_{position_side}"

        logger.info(f"[STRATEGY_UPDATE] {symbol} algoId={algo_id} type={strategy_type} ps={position_side} status={status}")

        if status in ["CANCELLED", "EXPIRED"] and algo_key in pending_algo_entries:
            config = pending_algo_entries[algo_key]
            logger.info(f"[STRATEGY] Algo entry for {symbol} ({position_side}) {status}. Removing from pending_algo_entries.")
            del pending_algo_entries[algo_key]
            # Use entry_order_id (algoId) for precise matching instead of composite key
            update_pending_order({"entry_order_id": str(algo_id)}, {"status": status})

    except Exception as e:
        log_error("handle_strategy_update", e, event)
        logger.error(f"Error handling strategy update: {str(e)}")
