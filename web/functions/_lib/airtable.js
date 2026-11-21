// Airtable ilə iş: təkrar cəhdli sorğu, menyu oxuma, menyu keşi.

const DEFAULT_TABLES = {
  menu: 'tbl3GmKrXkHxDNECy',
  orders: 'tblcP7WslS0HQ5dxY',
  items: 'tblH6wh7lnPvxkJ5f',
};

export function tables(env) {
  return {
    menu: env.MENU_TABLE_ID || DEFAULT_TABLES.menu,
    orders: env.ORDERS_TABLE_ID || DEFAULT_TABLES.orders,
    items: env.ORDER_ITEMS_TABLE_ID || DEFAULT_TABLES.items,
  };
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const RETRYABLE = new Set([429, 500, 502, 503, 504]);

/** Airtable REST sorğusu. 429/5xx üçün 2 təkrar. Həmişə {ok, status, json} qaytarır (atmır). */
export async function at(env, method, tableId, { recordId, query, body } = {}) {
  const url = new URL(
    `https://api.airtable.com/v0/${env.AIRTABLE_BASE_ID}/${tableId}${recordId ? `/${recordId}` : ''}`,
  );
  for (const [k, v] of query || []) url.searchParams.append(k, v);
  const delay = Number(env.AT_RETRY_MS ?? 400);
  let last = { ok: false, status: 0, json: {} };

  for (let attempt = 0; attempt < 3; attempt++) {
    try {
      const res = await fetch(url, {
        method,
        headers: { Authorization: `Bearer ${env.AIRTABLE_TOKEN}`, 'Content-Type': 'application/json' },
        body: body ? JSON.stringify(body) : undefined,
        signal: AbortSignal.timeout(8000),
      });
      const json = await res.json().catch(() => ({}));
      last = { ok: res.ok, status: res.status, json };
      if (res.ok || !RETRYABLE.has(res.status)) return last;
    } catch (e) {
      last = { ok: false, status: 0, json: { error: String(e) } };
    }
    if (attempt < 2) await sleep(delay * (attempt + 1));
  }
  return last;
}

const MENU_FIELDS = [
  'Name', 'Description', 'Category', 'Price', 'Photo', 'Available', 'Featured',
  'Dietary Tags', 'Allergens', 'Prep Time (min)', 'Sort Order',
];

/** Airtable recordunu menyu məhsuluna çevirir. Aktiv olmayan və qiyməti olmayan məhsullar atılır. */
export function toItem(rec) {
  const f = rec.fields || {};
  if (!f.Name || !f.Available) return null;
  if (f.Price === undefined || f.Price === null) return null;
  const price = Number(f.Price);
  if (!Number.isFinite(price) || price < 0) return null;
  const photo = Array.isArray(f.Photo) && f.Photo[0]
    ? f.Photo[0].thumbnails?.large?.url || f.Photo[0].url || null
    : null;
  return {
    id: rec.id,
    name: String(f.Name),
    description: f.Description ? String(f.Description) : '',
    category: f.Category ? String(f.Category) : 'Ümumi',
    price: Math.round(price * 100) / 100,
    photo,
    featured: !!f.Featured,
    tags: Array.isArray(f['Dietary Tags']) ? f['Dietary Tags'].map(String) : [],
    allergens: Array.isArray(f.Allergens) ? f.Allergens.map(String) : [],
    prep: Number.isFinite(Number(f['Prep Time (min)'])) && f['Prep Time (min)'] ? Number(f['Prep Time (min)']) : null,
    sort: Number.isFinite(Number(f['Sort Order'])) && f['Sort Order'] !== undefined ? Number(f['Sort Order']) : null,
  };
}

/** Bütün aktiv menyu. Xəta olarsa null (boş menyu ilə qarışmasın). */
export async function fetchMenu(env) {
  const items = [];
  let offset;
  do {
    const query = [['pageSize', '100'], ...MENU_FIELDS.map((f) => ['fields[]', f])];
    if (offset) query.push(['offset', offset]);
    const r = await at(env, 'GET', tables(env).menu, { query });
    if (!r.ok) return null;
    for (const rec of r.json.records || []) {
      const item = toItem(rec);
      if (item) items.push(item);
    }
    offset = r.json.offset;
  } while (offset);
  return items;
}

let cache = { items: null, ts: 0 };

export function resetMenuCache() {
  cache = { items: null, ts: 0 };
}

/** Keşlənmiş menyu. force=true (sifariş zamanı) həmişə təzə oxuyur və xətada null qaytarır (fail-closed). */
export async function getMenu(env, { force = false } = {}) {
  const ttl = Number(env.MENU_CACHE_TTL ?? 30) * 1000;
  const now = Date.now();
  if (!force && cache.items && now - cache.ts < ttl) return cache.items;
  const items = await fetchMenu(env);
  if (items === null) return force ? null : cache.items;
  cache = { items, ts: now };
  return items;
}

/** Kateqoriyalara böl: məhsullar Sort Order, sonra ada görə; kateqoriyalar ən kiçik Sort Order-ə görə. */
export function groupMenu(items) {
  const cmp = (a, b) => (a.sort ?? 1e9) - (b.sort ?? 1e9) || a.name.localeCompare(b.name, 'az');
  const by = new Map();
  for (const it of [...items].sort(cmp)) {
    if (!by.has(it.category)) by.set(it.category, []);
    by.get(it.category).push(it);
  }
  const minSort = (list) => Math.min(...list.map((i) => i.sort ?? 1e9));
  return [...by.entries()]
    .map(([name, list]) => ({ name, items: list, _o: minSort(list) }))
    .sort((a, b) => a._o - b._o || a.name.localeCompare(b.name, 'az'))
    .map(({ name, items: list }) => ({ name, items: list }));
}
