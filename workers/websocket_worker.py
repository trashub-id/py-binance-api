import asyncio
import logging
import json
from binance.websocket.um_futures.websocket_client import UMFuturesWebsocketClient
from core.binance_client import WS_URL, get_listen_key, keepalive_listen_key
from execution.order_manager import handle_order_update, handle_strategy_update

logger = logging.getLogger(__name__)

# Global instances for websocket
listen_key = None
ws_client = None

def on_ws_message(_, message):
    """Callback for WebSocket events."""
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
            logger.warning("Listen key expired from WS event. System may need restart/reconnect.")
    except Exception as e:
        logger.error(f"WebSocket parse error: {str(e)}")

def on_ws_error(_, error):
    logger.error(f"WebSocket Error: {error}")

def on_ws_close(*args):
    # args dapat menerima 'ws' saja atau beserta 'status_code' dan 'msg'
    logger.warning(f"WebSocket Closed: {args}")

async def keepalive_loop():
    """Periodic task to ping the Binance API and renew the listenKey."""
    global listen_key
    while True:
        # Renew listen key every 50 minutes (validity is 60 minutes)
        await asyncio.sleep(50 * 60)
        try:
            logger.info("Renewing listenKey...")
            await asyncio.to_thread(keepalive_listen_key, listen_key)
        except Exception as e:
            logger.error(f"Keep-Alive failed: {str(e)}")
            try:
                # If expired/invalid, grab a new one
                listen_key = await asyncio.to_thread(get_listen_key)
                logger.info("Provisioned new listenKey.")
            except Exception as fallback_e:
                logger.error(f"Fallback keep-alive check failed: {str(fallback_e)}")

async def boot_websocket_listener():
    """Start the websocket client and its keepalive loop."""
    global listen_key, ws_client
    try:
        listen_key = await asyncio.to_thread(get_listen_key)
        logger.info(f"Successfully obtained listenKey")
        
        ws_client = UMFuturesWebsocketClient(
            stream_url=WS_URL,
            on_message=on_ws_message,
            on_error=on_ws_error,
            on_close=on_ws_close
        )
        ws_client.user_data(listen_key=listen_key)
        logger.info("User Data Stream WebSocket started.")
        
        # Setup listenKey periodic Keep-Alive
        asyncio.create_task(keepalive_loop())
    except Exception as e:
        logger.error(f"Failed to boot WebSocket listener: {str(e)}")

def stop_websocket_listener():
    global ws_client
    if ws_client:
        logger.info("Stopping WebSocket listener...")
        ws_client.stop()
