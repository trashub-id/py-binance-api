import asyncio
import logging
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI
from binance.websocket.um_futures.websocket_client import UMFuturesWebsocketClient

from core.binance_client import WS_URL, get_listen_key, keepalive_listen_key
from execution.order_manager import process_webhook_payload, handle_order_update
from core.converter import WebhookPayload
from database.supabase_logger import init_supabase

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s")
logger = logging.getLogger("main")

order_queue = asyncio.Queue()
listen_key = None
ws_client = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application Lifespan (Startup & Shutdown)"""
    global listen_key, ws_client
    
    logger.info("Initializing bot components...")
    
    # Init database connection
    init_supabase()
    
    # 1. Start the queue consumer worker
    asyncio.create_task(order_worker())
    
    # 2. Boot WebSocket
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
        
        # 3. Setup listenKey periodic Keep-Alive
        asyncio.create_task(keepalive_loop())
    except Exception as e:
        logger.error(f"Failed to boot WebSocket listener: {str(e)}")
        
    yield # App is running
    
    # Graceful cleanup
    if ws_client:
        logger.info("Stopping WebSocket listener...")
        ws_client.stop()

app = FastAPI(title="Binance Futures Event-Driven Bot", lifespan=lifespan)
order_queue = asyncio.Queue()
listen_key = None
ws_client = None

async def order_worker():
    """Background task to pull incoming signals from the async queue and process."""
    logger.info("Background order worker started.")
    while True:
        payload = await order_queue.get()
        try:
            # We use to_thread so the synchronous HTTP request doesn't block the async event loop
            await asyncio.to_thread(process_webhook_payload, payload)
        except Exception as e:
            logger.error(f"Order worker error: {str(e)}")
        finally:
            order_queue.task_done()

def on_ws_message(_, message):
    """Callback for WebSocket events."""
    try:
        data = json.loads(message)
        # Handle Binance User Data Stream events
        if data.get("e") == "ORDER_TRADE_UPDATE":
            # Extract 'o' payload inside ORDER_TRADE_UPDATE
            handle_order_update(data)
            
        elif data.get("e") == "listenKeyExpired":
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
                # To be completely robust, we'd need to restart the socket instance here,
                # but depending on the state, a container restart might be preferred if connection dropped entirely.
            except Exception as fallback_e:
                logger.error(f"Fallback keep-alive check failed: {str(fallback_e)}")

@app.post("/webhook")
async def receive_webhook(payload: WebhookPayload):
    """
    HTTP POST endpoint to receive trading signals.
    """
    logger.info(f"Incoming Webhook Signal: {payload.symbol} {payload.side} {payload.quantity}")
    
    # Put signal in queue to ensure quick 200 OK response to webhook caller
    await order_queue.put(payload)
    
    return {"status": "success", "message": "Payload queued"}

if __name__ == "__main__":
    import uvicorn
    # Menjalankan FastAPI dengan port 8000
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
