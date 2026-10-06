"""Nanang's Authentic Recipes Mandaue - Cebu Distributor, Inventory and Sales, a Flask app with a Firebase Firestore database."""
import calendar
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
from werkzeug.security import check_password_hash

try:  # load .env when running on your own computer
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from markupsafe import Markup, escape
from pricing import (PAID_METHODS, PAY_LABEL, PAY_METHODS, TIER_LABEL, TO_COLLECT, SaleError, build_draft, cap_first,
                     cap_words, clean_request)

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
LOG_LABEL = {"sale": "Sold", "in": "Stock In", "out": "Stock Out", "adjust": "Adjustment", "void": "Voided Order",
             "opening": "Opening Stock"}
STOCK_OUT_REASONS = ("Spoiled", "Expired", "Damaged", "Free / Sample", "Other")
BACKUP_REMIND_DAYS = 7

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
    # HTTPS-only cookie when hosted (Railway or Render set these); plain http on your own computer
    SESSION_COOKIE_SECURE=bool(os.environ.get("RAILWAY_ENVIRONMENT") or os.environ.get("RAILWAY_ENVIRONMENT_NAME")
                               or os.environ.get("RENDER")),
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


app.add_template_filter(cap_words, "cap_words")  # names and addresses saved before capitals were fixed
app.add_template_filter(cap_first, "cap_first")  # notes


@app.template_filter("pay")
def _pay(method):
    return PAY_LABEL.get(method, method)


@app.template_filter("peso_short")
def _peso_short(n):
    """Short amounts for small calendar boxes: ₱850, ₱12.3k, ₱1.2M."""
    n = float(n or 0)
    if n < 1000:
        return peso(n)
    if n < 1_000_000:
        return f"₱{n / 1000:.1f}".rstrip("0").rstrip(".") + "k"
    return f"₱{n / 1_000_000:.1f}".rstrip("0").rstrip(".") + "M"


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
    PAID_METHODS=PAID_METHODS, TO_COLLECT=TO_COLLECT,
)


# ------------------------------------------------------------------
# Security: login, CSRF, login rate limit
# ------------------------------------------------------------------
ADMIN_USERNAME = "nanangsadmin"
# Only the hash lives in the environment (Railway Variables or .env), never the password itself.
# Make one with: python make_password.py
ADMIN_PASSWORD_HASH = os.environ.get("ADMIN_PASSWORD_HASH", "").strip()
if not ADMIN_PASSWORD_HASH:
    print("WARNING: ADMIN_PASSWORD_HASH is not set. Nobody can sign in until you set it (see make_password.py).")

LOGIN_MAX_FAILS = 5
LOGIN_LOCK_SECONDS = 15 * 60
_login_fails = {}  # ip -> [fail count, time of first fail]
_login_lock = threading.Lock()


def login_blocked(ip):
    with _login_lock:
        n, since = _login_fails.get(ip, (0, 0))
        if n and time.time() - since > LOGIN_LOCK_SECONDS:
            _login_fails.pop(ip, None)
            return False
        return n >= LOGIN_MAX_FAILS


def login_failed(ip):
    with _login_lock:
        n, since = _login_fails.get(ip, (0, time.time()))
        _login_fails[ip] = (n + 1, since)


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


app.jinja_env.globals["csrf_token"] = csrf_token


def password_ok(pw):
    if not ADMIN_PASSWORD_HASH:
        return False
    try:
        return check_password_hash(ADMIN_PASSWORD_HASH, pw)
    except ValueError:  # not a valid hash
        return False


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
        ip = request.remote_addr or ""
        if not ADMIN_PASSWORD_HASH:
            return render_template("login.html", error="Sign-in is not set up yet: ADMIN_PASSWORD_HASH is missing.")
        if login_blocked(ip):
            return render_template("login.html", error="Too many wrong tries. Wait 15 minutes and try again."), 429
        if hmac.compare_digest(user.encode(), ADMIN_USERNAME.encode()) and password_ok(pw):
            with _login_lock:
                _login_fails.pop(ip, None)
            session.clear()
            session.permanent = True
            session["admin"] = True
            csrf_token()
            nxt = request.args.get("next") or ""
            return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("dashboard"))
        login_failed(ip)
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
    unpaid = db().to_collect()
    collect = {"total": sum(s.get("total") or 0 for s in unpaid), "orders": len(unpaid)}
    last = to_ph(db().last_backup())
    backup_days = (now_ph() - last).days if last else None
    backup_due = bool(products) and (backup_days is None or backup_days >= BACKUP_REMIND_DAYS)
    return render_template("dashboard.html", products=products, sales=sales, low=low, stats=stats, collect=collect,
                           backup_days=backup_days, backup_due=backup_due,
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
    customers = sorted(db().list_customers(), key=lambda c: to_ph(c.get("lastOrderAt")) or datetime.min.replace(tzinfo=PH),
                       reverse=True)
    customers = [{"name": cap_words(c.get("name", "")), "contact": c.get("contact", ""),
                  "address": cap_words(c.get("address", ""))}
                 for c in customers[:1000] if c.get("name")]
    return render_template("order.html", products=data, cats=categories(products), customers=customers)


@app.route("/draft")
def draft():
    products = sort_products(db().list_products())
    data = [{"id": p["id"], "name": p["name"], "category": p.get("category", ""),
             "srp": p.get("srp") or 0, "reseller": p.get("reseller") or 0,
             "dealer": p.get("dealer") or 0} for p in products]
    saved = None
    did = request.args.get("id", "").strip()
    if did:
        d = db().get_draft(did)
        if not d:
            flash("That draft no longer exists.", "error")
            return redirect(url_for("drafts"))
        # Reopened drafts use today's prices; the saved total is shown so changes are easy to spot.
        saved = {"id": d["id"], "items": [[i["productId"], i["qty"]] for i in d.get("items") or []],
                 "tierMode": d.get("tier", "srp"), "customer": d.get("customer", ""), "contact": d.get("contact", ""),
                 "address": d.get("address", ""), "note": d.get("note", ""), "discount": d.get("discount") or 0,
                 "total": d.get("total") or 0, "savedAt": _dt(d.get("updatedAt"))}
    customers = sorted(db().list_customers(), key=lambda c: to_ph(c.get("lastOrderAt")) or datetime.min.replace(tzinfo=PH),
                       reverse=True)
    customers = [{"name": cap_words(c.get("name", "")), "contact": c.get("contact", ""),
                  "address": cap_words(c.get("address", ""))}
                 for c in customers[:1000] if c.get("name")]
    return render_template("draft.html", products=data, cats=categories(products), today=date_key(), saved=saved,
                           customers=customers)


@app.route("/api/draft", methods=["POST"])
def api_draft():
    data = request.get_json(silent=True)
    try:
        products = {p["id"]: p for p in db().list_products()}
        draft_data = build_draft(data, products)
        did = db().save_draft(draft_data, str(data.get("id") or "").strip() or None)
    except user_error_types() as e:
        return jsonify(error=str(e)), 400
    return jsonify(id=did, url=url_for("draft", id=did))


@app.route("/drafts")
def drafts():
    return render_template("drafts.html", drafts=db().recent_drafts(300))


@app.route("/drafts/<did>/delete", methods=["POST"])
def draft_delete(did):
    db().delete_draft(did)
    flash("Draft deleted.")
    return redirect(url_for("drafts"))


def order_day_prefix():
    """Orders are numbered per day in Philippine time: YYMMDD-001, YYMMDD-002, ..."""
    return now_ph().strftime("%y%m%d")


@app.route("/api/sale", methods=["POST"])
def api_sale():
    try:
        req = clean_request(request.get_json(silent=True))
        sid = db().create_sale(req, SETTINGS, order_day_prefix())
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
        "name": cap_words(" ".join(f.get("name", "").split()))[:150],
        "category": cap_words(" ".join(f.get("category", "").split()))[:60],
        "srp": money("srp", "SRP"),
        "reseller": money("reseller", "Reseller"),
        "dealer": money("dealer", "Dealer"),
        "cost": None,
        "stock": whole("stock", "stock"),
        "lowStock": whole("lowStock", "low-stock alert", SETTINGS["low_stock"]),
    }
    if f.get("cost", "").strip():
        data["cost"] = money("cost", "cost")
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
                db().update_product(pid, data, cap_first(request.form.get("reason", "").strip())[:200])
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
    flash(f"Loaded {n} products. Now add your stock in Stock In." if n else "All products are already loaded.")
    return redirect(url_for("products"))


@app.route("/products/sync", methods=["POST"])
def product_sync():
    """Apply the prices in products.json to the products already loaded. Stock and cost don't change."""
    with open(os.path.join(BASE, "products.json"), encoding="utf-8") as fh:
        items = json.load(fh)
    added, updated, not_on_list = db().sync_price_list(items, SETTINGS["low_stock"])
    msg = f"Price list applied: {updated} products updated, {added} new products added."
    if not_on_list:
        msg += " Not on the new list (left as is): " + ", ".join(not_on_list) + "."
    flash(msg)
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
    rows = [["Product", "Category", "SRP", "Reseller", "Dealer", "Your cost", "Stock", "Low-stock level",
             "Stock value (dealer)"]]
    for p in sort_products(db().list_products()):
        s = p.get("stock") or 0
        rows.append([p["name"], p.get("category"), p.get("srp"), p.get("reseller"), p.get("dealer"), p.get("cost"), s,
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
    db().note_backup()
    return Response(json.dumps(data, ensure_ascii=False, indent=1), mimetype="application/json",
                    headers={"Content-Disposition": f'attachment; filename="backup-{date_key()}.json"'})


# ------------------------------------------------------------------
# Stock in
# ------------------------------------------------------------------
def stock_page(mode):
    """mode "in": deliveries. mode "out": spoiled, expired, damaged or free packs."""
    if request.method == "POST":
        pid = request.form.get("product", "")
        note = cap_first(request.form.get("note", "").strip())[:200]
        reason = request.form.get("reason", "")
        try:
            qty = int(request.form.get("qty", 0))
        except ValueError:
            qty = 0
        if not pid:
            flash("Choose a product.", "error")
        elif qty <= 0:
            flash("Enter how many packs.", "error")
        elif mode == "out" and reason not in STOCK_OUT_REASONS:
            flash("Choose a reason.", "error")
        else:
            try:
                if mode == "in":
                    name = db().restock(pid, qty, note)
                    flash(f"Added {qty} × {name}.")
                else:
                    name = db().stock_out(pid, qty, f"{reason}, {note[:1].lower() + note[1:]}" if note else reason)
                    flash(f"Removed {qty} × {name} ({reason.lower()}).")
            except user_error_types() as e:
                flash(str(e), "error")
        return redirect(url_for(request.endpoint, note=note if mode == "in" else None))
    products = sort_products(db().list_products())
    types = ("in", "opening") if mode == "in" else ("out",)
    today_logs = [l for l in db().logs_since(day_start(date_key())) if l.get("type") in types]
    return render_template("restock.html", mode=mode, products=products, cats=categories(products),
                           today_logs=today_logs, reasons=STOCK_OUT_REASONS,
                           selected=request.args.get("product", ""), note=request.args.get("note", ""))


@app.route("/restock", methods=["GET", "POST"])
def restock():
    return stock_page("in")


@app.route("/stock-out", methods=["GET", "POST"])
def stock_out():
    return stock_page("out")


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


def summarize(rows):
    """Totals, best sellers and profit for a list of sales.
    Profit uses the cost saved on each sale, or the product's current cost for older sales.
    Items with no cost at all are left out of profit (and counted in missing_cost)."""
    done = [s for s in rows if s.get("status") != "voided"]
    costs = {p["id"]: p.get("cost") for p in db().list_products()} if done else {}
    agg, profit, missing = {}, 0, set()
    for s in done:
        sub = s.get("subtotal") or 0
        factor = (s.get("total") or 0) / sub if sub else 1  # spread the discount over the items
        for i in s["items"]:
            a = agg.setdefault(i["productId"], {"name": i["name"], "qty": 0, "amount": 0, "profit": 0, "costed": True})
            a["qty"] += i["qty"]
            a["amount"] += i["subtotal"]
            cost = i.get("cost")
            if cost is None:
                cost = costs.get(i["productId"])
            if cost is None:
                a["costed"] = False
                missing.add(i["productId"])
                continue
            p = i["subtotal"] * factor - cost * i["qty"]
            a["profit"] += p
            profit += p
    total = sum(s["total"] for s in done)
    stats = {"total": total, "orders": len(done), "voided": len(rows) - len(done),
             "packs": sum(s["packs"] for s in done), "avg": round(total / len(done)) if done else 0,
             "profit": round(profit, 2), "missing_cost": len(missing), "has_cost": len(missing) < len(agg)}
    return stats, sorted(agg.values(), key=lambda a: -a["qty"])


@app.route("/sales")
def sales():
    f, to, rng = sales_range()
    rows = db().sales_between(day_start(f), day_start(to) + timedelta(days=1))
    stats, items = summarize(rows)
    return render_template("sales.html", rows=rows, stats=stats, items=items, f=f, to=to, rng=rng, multi_day=f != to)


@app.route("/sales/print")
def sales_print():
    f, to, rng = sales_range()
    rows = db().sales_between(day_start(f), day_start(to) + timedelta(days=1))
    stats, items = summarize(rows)
    return render_template("sales_print.html", rows=rows, stats=stats, items=items,
                           f=f, to=to, rng=rng, multi_day=f != to, today=date_key())


@app.route("/calendar")
def sales_calendar():
    """Month calendar with each day's sales. Click a day to see what was sold."""
    today = date_key()
    try:
        first = datetime.strptime(request.args.get("month", "") + "-01", "%Y-%m-%d").date()
    except ValueError:
        first = day_start(today).date().replace(day=1)
    nxt = (first.replace(day=28) + timedelta(days=4)).replace(day=1)
    prev = (first - timedelta(days=1)).replace(day=1)
    month = first.strftime("%Y-%m")

    rows = db().sales_between(day_start(first.isoformat()), day_start(nxt.isoformat()))
    by_day = {}
    for s in rows:
        by_day.setdefault(date_key(to_ph(s["createdAt"])), []).append(s)
    days = {}
    for key, ss in by_day.items():
        done = [s for s in ss if s.get("status") != "voided"]
        days[key] = {"total": sum(s["total"] for s in done), "orders": len(done),
                     "packs": sum(s["packs"] for s in done)}
    top = max((d["total"] for d in days.values()), default=0)
    for d in days.values():  # shade busier days darker
        d["level"] = 0 if not d["total"] else 1 + min(int(d["total"] / top * 3), 2) if top else 0

    selected = valid_key(request.args.get("day"))
    if not selected or not selected.startswith(month):
        selected = today if today.startswith(month) else None
    day = None
    if selected:
        day_rows = by_day.get(selected, [])
        stats, items = summarize(day_rows)
        d = day_start(selected)
        day = {"key": selected, "label": f"{d:%A, %B} {d.day}, {d.year}", "rows": day_rows, "stats": stats,
               "sold": items}

    weeks = [[{"key": dt.isoformat(), "num": dt.day, "in_month": dt.month == first.month,
               **days.get(dt.isoformat(), {"total": 0, "orders": 0, "level": 0})}
              for dt in week] for week in calendar.Calendar(firstweekday=6).monthdatescalendar(first.year, first.month)]
    month_stats = {"total": sum(d["total"] for d in days.values()), "orders": sum(d["orders"] for d in days.values()),
                   "packs": sum(d["packs"] for d in days.values()), "days": sum(1 for d in days.values() if d["orders"])}
    best = max(days.items(), key=lambda kv: kv[1]["total"], default=None)
    return render_template("calendar.html", weeks=weeks, month=month, month_label=f"{first:%B %Y}",
                           prev=prev.strftime("%Y-%m"), next=nxt.strftime("%Y-%m"), today=today,
                           this_month=today[:7], selected=selected, day=day, month_stats=month_stats,
                           best=best if best and best[1]["total"] else None)


@app.route("/sales/export.csv")
def sales_export():
    f, to, _ = sales_range()
    rows = [["Date", "Time", "Order no.", "Buyer", "Contact", "Price level", "Product", "Qty", "Price", "Amount",
             "Your cost", "Order subtotal", "Discount", "Order total", "Payment", "Status", "Note"]]
    for s in reversed(db().sales_between(day_start(f), day_start(to) + timedelta(days=1))):
        d = to_ph(s.get("createdAt"))
        for n, i in enumerate(s["items"]):
            first = n == 0
            rows.append([d.strftime("%Y-%m-%d") if d else "", d.strftime("%I:%M %p") if d else "", s["orderNo"],
                         cap_words(s["buyer"]), s.get("contact"), TIER_LABEL.get(s["tier"]), i["name"], i["qty"], i["price"],
                         i["subtotal"], i.get("cost"), s["subtotal"] if first else "", s["discount"] if first else "",
                         s["total"] if first else "", s["payMethod"], s["status"], s.get("note")])
    return csv_response(f"sales-{f}_to_{to}.csv", rows)


@app.route("/sales/<sid>")
def receipt(sid):
    s = db().get_sale(sid)
    if not s:
        abort(404)
    return render_template("receipt.html", s=s, new=request.args.get("new"))


@app.route("/sales/<sid>/paid", methods=["POST"])
def mark_paid(sid):
    try:
        method = request.form.get("method", "")
        db().mark_paid(sid, method)
        flash(f"Marked as paid ({PAY_LABEL.get(method, method)}).")
    except user_error_types() as e:
        flash(str(e), "error")
    back = request.form.get("back")
    return redirect(url_for("balances") if back == "balances" else url_for("receipt", sid=sid))


@app.route("/balances")
def balances():
    rows = db().to_collect()
    by_buyer = {}
    for s in rows:
        b = by_buyer.setdefault(" ".join(s["buyer"].lower().split()),
                                {"name": cap_words(s["buyer"]), "contact": s.get("contact"), "total": 0, "orders": 0})
        b["total"] += s.get("total") or 0
        b["orders"] += 1
    return render_template("balances.html", rows=rows, total=sum(s.get("total") or 0 for s in rows),
                           buyers=sorted(by_buyer.values(), key=lambda b: -b["total"]), now=now_ph())


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
