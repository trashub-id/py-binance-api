from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP

def round_step_size(quantity: float, step_size: str) -> float:
    """
    Rounds the quantity to the nearest valid stepSize for a symbol.
    Always rounds down to prevent insufficient balance issues.
    """
    qty_dec = Decimal(str(quantity))
    step_dec = Decimal(step_size)
    
    rounded = (qty_dec / step_dec).quantize(Decimal('1'), rounding=ROUND_DOWN) * step_dec
    
    # Optional formatting to remove trailing zeroes if it is fully integer
    if rounded == rounded.to_integral():
        return float(rounded)
        
    # Standard string conversion handles decimals properly
    return float(rounded)

def round_tick_size(price: float, tick_size: str) -> float:
    """
    Rounds the price to the nearest valid tickSize for a symbol.
    """
    price_dec = Decimal(str(price))
    tick_dec = Decimal(tick_size)
    
    # Use ROUND_HALF_UP for prices
    rounded = (price_dec / tick_dec).quantize(Decimal('1'), rounding=ROUND_HALF_UP) * tick_dec
    
    return float(rounded)
