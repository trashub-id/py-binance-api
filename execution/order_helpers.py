import math
import logging
from core.binance_client import rest_client, get_exchange_info

logger = logging.getLogger(__name__)

def count_decimals(value: float) -> int:
    if math.floor(value) == value:
        return 0
    return len(str(value).split('.')[1])

def get_quantity_and_leverage(entry_price: str, sl_price: str, percent_risk: str, percent_balance: str, balance: str, symbol: str) -> dict:
    """
    Hitung quantity dan leverage berdasarkan SL, entry, dan risk.
    Percent balance otomatis disesuaikan jika leverage di-up.
    """
    entry = float(entry_price)
    sl = float(sl_price)
    risk = float(percent_risk)
    pct_balance = float(percent_balance)
    bal = float(balance)

    exchange_info = get_exchange_info()
    symbol_info = next((s for s in exchange_info.get("symbols", []) if s["symbol"] == symbol.upper()), None)
    if not symbol_info:
        raise ValueError(f"Symbol {symbol} not found in exchangeInfo")

    step_size = "0.001"
    min_qty = "0.001"
    min_notional = "0"

    for f in symbol_info.get("filters", []):
        if f["filterType"] == "LOT_SIZE":
            step_size = f["stepSize"]
            min_qty = f["minQty"]
        elif f["filterType"] == "MIN_NOTIONAL":
            min_notional = f.get("notional", "0")

    step_size_f = float(step_size)
    min_qty_f = float(min_qty)
    min_notional_f = float(min_notional)
    decimal_qty = count_decimals(step_size_f)

    price_diff = abs(entry - sl)
    if price_diff == 0:
        raise ValueError("Stop loss must be different from entry")

    percent_drop = price_diff / entry

    raw_leverage = risk / percent_drop / pct_balance
    leverage = math.ceil(raw_leverage)

    pct_balance_2 = risk / percent_drop / leverage
    allocated_capital = bal * (pct_balance_2 / 100)

    qty = (allocated_capital * leverage) / entry
    margin = (qty * entry) / leverage

    if margin > allocated_capital:
        qty = qty * (allocated_capital / margin)

    # Bulatkan qty ke bawah sesuai stepSize
    qty_num = math.floor(qty / step_size_f) * step_size_f
    qty_formatted = f"%.{decimal_qty}f" % qty_num
    qty_num_parsed = float(qty_formatted)

    margin = (qty_num_parsed * entry) / leverage
    notional = qty_num_parsed * entry

    logger.debug(f"Calculated Qty: {qty_formatted}, Leverage: {leverage}")

    if qty_num_parsed < min_qty_f:
         raise ValueError(f"Unable to find valid quantity: below minQty. Qty={qty_num_parsed}, MinQty={min_qty_f}")

    if margin > allocated_capital:
         raise ValueError("Unable to find valid quantity within allocated capital")

    if notional < min_notional_f:
         raise ValueError(f"Notional {notional} is below minNotional {min_notional_f}")

    return {
        "quantity": qty_formatted,
        "leverage": leverage
    }

def clean_symbol(symbol: str):
    """
    Membersihkan semua order dan posisi terbuka untuk symbol tertentu.
    Flow:
      1. Cancel ALL open orders (regular)
      2. Cancel ALL algo/conditional orders
      3. Close ALL open positions (MARKET order)
    """
    symbol = symbol.upper()

    # 1. Cancel all regular open orders
    try:
        rest_client.cancel_open_orders(symbol=symbol)
        logger.info(f"[CLEAN] Canceled all open orders for {symbol}")
    except Exception as e:
        # -2011 = "Unknown order" (no orders to cancel) — safe to ignore
        logger.debug(f"[CLEAN] cancel_open_orders: {str(e)}")

    # 2. Cancel all algo/conditional orders
    try:
        rest_client.sign_request("DELETE", "/fapi/v1/algoOpenOrders", {"symbol": symbol})
        logger.info(f"[CLEAN] Canceled all algo orders for {symbol}")
    except Exception as e:
        logger.debug(f"[CLEAN] cancel_algo_orders: {str(e)}")

    # 3. Close all open positions
    cancel_position_by_symbol(symbol)


def cancel_position_by_symbol(symbol: str) -> list:
    """
    Fetches all positions for a symbol and sends MARKET orders to close any open quantities.
    One-Way Mode: positionSide tidak dikirim, side ditentukan dari tanda positionAmt.
    """
    symbol = symbol.upper()
    positions = rest_client.get_position_risk(symbol=symbol)

    close_orders = []
    for pos in positions:
        amt = float(pos["positionAmt"])
        if amt != 0:
            qty = abs(amt)
            # One-Way Mode: amt positif = long (close dengan SELL), amt negatif = short (close dengan BUY)
            side = "SELL" if amt > 0 else "BUY"

            try:
                res = rest_client.new_order(
                    symbol=symbol,
                    side=side,
                    type="MARKET",
                    quantity=qty,
                    reduceOnly="true"
                )
                close_orders.append(res)
                logger.info(f"[CLEAN] Closed position for {symbol}, amt: {amt}")
            except Exception as e:
                logger.error(f"Failed to close position for {symbol}: {str(e)}")
                raise e
    return close_orders
