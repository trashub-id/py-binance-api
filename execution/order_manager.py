import logging
from core.binance_client import rest_client, get_symbol_filters
from core.precision import round_step_size, round_tick_size
from core.converter import extract_order_params, WebhookPayload
from database.supabase_logger import log_error, log_trade, update_trade

logger = logging.getLogger(__name__)

# In-memory store mapping entry orderId -> TP/SL config
pending_entries = {}

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

def handle_order_update(event: dict):
    """
    Called when WebSocket receives ORDER_TRADE_UPDATE.
    event is the payload inside the 'o' key of the user data stream message.
    """
    try:
        order = event.get("o", {})
        if not order:
            return
            
        order_id = str(order.get("i"))
        status = order.get("X")
        
        # Update trade status in DB for visibility
        update_trade({"entry_order_id": order_id}, {"status": status})
        
        # If it's an Entry order that just FILLED
        if status == "FILLED" and order_id in pending_entries:
            config = pending_entries[order_id]
            logger.info(f"Entry {order_id} FILLED. Placing TP/SL for {config['symbol']}")
            
            # 1. Place TP
            if config["tp_type"] == "LIMIT":
                # Special handler for LIMIT type TP: reduceOnly=True + qty
                tp_params = {
                    "symbol": config["symbol"],
                    "side": config["close_side"],
                    "type": "LIMIT",
                    "quantity": config["quantity"],
                    "price": config["tp_price"],
                    "timeInForce": "GTC",
                    "reduceOnly": "true"
                }
            else:
                # E.g. TAKE_PROFIT_MARKET
                tp_params = {
                    "symbol": config["symbol"],
                    "side": config["close_side"],
                    "type": config["tp_type"],
                    "stopPrice": config["tp_price"],
                    "closePosition": "true"
                }
            
            # Send TP Request
            try:
                res_tp = rest_client.new_order(**tp_params)
                update_trade({"entry_order_id": order_id}, {"tp_order_id": str(res_tp.get("orderId"))})
                logger.info(f"TP Placed Successfully: {res_tp}")
            except Exception as e:
                log_error("place_tp_order", e, tp_params)
                logger.error(f"Failed to place TP order: {str(e)}")
            
            # 2. Place SL
            # SL STOP_MARKET requires closePosition=true and NO quantity
            sl_params = {
                "symbol": config["symbol"],
                "side": config["close_side"],
                "type": config["sl_type"],
                "stopPrice": config["sl_price"],
                "closePosition": "true"
            }
            
            # Send SL Request
            try:
                res_sl = rest_client.new_order(**sl_params)
                update_trade({"entry_order_id": order_id}, {"sl_order_id": str(res_sl.get("orderId"))})
                logger.info(f"SL Placed Successfully: {res_sl}")
            except Exception as e:
                log_error("place_sl_order", e, sl_params)
                logger.error(f"Failed to place SL order: {str(e)}")
            
            # Remove from pending calculations so we don't trigger it again
            del pending_entries[order_id]
            
    except Exception as e:
        log_error("handle_order_update", e, event)
        logger.error(f"Error handling order update: {str(e)}")
