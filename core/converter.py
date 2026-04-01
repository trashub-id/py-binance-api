from pydantic import BaseModel

class OrderDetail(BaseModel):
    type: str
    price: float

class WebhookPayload(BaseModel):
    symbol: str
    side: str
    quantity: float
    entry: OrderDetail
    tp: OrderDetail
    sl: OrderDetail

def extract_order_params(order_type: str) -> dict:
    """
    Translates payload order types to Binance accepted types and modifiers.
    Specifically handles POST_ONLY mapping to LIMIT + GTX.
    """
    order_type = order_type.upper()
    
    if order_type == "POST_ONLY":
        return {
            "type": "LIMIT",
            "timeInForce": "GTX"
        }
    
    if order_type == "LIMIT":
        return {
            "type": "LIMIT",
            "timeInForce": "GTC"
        }
        
    return {
        "type": order_type
    }
