import math

def plan_trade(side: str, entry: float, atr: float, rr: float = 2.0, atr_mult: float = 1.2,
               account_usd: float = 1000.0, risk_pct: float = 1.0):
    """
    side: BUY yoki SELL
    entry: kirish narxi
    atr: ATR (o'rtacha harakat) — masalan 3m yoki 1h dan
    rr: Risk/Reward (TP = rr * risk)
    atr_mult: stop masofasi = atr * atr_mult
    risk_pct: accountdan risk foizi (1% tavsiya)
    """
    side = side.upper().strip()
    risk_usd = account_usd * (risk_pct / 100.0)
    stop_dist = atr * atr_mult

    if stop_dist <= 0:
        raise ValueError("ATR yoki stop_dist noto'g'ri (0 dan katta bo'lishi kerak).")

    if side == "BUY":
        sl = entry - stop_dist
        tp = entry + stop_dist * rr
    elif side == "SELL":
        sl = entry + stop_dist
        tp = entry - stop_dist * rr
    else:
        raise ValueError("side faqat BUY yoki SELL bo'lishi kerak")

    # shares/qty
    qty = risk_usd / stop_dist
    qty_floor = math.floor(qty)  # aksiyada butun son
    return {
        "side": side,
        "entry": round(entry, 4),
        "sl": round(sl, 4),
        "tp": round(tp, 4),
        "risk_usd": round(risk_usd, 2),
        "stop_dist": round(stop_dist, 4),
        "qty_est": round(qty, 2),
        "qty_floor": qty_floor
    }

if __name__ == "__main__":
    # tez test
    print(plan_trade("BUY", entry=100.0, atr=0.8, rr=2.0, atr_mult=1.2, account_usd=1000, risk_pct=1.0))
