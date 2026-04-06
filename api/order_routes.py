import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional

from config.settings import WEBHOOK_SECRET
from core.binance_client import rest_client, get_symbol_filters, new_algo_order
from core.precision import round_tick_size
from execution.order_helpers import get_quantity_and_leverage, clean_symbol
from database.supabase_logger import get_last_wallet_entry, update_signal, remove_signal, log_trade
from execution.order_manager import pending_entries, pending_algo_entries

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/order", tags=["order"])

class PlaceOrderRequest(BaseModel):
    password: str = Field(..., alias="pass")
    type: str
    coin: str
    positionSide: Optional[str] = None
    type_entry: Optional[str] = None
    type_tp: Optional[str] = None
    type_sl: Optional[str] = None
    entry: Optional[str] = None
    tp: Optional[str] = None
    sl: Optional[str] = None
    percent_balance: Optional[str] = None
    percent_risk: Optional[str] = None
    tp_cancel_percent: Optional[str] = None

class StopAutoRequest(BaseModel):
    password: str = Field(..., alias="pass")
    type: str
    coin: str
    positionSide: Optional[str] = None
    entry: Optional[str] = None
    tp_percent: Optional[str] = None
    sl_percent: Optional[str] = None
    percent_balance: Optional[str] = None
    percent_risk: Optional[str] = None

@router.post("/place-order")
async def place_order(payload: PlaceOrderRequest):
    if payload.password != WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Upssss...")

    symbol = str(payload.coin).upper()

    if payload.type == "trigger_cancel":
        if not payload.positionSide:
            raise HTTPException(status_code=400, detail="positionSide is required for cancel")
        try:
            clean_symbol(symbol, payload.positionSide)
            logger.info(f"[TP CANCEL ✅] {symbol} {payload.positionSide} orders & positions cleaned")
            remove_signal(symbol)
            return {"status": "success", "message": "Canceled"}
        except Exception as e:
            logger.error(f"Error triggering cancel: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    if payload.type != "trigger_order":
        return {"message": "Not Trigger Order!"}

    if not all([payload.entry, payload.tp, payload.sl, payload.positionSide, payload.percent_balance, payload.percent_risk, payload.tp_cancel_percent]):
        return {"message": "JSON TIDAK LENGKAP!"}

    wallet = get_last_wallet_entry()
    if not wallet or "wallet_balance" not in wallet or "wallet_balance_percent" not in wallet:
        return {"message": "Wallet data not available!"}

    wallet_balance = float(wallet["wallet_balance"])
    wallet_balance_percent = float(wallet["wallet_balance_percent"])
    try:
        balance = str(round((wallet_balance * wallet_balance_percent) / 100, 2))
    except Exception:
        balance = "0"
        
    # Tentukan side berdasarkan positionSide dari payload
    side = "BUY" if payload.positionSide == "LONG" else "SELL"
    close_side = "SELL" if payload.positionSide == "LONG" else "BUY"

    try:
        # 1. CLEAN: Cancel specific side orders, algo orders, and positions
        clean_symbol(symbol, payload.positionSide)

        ql = get_quantity_and_leverage(
            entry_price=payload.entry,
            sl_price=payload.sl,
            percent_risk=payload.percent_risk,
            percent_balance=payload.percent_balance,
            balance=balance,
            symbol=symbol
        )

        rest_client.change_leverage(symbol=symbol, leverage=ql["leverage"])

        update_signal({
            "symbol": symbol,
            "entry": payload.entry,
            "tp": payload.tp,
            "tp_cancel_percent": payload.tp_cancel_percent
        })

        # Entry Order (Hedge Mode: dengan positionSide)
        entry_params = {
            "symbol": symbol,
            "side": side,
            "positionSide": payload.positionSide,
            "quantity": ql["quantity"],
            "type": payload.type_entry or "MARKET"
        }
        if payload.type_entry == "LIMIT":
            entry_params["price"] = payload.entry
            entry_params["timeInForce"] = "GTC"
            
        entry_order = rest_client.new_order(**entry_params)
        entry_order_id = str(entry_order.get("orderId"))

        trade_data = {
            "entry_order_id": entry_order_id,
            "symbol": symbol,
            "side": side,
            "quantity": ql["quantity"],
            "entry_price": float(payload.entry) if payload.entry else 0,
            "order_type": payload.type_entry or "MARKET",
            "status": entry_order.get("status", "NEW"),
            "payload": payload.model_dump()
        }
        log_trade(trade_data)

        # Simpan TP di pending_entries → WebSocket akan pasang saat entry FILLED
        # (reduceOnly LIMIT tidak bisa dipasang sebelum ada posisi)
        tick_size, _ = get_symbol_filters(symbol)
        tp_price_rounded = round_tick_size(float(payload.tp), tick_size)

        pending_entries[entry_order_id] = {
            "symbol": symbol,
            "position_side": payload.positionSide,
            "close_side": close_side,
            "quantity": ql["quantity"],
            "tp_price": tp_price_rounded,
            "tp_type": "LIMIT",
            # sl_price tidak diisi karena SL sudah dipasang langsung di bawah
        }

        # Stop Loss Order via Algo Order API (langsung, tidak perlu tunggu FILL)
        sl_params = {
            "symbol": symbol,
            "algoType": "CONDITIONAL",
            "side": close_side,
            "positionSide": payload.positionSide,
            "type": "STOP_MARKET",
            "quantity": ql["quantity"],
            "triggerPrice": payload.sl,
            "priceProtect": "TRUE"
        }
        
        sl_order = new_algo_order(**sl_params)

        return {
            "message": "Success Trigger Order! TP akan dipasang via WebSocket saat entry FILLED.",
            "entryOrder": entry_order,
            "slOrder": sl_order
        }

    except Exception as e:
        logger.error(f"Place order error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/place-stop-auto")
async def place_stop_auto(payload: StopAutoRequest):
    if payload.password != WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Upssss...")

    symbol = str(payload.coin).upper()

    if payload.type == "trigger_cancel":
        if not payload.positionSide:
            raise HTTPException(status_code=400, detail="positionSide is required for cancel")
        try:
            clean_symbol(symbol, payload.positionSide)
            logger.info(f"[STOP-AUTO CANCEL ✅] {symbol} {payload.positionSide} orders & positions cleaned")
            remove_signal(symbol)
            return {"status": "success", "message": "Canceled"}
        except Exception as e:
            logger.error(f"Error triggering cancel: {str(e)}")
            raise HTTPException(status_code=500, detail=str(e))

    if payload.type != "trigger_order":
        return {"message": "Not Trigger Order!"}

    if not all([payload.entry, payload.tp_percent, payload.sl_percent, payload.positionSide, payload.percent_balance, payload.percent_risk]):
        return {"message": "JSON TIDAK LENGKAP!"}

    try:
        entry_num = float(payload.entry)
        tp_percent_num = float(payload.tp_percent)
        sl_percent_num = float(payload.sl_percent)
    except ValueError:
        return {"message": "ENTRY / TP_PERCENT / SL_PERCENT TIDAK VALID!"}

    is_long = payload.positionSide == "LONG"
    sl_price_num = entry_num * (1 - sl_percent_num / 100) if is_long else entry_num * (1 + sl_percent_num / 100)
    sl_price_str = str(sl_price_num)

    # Tentukan side berdasarkan positionSide dari payload
    side = "BUY" if payload.positionSide == "LONG" else "SELL"
    close_side = "SELL" if payload.positionSide == "LONG" else "BUY"

    wallet = get_last_wallet_entry()
    if not wallet or "wallet_balance" not in wallet or "wallet_balance_percent" not in wallet:
        return {"message": "Wallet data not available!"}

    wallet_balance = float(wallet["wallet_balance"])
    wallet_balance_percent = float(wallet["wallet_balance_percent"])
    try:
        balance = str(round((wallet_balance * wallet_balance_percent) / 100, 2))
    except Exception:
        balance = "0"

    try:
        # 1. CLEAN: Cancel specific side orders, algo orders, and positions
        clean_symbol(symbol, payload.positionSide)

        ql = get_quantity_and_leverage(
            entry_price=payload.entry,
            sl_price=sl_price_str,
            percent_risk=payload.percent_risk,
            percent_balance=payload.percent_balance,
            balance=balance,
            symbol=symbol
        )

        rest_client.change_leverage(symbol=symbol, leverage=ql["leverage"])

        # Entry Order via Algo Order API (STOP_MARKET harus melalui algo endpoint)
        entry_params = {
            "symbol": symbol,
            "algoType": "CONDITIONAL",
            "side": side,
            "positionSide": payload.positionSide,
            "type": "STOP_MARKET",
            "triggerPrice": payload.entry, 
            "quantity": ql["quantity"],
            "priceProtect": "TRUE"
        }
        
        entry_order = new_algo_order(**entry_params)
        algo_id = str(entry_order.get("algoId", ""))
        logger.info(f"[STOP-AUTO] Algo entry placed: algoId={algo_id}, symbol={symbol}, side={side}")
        
        trade_data = {
            "entry_order_id": algo_id,
            "symbol": symbol,
            "side": side,
            "quantity": ql["quantity"],
            "entry_price": float(payload.entry) if payload.entry else 0,
            "order_type": "STOP_MARKET",
            "status": entry_order.get("algoStatus", "NEW"),
            "payload": payload.model_dump()
        }
        log_trade(trade_data)
        
        # Simpan di memory BY SYMBOL agar WebSocket bisa pasang TP/SL saat FILLED
        # TP/SL dihitung dari FILL PRICE (bukan entry signal) karena signal hanya kirim persen
        # (Algo orders return algoId, but ORDER_TRADE_UPDATE fires with a different orderId)
        pending_algo_entries[symbol] = {
            "algo_id": algo_id,
            "symbol": symbol,
            "position_side": payload.positionSide,
            "close_side": close_side,
            "quantity": ql["quantity"],
            "tp_percent": tp_percent_num,
            "sl_percent": sl_percent_num,
            "is_long": is_long,
            "tp_type": "LIMIT",
            "sl_type": "STOP_MARKET"
        }

        update_signal({
            "symbol": symbol,
            "positionSide": payload.positionSide,
            "tp_percent": payload.tp_percent,
            "sl_percent": payload.sl_percent,
        })

        return {
            "message": "Success Trigger Order (STOP AUTO)! TP/SL akan dipasang via WebSocket saat entry FILLED.",
            "entryOrder": entry_order
        }

    except Exception as e:
        logger.error(f"Place stop auto error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
