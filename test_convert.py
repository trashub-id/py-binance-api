import logging
from core.binance_client import rest_client 
try:
    print(rest_client.list_all_convert_pairs())
    print("Calling send_quote_request...")
    res = rest_client.send_quote_request(fromAsset='USDT', toAsset='BNB', fromAmount=5.0)
    print("Quote Res:", res)
except Exception as e:
    print(f"Error: {e}")
