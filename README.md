# Restoran sifariş botu (Telegram + Airtable)

Müştəri menyudan seçir, səbət yığır, **masada** və ya **çatdırılma** sifarişi verir. Sifariş Airtable-a yazılır və
**restoranın Telegram qrupuna dərhal bildiriş gedir**.

## Quraşdırma
1. `pip install -r requirements.txt`
2. `.env.example` → `.env` kopyala və doldur.
3. `python bot.py`

### Airtable sahələri
| Cədvəl | Sahələr |
|---|---|
| Menu | `Name`, `Category` (single select), `Price` (number), `Available` (checkbox) |
| Orders | `Order Type` (single select: `Çatdırılma`, `Özü götürür`, `Masada`), `Customer Name`, `Phone`, `Status` (single select, `Yeni` seçimi olmalı), `Table Number` (number), `Delivery Address` |
| Order Items | `Order` (link → Orders), `Menu Item` (link → Menu), `Quantity` (number) |

Cədvəl ID-ləri fərqlidirsə `.env`-də `MENU_TABLE_ID`, `ORDERS_TABLE_ID`, `ORDER_ITEMS_TABLE_ID` ilə dəyiş.

### Restorana bildiriş (ADMIN_CHAT_ID)
Botu restoranın Telegram qrupuna əlavə et, qrupa bir mesaj yaz, sonra
`https://api.telegram.org/bot<TOKEN>/getUpdates` cavabında `chat.id` (qrup üçün mənfi rəqəm) tap. `.env`-ə yaz.

### Masa QR kodları
Hər masa üçün QR kod yarat: `https://t.me/<bot_username>?start=table_5` (5 = masa nömrəsi).
Müştəri oxuyanda masa avtomatik seçilir, nömrə yazmır. `REQUIRE_TABLE_QR=1` olarsa masada sifariş yalnız QR ilə mümkündür
(restoranda olmayan şəxsin saxta sifarişinin qarşısı).

## Hər restoran üçün
Bir restoran = bir bot tokeni (BotFather) + bir Airtable base + bir `.env`. Eyni kodu hər restoran üçün ayrıca işə sal.

## Server
Bot polling ilə işləyir, ona görə həmişə açıq olmalıdır (VPS, Render "Background Worker", Railway və s.). `systemd` nümunəsi:
```
[Service]
WorkingDirectory=/opt/restaurant-bot
ExecStart=/usr/bin/python3 bot.py
Restart=always
```
Bot restart olarsa səbətlər sıfırlanır (sifarişlər Airtable-dadır, itmir).

## Testlər
`pip install pytest` → `python -m pytest -q` (Telegram/Airtable tələb etmir).

## Məlum məhdudiyyətlər
- Müştəriyə sifariş statusu ("hazırdır", "yoldadır") göndərilmir. Bunun üçün Orders cədvəlinə `Telegram ID` sahəsi və status izləyən əlavə lazımdır.
- Ödəniş yoxdur (nağd/kartla yerində).
- Çox restoranlı vahid panel yoxdur; hər restoran ayrıca deploy olunur.
