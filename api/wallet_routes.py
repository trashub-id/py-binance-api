import logging
from datetime import datetime
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional

from core.binance_client import rest_client as client
import database.supabase_logger as supabase_logger
from config.settings import WEBHOOK_SECRET

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/wallet", tags=["wallet"])

class RebalanceRequest(BaseModel):
    password: str = Field(..., alias="pass")
    type: Optional[str] = "rebalance"
    min_bnb_percent: float
    fromAsset: str

class UpdateDailyRequest(BaseModel):
    password: str = Field(..., alias="pass")
    type: Optional[str] = "trigger_update_wallet"
    wallet_balance_percent: float
    targetAsset: str

async def convert_assets(from_asset: str, to_asset: str, amount: float) -> dict:
    try:
        # Step 1: Get Quote
        quote_res = client.send_quote_request(fromAsset=from_asset, toAsset=to_asset, fromAmount=amount)
        quote_id = quote_res.get("quoteId")
        if not quote_id:
            raise ValueError(f"No quoteId returned: {quote_res}")
        
        # Step 2: Accept Quote
        accept_res = client.accept_offered_quote(quoteId=quote_id)
        
        # Step 3: Log success
        if supabase_logger.supabase:
            supabase_logger.supabase.table("bot_logs").insert({
                "context": "convert_assets",
                "message": f"Successfully converted {amount} {from_asset} to {to_asset}",
                "payload": accept_res
            }).execute()
        return accept_res
    except Exception as e:
        if supabase_logger.supabase:
            supabase_logger.log_error("convert_assets", e, payload={"fromAsset": from_asset, "toAsset": to_asset, "amount": amount})
        logger.error(f"Failed to convert assets: {e}")
        raise ValueError(f"Conversion failed: {str(e)}")

@router.post("/rebalance-bnb")
async def rebalance_bnb_endpoint(payload: RebalanceRequest):
    if payload.password != WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    try:
        # 1. Fetch account balance
        account_info = client.account()
        assets = account_info.get("assets", [])
        
        from_balance = 0.0
        bnb_balance = 0.0
        
        for asset in assets:
            if asset["asset"] == payload.fromAsset:
                from_balance = float(asset["walletBalance"])
            elif asset["asset"] == "BNB":
                bnb_balance = float(asset["walletBalance"])
        
        # 2. Fetch BNB Price
        ticker = client.ticker_price(symbol="BNBUSDT")
        bnb_price = float(ticker["price"]) if isinstance(ticker, dict) else float(ticker[0]["price"])
        
        # 3. Calculate metrics
        bnb_usd_value = bnb_balance * bnb_price
        total_usd_value = bnb_usd_value + from_balance
        
        if total_usd_value <= 0:
             return {"status": "success", "message": "Zero balance", "percent_before": 0, "percent_after": 0}
            
        current_bnb_percent = (bnb_usd_value / total_usd_value) * 100
        
        if current_bnb_percent < payload.min_bnb_percent:
            # Need to buy BNB
            target_bnb_usd = (payload.min_bnb_percent / 100) * total_usd_value
            usd_to_buy = target_bnb_usd - bnb_usd_value
            
            if usd_to_buy > from_balance:
                usd_to_buy = from_balance # don't exceed available
            
            # Execute Conversion
            if usd_to_buy > 0.1: # Threshold to avoid dust convert error
                # We round to typical precision (e.g. 2 decimal for USDT)
                usd_to_buy = round(usd_to_buy, 2)
                await convert_assets(payload.fromAsset, "BNB", usd_to_buy)
                
                # Assume conversion slightly changes percentage (calculating new ideally requires refetch, but we estimate here)
                new_bnb_usd_value = bnb_usd_value + usd_to_buy
                percent_after = (new_bnb_usd_value / total_usd_value) * 100
                
                return {
                    "status": "success_rebalanced", 
                    "percent_before": round(current_bnb_percent, 2), 
                    "percent_after": round(percent_after, 2)
                }
        
        return {
            "status": "success_no_action",
            "percent_before": round(current_bnb_percent, 2),
            "percent_after": round(current_bnb_percent, 2)
        }
    
    except Exception as e:
        supabase_logger.log_error("rebalance_bnb_endpoint", e, payload=payload.model_dump())
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/update-daily")
async def update_daily_endpoint(payload: UpdateDailyRequest):
    if payload.password != WEBHOOK_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")
    
    try:
        account_info = client.account()
        wallet_balance = float(account_info.get("totalWalletBalance", 0.0))
        unrealized_pnl = float(account_info.get("totalUnrealizedProfit", 0.0))
        
        today_date = datetime.utcnow().strftime('%Y-%m-%d')
        
        # Calculate some additional metrics for daily_portfolio (e.g., from assets)
        assets = account_info.get("assets", [])
        bnb_balance = 0.0
        usd_balance = 0.0
        
        for asset in assets:
            if asset["asset"] == payload.targetAsset:
                usd_balance += float(asset["walletBalance"])
            elif asset["asset"] == "BNB":
                bnb_balance += float(asset["walletBalance"])
        
        try:
            ticker = client.ticker_price(symbol="BNBUSDT")
            bnb_price = float(ticker["price"]) if isinstance(ticker, dict) else float(ticker[0]["price"])
        except:
            bnb_price = 0.0
            
        wallet_balance_usd = usd_balance + (bnb_balance * bnb_price)
        
        data = {
            "date": today_date,
            "wallet_balance": wallet_balance,
            "wallet_balance_percent": payload.wallet_balance_percent,
            "wallet_balance_usd_pair": usd_balance,
            "wallet_balance_usd": wallet_balance_usd,
            "wallet_balance_bnb": bnb_balance,
            "unrealized_pnl": unrealized_pnl,
            "target_asset": payload.targetAsset
        }
        
        if supabase_logger.supabase:
            # Perform UPSERT (insert with on_conflict)
            res = supabase_logger.supabase.table("daily_portfolio").upsert(data, on_conflict="date").execute()
            return {"status": "success", "data": data}
        else:
            return {"status": "ignored", "message": "Supabase not configured"}

    except Exception as e:
        supabase_logger.log_error("update_daily_endpoint", e, payload=payload.model_dump())
        raise HTTPException(status_code=500, detail=str(e))
