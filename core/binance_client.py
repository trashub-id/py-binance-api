import logging
from binance.um_futures import UMFutures
from binance.websocket.um_futures.websocket_client import UMFuturesWebsocketClient
from config.settings import BINANCE_API_KEY, BINANCE_API_SECRET, IS_TESTNET

logger = logging.getLogger(__name__)

# Base URLs based on environment
BASE_URL = "https://testnet.binancefuture.com" if IS_TESTNET else "https://fapi.binance.com"
WS_URL = "wss://stream.binancefuture.com" if IS_TESTNET else "wss://fstream.binance.com"

# The UMFutures REST client
rest_client = UMFutures(key=BINANCE_API_KEY, secret=BINANCE_API_SECRET, base_url=BASE_URL)

# Websocket client wrapper
ws_client = None

# Cache for exchange_info
_exchange_info_cache = None

def get_exchange_info() -> dict:
    """Fetch and cache exchange info to avoid repeating API calls."""
    global _exchange_info_cache
    if not _exchange_info_cache:
        try:
            _exchange_info_cache = rest_client.exchange_info()
            logger.info("Fetched exchange_info successfully.")
        except Exception as e:
            logger.error(f"Failed to fetch exchange_info: {str(e)}")
            raise e
    return _exchange_info_cache

def get_symbol_filters(symbol: str) -> tuple[str, str]:
    """Retrieve tickSize and stepSize for a specific symbol."""
    info = get_exchange_info()
    symbols = info.get("symbols", [])
    
    tick_size = "0.01" # Default fallback
    step_size = "0.001"
    
    for s in symbols:
        if s["symbol"] == symbol.upper():
            filters = s.get("filters", [])
            for f in filters:
                if f["filterType"] == "PRICE_FILTER":
                    tick_size = f["tickSize"]
                elif f["filterType"] == "LOT_SIZE":
                    step_size = f["stepSize"]
            break
            
    return tick_size, step_size

def get_listen_key() -> str:
    """Creates a new listen key for USER_DATA_STREAM."""
    try:
        response = rest_client.new_listen_key()
        return response["listenKey"]
    except Exception as e:
        logger.error(f"Failed to create listen key: {str(e)}")
        raise e

def keepalive_listen_key(listen_key: str):
    """Extends the listen key validity by 60 mins."""
    try:
        rest_client.renew_listen_key(listen_key)
        logger.debug(f"Renewed listen key: {listen_key}")
    except Exception as e:
        logger.error(f"Failed to renew listen key: {str(e)}")

def new_algo_order(**params) -> dict:
    """
    Places a conditional/algo order via /fapi/v1/algoOrder.
    Used for STOP_MARKET orders which are not supported on the regular /fapi/v1/order endpoint.
    """
    try:
        response = rest_client.sign_request("POST", "/fapi/v1/algoOrder", params)
        logger.info(f"Algo order placed: {response}")
        return response
    except Exception as e:
        logger.error(f"Failed to place algo order: {str(e)}")
        raise e

