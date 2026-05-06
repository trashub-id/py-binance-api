import asyncio
import logging
import json
import time
from binance.websocket.um_futures.websocket_client import UMFuturesWebsocketClient
from core.binance_client import WS_URL, get_listen_key, keepalive_listen_key
from execution.order_manager import handle_order_update, handle_strategy_update, pending_entries, pending_algo_entries
from database.supabase_logger import log_error

logger = logging.getLogger(__name__)

# Global instances for websocket
listen_key = None
ws_client = None

# Reconnect settings
MAX_RECONNECT_RETRIES = 10
INITIAL_BACKOFF_SECONDS = 3
KEEPALIVE_INTERVAL_SECONDS = 50 * 60  # 50 minutes (key valid 60 min)
HEALTH_CHECK_INTERVAL_SECONDS = 5 * 60  # 5 minutes (was 10, reduced for faster detection)

# Control flags
_shutting_down = False
_reconnecting = False  # Prevent concurrent reconnects
_event_loop = None  # Reference to the main event loop
_last_message_time = 0  # Tracks last WS message for health check


def on_ws_message(_, message):
    """Callback for WebSocket events."""
    global _last_message_time
    _last_message_time = time.time()
    
    try:
        data = json.loads(message)
        event_type = data.get("e")

        # Handle Binance User Data Stream events
        if event_type == "ORDER_TRADE_UPDATE":
            handle_order_update(data)

        elif event_type == "STRATEGY_ORDER_TRADE_UPDATE":
            # Algo/conditional order status changes (TRIGGERED, CANCELLED, EXPIRED)
            handle_strategy_update(data)
            
        elif event_type == "listenKeyExpired":
            logger.warning("Listen key expired from WS event. Triggering reconnect...")
            log_error("ws_listen_key_expired", Exception("listenKeyExpired event received from WebSocket"))
            _schedule_reconnect()

    except Exception as e:
        logger.error(f"WebSocket parse error: {str(e)}")
        log_error("ws_message_parse", e, {"raw_message": str(message)[:500]})

def on_ws_error(_, error):
    logger.error(f"WebSocket Error: {error}")
    log_error("ws_error", Exception(str(error)))

def on_ws_close(*args):
    # args dapat menerima 'ws' saja atau beserta 'status_code' dan 'msg'
    logger.warning(f"WebSocket Closed: {args}")
    log_error("ws_closed", Exception(f"WebSocket connection closed: {args}"))
    
    if not _shutting_down:
        logger.info("Unexpected WebSocket close. Scheduling reconnect...")
        _schedule_reconnect()


def _schedule_reconnect():
    """Schedule a reconnect from any thread (WS callbacks run in WS thread)."""
    global _event_loop
    if _event_loop and not _shutting_down:
        _event_loop.call_soon_threadsafe(
            lambda: _event_loop.create_task(_reconnect_websocket())
        )


async def _reconnect_websocket():
    """Stop old WS, create new listenKey, start new WS with exponential backoff."""
    global listen_key, ws_client, _reconnecting
    
    if _shutting_down:
        return
    
    # Prevent concurrent reconnects
    if _reconnecting:
        logger.debug("Reconnect already in progress, skipping.")
        return
    _reconnecting = True
    
    try:
        # Stop old connection safely
        if ws_client:
            try:
                ws_client.stop()
            except Exception:
                pass
            ws_client = None

        for attempt in range(MAX_RECONNECT_RETRIES):
            if _shutting_down:
                return
                
            backoff = INITIAL_BACKOFF_SECONDS * (2 ** attempt)
            logger.info(f"Reconnect attempt {attempt + 1}/{MAX_RECONNECT_RETRIES} "
                        f"(waiting {backoff}s backoff)...")
            await asyncio.sleep(backoff)
            
            try:
                # Get fresh listen key
                listen_key = await asyncio.to_thread(get_listen_key)
                logger.info(f"Obtained fresh listenKey for reconnect.")
                
                # Create new WebSocket client
                ws_client = UMFuturesWebsocketClient(
                    stream_url=WS_URL,
                    on_message=on_ws_message,
                    on_error=on_ws_error,
                    on_close=on_ws_close
                )
                ws_client.user_data(listen_key=listen_key)
                
                logger.info(f"WebSocket reconnected successfully on attempt {attempt + 1}.")
                _last_message_time = time.time()  # Reset health check timer
                if pending_entries or pending_algo_entries:
                    logger.warning(f"Reconnected with {len(pending_entries)} pending regular and {len(pending_algo_entries)} pending algo orders. Reconciliation worker will handle missed fills.")
                
                log_error("ws_reconnect_success", 
                          Exception(f"Reconnected on attempt {attempt + 1}"),
                          {"attempt": attempt + 1})
                return  # Success!
                
            except Exception as e:
                logger.error(f"Reconnect attempt {attempt + 1} failed: {str(e)}")
                log_error("ws_reconnect_failed", e, {"attempt": attempt + 1})
        
        # All retries exhausted
        error_msg = f"All {MAX_RECONNECT_RETRIES} reconnect attempts failed. WebSocket is DOWN!"
        logger.critical(error_msg)
        log_error("ws_reconnect_exhausted", Exception(error_msg))
        
    finally:
        _reconnecting = False


async def keepalive_loop():
    """Periodic task to renew the listenKey."""
    global listen_key
    while not _shutting_down:
        await asyncio.sleep(KEEPALIVE_INTERVAL_SECONDS)
        
        if _shutting_down:
            break
            
        try:
            logger.info("Renewing listenKey...")
            await asyncio.to_thread(keepalive_listen_key, listen_key)
            logger.info("ListenKey renewed successfully.")
        except Exception as e:
            logger.error(f"ListenKey renewal failed: {str(e)}")
            log_error("ws_keepalive_failed", e, {"listen_key": listen_key[:8] + "..." if listen_key else None})
            
            # Renewal failed → listenKey is dead → must reconnect WebSocket
            logger.info("ListenKey invalid. Triggering full WebSocket reconnect...")
            await _reconnect_websocket()


async def health_check_loop():
    """
    Separate health check loop that runs more frequently than keepalive.
    Detects silent WebSocket disconnects and logs pending order counts for visibility.
    """
    while not _shutting_down:
        await asyncio.sleep(HEALTH_CHECK_INTERVAL_SECONDS)
        
        if _shutting_down:
            break
        
        # Log pending entries count for visibility
        regular_count = len(pending_entries)
        algo_count = len(pending_algo_entries)
        if regular_count > 0 or algo_count > 0:
            logger.info(f"[HEALTH] Pending entries: {regular_count} regular, {algo_count} algo")
        
        # Health check: detect silent WebSocket disconnects
        if _last_message_time > 0:
            silence_duration = time.time() - _last_message_time
            if silence_duration > HEALTH_CHECK_INTERVAL_SECONDS:
                logger.warning(f"No WebSocket message received for {silence_duration:.0f}s. Triggering reconnect...")
                log_error("ws_silent_disconnect", 
                          Exception(f"No WS message for {silence_duration:.0f}s"),
                          {"last_message_age_seconds": round(silence_duration),
                           "pending_regular": regular_count,
                           "pending_algo": algo_count})
                await _reconnect_websocket()


async def boot_websocket_listener():
    """Start the websocket client and its keepalive + health check loops."""
    global listen_key, ws_client, _event_loop, _shutting_down, _last_message_time
    _shutting_down = False
    
    try:
        # Store event loop reference so WS thread callbacks can schedule reconnects
        _event_loop = asyncio.get_running_loop()
        
        listen_key = await asyncio.to_thread(get_listen_key)
        logger.info(f"Successfully obtained listenKey")
        
        ws_client = UMFuturesWebsocketClient(
            stream_url=WS_URL,
            on_message=on_ws_message,
            on_error=on_ws_error,
            on_close=on_ws_close
        )
        ws_client.user_data(listen_key=listen_key)
        _last_message_time = time.time()  # Initialize health check timer
        logger.info("User Data Stream WebSocket started.")
        
        # Setup listenKey periodic Keep-Alive (every 50 min)
        asyncio.create_task(keepalive_loop())
        # Setup separate health check (every 5 min) — faster detection of silent disconnects
        asyncio.create_task(health_check_loop())
    except Exception as e:
        logger.error(f"Failed to boot WebSocket listener: {str(e)}")
        log_error("ws_boot_failed", e)

def stop_websocket_listener():
    global ws_client, _shutting_down
    _shutting_down = True
    if ws_client:
        logger.info("Stopping WebSocket listener...")
        ws_client.stop()

