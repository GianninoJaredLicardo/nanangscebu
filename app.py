"""Nanang's Authentic Recipes Mandaue - Cebu Distributor, Inventory and Sales, a Flask app with a Firebase Firestore database."""
import csv
import hmac
import io
import json
import os
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone

from flask import (Flask, Response, abort, flash, jsonify, redirect, render_template, request,
                   session, url_for)
from werkzeug.middleware.proxy_fix import ProxyFix

try:  # load .env when running on your own computer
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from markupsafe import Markup, escape
from pricing import PAY_METHODS, TIER_LABEL, SaleError, clean_request

BASE = os.path.dirname(os.path.abspath(__file__))
PH = timezone(timedelta(hours=8))  # Philippines, no daylight saving

SETTINGS = {
    # Registered trade name: always shown in full, never shortened.
    "shop_name": "Nanang's Authentic Recipes Mandaue - Cebu Distributor",
    "contact": os.environ.get("SHOP_CONTACT", "0961 565 5590"),
    "reseller_min": float(os.environ.get("RESELLER_MIN", 2000)),
    "dealer_min": float(os.environ.get("DEALER_MIN", 5000)),
    "low_stock": int(os.environ.get("LOW_STOCK", 5)),
}
CATEGORY_ORDER = ["Ready-to-Heat", "Easy-to-Cook", "Dimsum", "Sulit Pack"]
LOG_LABEL = {"sale": "Sold", "in": "Stock in", "adjust": "Adjustment", "void": "Voided order", "opening": "Opening stock"}

# ------------------------------------------------------------------
# App setup
# ------------------------------------------------------------------
app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
_secret = os.environ.get("SECRET_KEY")
if not _secret:
    print("WARNING: SECRET_KEY is not set. Using a temporary key; you will be logged out on restart.")
app.config.update(
    SECRET_KEY=_secret or secrets.token_hex(32),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=bool(os.environ.get("RENDER")),  # HTTPS on Render
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    MAX_CONTENT_LENGTH=1024 * 1024,
)

_store = None
_store_lock = threading.Lock()


def db():
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                from store import FirestoreStore
                _store = FirestoreStore()
    return _store


def user_error_types():
    from store import StoreError
    return (StoreError, SaleError)


# ------------------------------------------------------------------
# Time helpers (all dates shown in Philippine time)
# ------------------------------------------------------------------
def now_ph():
    return datetime.now(PH)


def date_key(dt=None):
    return (dt or now_ph()).astimezone(PH).strftime("%Y-%m-%d")


def day_start(key):
    return datetime.strptime(key, "%Y-%m-%d").replace(tzinfo=PH)


def valid_key(s):
    try:
        day_start(s)
        return s
    except (TypeError, ValueError):
        return None


def to_ph(dt):
    if not isinstance(dt, datetime):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(PH)


# ------------------------------------------------------------------
# Template filters
# ------------------------------------------------------------------
def peso(n):
    n = float(n or 0)
    return "₱{:,.0f}".format(n) if n == int(n) else "₱{:,.2f}".format(n)


@app.template_filter("peso")
def _peso(n):
    return peso(n)


def fmt_time(d):
    return f"{d.hour % 12 or 12}:{d:%M} {d:%p}"


@app.template_filter("dt")
def _dt(v):
    d = to_ph(v)
    return f"{d:%b} {d.day}, {d.year}, {fmt_time(d)}" if d else ""


@app.template_filter("time")
def _time(v):
    d = to_ph(v)
    return fmt_time(d) if d else ""


@app.template_filter("num")
def _num(n):
    return "{:,}".format(int(n or 0))


def stock_state(p):
    s = p.get("stock") or 0
    low = p.get("lowStock")
    low = SETTINGS["low_stock"] if low is None else low
    return "out" if s <= 0 else "low" if s <= low else "ok"


def cat_rank(c):
    return CATEGORY_ORDER.index(c) if c in CATEGORY_ORDER else 99


def sort_products(ps):
    return sorted(ps, key=lambda p: (cat_rank(p.get("category")), p.get("category") or "", p.get("name") or ""))


def categories(ps):
    return sorted({p.get("category") for p in ps if p.get("category")}, key=lambda c: (cat_rank(c), c))


SHOP_LOCATION = "Mandaue - Cebu Distributor"


@app.template_filter("brand")
def brand_filter(name):
    """Show the full trade name, keeping 'Mandaue - Cebu Distributor' on one line."""
    name = str(name)
    if name.endswith(SHOP_LOCATION):
        return Markup(f'{escape(name[:-len(SHOP_LOCATION)])}<span class="nw">{SHOP_LOCATION}</span>')
    return escape(name)


app.jinja_env.globals.update(
    SETTINGS=SETTINGS, TIER_LABEL=TIER_LABEL, LOG_LABEL=LOG_LABEL, stock_state=stock_state, PAY_METHODS=PAY_METHODS,
)


# ------------------------------------------------------------------
# Security: login, CSRF, login rate limit
# ------------------------------------------------------------------
ADMIN_USERNAME = "nanangsadmin"
BUILT_IN_ADMIN_PASSWORD = "nanangscebu"


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


app.jinja_env.globals["csrf_token"] = csrf_token


def password_ok(pw):
    return hmac.compare_digest(BUILT_IN_ADMIN_PASSWORD.encode(), pw.encode())


PUBLIC = {"login", "static", "healthz"}


@app.before_request
def guard():
    if request.method == "POST":
        tok = request.form.get("csrf") or request.headers.get("X-CSRF-Token") or ""
        if not session.get("csrf") or not hmac.compare_digest(tok, session["csrf"]):
            if request.path.startswith("/api/"):
                return jsonify(error="Your session expired. Refresh the page."), 400
            flash("Your session expired. Please try again.", "error")
            return redirect(request.path)
    if request.endpoint not in PUBLIC and not session.get("admin"):
        if request.path.startswith("/api/"):
            return jsonify(error="Please sign in again."), 401
        return redirect(url_for("login", next=request.full_path if request.method == "GET" else None))


@app.after_request
def headers(resp):
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "same-origin"
    return resp


@app.route("/healthz")
def healthz():
    return "ok"


@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("admin"):
        return redirect(url_for("dashboard"))
    error = ""
    if request.method == "POST":
        user = request.form.get("username", "").strip().lower()
        pw = request.form.get("password", "")
        if hmac.compare_digest(user.encode(), ADMIN_USERNAME.encode()) and password_ok(pw):
            session.clear()
            session.permanent = True
            session["admin"] = True
            csrf_token()
            nxt = request.args.get("next") or ""
            return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("dashboard"))
        error = "Wrong username or password."
    return render_template("login.html", error=error)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("login"))


# ------------------------------------------------------------------
# Dashboard
# ------------------------------------------------------------------
@app.route("/")
def dashboard():
    products = sort_products(db().list_products())
    t = date_key()
    sales = db().sales_between(day_start(t), day_start(t) + timedelta(days=1))
    done = [s for s in sales if s.get("status") != "voided"]
    low = sorted([p for p in products if stock_state(p) != "ok"], key=lambda p: p.get("stock") or 0)
    stats = {
        "sales": sum(s["total"] for s in done),
        "orders": len(done),
        "packs": sum(s["packs"] for s in done),
        "stock": sum(p.get("stock") or 0 for p in products),
        "value": sum((p.get("stock") or 0) * (p.get("dealer") or 0) for p in products),
    }
    return render_template("dashboard.html", products=products, sales=sales, low=low, stats=stats,
                           today=f"{now_ph():%A, %B} {now_ph().day}, {now_ph().year}")


# ------------------------------------------------------------------
# New order
# ------------------------------------------------------------------
@app.route("/order")
def order():
    products = sort_products(db().list_products())
    data = [{"id": p["id"], "name": p["name"], "category": p.get("category", ""), "srp": p.get("srp") or 0,
             "reseller": p.get("reseller") or 0, "dealer": p.get("dealer") or 0, "stock": p.get("stock") or 0,
             "state": stock_state(p)} for p in products]
    return render_template("order.html", products=data, cats=categories(products))


@app.route("/draft")
def draft():
    products = sort_products(db().list_products())
    data = [{"id": p["id"], "name": p["name"], "category": p.get("category", ""),
             "srp": p.get("srp") or 0, "reseller": p.get("reseller") or 0,
             "dealer": p.get("dealer") or 0} for p in products]
    return render_template("draft.html", products=data, cats=categories(products), today=date_key())


def order_number():
    return now_ph().strftime("%y%m%d") + "-" + secrets.token_hex(2).upper()


@app.route("/api/sale", methods=["POST"])
def api_sale():
    try:
        req = clean_request(request.get_json(silent=True))
        sid = db().create_sale(req, SETTINGS, order_number())
    except user_error_types() as e:
        return jsonify(error=str(e)), 400
    return jsonify(id=sid, url=url_for("receipt", sid=sid, new=1))


# ------------------------------------------------------------------
# Products
# ------------------------------------------------------------------
@app.route("/products")
def products():
    ps = sort_products(db().list_products())
    return render_template("products.html", products=ps, cats=categories(ps),
                           low_count=sum(1 for p in ps if stock_state(p) != "ok"),
                           packs=sum(p.get("stock") or 0 for p in ps),
                           stock_filter=request.args.get("stock", "all"))


def read_product_form(existing=None):
    f = request.form
    errors = []

    def money(key, label):
        try:
            v = float(f.get(key, ""))
            if v < 0:
                raise ValueError
            return v
        except ValueError:
            errors.append(f"Enter a valid {label} price.")
            return 0

    def whole(key, label, default=0):
        raw = f.get(key, "")
        if raw == "":
            return default
        try:
            v = int(raw)
            if v < 0:
                raise ValueError
            return v
        except ValueError:
            errors.append(f"Enter a whole number for {label}.")
            return default

    data = {
        "name": f.get("name", "").strip()[:150],
        "category": f.get("category", "").strip()[:60],
        "srp": money("srp", "SRP"),
        "reseller": money("reseller", "Reseller"),
        "dealer": money("dealer", "Dealer"),
        "stock": whole("stock", "stock"),
        "lowStock": whole("lowStock", "low-stock alert", SETTINGS["low_stock"]),
    }
    if not data["name"]:
        errors.append("Enter the product name.")
    if not data["category"]:
        errors.append("Enter a category.")
    if data["name"]:
        for p in db().list_products():
            if p["name"].strip().lower() == data["name"].lower() and (not existing or p["id"] != existing["id"]):
                errors.append("A product with this name already exists.")
                break
    return data, errors


@app.route("/products/new", methods=["GET", "POST"])
def product_new():
    p, errors = None, []
    if request.method == "POST":
        data, errors = read_product_form()
        if not errors:
            db().create_product(data)
            flash(f"Added {data['name']}.")
            return redirect(url_for("products"))
        p = data
    return render_template("product_form.html", p=p, is_new=True, errors=errors,
                           cats=categories(db().list_products()) + CATEGORY_ORDER)


@app.route("/products/<pid>/edit", methods=["GET", "POST"])
def product_edit(pid):
    existing = db().get_product(pid)
    if not existing:
        flash("That product no longer exists.", "error")
        return redirect(url_for("products"))
    p, errors = existing, []
    if request.method == "POST":
        data, errors = read_product_form(existing)
        if not errors:
            try:
                db().update_product(pid, data, request.form.get("reason", "").strip()[:200])
                flash("Changes saved.")
                return redirect(url_for("products"))
            except user_error_types() as e:
                errors = [str(e)]
        p = {**existing, **data}
    return render_template("product_form.html", p=p, is_new=False, errors=errors,
                           cats=categories(db().list_products()) + CATEGORY_ORDER)


@app.route("/products/<pid>/delete", methods=["POST"])
def product_delete(pid):
    p = db().get_product(pid)
    db().delete_product(pid)
    flash(f"Deleted {p['name'] if p else 'product'}.")
    return redirect(url_for("products"))


@app.route("/products/seed", methods=["POST"])
def product_seed():
    with open(os.path.join(BASE, "products.json"), encoding="utf-8") as fh:
        items = json.load(fh)
    n = db().seed_products(items, SETTINGS["low_stock"])
    flash(f"Loaded {n} products. Now add your stock in Stock in." if n else "All products are already loaded.")
    return redirect(url_for("products"))


def csv_response(filename, rows):
    buf = io.StringIO()
    buf.write("\ufeff")  # so Excel shows ₱ and accents correctly
    csv.writer(buf).writerows(rows)
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.route("/products/print")
def products_print():
    ps = sort_products(db().list_products())
    return render_template("products_print.html", products=ps, cats=categories(ps),
                           low_count=sum(1 for p in ps if stock_state(p) != "ok"),
                           packs=sum(p.get("stock") or 0 for p in ps),
                           today=date_key())


@app.route("/products/export.csv")
def products_export():
    rows = [["Product", "Category", "SRP", "Reseller", "Dealer", "Stock", "Low-stock level", "Stock value (dealer)"]]
    for p in sort_products(db().list_products()):
        s = p.get("stock") or 0
        rows.append([p["name"], p.get("category"), p.get("srp"), p.get("reseller"), p.get("dealer"), s,
                     p.get("lowStock"), s * (p.get("dealer") or 0)])
    return csv_response(f"stock-{date_key()}.csv", rows)


@app.route("/backup.json")
def backup():
    def plain(v):
        if isinstance(v, datetime):
            return to_ph(v).isoformat()
        if isinstance(v, dict):
            return {k: plain(x) for k, x in v.items()}
        if isinstance(v, list):
            return [plain(x) for x in v]
        return v
    data = plain(db().export_all())
    return Response(json.dumps(data, ensure_ascii=False, indent=1), mimetype="application/json",
                    headers={"Content-Disposition": f'attachment; filename="backup-{date_key()}.json"'})


# ------------------------------------------------------------------
# Stock in
# ------------------------------------------------------------------
@app.route("/restock", methods=["GET", "POST"])
def restock():
    if request.method == "POST":
        pid = request.form.get("product", "")
        note = request.form.get("note", "").strip()[:200]
        try:
            qty = int(request.form.get("qty", 0))
        except ValueError:
            qty = 0
        if not pid:
            flash("Choose a product.", "error")
        elif qty <= 0:
            flash("Enter how many packs you received.", "error")
        else:
            try:
                name = db().restock(pid, qty, note)
                flash(f"Added {qty} × {name}.")
            except user_error_types() as e:
                flash(str(e), "error")
        return redirect(url_for("restock", note=note))
    products = sort_products(db().list_products())
    today_logs = [l for l in db().logs_since(day_start(date_key())) if l.get("type") in ("in", "opening")]
    return render_template("restock.html", products=products, cats=categories(products), today_logs=today_logs,
                           selected=request.args.get("product", ""), note=request.args.get("note", ""))


# ------------------------------------------------------------------
# Sales
# ------------------------------------------------------------------
def sales_range():
    t = date_key()
    rng = request.args.get("range", "")
    if rng == "yesterday":
        f = to = (day_start(t) - timedelta(days=1)).strftime("%Y-%m-%d")
    elif rng == "week":
        f, to = (day_start(t) - timedelta(days=6)).strftime("%Y-%m-%d"), t
    elif rng == "month":
        f, to = t[:8] + "01", t
    else:
        f = valid_key(request.args.get("from")) or t
        to = valid_key(request.args.get("to")) or f
        rng = rng if rng == "today" else ("today" if f == to == t and not request.args.get("from") else "")
    if to < f:
        f, to = to, f
    return f, to, rng


@app.route("/sales")
def sales():
    f, to, rng = sales_range()
    rows = db().sales_between(day_start(f), day_start(to) + timedelta(days=1))
    done = [s for s in rows if s.get("status") != "voided"]
    agg = {}
    for s in done:
        for i in s["items"]:
            a = agg.setdefault(i["productId"], {"name": i["name"], "qty": 0, "amount": 0})
            a["qty"] += i["qty"]
            a["amount"] += i["subtotal"]
    total = sum(s["total"] for s in done)
    stats = {"total": total, "orders": len(done), "voided": len(rows) - len(done),
             "packs": sum(s["packs"] for s in done), "avg": round(total / len(done)) if done else 0}
    return render_template("sales.html", rows=rows, stats=stats, items=sorted(agg.values(), key=lambda a: -a["qty"]),
                           f=f, to=to, rng=rng, multi_day=f != to)


@app.route("/sales/print")
def sales_print():
    f, to, rng = sales_range()
    rows = db().sales_between(day_start(f), day_start(to) + timedelta(days=1))
    done = [s for s in rows if s.get("status") != "voided"]
    agg = {}
    for s in done:
        for i in s["items"]:
            a = agg.setdefault(i["productId"], {"name": i["name"], "qty": 0, "amount": 0})
            a["qty"] += i["qty"]
            a["amount"] += i["subtotal"]
    total = sum(s["total"] for s in done)
    stats = {"total": total, "orders": len(done), "voided": len(rows) - len(done),
             "packs": sum(s["packs"] for s in done), "avg": round(total / len(done)) if done else 0}
    return render_template("sales_print.html", rows=rows, stats=stats, items=sorted(agg.values(), key=lambda a: -a["qty"]),
                           f=f, to=to, rng=rng, multi_day=f != to, today=date_key())


@app.route("/sales/export.csv")
def sales_export():
    f, to, _ = sales_range()
    rows = [["Date", "Time", "Order no.", "Buyer", "Contact", "Price level", "Product", "Qty", "Price", "Amount",
             "Order subtotal", "Discount", "Order total", "Payment", "Status", "Note"]]
    for s in reversed(db().sales_between(day_start(f), day_start(to) + timedelta(days=1))):
        d = to_ph(s.get("createdAt"))
        for n, i in enumerate(s["items"]):
            first = n == 0
            rows.append([d.strftime("%Y-%m-%d") if d else "", d.strftime("%I:%M %p") if d else "", s["orderNo"],
                         s["buyer"], s.get("contact"), TIER_LABEL.get(s["tier"]), i["name"], i["qty"], i["price"],
                         i["subtotal"], s["subtotal"] if first else "", s["discount"] if first else "",
                         s["total"] if first else "", s["payMethod"], s["status"], s.get("note")])
    return csv_response(f"sales-{f}_to_{to}.csv", rows)


@app.route("/sales/<sid>")
def receipt(sid):
    s = db().get_sale(sid)
    if not s:
        abort(404)
    return render_template("receipt.html", s=s, new=request.args.get("new"))


@app.route("/sales/<sid>/void", methods=["POST"])
def void(sid):
    try:
        db().void_sale(sid)
        flash("Order voided. Stock was returned.")
    except user_error_types() as e:
        flash(str(e), "error")
    return redirect(url_for("receipt", sid=sid))


@app.route("/sales/<sid>/delete", methods=["POST"])
def delete_sale(sid):
    try:
        db().delete_sale(sid)
        flash("Voided order deleted.")
    except user_error_types() as e:
        flash(str(e), "error")
        return redirect(url_for("receipt", sid=sid))
    return redirect(url_for("sales"))


# ------------------------------------------------------------------
# Stock log
# ------------------------------------------------------------------
@app.route("/log")
def log():
    kind = request.args.get("type", "all")
    logs = db().recent_logs(300)
    if kind != "all":
        logs = [l for l in logs if l.get("type") == kind or (kind == "in" and l.get("type") == "opening")]
    return render_template("log.html", logs=logs, kind=kind)


@app.route("/log/<lid>/delete", methods=["POST"])
def log_delete(lid):
    db().delete_log(lid)
    flash("History entry deleted.")
    kind = request.form.get("type", "all")
    return redirect(url_for("log", type=kind) if kind != "all" else url_for("log"))


@app.route("/log/clear", methods=["POST"])
def log_clear():
    n = db().clear_logs()
    flash(f"Stock history cleared ({n} entries deleted)." if n else "There was no history to clear.")
    return redirect(url_for("log"))


# ------------------------------------------------------------------
# Errors
# ------------------------------------------------------------------
@app.errorhandler(404)
def not_found(_):
    return render_template("error.html", title="Page not found",
                           message="This page doesn't exist. It may have been deleted."), 404


@app.errorhandler(500)
def server_error(e):
    msg = "Something went wrong. Try again in a moment."
    original = getattr(e, "original_exception", None)
    text = str(original or "")
    if "Quota" in text or "RESOURCE_EXHAUSTED" in text or "429" in text:
        msg = "Today's free database limit was reached. It resets tomorrow."
    elif "Firebase key" in text:
        msg = text
    return render_template("error.html", title="Something went wrong", message=msg), 500


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1", port=int(os.environ.get("PORT", 5000)))
