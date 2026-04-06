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

def clean_symbol(symbol: str, position_side: str):
    """
    Membersihkan order dan posisi terbuka HANYA untuk positionSide tertentu.
    Flow:
      1. Cancel specific open orders (regular)
      2. Cancel specific algo/conditional orders
      3. Close open positions untuk positionSide tersebut
    """
    symbol = symbol.upper()
    position_side = position_side.upper()

    # 1. Cancel specific regular open orders
    try:
        open_orders = rest_client.get_open_orders(symbol=symbol)
        for order in open_orders:
            if order.get("positionSide", "").upper() == position_side:
                try:
                    rest_client.cancel_order(symbol=symbol, orderId=order["orderId"])
                    logger.info(f"[CLEAN] Canceled open order {order['orderId']} ({position_side}) for {symbol}")
                except Exception as e:
                    logger.debug(f"[CLEAN] Failed to cancel open order {order['orderId']}: {str(e)}")
    except Exception as e:
        logger.debug(f"[CLEAN] error fetching open_orders: {str(e)}")

    # 2. Cancel specific algo/conditional orders
    try:
        algo_orders = rest_client.sign_request("GET", "/fapi/v1/algoOpenOrders", {"symbol": symbol})
        
        # Binance API /algoOpenOrders bisa return list atau dict
        algo_list = []
        if isinstance(algo_orders, list):
            algo_list = algo_orders
        elif isinstance(algo_orders, dict):
            # Coba ambil lists dari key yang umum di response Binance
            for key in ["openAlgoOrders", "algoOrderList", "orders"]:
                if key in algo_orders:
                    algo_list = algo_orders[key]
                    break

        for algo in algo_list:
            if algo.get("positionSide", "").upper() == position_side:
                try:
                    rest_client.sign_request("DELETE", "/fapi/v1/algoOrder", {"symbol": symbol, "algoId": algo.get("algoId")})
                    logger.info(f"[CLEAN] Canceled algo order {algo.get('algoId')} ({position_side}) for {symbol}")
                except Exception as e:
                    logger.debug(f"[CLEAN] Failed to cancel algo order {algo.get('algoId')}: {str(e)}")
    except Exception as e:
        logger.debug(f"[CLEAN] error fetching algo_orders: {str(e)}")

    # 3. Close open positions
    cancel_position_by_side(symbol, position_side)


def cancel_position_by_side(symbol: str, position_side: str) -> list:
    """
    Fetches all positions for a symbol and sends MARKET orders to close any open quantities
    matching the specified position_side.
    Hedge Mode: positionSide dikirim, side disesuaikan, reduceOnly tidak diperbolehkan.
    """
    symbol = symbol.upper()
    position_side = position_side.upper()
    positions = rest_client.get_position_risk(symbol=symbol)

    close_orders = []
    for pos in positions:
        if pos.get("positionSide", "").upper() != position_side:
            continue
            
        amt = float(pos["positionAmt"])
        if amt != 0:
            qty = abs(amt)
            # Hedge Mode: close LONG dengan SELL, close SHORT dengan BUY
            side = "SELL" if position_side == "LONG" else "BUY"

            try:
                res = rest_client.new_order(
                    symbol=symbol,
                    side=side,
                    positionSide=position_side,
                    type="MARKET",
                    quantity=qty
                )
                close_orders.append(res)
                logger.info(f"[CLEAN] Closed position for {symbol} ({position_side}), amt: {amt}")
            except Exception as e:
                logger.error(f"Failed to close position for {symbol} ({position_side}): {str(e)}")
                raise e
    return close_orders
