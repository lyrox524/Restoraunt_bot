import core
import pytest


class Resp:
    def __init__(self, status=200, body=None, text=""):
        self.status_code, self._body, self.text = status, body or {}, text
        self.ok = 200 <= status < 300

    def json(self):
        return self._body


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    core.reset_menu_cache()
    monkeypatch.setattr(core.time, "sleep", lambda s: None)
    yield
    core.reset_menu_cache()


def item(i="rec1", price=5.0, cat="Yemək", name="Plov"):
    return {"id": i, "name": name, "category": cat, "price": price}


# ---------------------------------------------------------------- Airtable sorğu
def test_request_retries_on_429_then_succeeds(monkeypatch):
    seq = iter([Resp(429), Resp(503), Resp(200)])
    monkeypatch.setattr(core.requests, "request", lambda *a, **k: next(seq))
    assert core.airtable_request("GET", "u").ok


def test_request_does_not_retry_on_400(monkeypatch):
    calls = []
    monkeypatch.setattr(core.requests, "request", lambda *a, **k: calls.append(1) or Resp(400, text="bad"))
    assert not core.airtable_request("GET", "u").ok
    assert len(calls) == 1


def test_request_returns_none_after_network_errors(monkeypatch):
    def boom(*a, **k):
        raise core.requests.ConnectionError("x")
    monkeypatch.setattr(core.requests, "request", boom)
    assert core.airtable_request("GET", "u") is None


# ---------------------------------------------------------------- menyu
def test_fetch_menu_paginates_and_filters(monkeypatch):
    pages = iter([
        Resp(200, {"records": [{"id": "a", "fields": {"Name": "A", "Available": True, "Price": 2, "Category": "X"}},
                               {"id": "b", "fields": {"Name": "B", "Available": False, "Price": 3}}], "offset": "o1"}),
        Resp(200, {"records": [{"id": "c", "fields": {"Name": "C", "Available": True, "Price": "bad"}},
                               {"id": "d", "fields": {"Name": "D", "Available": True, "Price": 4}}]}),
    ])
    seen = []
    monkeypatch.setattr(core.requests, "request", lambda m, u, **k: seen.append(k.get("params")) or next(pages))
    menu = core._fetch_menu_from_airtable()
    assert [i["id"] for i in menu] == ["a", "d"]               # B aktiv deyil, C qiyməti pozuq
    assert menu[1]["category"] == "Ümumi"
    assert seen[1]["offset"] == "o1"


def test_fetch_menu_failure_is_none_not_empty(monkeypatch):
    monkeypatch.setattr(core.requests, "request", lambda *a, **k: Resp(500))
    assert core._fetch_menu_from_airtable() is None


def test_get_menu_is_cached_and_falls_back_to_stale(monkeypatch):
    calls = []
    results = iter([[item()], None])
    monkeypatch.setattr(core, "_fetch_menu_from_airtable", lambda: calls.append(1) or next(results))
    assert core.get_menu()[0]["id"] == "rec1"
    core.get_menu()
    assert len(calls) == 1                                       # TTL daxilində yenidən sorğu yoxdur
    assert core.get_menu(force=True)[0]["id"] == "rec1"          # Airtable düşdü: köhnə keş
    assert len(calls) == 2


def test_get_menu_empty_when_no_cache_and_failure(monkeypatch):
    monkeypatch.setattr(core, "_fetch_menu_from_airtable", lambda: None)
    assert core.get_menu() == []


def test_cat_id_short_stable_and_ascii():
    c = core.cat_id("Şirniyyatlar və içkilər " * 5)
    assert c == core.cat_id("Şirniyyatlar və içkilər " * 5) and len(c) == 8
    assert len(f"items:{c}:12".encode()) < 64


def test_items_for_category_and_paginate():
    menu = [item(f"r{i}", cat="A" if i % 2 else "B") for i in range(45)]
    assert len(core.items_for_category(menu, "all")) == 45
    assert len(core.items_for_category(menu, core.cat_id("A"))) == 22
    chunk, page, pages = core.paginate(menu, 2)
    assert (len(chunk), page, pages) == (5, 2, 3)
    assert core.paginate(menu, 99)[1] == 2 and core.paginate(menu, -5)[1] == 0
    assert core.paginate([], 0) == ([], 0, 1)


# ---------------------------------------------------------------- səbət
def test_add_to_cart_limits():
    cart = []
    assert core.add_to_cart(cart, item()) == "ok" and cart[0]["quantity"] == 1
    for _ in range(core.MAX_QTY_PER_ITEM - 1):
        assert core.add_to_cart(cart, item()) == "ok"
    assert core.add_to_cart(cart, item()) == "max_qty"
    full = [item(f"r{i}") for i in range(core.MAX_ITEMS_IN_CART)]
    assert core.add_to_cart(full, item("new")) == "cart_full"


def test_cart_total_and_summary():
    cart = [{**item(), "quantity": 2}, {**item("r2", 3.5, name="Çay"), "quantity": 1}]
    assert core.cart_total(cart) == 13.5
    assert core.cart_summary(cart) == "Plov x2, Çay x1"


def test_reconcile_updates_price_and_removes_inactive():
    cart = [{**item("a", 5.0), "quantity": 2}, {**item("gone", 1.0, name="Köhnə"), "quantity": 1}]
    new, notes = core.reconcile_cart(cart, [item("a", 6.0)])
    assert [i["id"] for i in new] == ["a"] and new[0]["price"] == 6.0 and new[0]["quantity"] == 2
    assert len(notes) == 2 and "6.00" in notes[0] + notes[1] and "Köhnə" in notes[0] + notes[1]


def test_reconcile_no_changes_no_notes():
    new, notes = core.reconcile_cart([{**item("a", 5.0), "quantity": 1}], [item("a", 5.0)])
    assert notes == [] and len(new) == 1


# ---------------------------------------------------------------- yoxlamalar
@pytest.mark.parametrize("p,ok", [("+994501234567", True), ("050 123 45 67", True), ("(012) 555-11-22", True),
                                  ("12345", False), ("abcdefgh", False), ("", False), (None, False),
                                  ("+" + "9" * 30, False), ("050-1234; DROP", False)])
def test_valid_phone(p, ok):
    assert core.valid_phone(p) is ok


@pytest.mark.parametrize("p,exp", [("table_5", 5), ("table_12", 12), ("table_", None), ("x", None), (None, None),
                                   ("table_5; x", None), ("table_1234", None)])
def test_parse_table_payload(p, exp):
    assert core.parse_table_payload(p) == exp


# ---------------------------------------------------------------- sifariş
def test_submit_order_writes_order_and_batches_items(monkeypatch):
    calls = []

    def fake(method, url, **kw):
        calls.append((method, url, kw))
        return Resp(200, {"id": "recORD"})
    monkeypatch.setattr(core, "airtable_request", fake)
    cart = [{**item(f"r{i}"), "quantity": 2} for i in range(25)]
    ok, oid = core.submit_order("Çatdırılma", "Əli", "+994501234567", None, "Bakı, X küç. 1", cart)
    assert ok and oid == "recORD"
    assert len(calls) == 1 + 3                                   # 1 order + 3 batch (10+10+5)
    f = calls[0][2]["json"]["fields"]
    assert f["Status"] == "Yeni" and f["Delivery Address"] and "Table Number" not in f
    assert [len(c[2]["json"]["records"]) for c in calls[1:]] == [10, 10, 5]
    assert calls[1][2]["json"]["records"][0]["fields"] == {"Order": ["recORD"], "Menu Item": ["r0"], "Quantity": 2}


def test_submit_order_table_number(monkeypatch):
    calls = []
    monkeypatch.setattr(core, "airtable_request", lambda m, u, **k: calls.append(k) or Resp(200, {"id": "r"}))
    core.submit_order("Masada", "A", "-", 7, None, [{**item(), "quantity": 1}])
    assert calls[0]["json"]["fields"]["Table Number"] == 7


def test_submit_order_rolls_back_when_items_fail(monkeypatch):
    log = []

    def fake(method, url, **kw):
        log.append(method)
        if method == "POST" and url.endswith(core.ORDERS_TABLE_ID):
            return Resp(200, {"id": "recX"})
        if method == "POST":
            return Resp(422)
        return Resp(200)                                         # DELETE
    monkeypatch.setattr(core, "airtable_request", fake)
    ok, oid = core.submit_order("Masada", "A", "-", 3, None, [{**item(), "quantity": 1}])
    assert (ok, oid) == (False, None)
    assert log == ["POST", "POST", "DELETE"]


def test_submit_order_fails_cleanly_when_order_create_fails(monkeypatch):
    monkeypatch.setattr(core, "airtable_request", lambda *a, **k: Resp(500))
    assert core.submit_order("Masada", "A", "-", 3, None, [{**item(), "quantity": 1}]) == (False, None)


def test_submit_order_rejects_empty_cart():
    assert core.submit_order("Masada", "A", "-", 3, None, []) == (False, None)


def test_admin_message_contents():
    cart = [{**item(), "quantity": 2}, {**item("r2", 3.0, name="Çay"), "quantity": 1}]
    t = core.admin_message("Masada", "Əli", "-", 5, None, cart, "recABCDE12345")
    assert "Masa: 5" in t and "Plov × 2" in t and "Çay × 1" in t and "13.00" in t and "#12345" in t
    assert "📞" not in t                                          # telefon "-" göstərilmir
    d = core.admin_message("Çatdırılma", "Əli", "+99450", None, "Bakı", cart)
    assert "+99450" in d and "Bakı" in d and "Masa" not in d
