import asyncio
import logging
from core.state import order_queue
from execution.order_manager import process_webhook_payload

logger = logging.getLogger(__name__)

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
