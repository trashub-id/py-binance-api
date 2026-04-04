import logging
import traceback
import json
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
        except Exception as e:
            logger.error(f"Failed to connect Supabase: {str(e)}")
    else:
        logger.warning("Supabase URL or Key is missing. Database logging disabled.")

def log_error(context: str, error: Exception, payload: dict = None):
    """
    Logs an error and its traceback to the bot_logs table.
    """
    try:
        if not supabase:
            logger.error(f"[{context}] {str(error)} | Traceback: {traceback.format_exc()}")
            return
            
        error_trace = traceback.format_exc()
        
        data = {
            "context": context,
            "message": str(error),
            "error_trace": error_trace,
            "payload": payload if payload else {}
        }
        
        supabase.table("bot_logs").insert(data).execute()
        
    except Exception as e:
        logger.error(f"Failed to log error to Supabase: {str(e)}")

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
