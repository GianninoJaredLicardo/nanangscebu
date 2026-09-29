"""All database code. Uses Firebase Cloud Firestore through the Firebase Admin SDK.

Collections:
  products/{id}   name, category, srp, reseller, dealer, cost, stock, lowStock, createdAt, updatedAt
  sales/{id}      orderNo, buyer, contact, address, tier, items[], packs, subtotal, discount, total,
                  payMethod, amountPaid, change, note, status, createdAt, voidedAt, collectedAt
  stockLogs/{id}  productId, name, type (sale|in|out|adjust|void|opening), change, before, after,
                  note, saleId, orderNo, createdAt
  customers/{key} name, contact, address, orders, lastOrderAt (key = hash of the lowercased name)
  counters/{id}   orders-YYMMDD: {n} for daily order numbers
  meta/backup     lastAt: when a backup was last downloaded
"""
import hashlib
import json
import os
from datetime import datetime, timezone

import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from pricing import PAID_METHODS, TO_COLLECT, SaleError, build_sale


class StoreError(Exception):
    """A problem the user should see (e.g. product was deleted)."""


def _credentials():
    raw = os.environ.get("FIREBASE_CREDENTIALS", "").strip()
    if raw:
        return credentials.Certificate(json.loads(raw))
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.environ.get("FIREBASE_CREDENTIALS_FILE", "").strip() or "serviceAccountKey.json"
    if not os.path.isabs(path):
        path = os.path.join(here, path)  # look next to app.py, wherever you start it from
    if not os.path.exists(path):
        # Windows often hides ".json", so the file may really be "serviceAccountKey.json.json"
        if os.path.exists(path + ".json"):
            path = path + ".json"
        else:
            found = [f for f in os.listdir(here) if f.endswith(".json") and "firebase-adminsdk" in f]
            if found:
                path = os.path.join(here, found[0])
            else:
                raise RuntimeError(
                    f"Firebase key not found. Put serviceAccountKey.json in {here}, "
                    "or set FIREBASE_CREDENTIALS to the key's JSON text."
                )
    return credentials.Certificate(path)


def _now():
    return datetime.now(timezone.utc)


def _doc(snap):
    return {"id": snap.id, **(snap.to_dict() or {})}


def customer_key(name):
    """Same buyer name (ignoring case and extra spaces) -> same customer record."""
    norm = " ".join(str(name).lower().split())
    return hashlib.sha1(norm.encode("utf-8")).hexdigest()[:20]


class FirestoreStore:
    def __init__(self):
        if not firebase_admin._apps:
            firebase_admin.initialize_app(_credentials())
        self.db = firestore.client()
        self.products = self.db.collection("products")
        self.sales = self.db.collection("sales")
        self.logs = self.db.collection("stockLogs")
        self.customers = self.db.collection("customers")
        self.counters = self.db.collection("counters")
        self.meta = self.db.collection("meta")

    def _log(self, tx_or_batch, **fields):
        tx_or_batch.set(self.logs.document(), {"createdAt": _now(), **fields})

    # ---------------- products ----------------
    def list_products(self):
        return [_doc(s) for s in self.products.stream()]

    def get_product(self, pid):
        s = self.products.document(pid).get()
        return _doc(s) if s.exists else None

    def create_product(self, data):
        ref = self.products.document()
        batch = self.db.batch()
        now = _now()
        batch.set(ref, {**data, "createdAt": now, "updatedAt": now})
        if data["stock"] > 0:
            self._log(batch, productId=ref.id, name=data["name"], type="opening", change=data["stock"],
                      before=0, after=data["stock"], note="Starting stock")
        batch.commit()
        return ref.id

    def update_product(self, pid, data, reason=""):
        ref = self.products.document(pid)

        @firestore.transactional
        def run(tx):
            snap = ref.get(transaction=tx)
            if not snap.exists:
                raise StoreError("This product was deleted.")
            before = (snap.to_dict() or {}).get("stock") or 0
            tx.update(ref, {**data, "updatedAt": _now()})
            if data["stock"] != before:
                self._log(tx, productId=pid, name=data["name"], type="adjust", change=data["stock"] - before,
                          before=before, after=data["stock"], note=reason or "Stock corrected")

        run(self.db.transaction())

    def delete_product(self, pid):
        self.products.document(pid).delete()

    def seed_products(self, items, low_stock):
        existing = {s.id for s in self.products.select([]).stream()}
        batch = self.db.batch()
        now = _now()
        added = 0
        for p in items:
            if p["id"] in existing:
                continue
            batch.set(self.products.document(p["id"]), {
                "name": p["name"], "category": p["category"], "srp": p["srp"], "reseller": p["reseller"],
                "dealer": p["dealer"], "stock": 0, "lowStock": low_stock, "createdAt": now, "updatedAt": now,
            })
            added += 1
        if added:
            batch.commit()
        return added

    def restock(self, pid, qty, note):
        ref = self.products.document(pid)

        @firestore.transactional
        def run(tx):
            snap = ref.get(transaction=tx)
            if not snap.exists:
                raise StoreError("This product was deleted.")
            p = snap.to_dict()
            before = p.get("stock") or 0
            after = before + qty
            tx.update(ref, {"stock": after, "updatedAt": _now()})
            self._log(tx, productId=pid, name=p["name"], type="in", change=qty, before=before, after=after,
                      note=note or "Stock received")
            return p["name"]

        return run(self.db.transaction())

    def stock_out(self, pid, qty, note):
        """Remove spoiled, expired, damaged or free packs from stock."""
        ref = self.products.document(pid)

        @firestore.transactional
        def run(tx):
            snap = ref.get(transaction=tx)
            if not snap.exists:
                raise StoreError("This product was deleted.")
            p = snap.to_dict()
            before = p.get("stock") or 0
            if qty > before:
                raise StoreError(f"Only {before} {p['name']} in stock. You can't remove {qty}.")
            after = before - qty
            tx.update(ref, {"stock": after, "updatedAt": _now()})
            self._log(tx, productId=pid, name=p["name"], type="out", change=-qty, before=before, after=after,
                      note=note or "Stock Out")
            return p["name"]

        return run(self.db.transaction())

    # ---------------- sales ----------------
    def create_sale(self, req, settings, day_prefix):
        """Check stock, save the sale and deduct stock, all at once (or nothing).
        Order numbers count up each day: YYMMDD-001, YYMMDD-002, ..."""
        refs = [self.products.document(pid) for pid in req["qty_by_id"]]
        sale_ref = self.sales.document()
        counter_ref = self.counters.document(f"orders-{day_prefix}")
        cust_ref = self.customers.document(customer_key(req["buyer"]))

        @firestore.transactional
        def run(tx):
            snaps = [r.get(transaction=tx) for r in refs]
            counter = counter_ref.get(transaction=tx)
            products = {s.id: _doc(s) for s in snaps if s.exists}
            n = ((counter.to_dict() or {}).get("n") or 0) + 1 if counter.exists else 1
            order_no = f"{day_prefix}-{n:03d}"
            sale = build_sale(products, req, settings, _now(), order_no)
            tx.set(counter_ref, {"n": n})
            tx.set(sale_ref, sale)
            tx.set(cust_ref, {"name": sale["buyer"], "contact": sale["contact"], "address": sale["address"],
                              "lastOrderAt": sale["createdAt"], "orders": firestore.Increment(1)}, merge=True)
            for it in sale["items"]:
                before = products[it["productId"]].get("stock") or 0
                after = before - it["qty"]
                tx.update(self.products.document(it["productId"]), {"stock": after, "updatedAt": _now()})
                self._log(tx, productId=it["productId"], name=it["name"], type="sale", change=-it["qty"],
                          before=before, after=after, note=f"Order {order_no}, {sale['buyer']}",
                          saleId=sale_ref.id, orderNo=order_no)
            return sale_ref.id

        return run(self.db.transaction())

    def get_sale(self, sid):
        s = self.sales.document(sid).get()
        return _doc(s) if s.exists else None

    def void_sale(self, sid):
        sale_ref = self.sales.document(sid)

        @firestore.transactional
        def run(tx):
            ss = sale_ref.get(transaction=tx)
            if not ss.exists:
                raise StoreError("This order no longer exists.")
            sale = ss.to_dict()
            if sale.get("status") == "voided":
                raise StoreError("This order was already voided.")
            snaps = [self.products.document(i["productId"]).get(transaction=tx) for i in sale["items"]]
            for it, ps in zip(sale["items"], snaps):
                if not ps.exists:
                    continue  # product was deleted: nothing to return
                before = (ps.to_dict() or {}).get("stock") or 0
                after = before + it["qty"]
                tx.update(ps.reference, {"stock": after, "updatedAt": _now()})
                self._log(tx, productId=it["productId"], name=it["name"], type="void", change=it["qty"],
                          before=before, after=after, note=f"Voided order {sale['orderNo']}",
                          saleId=sid, orderNo=sale["orderNo"])
            tx.update(sale_ref, {"status": "voided", "voidedAt": _now()})

        run(self.db.transaction())

    def mark_paid(self, sid, method):
        """A "To collect" order was paid: record how and when."""
        if method not in PAID_METHODS:
            raise StoreError("Choose how the buyer paid.")
        sale_ref = self.sales.document(sid)

        @firestore.transactional
        def run(tx):
            ss = sale_ref.get(transaction=tx)
            if not ss.exists:
                raise StoreError("This order no longer exists.")
            sale = ss.to_dict() or {}
            if sale.get("status") == "voided":
                raise StoreError("This order was voided.")
            if sale.get("payMethod") != TO_COLLECT:
                raise StoreError("This order is already paid.")
            tx.update(sale_ref, {"payMethod": method, "collectedAt": _now()})

        run(self.db.transaction())

    def to_collect(self):
        """Unpaid orders (payment "To collect"), oldest first."""
        q = self.sales.where(filter=FieldFilter("payMethod", "==", TO_COLLECT))
        rows = [_doc(s) for s in q.stream()]
        rows = [s for s in rows if s.get("status") != "voided"]
        return sorted(rows, key=lambda s: s.get("createdAt") or _now())

    def delete_sale(self, sid):
        sale_ref = self.sales.document(sid)

        @firestore.transactional
        def run(tx):
            ss = sale_ref.get(transaction=tx)
            if not ss.exists:
                raise StoreError("This order no longer exists.")
            sale = ss.to_dict() or {}
            if sale.get("status") != "voided":
                raise StoreError("Only voided orders can be deleted.")
            tx.delete(sale_ref)

        run(self.db.transaction())

    def sales_between(self, start, end):
        q = (self.sales.where(filter=FieldFilter("createdAt", ">=", start))
             .where(filter=FieldFilter("createdAt", "<", end))
             .order_by("createdAt", direction=firestore.Query.DESCENDING))
        return [_doc(s) for s in q.stream()]

    # ---------------- customers ----------------
    def list_customers(self):
        rows = [_doc(s) for s in self.customers.stream()]
        if not rows:
            rows = self._backfill_customers()
        return rows

    def _backfill_customers(self):
        """First time only: build the customer list from past sales (newest details win)."""
        found = {}
        for s in self.sales.order_by("createdAt").stream():
            d = s.to_dict() or {}
            if not d.get("buyer"):
                continue
            k = customer_key(d["buyer"])
            c = found.setdefault(k, {"orders": 0})
            c.update(name=d["buyer"], contact=d.get("contact") or "", address=d.get("address") or "",
                     lastOrderAt=d.get("createdAt"))
            c["orders"] += 1
        items = list(found.items())
        for i in range(0, len(items), 400):
            batch = self.db.batch()
            for k, c in items[i:i + 400]:
                batch.set(self.customers.document(k), c)
            batch.commit()
        return [{"id": k, **c} for k, c in items]

    # ---------------- stock log ----------------
    def logs_since(self, start):
        q = self.logs.where(filter=FieldFilter("createdAt", ">=", start)).order_by(
            "createdAt", direction=firestore.Query.DESCENDING)
        return [_doc(s) for s in q.stream()]

    def recent_logs(self, limit=300):
        q = self.logs.order_by("createdAt", direction=firestore.Query.DESCENDING).limit(limit)
        return [_doc(s) for s in q.stream()]

    def delete_log(self, lid):
        self.logs.document(lid).delete()

    def clear_logs(self):
        """Delete every stock log entry (stock counts are not touched). Returns how many were removed."""
        total = 0
        while True:
            refs = [s.reference for s in self.logs.select([]).limit(400).stream()]
            if not refs:
                return total
            batch = self.db.batch()
            for ref in refs:
                batch.delete(ref)
            batch.commit()
            total += len(refs)

    # ---------------- backup ----------------
    def export_all(self):
        return {
            "products": [_doc(s) for s in self.products.stream()],
            "sales": [_doc(s) for s in self.sales.stream()],
            "stockLogs": [_doc(s) for s in self.logs.stream()],
            "customers": [_doc(s) for s in self.customers.stream()],
        }

    def note_backup(self):
        self.meta.document("backup").set({"lastAt": _now()})

    def last_backup(self):
        s = self.meta.document("backup").get()
        return (s.to_dict() or {}).get("lastAt") if s.exists else None


__all__ = ["FirestoreStore", "StoreError", "SaleError"]
