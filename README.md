# 🍽️ Restoran Sifariş Botu (Telegram + Airtable)

![Python](https://img.shields.io/badge/Python-3.10+-blue)
![Telegram](https://img.shields.io/badge/Telegram-Bot-26A5E4)
![Airtable](https://img.shields.io/badge/Airtable-API-yellow)

[![Demo videosu](preview.jpg)](brag.mp4)

Müştəri menyudan seçir, səbət yığır, **masada** və ya **çatdırılma** sifarişi verir.
Sifariş Airtable-a yazılır və **restoranın Telegram qrupuna dərhal bildiriş gedir**.

## ✨ Xüsusiyyətlər
- ✅ Menyu + səbət
- ✅ Masada / çatdırılma / özü götürür
- ✅ Airtable inteqrasiyası
- ✅ Telegram qrupuna real-time bildiriş
- ✅ Masa QR kodları (`?start=table_5`)
- ✅ Çox restoran dəstəyi

## 📸 Ekran görüntüləri
| Menyu | Səbət | Admin bildirişi |
|---|---|---|
| ![](docs/menu.png) | ![](docs/cart.png) | ![](docs/admin.png) |

## 🚀 Quraşdırma
1. `pip install -r requirements.txt`
2. `.env.example` → `.env` kopyala və doldur
3. `python bot.py`

### `.env` nümunəsi
```env
TELEGRAM_TOKEN=...
AIRTABLE_API_KEY=...
AIRTABLE_BASE_ID=...
ADMIN_CHAT_ID=-100...
REQUIRE_TABLE_QR=1
