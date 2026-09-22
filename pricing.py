"""Order math: price level, totals, stock check. No database code here."""

TIERS = ("srp", "reseller", "dealer")
TIER_LABEL = {"srp": "SRP", "reseller": "Reseller", "dealer": "Dealer"}
PAY_METHODS = ("Cash", "GCash", "Bank transfer", "To collect")


class SaleError(Exception):
    """A problem with the order that the user should see."""


def pick_tier(lines, mode, reseller_min, dealer_min):
    """lines: list of (product_dict, qty). mode: 'auto' or a tier."""
    if mode in TIERS:
        return mode
    totals = {t: sum((p.get(t) or 0) * q for p, q in lines) for t in TIERS}
    if totals["dealer"] >= dealer_min:
        return "dealer"
    if totals["reseller"] >= reseller_min:
        return "reseller"
    return "srp"


def _num(v, default=0.0):
    try:
        n = float(v)
        return n if n == n and n not in (float("inf"), float("-inf")) else default
    except (TypeError, ValueError):
        return default


def clean_request(data):
    """Validate the JSON sent by the order page. Returns a clean dict."""
    if not isinstance(data, dict):
        raise SaleError("Invalid order.")
    qty_by_id = {}
    for it in data.get("items") or []:
        pid = str(it.get("id", "")).strip()
        try:
            q = int(it.get("qty", 0))
        except (TypeError, ValueError):
            q = 0
        if pid and q > 0:
            qty_by_id[pid] = qty_by_id.get(pid, 0) + q
    if not qty_by_id:
        raise SaleError("Add at least one product to the order.")
    if len(qty_by_id) > 150:
        raise SaleError("Too many different products in one order.")

    mode = data.get("tierMode", "auto")
    if mode not in TIERS:
        mode = "auto"
    pay = data.get("payMethod") if data.get("payMethod") in PAY_METHODS else "Cash"
    paid_raw = data.get("amountPaid")
    return {
        "qty_by_id": qty_by_id,
        "mode": mode,
        "buyer": (str(data.get("buyer") or "").strip() or "Walk-in")[:120],
        "contact": str(data.get("contact") or "").strip()[:200],
        "note": str(data.get("note") or "").strip()[:300],
        "discount": max(_num(data.get("discount")), 0),
        "payMethod": pay,
        "amountPaid": None if paid_raw in (None, "") else max(_num(paid_raw), 0),
    }


def build_sale(products_by_id, req, settings, now, order_no):
    """Compute the sale from CURRENT product data. Raises SaleError on any problem."""
    lines = []
    for pid, qty in req["qty_by_id"].items():
        p = products_by_id.get(pid)
        if not p:
            raise SaleError("A product in this order was deleted. Refresh the page and try again.")
        lines.append((p, qty))

    short = [f"{p['name']} (only {p.get('stock', 0)} left)" for p, q in lines if (p.get("stock") or 0) < q]
    if short:
        raise SaleError("Not enough stock: " + ", ".join(short))

    tier = pick_tier(lines, req["mode"], settings["reseller_min"], settings["dealer_min"])
    items = []
    for p, q in lines:
        price = p.get(tier) or 0
        items.append({"productId": p["id"], "name": p["name"], "qty": q, "price": price, "subtotal": price * q})

    subtotal = sum(i["subtotal"] for i in items)
    discount = min(req["discount"], subtotal)
    total = subtotal - discount
    paid = req["amountPaid"]
    return {
        "orderNo": order_no,
        "buyer": req["buyer"],
        "contact": req["contact"],
        "tier": tier,
        "items": items,
        "packs": sum(i["qty"] for i in items),
        "subtotal": subtotal,
        "discount": discount,
        "total": total,
        "payMethod": req["payMethod"],
        "amountPaid": paid,
        "change": None if paid is None else max(paid - total, 0),
        "note": req["note"],
        "status": "completed",
        "createdAt": now,
    }
