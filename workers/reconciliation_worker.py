import asyncio
import logging
import time
from core.binance_client import rest_client, get_symbol_filters
from core.precision import round_tick_size
from execution.order_manager import _place_tp_sl, pending_entries, pending_algo_entries
from database.supabase_logger import get_all_pending_orders, update_pending_order, claim_pending_order, cleanup_stale_pending_orders, log_error

logger = logging.getLogger(__name__)

# Counter for stale cleanup (run every ~50 reconciliation cycles = ~25 minutes)
_cleanup_counter = 0
CLEANUP_EVERY_N_CYCLES = 50

async def reconciliation_loop():
    """
    Background worker that runs periodically to find PENDING orders in Supabase 
    that might have been FILLED while WebSocket was disconnected.
    """
    global _cleanup_counter
    logger.info("Reconciliation worker started.")
    # Wait a bit before first run to allow boot sequence to finish
    await asyncio.sleep(10)
    
    while True:
        try:
            # We run the synchronous checks in a thread to avoid blocking async loop
            await asyncio.to_thread(_run_reconciliation)
            
            # Periodically cleanup stale records to prevent DB bloat
            _cleanup_counter += 1
            if _cleanup_counter >= CLEANUP_EVERY_N_CYCLES:
                _cleanup_counter = 0
                await asyncio.to_thread(cleanup_stale_pending_orders)
                
        except Exception as e:
            logger.error(f"Error in reconciliation loop: {str(e)}")
            log_error("reconciliation_loop", e)
            
        # Run every 30 seconds
        await asyncio.sleep(30)


def _run_reconciliation():
    orders = get_all_pending_orders()
    if not orders:
        return
        
    for order in orders:
        try:
            symbol = order["symbol"]
            position_side = order.get("position_side", "")
            flow_type = order.get("flow_type", "regular")
            entry_order_id = order["entry_order_id"]
            
            if flow_type == "regular":
                _check_regular_order(order, symbol, entry_order_id)
            elif flow_type == "algo":
                _check_algo_order(order, symbol, position_side)
                
        except Exception as e:
            logger.error(f"Reconciliation error for order {order.get('entry_order_id')}: {str(e)}")
            log_error("reconciliation_check", e, {"order_id": order.get("entry_order_id")})

def _check_regular_order(order: dict, symbol: str, entry_order_id: str):
    # Fetch order status from Binance
    try:
        order_info = rest_client.get_order(symbol=symbol, orderId=int(entry_order_id))
    except Exception as e:
        if "Order does not exist" in str(e):
             logger.warning(f"[RECONCILIATION] Regular order {entry_order_id} does not exist on Binance. Marking CANCELLED.")
             _cleanup_order(entry_order_id, "CANCELLED", None)
             return
        raise e
        
    status = order_info.get("status")
    
    if status == "FILLED":
        # Atomically claim to prevent WebSocket handler from double-placing
        if not claim_pending_order({"entry_order_id": entry_order_id}):
            logger.info(f"[RECONCILIATION] Regular order {entry_order_id} already claimed. Skipping.")
            # Still clean up in-memory dict
            if entry_order_id in pending_entries:
                del pending_entries[entry_order_id]
            return
        
        logger.info(f"[RECONCILIATION] Found missed FILLED for regular order {entry_order_id}. Placing TP/SL.")
        config = {
            "symbol": symbol,
            "position_side": order.get("position_side"),
            "close_side": order["close_side"],
            "quantity": order["quantity"],
            "tp_price": order["tp_price"],
            "tp_type": order.get("tp_type", "LIMIT"),
            "sl_price": order.get("sl_price"),
            "sl_type": order.get("sl_type", "STOP_MARKET")
        }
        _place_tp_sl(entry_order_id, config)
        _cleanup_order(entry_order_id, "FILLED", None)
        
    elif status in ["CANCELED", "EXPIRED", "REJECTED"]:
        logger.info(f"[RECONCILIATION] Regular order {entry_order_id} is {status}. Cleaning up.")
        _cleanup_order(entry_order_id, status, None)


def _check_algo_order(order: dict, symbol: str, position_side: str):
    entry_order_id = order["entry_order_id"]
    algo_key = f"{symbol}_{position_side}"
    
    # For algo orders, we check if the position is open.
    # If position is open, the algo order must have triggered and filled.
    positions = rest_client.get_position_risk(symbol=symbol)
    pos = next((p for p in positions if p.get("positionSide", "").upper() == position_side.upper()), None)
    
    if pos and float(pos["positionAmt"]) != 0:
        # Atomically claim to prevent WebSocket handler from double-placing
        if not claim_pending_order({"entry_order_id": entry_order_id}):
            logger.info(f"[RECONCILIATION] Algo order {entry_order_id} already claimed. Skipping.")
            if algo_key in pending_algo_entries:
                del pending_algo_entries[algo_key]
            return
        
        fill_price = float(pos["entryPrice"])
        logger.info(f"[RECONCILIATION] Found open position for {symbol} {position_side}. Algo must have triggered. Placing TP/SL.")
        
        is_long = order.get("is_long", True)
        tp_pct = float(order.get("tp_percent", 0))
        sl_pct = float(order.get("sl_percent", 0))
        
        tp_price_raw = fill_price * (1 + tp_pct / 100) if is_long else fill_price * (1 - tp_pct / 100)
        sl_price_raw = fill_price * (1 - sl_pct / 100) if is_long else fill_price * (1 + sl_pct / 100)
        
        tick_size, _ = get_symbol_filters(symbol)
        tp_price = round_tick_size(tp_price_raw, tick_size)
        sl_price = round_tick_size(sl_price_raw, tick_size)
        
        # Use actual position amount to be safe, or fallback to config quantity
        qty = str(abs(float(pos["positionAmt"])))
        
        config = {
            "symbol": symbol,
            "position_side": position_side,
            "close_side": order["close_side"],
            "quantity": qty,
            "tp_price": tp_price,
            "sl_price": sl_price,
            "tp_type": order.get("tp_type", "LIMIT"),
            "sl_type": order.get("sl_type", "STOP_MARKET"),
        }
        _place_tp_sl(entry_order_id, config)
        _cleanup_order(entry_order_id, "FILLED", algo_key)
    else:
        # Check if algo order is still open. If not, and position is 0, it was cancelled/expired.
        try:
            open_algos = rest_client.sign_request("GET", "/fapi/v1/openAlgoOrders", {"symbol": symbol})
            algo_list = []
            if isinstance(open_algos, list):
                algo_list = open_algos
            elif isinstance(open_algos, dict):
                for key in ["openAlgoOrders", "algoOrderList", "orders"]:
                    if key in open_algos:
                        algo_list = open_algos[key]
                        break
                        
            is_open = any(str(a.get("algoId")) == str(entry_order_id) for a in algo_list)
            if not is_open:
                logger.info(f"[RECONCILIATION] Algo order {entry_order_id} is no longer open and position is 0. Marking CANCELLED.")
                _cleanup_order(entry_order_id, "CANCELLED", algo_key)
                
        except Exception as e:
            logger.debug(f"[RECONCILIATION] Could not fetch openAlgoOrders for {symbol}: {str(e)}")


def _cleanup_order(entry_order_id: str, status: str, algo_key: str):
    update_pending_order({"entry_order_id": entry_order_id}, {"status": status})
    
    if entry_order_id in pending_entries:
        del pending_entries[entry_order_id]
        
    if algo_key and algo_key in pending_algo_entries:
        del pending_algo_entries[algo_key]
