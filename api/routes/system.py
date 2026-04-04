from fastapi import APIRouter
from fastapi.responses import JSONResponse, PlainTextResponse

router = APIRouter()

@router.get("/", include_in_schema=False)
async def root():
    """Health check endpoint so the browser displays bot status securely."""
    return JSONResponse(content={"status": "online", "message": "Binance Futures bot is active."})

@router.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Suppress browsers from spamming 404 errors when looking for a favicon."""
    return PlainTextResponse("")
