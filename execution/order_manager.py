import logging
from core.binance_client import rest_client, get_symbol_filters, new_algo_order
from core.precision import round_step_size, round_tick_size
from core.converter import extract_order_params, WebhookPayload, CancelPayload
from database.supabase_logger import log_error, log_trade, update_trade

logger = logging.getLogger(__name__)

# In-memory store mapping entry orderId → TP/SL config (for regular orders via place-order)
pending_entries = {}

# In-memory store mapping symbol → TP/SL config (for algo orders via place-stop-auto)
# Algo orders return algoId, but ORDER_TRADE_UPDATE fires with a NEW orderId,
# so we match by symbol + side instead.
pending_algo_entries = {}


def _place_tp_sl(entry_id: str, config: dict):
    """
    Place TP and/or SL orders based on pending config.
    Extracted as helper to avoid duplication between orderId and symbol-based flows.
    """
    symbol = config["symbol"]

    # 1. Place TP (only if tp_price is configured)
    if config.get("tp_price"):
        tp_type = config.get("tp_type", "LIMIT")

        if tp_type == "LIMIT":
            tp_params = {
                "symbol": symbol,
                "side": config["close_side"],
                "type": "LIMIT",
                "quantity": config["quantity"],
                "price": config["tp_price"],
                "timeInForce": "GTX", # GTX ensures 100% Post Only (Maker) on Binance Futures
                "reduceOnly": "true"
            }
        else:
            # E.g. TAKE_PROFIT_MARKET → via Algo Order API
            tp_params = {
                "symbol": symbol,
                "algoType": "CONDITIONAL",
                "side": config["close_side"],
                "type": tp_type,
                "triggerPrice": config["tp_price"],
                "quantity": config["quantity"],
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
        sl_params = {
            "symbol": symbol,
            "algoType": "CONDITIONAL",
            "side": config["close_side"],
            "type": "STOP_MARKET",
            "quantity": config["quantity"],
            "triggerPrice": config["sl_price"],
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


def process_webhook_payload(payload: WebhookPayload):
    """
    Processes the incoming webhook payload:
    1. Fetches precision rules
    2. Rounds quantities and prices
    3. Sends Entry order
    4. Saves state for TP/SL execution
    """
    symbol = payload.symbol.upper()
    try:
        tick_size, step_size = get_symbol_filters(symbol)
        
        # Calculate precise quantities and prices
        qty = round_step_size(payload.quantity, step_size)
        entry_price = round_tick_size(payload.entry.price, tick_size)
        
        # Prepare entry parameters
        entry_params = {
            "symbol": symbol,
            "side": payload.side.upper(),
            "quantity": qty,
            "price": entry_price,
        }
        
        # Add converted order type params (like type, timeInForce)
        entry_params.update(extract_order_params(payload.entry.type))
        
        logger.info(f"Sending Entry Order: {entry_params}")
        
        # Send REST order
        response = rest_client.new_order(**entry_params)
        
        order_id = str(response["orderId"])
        status = response.get("status", "NEW")
        
        # Store pending TP/SL calculations in memory
        tp_price = round_tick_size(payload.tp.price, tick_size)
        sl_price = round_tick_size(payload.sl.price, tick_size)
        close_side = "SELL" if payload.side.upper() == "BUY" else "BUY"
        
        pending_entries[order_id] = {
            "symbol": symbol,
            "close_side": close_side,
            "quantity": qty,
            "tp_price": tp_price,
            "sl_price": sl_price,
            "tp_type": payload.tp.type.upper(),
            "sl_type": payload.sl.type.upper()
        }
        
        # Log to Supabase trades
        trade_data = {
            "entry_order_id": order_id,
            "symbol": symbol,
            "side": payload.side.upper(),
            "quantity": qty,
            "entry_price": entry_price,
            "order_type": payload.entry.type.upper(),
            "status": status,
            "payload": payload.model_dump()
        }
        log_trade(trade_data)
        
        return response
        
    except Exception as e:
        context = f"process_webhook_payload_{symbol}"
        log_error(context, e, payload.model_dump())
        logger.error(f"Failed to process webhook: {str(e)}")
        raise e

def process_cancel_payload(payload: CancelPayload):
    """
    Processes incoming cancel payload to explicitly cancel pending limits.
    """
    symbol = payload.symbol.upper()
    try:
        logger.info(f"Processing Cancel Request for {symbol}: {payload.model_dump()}")
        
        if payload.cancel_all:
            response = rest_client.cancel_open_orders(symbol=symbol)
            # Cleanup internal tracking state
            keys_to_delete = [k for k, v in pending_entries.items() if v["symbol"] == symbol]
            for k in keys_to_delete:
                del pending_entries[k]
            # Also cleanup algo entries
            if symbol in pending_algo_entries:
                del pending_algo_entries[symbol]
            logger.info(f"Canceled ALL open orders for {symbol}")
            return {"status": "success", "message": f"Canceled all orders for {symbol}"}
            
        elif payload.order_id:
            response = rest_client.cancel_order(symbol=symbol, orderId=int(payload.order_id))
            if payload.order_id in pending_entries:
                del pending_entries[payload.order_id]
            logger.info(f"Canceled specific order {payload.order_id} for {symbol}")
            return {"status": "success", "message": f"Canceled order {payload.order_id}"}
            
        else:
            raise ValueError("Must provide either 'cancel_all=True' or 'order_id'")
            
    except Exception as e:
        context = f"process_cancel_payload_{symbol}"
        log_error(context, e, payload.model_dump())
        logger.error(f"Failed to process cancel payload: {str(e)}")
        raise e

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
        
        logger.info(f"[ORDER_UPDATE] {symbol} orderId={order_id} side={order_side} status={status}")
        
        # Check if this order relates to a pending algo entry, map its ID in DB
        if symbol in pending_algo_entries:
            config = pending_algo_entries[symbol]
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
                config = pending_entries[order_id]
                logger.info(f"[FILL] Entry {order_id} FILLED (orderId match). Placing TP/SL for {config['symbol']}")
                _place_tp_sl(order_id, config)
                del pending_entries[order_id]
                return

            # === Strategy 2: symbol-based lookup (place-stop-auto / algo flow) ===
            if symbol in pending_algo_entries:
                config = pending_algo_entries[symbol]
                # Derive expected entry side from close_side
                entry_side = "BUY" if config["close_side"] == "SELL" else "SELL"
                
                if order_side == entry_side:
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
                        resolved_config = {
                            "symbol": symbol,
                            "close_side": config["close_side"],
                            "quantity": config["quantity"],
                            "tp_price": tp_price,
                            "sl_price": sl_price,
                            "tp_type": config.get("tp_type", "LIMIT"),
                            "sl_type": config.get("sl_type", "STOP_MARKET"),
                        }
                        _place_tp_sl(order_id, resolved_config)
                    else:
                        logger.error(f"[FILL] Algo entry FILLED for {symbol} but fill price is 0. Cannot place TP/SL.")
                    
                    del pending_algo_entries[symbol]
                    return
                else:
                    logger.debug(f"[FILL] {symbol} FILLED but side={order_side} != entry_side={entry_side}. Skipping.")

        elif status in ["CANCELED", "EXPIRED"]:
            if order_id in pending_entries:
                logger.info(f"Entry {order_id} {status}. Removing from pending_entries.")
                del pending_entries[order_id]
            
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

        logger.info(f"[STRATEGY_UPDATE] {symbol} algoId={algo_id} type={strategy_type} status={status}")

        if status in ["CANCELLED", "EXPIRED"] and symbol in pending_algo_entries:
            logger.info(f"[STRATEGY] Algo entry for {symbol} {status}. Removing from pending_algo_entries.")
            del pending_algo_entries[symbol]

    except Exception as e:
        log_error("handle_strategy_update", e, event)
        logger.error(f"Error handling strategy update: {str(e)}")
