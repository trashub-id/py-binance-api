import asyncio
import logging
from fastapi import APIRouter, HTTPException

from core.state import order_queue
from core.converter import WebhookPayload, CancelPayload
from execution.order_manager import process_cancel_payload

logger = logging.getLogger(__name__)

router = APIRouter()

@router.post("/webhook")
async def receive_webhook(payload: WebhookPayload):
    """
    HTTP POST endpoint to receive trading signals.
    """
    logger.info(f"Incoming Webhook Signal: {payload.symbol} {payload.side} {payload.quantity}")
    
    # Put signal in queue to ensure quick 200 OK response
    await order_queue.put(payload)
    
    return {"status": "success", "message": "Payload queued"}

@router.post("/cancel")
async def receive_cancel(payload: CancelPayload):
    """
    HTTP POST endpoint to receive cancellation signals.
    Bypasses the queue to cancel orders instantly.
    """
    logger.info(f"Incoming Cancel Signal for {payload.symbol}")
    
    try:
        # Menjalankan pemanggilan REST sinkron di thread terpisah agar tak nge-block async loop
        result = await asyncio.to_thread(process_cancel_payload, payload)
        return result
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
