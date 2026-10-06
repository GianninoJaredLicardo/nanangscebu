"""Order math: price level, totals, stock check. No database code here."""
import re

TIERS = ("srp", "reseller", "dealer")
TIER_LABEL = {"srp": "SRP", "reseller": "Reseller", "dealer": "Dealer"}
PAY_METHODS = ("Cash", "GCash", "Bank transfer", "To collect")
TO_COLLECT = "To collect"
PAY_LABEL = {"Bank transfer": "Bank Transfer", "To collect": "To Collect"}  # how saved payment names are shown
PAID_METHODS = tuple(m for m in PAY_METHODS if m != TO_COLLECT)


def cap_words(text):
    """'ana dela cruz' -> 'Ana Dela Cruz'. Only lowercase first letters change, so 'GCash' or 'McCoy' stay as typed."""
    return re.sub(r"(?<![\w'’])([a-zñ])", lambda m: m.group(1).upper(), str(text or ""))


def cap_first(text):
    """'deliver saturday' -> 'Deliver saturday'."""
    text = str(text or "")
    i = len(text) - len(text.lstrip())
    return text[:i] + text[i:i + 1].upper() + text[i + 1:]


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
    buyer = cap_words(" ".join(str(data.get("buyer") or "").split()))[:120]
    contact = (str(data.get("contact") or "").strip())[:200]
    address = cap_words(" ".join(str(data.get("address") or "").split()))[:300]
    if not buyer:
        raise SaleError("Enter the buyer name.")
    if not contact:
        raise SaleError("Enter the buyer contact number.")
    if not address:
        raise SaleError("Enter the buyer address.")
    return {
        "qty_by_id": qty_by_id,
        "mode": mode,
        "buyer": buyer,
        "contact": contact,
        "address": address,
        "note": cap_first(str(data.get("note") or "").strip())[:300],
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
        item = {"productId": p["id"], "name": p["name"], "qty": q, "price": price, "subtotal": price * q}
        if p.get("cost") is not None:
            item["cost"] = p["cost"]  # your buying cost at the time of sale, for profit reports
        items.append(item)

    subtotal = sum(i["subtotal"] for i in items)
    discount = min(req["discount"], subtotal)
    total = subtotal - discount
    paid = req["amountPaid"]
    return {
        "orderNo": order_no,
        "buyer": req["buyer"],
        "contact": req["contact"],
        "address": req.get("address", ""),
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


def build_draft(data, products_by_id):
    """Validate a Draft quote sent by the draft page and price it from CURRENT product data.
    Customer name, contact number and address are all optional. Stock is never checked."""
    if not isinstance(data, dict):
        raise SaleError("Invalid draft.")
    qty_by_id = {}
    for it in data.get("items") or []:
        if not isinstance(it, dict):
            continue
        pid = str(it.get("id", "")).strip()
        try:
            q = int(it.get("qty", 0))
        except (TypeError, ValueError):
            q = 0
        if pid in products_by_id and q > 0:
            qty_by_id[pid] = min(qty_by_id.get(pid, 0) + q, 9999)
    if not qty_by_id:
        raise SaleError("Add at least one product to the draft.")
    if len(qty_by_id) > 150:
        raise SaleError("Too many different products in one draft.")
    tier = data.get("tierMode") if data.get("tierMode") in TIERS else "srp"
    items = []
    for pid, q in qty_by_id.items():
        p = products_by_id[pid]
        price = p.get(tier) or 0
        items.append({"productId": pid, "name": p["name"], "qty": q, "price": price, "subtotal": price * q})
    subtotal = sum(i["subtotal"] for i in items)
    discount = min(max(_num(data.get("discount")), 0), subtotal)
    return {
        "customer": cap_words(" ".join(str(data.get("customer") or "").split()))[:120],
        "contact": str(data.get("contact") or "").strip()[:200],
        "address": cap_words(" ".join(str(data.get("address") or "").split()))[:300],
        "note": cap_first(str(data.get("note") or "").strip())[:300],
        "tier": tier,
        "items": items,
        "packs": sum(i["qty"] for i in items),
        "subtotal": subtotal,
        "discount": discount,
        "total": subtotal - discount,
    }
