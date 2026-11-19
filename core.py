"""Telegram-dan asılı olmayan məntiq: Airtable, menyu keşi, səbət, sifariş. Ayrıca test olunur."""
import hashlib
import logging
import os
import re
import threading
import time

import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("restaurant_bot")

BOT_TOKEN = os.getenv("BOT_TOKEN")
AIRTABLE_TOKEN = os.getenv("AIRTABLE_TOKEN")
BASE_ID = os.getenv("AIRTABLE_BASE_ID")

# Hər restoran üçün ayrıca deploy: cədvəl ID-ləri env ilə dəyişir (standart: mövcud base)
MENU_TABLE_ID = os.getenv("MENU_TABLE_ID", "tbl3GmKrXkHxDNECy")
ORDERS_TABLE_ID = os.getenv("ORDERS_TABLE_ID", "tblcP7WslS0HQ5dxY")
ORDER_ITEMS_TABLE_ID = os.getenv("ORDER_ITEMS_TABLE_ID", "tblH6wh7lnPvxkJ5f")

RESTAURANT_NAME = os.getenv("RESTAURANT_NAME", "")
CURRENCY = os.getenv("CURRENCY", "AZN")


def _env_int(name):
    raw = (os.getenv(name) or "").strip()
    try:
        return int(raw) if raw else None
    except ValueError:
        return None


# Yeni sifarişlərin gedəcəyi Telegram chat/qrup ID-si (mətbəx/admin). Boşdursa bildiriş getmir.
ADMIN_CHAT_ID = _env_int("ADMIN_CHAT_ID")
# 1 olarsa, masada sifariş yalnız masadakı QR (t.me/bot?start=table_5) ilə mümkündür
REQUIRE_TABLE_QR = (os.getenv("REQUIRE_TABLE_QR") or "0").strip() == "1"
MENU_CACHE_TTL = int(os.getenv("MENU_CACHE_TTL", "60"))
REQUEST_TIMEOUT = 25
MAX_QTY_PER_ITEM = 20
MAX_ITEMS_IN_CART = 40
PAGE_SIZE = 20

AIRTABLE_API = f"https://api.airtable.com/v0/{BASE_ID}"


def validate_settings():
    missing = [n for n, v in (("BOT_TOKEN", BOT_TOKEN), ("AIRTABLE_TOKEN", AIRTABLE_TOKEN),
                              ("AIRTABLE_BASE_ID", BASE_ID)) if not v]
    if missing:
        raise ValueError(f"XƏTA: .env faylında {', '.join(missing)} olmalıdır!")


def _headers():
    return {"Authorization": f"Bearer {AIRTABLE_TOKEN}", "Content-Type": "application/json"}


# ------------------------------------------------------------------ Airtable
def airtable_request(method, url, **kwargs):
    """Vahid timeout, xəta loqu və 429/5xx üçün 2 təkrar. Uğursuzluqda None və ya (ok olmayan) cavab."""
    response = None
    for attempt in range(3):
        try:
            response = requests.request(method, url, headers=_headers(), timeout=REQUEST_TIMEOUT, **kwargs)
        except requests.RequestException:
            logger.exception("Airtable ilə əlaqə xətası (cəhd %s)", attempt + 1)
            response = None
        else:
            if response.ok:
                return response
            if response.status_code not in (429, 500, 502, 503, 504):
                break
            logger.warning("Airtable HTTP %s (cəhd %s)", response.status_code, attempt + 1)
        if attempt < 2:
            time.sleep(1.0 + attempt)
    if response is not None and not response.ok:
        logger.error("Airtable API xətası | %s | %s | %s", response.status_code, url, response.text[:300])
    return response


def _fetch_menu_from_airtable():
    """Aktiv menyu məhsulları. Xəta olarsa None (boş menyu ilə qarışmasın)."""
    url = f"{AIRTABLE_API}/{MENU_TABLE_ID}"
    params = {"pageSize": 100}
    items = []
    while True:
        response = airtable_request("GET", url, params=params)
        if response is None or not response.ok:
            return None
        data = response.json()
        for record in data.get("records", []):
            fields = record.get("fields", {})
            name = fields.get("Name")
            if not name or not fields.get("Available", False):
                continue
            try:
                price = float(fields.get("Price", 0) or 0)
            except (TypeError, ValueError):
                logger.warning("Məhsul qiyməti düzgün deyil: %s", name)
                continue
            items.append({
                "id": record["id"],
                "name": str(name),
                "category": str(fields.get("Category") or "Ümumi"),
                "price": price,
            })
        offset = data.get("offset")
        if not offset:
            return items
        params = {"pageSize": 100, "offset": offset}


_menu_lock = threading.Lock()
_menu_cache = {"items": None, "ts": 0.0}


def get_menu(force=False):
    """Keşlənmiş menyu (TTL saniyə). Airtable düşərsə köhnə keş qaytarılır, yoxdursa []."""
    now = time.monotonic()
    with _menu_lock:
        fresh = _menu_cache["items"] is not None and now - _menu_cache["ts"] < MENU_CACHE_TTL
        if fresh and not force:
            return list(_menu_cache["items"])
        items = _fetch_menu_from_airtable()
        if items is None:
            logger.error("Menyu yenilənmədi; %s", "köhnə keş istifadə olunur" if _menu_cache["items"] else "keş yoxdur")
            return list(_menu_cache["items"] or [])
        _menu_cache["items"], _menu_cache["ts"] = items, now
        return list(items)


def reset_menu_cache():
    with _menu_lock:
        _menu_cache["items"], _menu_cache["ts"] = None, 0.0


def cat_id(category):
    """callback_data üçün qısa, sabit ID (Telegram limiti 64 bayt; Azərbaycan hərfləri 2 bayt tutur)."""
    return hashlib.md5(category.encode("utf-8")).hexdigest()[:8]


def categories(menu):
    return sorted({i["category"] for i in menu})


def items_for_category(menu, cid):
    if cid == "all":
        return list(menu)
    return [i for i in menu if cat_id(i["category"]) == cid]


def paginate(items, page, size=PAGE_SIZE):
    pages = max(1, -(-len(items) // size))
    page = min(max(page, 0), pages - 1)
    return items[page * size:(page + 1) * size], page, pages


# ------------------------------------------------------------------ səbət
def cart_total(cart):
    return sum(float(i["price"]) * int(i.get("quantity", 1)) for i in cart)


def cart_summary(cart):
    return ", ".join(f"{i['name']} x{i.get('quantity', 1)}" for i in cart)


def add_to_cart(cart, item):
    """('ok'|'max_qty'|'cart_full') qaytarır."""
    existing = next((x for x in cart if x["id"] == item["id"]), None)
    if existing:
        if existing.get("quantity", 1) >= MAX_QTY_PER_ITEM:
            return "max_qty"
        existing["quantity"] = existing.get("quantity", 1) + 1
        return "ok"
    if len(cart) >= MAX_ITEMS_IN_CART:
        return "cart_full"
    cart.append({**item, "quantity": 1})
    return "ok"


def reconcile_cart(cart, menu):
    """Sifarişdən əvvəl səbəti cari menyu ilə üzləşdirir: qiymətləri yeniləyir, aktiv olmayanları çıxarır.
    (yeni_səbət, mesajlar) qaytarır."""
    by_id = {i["id"]: i for i in menu}
    new, notes = [], []
    for line in cart:
        cur = by_id.get(line["id"])
        if cur is None:
            notes.append(f"❌ «{line['name']}» artıq mövcud deyil və sifarişdən çıxarıldı.")
            continue
        if abs(cur["price"] - float(line["price"])) > 0.005:
            notes.append(f"💱 «{cur['name']}» qiyməti dəyişib: {float(line['price']):.2f} → {cur['price']:.2f} {CURRENCY}.")
        new.append({**cur, "quantity": int(line.get("quantity", 1))})
    return new, notes


# ------------------------------------------------------------------ yoxlamalar
def valid_phone(text):
    text = (text or "").strip()
    digits = re.sub(r"\D", "", text)
    return bool(re.fullmatch(r"[+\d\s()\-]{7,20}", text)) and 7 <= len(digits) <= 15


def parse_table_payload(payload):
    """/start table_5 → 5; yanlışdırsa None."""
    m = re.fullmatch(r"table_(\d{1,3})", (payload or "").strip())
    return int(m.group(1)) if m else None


# ------------------------------------------------------------------ sifariş
def submit_order(order_type, customer_name, phone, table_number, delivery_address, cart):
    """Orders sətri + Order Items sətirləri. Items uğursuz olarsa Orders sətri silinir (yarımçıq/dublikat qalmasın).
    (ok, order_id) qaytarır."""
    if not cart:
        logger.error("Boş səbətlə sifariş göndərilə bilməz.")
        return False, None

    order_fields = {"Order Type": order_type, "Customer Name": customer_name, "Phone": phone, "Status": "Yeni"}
    if table_number is not None:
        order_fields["Table Number"] = int(table_number)
    if delivery_address:
        order_fields["Delivery Address"] = delivery_address

    resp = airtable_request("POST", f"{AIRTABLE_API}/{ORDERS_TABLE_ID}", json={"fields": order_fields})
    if resp is None or not resp.ok:
        return False, None
    order_id = resp.json().get("id")
    if not order_id:
        logger.error("Airtable sifariş ID-si qaytarmadı")
        return False, None

    lines = []
    for item in cart:
        qty = int(item.get("quantity", 1))
        if qty >= 1:
            lines.append({"fields": {"Order": [order_id], "Menu Item": [item["id"]], "Quantity": qty}})

    for start in range(0, len(lines), 10):          # Airtable: sorğuda maks. 10 record
        r = airtable_request("POST", f"{AIRTABLE_API}/{ORDER_ITEMS_TABLE_ID}", json={"records": lines[start:start + 10]})
        if r is None or not r.ok:
            logger.error("Order Items yazılmadı (sifariş %s); sifariş sətri silinir.", order_id)
            _rollback_order(order_id)
            return False, None

    logger.info("Sifariş Airtable-a yazıldı. Order ID: %s", order_id)
    return True, order_id


def _rollback_order(order_id):
    r = airtable_request("DELETE", f"{AIRTABLE_API}/{ORDERS_TABLE_ID}/{order_id}")
    if r is None or not r.ok:
        logger.error("Yarımçıq sifariş %s silinmədi, Airtable-da əl ilə yoxlayın.", order_id)


def admin_message(order_type, customer_name, phone, table_number, address, cart, order_id=None):
    head = "🆕 Yeni sifariş"
    lines = [head + (f" #{order_id[-5:]}" if order_id else ""), f"Növ: {order_type}"]
    if table_number is not None:
        lines.append(f"📍 Masa: {table_number}")
    lines.append(f"👤 {customer_name}")
    if phone and phone != "-":
        lines.append(f"📞 {phone}")
    if address:
        lines.append(f"🏠 {address}")
    lines.append("")
    lines += [f"• {i['name']} × {i.get('quantity', 1)}" for i in cart]
    lines.append(f"\n💰 {cart_total(cart):.2f} {CURRENCY}")
    return "\n".join(lines)
