import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI

from api.router import api_router
from workers.queue_worker import order_worker
from workers.websocket_worker import boot_websocket_listener, stop_websocket_listener
from database.supabase_logger import init_supabase

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s")
logger = logging.getLogger("main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application Lifespan (Startup & Shutdown)"""
    logger.info("Initializing bot components...")
    logger.info("Swagger UI Docs : http://127.0.0.1:8000/docs")
    logger.info("ReDoc Docs      : http://127.0.0.1:8000/redoc")
    
    # 1. Init database connection
    init_supabase()
    
    # 2. Start the queue consumer worker
    asyncio.create_task(order_worker())
    
    # 3. Boot WebSocket & Keep-alive API
    await boot_websocket_listener()
        
    yield # App is running
    
    # Graceful cleanup
    stop_websocket_listener()

app = FastAPI(title="Binance Futures Event-Driven Bot", lifespan=lifespan)
app.include_router(api_router)

if __name__ == "__main__":
    import uvicorn
    # Menjalankan FastAPI dengan port 8000
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
