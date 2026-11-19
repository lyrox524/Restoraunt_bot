import asyncio
import logging
import re
from collections import defaultdict

from aiogram import Bot, Dispatcher, F, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import core

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
logger = logging.getLogger("restaurant_bot")

dp = Dispatcher()

# Yaddaş: bot restart olarsa səbətlər və masa seçimi sıfırlanır.
user_carts = defaultdict(list)
user_tables = {}                      # QR ilə gələn masa nömrəsi (user_id → masa)
user_locks = defaultdict(asyncio.Lock)  # eyni istifadəçinin ikiqat sifarişinin qarşısı


class OrderStates(StatesGroup):
    waiting_table = State()
    waiting_name = State()
    waiting_phone = State()
    waiting_address = State()


# ------------------------------------------------------------------ köməkçilər
async def get_menu(force=False):
    return await asyncio.to_thread(core.get_menu, force)     # sinxron Airtable çağırışı event loop-u bloklamasın


async def safe_edit(callback: types.CallbackQuery, text, reply_markup=None):
    try:
        await callback.message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise


def menu_kb(menu):
    if not menu:
        return None
    rows = [[InlineKeyboardButton(text=f"📂 {c}", callback_data=f"items:{core.cat_id(c)}:0")]
            for c in core.categories(menu)]
    rows.append([InlineKeyboardButton(text="📋 Bütün Menyu", callback_data="items:all:0")])
    rows.append([InlineKeyboardButton(text="🛒 Səbətə Bax", callback_data="view_cart")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def greeting():
    name = f" «{core.RESTAURANT_NAME}»" if core.RESTAURANT_NAME else ""
    return f"👋 Xoş gəldiniz{name}! Menyudan seçim etmək üçün bölmə seçin:"


async def notify_admin(bot: Bot, text):
    if core.ADMIN_CHAT_ID is None:
        return
    try:
        await bot.send_message(core.ADMIN_CHAT_ID, text)
    except Exception:
        logger.exception("Admin bildirişi göndərilmədi (ADMIN_CHAT_ID=%s)", core.ADMIN_CHAT_ID)


# ------------------------------------------------------------------ menyu
@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext, command: CommandObject):
    await state.clear()
    table = core.parse_table_payload(command.args)
    if table is not None:
        user_tables[message.from_user.id] = table
        await message.answer(f"📍 Masa {table} seçildi.")

    kb = menu_kb(await get_menu())
    if not kb:
        await message.answer("⚠️ Hazırda menyu əlçatan deyil. Bir az sonra yenidən cəhd edin.")
        return
    await message.answer(greeting(), reply_markup=kb)


@dp.callback_query(F.data == "back_to_cats")
async def back_to_cats(callback: types.CallbackQuery):
    kb = menu_kb(await get_menu())
    if not kb:
        await callback.answer("Aktiv menyu tapılmadı.", show_alert=True)
        return
    await safe_edit(callback, "Menyu bölmələri:", kb)
    await callback.answer()


@dp.callback_query(F.data.startswith("items:"))
async def show_items(callback: types.CallbackQuery):
    try:
        _, cid, page_s = callback.data.split(":", 2)
        page = int(page_s)
    except ValueError:
        await callback.answer("Yanlış sorğu.", show_alert=True)
        return

    menu = await get_menu()
    items = core.items_for_category(menu, cid)
    if not items:
        await callback.answer("Bu bölmədə aktiv məhsul yoxdur.", show_alert=True)
        return

    chunk, page, pages = core.paginate(items, page)
    title = "🍽 Bütün Menyu" if cid == "all" else f"📂 {items[0]['category']}"
    if pages > 1:
        title += f" ({page + 1}/{pages})"

    rows = [[InlineKeyboardButton(text=f"{i['name'][:40]} — {i['price']:.2f} {core.CURRENCY} ➕",
                                  callback_data=f"add:{i['id']}")] for i in chunk]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"items:{cid}:{page - 1}"))
    if page < pages - 1:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"items:{cid}:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="⬅️ Geri", callback_data="back_to_cats"),
                 InlineKeyboardButton(text="🛒 Səbət", callback_data="view_cart")])

    await safe_edit(callback, title, InlineKeyboardMarkup(inline_keyboard=rows))
    await callback.answer()


# ------------------------------------------------------------------ səbət
@dp.callback_query(F.data.startswith("add:"))
async def add_to_cart(callback: types.CallbackQuery):
    item_id = callback.data.split(":", 1)[1]
    item = next((i for i in await get_menu() if i["id"] == item_id), None)
    if not item:
        await callback.answer("Bu məhsul mövcud deyil və ya hazırda aktiv deyil.", show_alert=True)
        return

    result = core.add_to_cart(user_carts[callback.from_user.id], item)
    if result == "max_qty":
        await callback.answer(f"Bir məhsuldan ən çox {core.MAX_QTY_PER_ITEM} ədəd.", show_alert=True)
    elif result == "cart_full":
        await callback.answer("Səbətdə çox məhsul var. Əvvəlcə sifarişi tamamlayın.", show_alert=True)
    else:
        await callback.answer(f"✅ {item['name']} səbətə əlavə olundu!")


async def render_cart(callback: types.CallbackQuery):
    cart = user_carts[callback.from_user.id]
    text = "🛒 Sizin səbətiniz:\n\n"
    rows = []
    for idx, item in enumerate(cart):
        qty = item.get("quantity", 1)
        text += f"{idx + 1}. {item['name']} × {qty} — {item['price'] * qty:.2f} {core.CURRENCY}\n"
        rows.append([InlineKeyboardButton(text=f"➖ 1 ədəd sil: {item['name'][:30]}", callback_data=f"del:{idx}")])
    text += f"\n💰 Ümumi məbləğ: {core.cart_total(cart):.2f} {core.CURRENCY}"
    rows.append([InlineKeyboardButton(text="✅ Sifarişi Təsdiqlə", callback_data="confirm_order")])
    rows.append([InlineKeyboardButton(text="🗑 Sifarişi İptal Et", callback_data="cancel_order"),
                 InlineKeyboardButton(text="➕ Menyuya Qayıt", callback_data="back_to_cats")])
    await safe_edit(callback, text, InlineKeyboardMarkup(inline_keyboard=rows))


@dp.callback_query(F.data == "view_cart")
async def view_cart(callback: types.CallbackQuery):
    if not user_carts[callback.from_user.id]:
        await callback.answer("Səbətiniz boşdur!", show_alert=True)
        return
    await render_cart(callback)
    await callback.answer()


@dp.callback_query(F.data.startswith("del:"))
async def delete_from_cart(callback: types.CallbackQuery):
    try:
        idx = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("Yanlış məhsul indeksi.", show_alert=True)
        return

    cart = user_carts[callback.from_user.id]
    if not 0 <= idx < len(cart):
        await callback.answer("Məhsul tapılmadı.", show_alert=True)
        return

    if cart[idx].get("quantity", 1) > 1:
        cart[idx]["quantity"] -= 1
    else:
        cart.pop(idx)

    await callback.answer("Məhsul səbətdən yeniləndi.")
    if cart:
        await render_cart(callback)
    else:
        await safe_edit(callback, "Səbət boşaldıldı. Menyuya qayıda bilərsiniz:", menu_kb(await get_menu()))


@dp.callback_query(F.data == "cancel_order")
async def cancel_order(callback: types.CallbackQuery, state: FSMContext):
    user_carts[callback.from_user.id] = []
    await state.clear()
    await safe_edit(callback, "❌ Sifariş ləğv edildi.", menu_kb(await get_menu()))
    await callback.answer()


# ------------------------------------------------------------------ sifariş
async def place_order(target: types.Message, user: types.User, order_type, name, phone, table=None, address=None):
    """Ortaq yekun addım: üzləşdirmə (qiymət/aktivlik) → Airtable → müştəriyə və admin-ə mesaj. True = göndərildi."""
    lock = user_locks[user.id]
    if lock.locked():
        await target.answer("⏳ Sifarişiniz artıq işlənir, gözləyin.")
        return False

    async with lock:
        cart = list(user_carts[user.id])
        if not cart:
            await target.answer("Səbət boşdur. /start yazaraq yenidən başlayın.")
            return False

        menu = await get_menu(force=True)
        if not menu:
            await target.answer("⚠️ Menyu hazırda yoxlanıla bilmir. Bir az sonra yenidən cəhd edin.")
            return False

        cart, notes = core.reconcile_cart(cart, menu)
        if notes:
            user_carts[user.id] = cart
            await target.answer("\n".join(notes) + "\n\nSəbət yeniləndi. Səbətə baxıb yenidən təsdiqləyin (/start).")
            return False

        ok, order_id = await asyncio.to_thread(core.submit_order, order_type, name, phone, table, address, cart)
        if not ok:
            await target.answer("⚠️ Sifariş göndərilmədi. Səbətiniz saxlanıldı, bir az sonra yenidən cəhd edin.")
            return False

        user_carts[user.id] = []
        total = core.cart_total(cart)
        if order_type == "Masada":
            text = (f"✅ Sifarişiniz qəbul edildi!\n📍 Masa: {table}\n🧾 Sifariş: {core.cart_summary(cart)}\n"
                    f"💰 Məbləğ: {total:.2f} {core.CURRENCY}\nNuş olsun!")
        else:
            text = (f"✅ Çatdırılma sifarişiniz qəbul edildi!\n\n👤 Ad: {name}\n📞 Tel: {phone}\n🏠 Ünvan: {address}\n"
                    f"🧾 Sifariş: {core.cart_summary(cart)}\n💰 Məbləğ: {total:.2f} {core.CURRENCY}")
        await target.answer(text)
        await notify_admin(target.bot, core.admin_message(order_type, name, phone, table, address, cart, order_id))
        return True


@dp.callback_query(F.data == "confirm_order")
async def choose_order_type(callback: types.CallbackQuery):
    if not user_carts[callback.from_user.id]:
        await callback.answer("Səbət boşdur.", show_alert=True)
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🍽 Masada (Restoranda)", callback_data="type:masada")],
        [InlineKeyboardButton(text="🛵 Çatdırılma", callback_data="type:catdirilma")],
        [InlineKeyboardButton(text="❌ Ləğv et", callback_data="cancel_order")],
    ])
    await safe_edit(callback, "Sifariş növünü seçin:", kb)
    await callback.answer()


@dp.callback_query(F.data == "type:masada")
async def order_in_place(callback: types.CallbackQuery, state: FSMContext):
    if not user_carts[callback.from_user.id]:
        await callback.answer("Səbət boşdur.", show_alert=True)
        return

    table = user_tables.get(callback.from_user.id)
    if table is not None:                                       # QR ilə gəlib: masa nömrəsi sorulmur
        await callback.answer()
        await place_order(callback.message, callback.from_user, "Masada",
                          callback.from_user.full_name or "Müştəri", "-", table=table)
        await state.clear()
        return

    if core.REQUIRE_TABLE_QR:
        await callback.answer("Masada sifariş üçün masadakı QR kodu oxudun.", show_alert=True)
        return

    await state.set_state(OrderStates.waiting_table)
    await safe_edit(callback, "Zəhmət olmasa masa nömrəsini yazın (məsələn: 5):")
    await callback.answer()


@dp.message(OrderStates.waiting_table)
async def process_table(message: types.Message, state: FSMContext):
    m = re.fullmatch(r"\s*(\d{1,3})\s*", message.text or "")
    if not m or int(m.group(1)) < 1:
        await message.answer("Masa nömrəsini rəqəmlə daxil edin (məsələn: 5).")
        return
    await place_order(message, message.from_user, "Masada",
                      message.from_user.full_name or "Müştəri", "-", table=int(m.group(1)))
    await state.clear()


@dp.callback_query(F.data == "type:catdirilma")
async def order_delivery(callback: types.CallbackQuery, state: FSMContext):
    if not user_carts[callback.from_user.id]:
        await callback.answer("Səbət boşdur.", show_alert=True)
        return
    await state.set_state(OrderStates.waiting_name)
    await safe_edit(callback, "Zəhmət olmasa ad və soyadınızı daxil edin:")
    await callback.answer()


@dp.message(OrderStates.waiting_name)
async def process_name(message: types.Message, state: FSMContext):
    name = (message.text or "").strip()
    if len(name) < 2 or len(name) > 80:
        await message.answer("Ad və soyadınızı düzgün daxil edin.")
        return
    await state.update_data(name=name)
    await state.set_state(OrderStates.waiting_phone)
    await message.answer("📞 Telefon nömrənizi yazın (məsələn: +994501234567):")


@dp.message(OrderStates.waiting_phone)
async def process_phone(message: types.Message, state: FSMContext):
    phone = (message.text or "").strip()
    if not core.valid_phone(phone):
        await message.answer("Telefon nömrəsini düzgün daxil edin (məsələn: +994501234567).")
        return
    await state.update_data(phone=phone)
    await state.set_state(OrderStates.waiting_address)
    await message.answer("🏠 Çatdırılma üçün tam ünvanı yazın:")


@dp.message(OrderStates.waiting_address)
async def process_address(message: types.Message, state: FSMContext):
    address = (message.text or "").strip()
    if len(address) < 5 or len(address) > 300:
        await message.answer("Zəhmət olmasa tam ünvanı daxil edin.")
        return
    data = await state.get_data()
    await place_order(message, message.from_user, "Çatdırılma", data["name"], data["phone"], address=address)
    await state.clear()


# ------------------------------------------------------------------ xətalar
@dp.error()
async def on_error(event: types.ErrorEvent):
    logger.error("Gözlənilməz xəta", exc_info=event.exception)
    try:
        if event.update.callback_query:
            await event.update.callback_query.answer("⚠️ Xəta baş verdi, yenidən cəhd edin.", show_alert=True)
        elif event.update.message:
            await event.update.message.answer("⚠️ Xəta baş verdi. /start yazıb yenidən cəhd edin.")
    except Exception:
        pass
    return True


async def main():
    core.validate_settings()
    if core.ADMIN_CHAT_ID is None:
        logger.warning("ADMIN_CHAT_ID təyin edilməyib: yeni sifarişlər restorana Telegram-da bildirilməyəcək!")
    bot = Bot(token=core.BOT_TOKEN)
    logger.info("Restoran botu başladılır...")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
