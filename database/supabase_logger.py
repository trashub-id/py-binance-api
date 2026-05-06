import logging
import traceback
import json
from datetime import datetime, timezone, timedelta
from supabase import create_client, Client
from config.settings import SUPABASE_URL, SUPABASE_KEY

logger = logging.getLogger(__name__)

supabase: Client = None

def init_supabase():
    """Initializes the Supabase client."""
    global supabase
    if SUPABASE_URL and SUPABASE_KEY:
        try:
            supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
            logger.info("Supabase connected.")
            
            # Diagnostic: verify DB operations actually work
            _run_boot_diagnostic()
        except Exception as e:
            logger.error(f"Failed to connect Supabase: {str(e)}")
    else:
        logger.warning("Supabase URL or Key is missing. Database logging disabled.")


def _run_boot_diagnostic():
    """Test insert+delete to bot_logs to verify Supabase connection is fully functional."""
    try:
        test_data = {
            "context": "boot_diagnostic",
            "message": "Supabase connection test — this record will be deleted immediately.",
            "error_trace": "",
            "payload": {}
        }
        res = supabase.table("bot_logs").insert(test_data).execute()
        if res.data:
            record_id = res.data[0].get("id")
            if record_id:
                supabase.table("bot_logs").delete().eq("id", record_id).execute()
            logger.info("✅ Supabase boot diagnostic PASSED: insert+delete to bot_logs successful.")
        else:
            logger.error("❌ Supabase boot diagnostic FAILED: insert returned no data. "
                         "Check if RLS policies are blocking service_role access.")
    except Exception as e:
        logger.error(f"❌ Supabase boot diagnostic FAILED: {str(e)}. "
                     f"DB operations may silently fail at runtime!")


def log_error(context: str, error: Exception, payload: dict = None):
    """
    Logs an error and its traceback to the bot_logs table.
    Falls back to file logging if Supabase insert fails.
    """
    error_trace = traceback.format_exc()
    error_msg = str(error)
    
    try:
        if not supabase:
            logger.error(f"[{context}] {error_msg} | Traceback: {error_trace}")
            _fallback_log(context, error_msg, error_trace, payload)
            return
            
        data = {
            "context": context,
            "message": error_msg,
            "error_trace": error_trace,
            "payload": payload if payload else {}
        }
        
        supabase.table("bot_logs").insert(data).execute()
        
    except Exception as e:
        # Supabase insert failed — fall back to file + stdout
        logger.error(f"Failed to log error to Supabase: {str(e)} | Original error: [{context}] {error_msg}")
        _fallback_log(context, error_msg, error_trace, payload)


def _fallback_log(context: str, message: str, trace: str, payload: dict = None):
    """Write error to a local file as fallback when Supabase is unavailable."""
    try:
        timestamp = datetime.now(timezone.utc).isoformat()
        entry = {
            "timestamp": timestamp,
            "context": context,
            "message": message,
            "error_trace": trace,
            "payload": payload
        }
        with open("bot_errors_fallback.log", "a") as f:
            f.write(json.dumps(entry, default=str) + "\n")
    except Exception:
        # Last resort — at least stdout has it via logger.error above
        pass


def log_trade(trade_data: dict):
    """
    Inserts a row into the trades table.
    """
    try:
        if not supabase:
            logger.info(f"Mock log trade: {trade_data}")
            return
            
        supabase.table("trades").insert(trade_data).execute()
        
    except Exception as e:
        logger.error(f"Failed to log trade to Supabase: {str(e)}")
        log_error("log_trade_failed", e, trade_data)

def update_trade(match_criteria: dict, update_data: dict):
    """
    Updates a row in the trades table.
    """
    try:
        if not supabase:
            logger.info(f"Mock update trade: {update_data} WHERE {match_criteria}")
            return
            
        builder = supabase.table("trades").update(update_data)
        for key, value in match_criteria.items():
            builder = builder.eq(key, value)
            
        builder.execute()
        
    except Exception as e:
        logger.error(f"Failed to update trade in Supabase: {str(e)}")

def get_last_wallet_entry() -> dict:
    """
    Fetches the latest wallet balance from daily_portfolio.
    """
    try:
        if not supabase:
            logger.warning("Supabase not init, mock wallet data.")
            return {"wallet_balance": 1000, "wallet_balance_percent": 100}

        res = supabase.table("daily_portfolio").select("*").order("date", desc=True).limit(1).execute()
        if res.data:
            return res.data[0]
        return None
    except Exception as e:
        logger.error(f"Failed to fetch last wallet entry: {str(e)}")
        return None

def update_signal(data: dict):
    """
    Upserts signal data to signals table.
    """
    try:
        if not supabase:
            return
        # Assume data has a unique key like 'symbol' to upsert correctly or supabase handles it based on PK
        supabase.table("signals").upsert(data).execute()
    except Exception as e:
        logger.error(f"Failed to upsert signal: {str(e)}")

def remove_signal(symbol: str):
    """
    Removes a signal from the signals table.
    """
    try:
        if not supabase:
            return
        supabase.table("signals").delete().eq("symbol", symbol).execute()
    except Exception as e:
        logger.error(f"Failed to remove signal for {symbol}: {str(e)}")

def save_pending_order(data: dict) -> bool:
    """
    Inserts a pending order into the pending_orders table.
    Returns True if successful, False otherwise.
    """
    try:
        if not supabase:
            logger.warning("Supabase not initialized. Pending order NOT saved to DB.")
            return False
        res = supabase.table("pending_orders").insert(data).execute()
        if res.data:
            logger.info(f"✅ Pending order saved to DB: {data.get('symbol')} {data.get('flow_type')} (entry_order_id={data.get('entry_order_id')})")
            return True
        else:
            logger.error(f"❌ Pending order insert returned empty data (possible RLS block): {data}")
            log_error("save_pending_order_empty", Exception("Insert returned no data — possible RLS block"), data)
            return False
    except Exception as e:
        logger.error(f"❌ Failed to save pending order: {str(e)}")
        log_error("save_pending_order_failed", e, data)
        return False

def update_pending_order(match_criteria: dict, update_data: dict):
    """
    Updates a pending order in the pending_orders table.
    """
    try:
        if not supabase:
            return
        update_data["updated_at"] = datetime.now(timezone.utc).isoformat()
        builder = supabase.table("pending_orders").update(update_data)
        for key, value in match_criteria.items():
            builder = builder.eq(key, value)
        builder.execute()
    except Exception as e:
        logger.error(f"Failed to update pending order: {str(e)}")
        log_error("update_pending_order_failed", e, {"match": match_criteria, "update": update_data})

def claim_pending_order(match_criteria: dict) -> bool:
    """
    Atomically claims a pending order by setting status to 'PROCESSING'.
    Only succeeds if the current status is 'PENDING'.
    Returns True if the claim was successful (row was updated), False otherwise.
    This prevents race conditions between WebSocket handler and reconciliation worker.
    """
    try:
        if not supabase:
            return False
        builder = supabase.table("pending_orders").update(
            {"status": "PROCESSING", "updated_at": datetime.now(timezone.utc).isoformat()}
        )
        for key, value in match_criteria.items():
            builder = builder.eq(key, value)
        # Only claim if still PENDING — atomic guard against double processing
        builder = builder.eq("status", "PENDING")
        res = builder.execute()
        # If no rows were updated, another process already claimed it
        return bool(res.data)
    except Exception as e:
        logger.error(f"Failed to claim pending order: {str(e)}")
        return False

def delete_pending_algo_order(symbol: str, position_side: str):
    """
    Deletes a pending algo order.
    """
    try:
        if not supabase:
            return
        supabase.table("pending_orders").delete().eq("symbol", symbol).eq("position_side", position_side).eq("flow_type", "algo").execute()
    except Exception as e:
        logger.error(f"Failed to delete pending algo order {symbol} {position_side}: {str(e)}")

def get_all_pending_orders() -> list:
    """
    Fetches all pending orders with status 'PENDING'.
    """
    try:
        if not supabase:
            return []
        res = supabase.table("pending_orders").select("*").eq("status", "PENDING").execute()
        return res.data if res.data else []
    except Exception as e:
        logger.error(f"Failed to fetch pending orders: {str(e)}")
        log_error("get_pending_orders_failed", e)
        return []

def cleanup_stale_pending_orders():
    """
    Deletes pending_orders records that are no longer PENDING and older than 24 hours.
    Prevents DB bloat from accumulating completed/cancelled records.
    """
    try:
        if not supabase:
            return 0
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        res = supabase.table("pending_orders").delete() \
            .neq("status", "PENDING") \
            .lt("updated_at", cutoff) \
            .execute()
        count = len(res.data) if res.data else 0
        if count > 0:
            logger.info(f"Cleaned up {count} stale pending_orders records.")
        return count
    except Exception as e:
        logger.error(f"Failed to cleanup stale pending orders: {str(e)}")
        return 0
