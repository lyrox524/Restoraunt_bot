import asyncio

import pytest

import bot
import core


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text):
        self.sent.append((chat_id, text))


class FakeMessage:
    def __init__(self, text=None, bot_=None):
        self.text, self.bot, self.answers, self.edits = text, bot_ or FakeBot(), [], []

    async def answer(self, text, reply_markup=None):
        self.answers.append(text)

    async def edit_text(self, text, reply_markup=None):
        self.edits.append((text, reply_markup))


class FakeUser:
    def __init__(self, uid=1, full_name="Əli Vəliyev"):
        self.id, self.full_name = uid, full_name


class FakeCallback:
    def __init__(self, data, user=None, message=None):
        self.data, self.from_user, self.message = data, user or FakeUser(), message or FakeMessage()
        self.alerts, self.toasts = [], []

    async def answer(self, text=None, show_alert=False):
        (self.alerts if show_alert else self.toasts).append(text)


class FakeState:
    def __init__(self):
        self.data, self.state, self.cleared = {}, None, 0

    async def clear(self):
        self.data, self.state = {}, None
        self.cleared += 1

    async def set_state(self, s):
        self.state = s

    async def update_data(self, **kw):
        self.data.update(kw)

    async def get_data(self):
        return dict(self.data)


class Cmd:
    def __init__(self, args=None):
        self.args = args


def run(coro):
    return asyncio.run(coro)


def mi(i="r1", price=5.0, cat="Yemək", name="Plov"):
    return {"id": i, "name": name, "category": cat, "price": price}


@pytest.fixture(autouse=True)
def env(monkeypatch):
    bot.user_carts.clear()
    bot.user_tables.clear()
    bot.user_locks.clear()
    menu = [mi("r1", 5.0), mi("r2", 3.0, name="Çay", cat="İçki")]
    monkeypatch.setattr(core, "get_menu", lambda force=False: list(menu))
    monkeypatch.setattr(core, "ADMIN_CHAT_ID", 999)
    monkeypatch.setattr(core, "REQUIRE_TABLE_QR", False)
    submitted = []

    def fake_submit(*a):
        submitted.append(a)
        return True, "recABCDE12345"
    monkeypatch.setattr(core, "submit_order", fake_submit)
    return {"menu": menu, "submitted": submitted, "monkeypatch": monkeypatch}


def fill_cart(uid=1):
    bot.user_carts[uid] = [{**mi("r1", 5.0), "quantity": 2}]


# ---------------------------------------------------------------- /start və QR
def test_start_with_qr_payload_remembers_table():
    m, st = FakeMessage(), FakeState()
    m.from_user = FakeUser(7)
    run(bot.cmd_start(m, st, Cmd("table_5")))
    assert bot.user_tables[7] == 5 and any("Masa 5" in a for a in m.answers) and len(m.answers) == 2


def test_start_ignores_bad_payload():
    m, st = FakeMessage(), FakeState()
    m.from_user = FakeUser(7)
    run(bot.cmd_start(m, st, Cmd("table_x")))
    assert 7 not in bot.user_tables and len(m.answers) == 1


def test_start_when_menu_unavailable(env):
    env["monkeypatch"].setattr(core, "get_menu", lambda force=False: [])
    m = FakeMessage()
    m.from_user = FakeUser()
    run(bot.cmd_start(m, FakeState(), Cmd()))
    assert "əlçatan deyil" in m.answers[0]


# ---------------------------------------------------------------- menyu və səbət
def test_show_items_pagination_buttons(env):
    env["menu"][:] = [mi(f"r{i}", cat="A") for i in range(45)]
    cb = FakeCallback("items:all:1")
    run(bot.show_items(cb))
    text, kb = cb.message.edits[0]
    assert "(2/3)" in text
    datas = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "items:all:0" in datas and "items:all:2" in datas
    assert len([d for d in datas if d.startswith("add:")]) == 20
    assert all(len(d.encode()) <= 64 for d in datas)


def test_show_items_bad_callback_and_empty_category():
    cb = FakeCallback("items:all:x")
    run(bot.show_items(cb))
    assert cb.alerts
    cb2 = FakeCallback("items:deadbeef:0")
    run(bot.show_items(cb2))
    assert cb2.alerts and not cb2.message.edits


def test_add_to_cart_handler():
    cb = FakeCallback("add:r1")
    run(bot.add_to_cart(cb))
    run(bot.add_to_cart(FakeCallback("add:r1")))
    assert bot.user_carts[1][0]["quantity"] == 2
    bad = FakeCallback("add:nope")
    run(bot.add_to_cart(bad))
    assert bad.alerts


def test_delete_from_cart_and_empty_cart_returns_to_menu():
    fill_cart()
    cb = FakeCallback("del:0")
    run(bot.delete_from_cart(cb))
    assert bot.user_carts[1][0]["quantity"] == 1 and "5.00" in cb.message.edits[-1][0]
    cb2 = FakeCallback("del:0")
    run(bot.delete_from_cart(cb2))
    assert bot.user_carts[1] == [] and "boşaldıldı" in cb2.message.edits[-1][0]
    cb3 = FakeCallback("del:7")
    run(bot.delete_from_cart(cb3))
    assert cb3.alerts


def test_safe_edit_swallows_not_modified_only():
    class M(FakeMessage):
        def __init__(self, err):
            super().__init__()
            self.err = err

        async def edit_text(self, text, reply_markup=None):
            raise bot.TelegramBadRequest(self.err)
    run(bot.safe_edit(FakeCallback("x", message=M("Bad Request: message is not modified")), "t"))
    with pytest.raises(bot.TelegramBadRequest):
        run(bot.safe_edit(FakeCallback("x", message=M("Bad Request: chat not found")), "t"))


# ---------------------------------------------------------------- masada sifariş
def test_dine_in_with_qr_submits_without_asking_table(env):
    fill_cart()
    bot.user_tables[1] = 4
    cb, st = FakeCallback("type:masada"), FakeState()
    run(bot.order_in_place(cb, st))
    assert env["submitted"][0][:5] == ("Masada", "Əli Vəliyev", "-", 4, None)
    assert bot.user_carts[1] == [] and "Masa: 4" in cb.message.answers[0]
    assert cb.message.bot.sent and cb.message.bot.sent[0][0] == 999 and "Masa: 4" in cb.message.bot.sent[0][1]


def test_dine_in_without_qr_asks_table_then_submits(env):
    fill_cart()
    cb, st = FakeCallback("type:masada"), FakeState()
    run(bot.order_in_place(cb, st))
    assert st.state is bot.OrderStates.waiting_table and not env["submitted"]
    bad = FakeMessage("abc")
    bad.from_user = FakeUser()
    run(bot.process_table(bad, st))
    assert not env["submitted"] and "rəqəmlə" in bad.answers[0]
    zero = FakeMessage("0")
    zero.from_user = FakeUser()
    run(bot.process_table(zero, st))
    assert not env["submitted"]
    ok = FakeMessage(" 12 ")
    ok.from_user = FakeUser()
    run(bot.process_table(ok, st))
    assert env["submitted"][0][3] == 12 and st.cleared >= 1


def test_dine_in_requires_qr_when_enabled(env):
    env["monkeypatch"].setattr(core, "REQUIRE_TABLE_QR", True)
    fill_cart()
    cb, st = FakeCallback("type:masada"), FakeState()
    run(bot.order_in_place(cb, st))
    assert cb.alerts and "QR" in cb.alerts[0] and not env["submitted"] and st.state is None


# ---------------------------------------------------------------- çatdırılma
def test_delivery_flow_validates_each_step(env):
    fill_cart()
    st = FakeState()
    cb = FakeCallback("type:catdirilma")
    run(bot.order_delivery(cb, st))
    assert st.state is bot.OrderStates.waiting_name

    def msg(t):
        m = FakeMessage(t)
        m.from_user = FakeUser()
        return m
    m = msg("A")
    run(bot.process_name(m, st))
    assert st.state is bot.OrderStates.waiting_name
    run(bot.process_name(msg("Əli Vəliyev"), st))
    m = msg("123")
    run(bot.process_phone(m, st))
    assert st.state is bot.OrderStates.waiting_phone and "düzgün" in m.answers[0]
    run(bot.process_phone(msg("+994501234567"), st))
    m = msg("x")
    run(bot.process_address(m, st))
    assert not env["submitted"]
    done = msg("Bakı, Nizami küç. 10")
    run(bot.process_address(done, st))
    sub = env["submitted"][0]
    assert sub[0] == "Çatdırılma" and sub[1] == "Əli Vəliyev" and sub[2] == "+994501234567" and sub[4] == "Bakı, Nizami küç. 10"
    assert "Çatdırılma sifarişiniz" in done.answers[0] and done.bot.sent[0][0] == 999 and st.data == {}


# ---------------------------------------------------------------- place_order qoruyucuları
def test_price_change_blocks_submission_and_updates_cart(env):
    fill_cart()
    env["menu"][0]["price"] = 7.0
    m = FakeMessage()
    ok = run(bot.place_order(m, FakeUser(), "Masada", "Əli", "-", table=2))
    assert ok is False and not env["submitted"]
    assert "7.00" in m.answers[0] and bot.user_carts[1][0]["price"] == 7.0 and bot.user_carts[1][0]["quantity"] == 2
    ok2 = run(bot.place_order(FakeMessage(), FakeUser(), "Masada", "Əli", "-", table=2))     # yenidən təsdiq
    assert ok2 is True and env["submitted"][0][5][0]["price"] == 7.0


def test_inactive_item_is_removed_and_order_not_sent(env):
    bot.user_carts[1] = [{**mi("gone", 1.0, name="Köhnə"), "quantity": 1}]
    m = FakeMessage()
    assert run(bot.place_order(m, FakeUser(), "Masada", "Əli", "-", table=2)) is False
    assert "Köhnə" in m.answers[0] and bot.user_carts[1] == [] and not env["submitted"]


def test_failed_submit_keeps_cart_and_no_admin_message(env):
    fill_cart()
    env["monkeypatch"].setattr(core, "submit_order", lambda *a: (False, None))
    m = FakeMessage()
    assert run(bot.place_order(m, FakeUser(), "Masada", "Əli", "-", table=2)) is False
    assert len(bot.user_carts[1]) == 1 and "saxlanıldı" in m.answers[0] and not m.bot.sent


def test_empty_cart_and_menu_down(env):
    m = FakeMessage()
    assert run(bot.place_order(m, FakeUser(), "Masada", "Əli", "-", table=2)) is False
    fill_cart()
    env["monkeypatch"].setattr(core, "get_menu", lambda force=False: [])
    m2 = FakeMessage()
    assert run(bot.place_order(m2, FakeUser(), "Masada", "Əli", "-", table=2)) is False
    assert "yoxlanıla bilmir" in m2.answers[0] and len(bot.user_carts[1]) == 1


def test_double_tap_creates_only_one_order(env):
    fill_cart()
    calls = []

    def slow(*a):
        import time
        time.sleep(0.2)
        calls.append(a)
        return True, "recABCDE12345"
    env["monkeypatch"].setattr(core, "submit_order", slow)

    async def both():
        m1, m2 = FakeMessage(), FakeMessage()
        return await asyncio.gather(
            bot.place_order(m1, FakeUser(), "Masada", "Əli", "-", table=2),
            bot.place_order(m2, FakeUser(), "Masada", "Əli", "-", table=2)), m2
    (r1, r2), m2 = run(both())
    assert sorted([r1, r2]) == [False, True] and len(calls) == 1


def test_admin_notification_failure_does_not_break_order(env):
    fill_cart()

    class BadBot(FakeBot):
        async def send_message(self, *a, **k):
            raise RuntimeError("blocked")
    m = FakeMessage(bot_=BadBot())
    assert run(bot.place_order(m, FakeUser(), "Masada", "Əli", "-", table=2)) is True
    assert bot.user_carts[1] == []


def test_no_admin_message_when_admin_chat_not_set(env):
    env["monkeypatch"].setattr(core, "ADMIN_CHAT_ID", None)
    fill_cart()
    m = FakeMessage()
    assert run(bot.place_order(m, FakeUser(), "Masada", "Əli", "-", table=2)) is True
    assert not m.bot.sent


def test_cancel_clears_cart_but_keeps_qr_table(env):
    fill_cart()
    bot.user_tables[1] = 3
    cb, st = FakeCallback("cancel_order"), FakeState()
    run(bot.cancel_order(cb, st))
    assert bot.user_carts[1] == [] and bot.user_tables[1] == 3


def test_validate_settings_reports_missing(monkeypatch):
    monkeypatch.setattr(core, "AIRTABLE_TOKEN", None)
    with pytest.raises(ValueError, match="AIRTABLE_TOKEN"):
        core.validate_settings()
