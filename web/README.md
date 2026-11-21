# SifarişGo — veb versiya (Cloudflare Pages)

Müştəri masadakı QR kodu oxuyur → telefonda menyu açılır → sifariş verir → sifariş Airtable-a yazılır və mətbəx Telegram qrupuna mesaj gedir. Pulsuz Cloudflare planında işləyir, server saxlamaq lazım deyil.

## 1. Telegram (mətbəx bildirişi)
1. Telegram-da `@BotFather` → `/newbot` → bot yaradın, **token**-i götürün (kimsəyə göndərməyin).
2. Mətbəx üçün qrup yaradın, botu qrupa əlavə edin.
3. Qrupun chat ID-sini öyrənin (məsələn `@RawDataBot`-u qrupa əlavə edib `chat id`-ə baxın; `-100…` ilə başlayır), sonra RawDataBot-u çıxarın.

## 2. Cloudflare Pages
1. dash.cloudflare.com → Workers & Pages → Create → Pages → Connect to Git → bu repo.
2. Build ayarları: **Root directory** `web`, **Build command** boş, **Build output directory** `public`.
3. Settings → Variables and secrets (Production) bölməsində aşağıdakıları əlavə edin (Secret kimi):

| Ad | Məcburi | Təsvir |
|---|---|---|
| `AIRTABLE_TOKEN` | bəli | Airtable personal access token (menyu oxuma + sifariş yazma) |
| `AIRTABLE_BASE_ID` | bəli | `app…` |
| `TELEGRAM_BOT_TOKEN` | tövsiyə | BotFather tokeni |
| `ADMIN_CHAT_ID` | tövsiyə | Mətbəx qrupunun ID-si |
| `RESTAURANT_NAME` | tövsiyə | Səhifədə görünən ad |
| `TABLE_SECRET` | tövsiyə | İstənilən uzun təsadüfi mətn; masa QR-ları imzalanır, saxta masa sifarişi bloklanır |
| `CURRENCY` | yox | standart `AZN` |
| `ENABLE_DELIVERY` / `ENABLE_PICKUP` | yox | `0` yazsanız həmin növ söndürülür |
| `MENU_CACHE_TTL` | yox | menyu keşi (saniyə), standart 30 |
| `MENU_TABLE_ID`, `ORDERS_TABLE_ID`, `ORDER_ITEMS_TABLE_ID` | yox | başqa restoran üçün başqa Airtable cədvəlləri |

Dəyişənləri dəyişdikdən sonra yenidən deploy edin.

## 3. Masa QR kodları
```
node scripts/table-links.mjs https://SAYTINIZ.pages.dev 12 SIZIN_TABLE_SECRET
```
12 masa üçün imzalı linklər çıxır (`?t=5&s=…`). Hər linki QR generatoruna verib masaya yapışdırın. Eyni `TABLE_SECRET` Cloudflare-də də olmalıdır. İmzasız link (`/?t=5`) `TABLE_SECRET` təyin olunubsa sifariş verə bilməz; sadəcə `/` isə menyuya baxış + özü götürmə/çatdırılma üçündür.

## 4. Lokal yoxlama
```
cp .dev.vars.example .dev.vars   # dəyərləri doldurun
npx wrangler pages dev public
npm test                         # Node 20+
```

## Məhdudiyyətlər
- IP üzrə sorğu limiti yoxdur (qorunma: gizli sahə + imzalı masa QR + eyni sifariş açarı ilə dublikat qoruması). Lazım olsa Cloudflare WAF rate limiting qoşun.
- Airtable şəkil linkləri müvəqqətidir; şəkillər hər menyu yükləməsində təzələnir.
- Hər restoran üçün ayrıca Cloudflare layihəsi və öz env dəyişənləri.
