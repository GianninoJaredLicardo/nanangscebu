"""All database code. Uses Firebase Cloud Firestore through the Firebase Admin SDK.

Collections:
  products/{id}   name, category, srp, reseller, dealer, stock, lowStock, createdAt, updatedAt
  sales/{id}      orderNo, buyer, contact, tier, items[], packs, subtotal, discount, total,
                  payMethod, amountPaid, change, note, status, createdAt, voidedAt
  stockLogs/{id}  productId, name, type (sale|in|adjust|void|opening), change, before, after,
                  note, saleId, orderNo, createdAt
"""
import json
import os
from datetime import datetime, timezone

import firebase_admin
from firebase_admin import credentials, firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from pricing import SaleError, build_sale


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


class FirestoreStore:
    def __init__(self):
        if not firebase_admin._apps:
            firebase_admin.initialize_app(_credentials())
        self.db = firestore.client()
        self.products = self.db.collection("products")
        self.sales = self.db.collection("sales")
        self.logs = self.db.collection("stockLogs")

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

    # ---------------- sales ----------------
    def create_sale(self, req, settings, order_no):
        """Check stock, save the sale and deduct stock, all at once (or nothing)."""
        refs = [self.products.document(pid) for pid in req["qty_by_id"]]
        sale_ref = self.sales.document()

        @firestore.transactional
        def run(tx):
            snaps = [r.get(transaction=tx) for r in refs]
            products = {s.id: _doc(s) for s in snaps if s.exists}
            sale = build_sale(products, req, settings, _now(), order_no)
            tx.set(sale_ref, sale)
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
        }


__all__ = ["FirestoreStore", "StoreError", "SaleError"]
