// Airtable və Telegram üçün yaddaşda saxta server: fetch əvəz olunur, şəbəkə lazım deyil.
import { resetMenuCache } from '../functions/_lib/airtable.js';

export const rid = (n) => `rec${String(n).padStart(14, '0')}`;

export const ENV = {
  AIRTABLE_TOKEN: 'pat_test',
  AIRTABLE_BASE_ID: 'appTEST',
  MENU_TABLE_ID: 'tblMenu',
  ORDERS_TABLE_ID: 'tblOrders',
  ORDER_ITEMS_TABLE_ID: 'tblItems',
  TELEGRAM_BOT_TOKEN: '123:tg',
  ADMIN_CHAT_ID: '-100500',
  AT_RETRY_MS: '1',
};

export function menuRecord(n, fields = {}) {
  return {
    id: rid(n),
    fields: { Name: `Yemək ${n}`, Category: 'Əsas yemək', Price: 10, Available: true, ...fields },
  };
}

export function seedMenu() {
  return [
    menuRecord(1, { Name: 'Dolma', Price: 12, 'Sort Order': 1, Description: 'Yarpaq dolması', Featured: true }),
    menuRecord(2, { Name: 'Çoban salatı', Category: 'Salat', Price: 6, 'Sort Order': 5, 'Dietary Tags': ['Vegan'] }),
    menuRecord(3, { Name: 'Qutab', Category: 'Başlanğıc', Price: 7, 'Sort Order': 2 }),
    menuRecord(4, { Name: 'Bitib', Price: 3, Available: false }),
    menuRecord(5, { Name: 'Qiymətsiz', Price: undefined }),
    menuRecord(6, { Name: 'Armudu çayı', Category: 'İçki', Price: 3, Photo: [{ url: 'https://x/o.jpg', thumbnails: { large: { url: 'https://x/l.jpg' } } }] }),
  ];
}

/** Saxta Airtable + Telegram. db: {menu, orders, items, calls, telegram, ...inyeksiya bayraqları} */
export function install(initialMenu = seedMenu(), opts = {}) {
  resetMenuCache();
  const db = {
    menu: initialMenu, orders: [], items: [], calls: [], telegram: [],
    pageSize: opts.pageSize ?? 100, rateLimited: 0, failItems: false, failMenu: false,
    failOrdersGet: false, failOrderCreate: false, telegramOk: true, orderSeq: 100, idSeq: 1000,
  };
  const real = globalThis.fetch;
  globalThis.fetch = async (input, init = {}) => {
    const url = new URL(String(input));
    const body = init.body ? JSON.parse(init.body) : undefined;
    const reply = (status, obj) => new Response(JSON.stringify(obj), { status, headers: { 'Content-Type': 'application/json' } });

    if (url.hostname === 'api.telegram.org') {
      db.telegram.push({ url: url.pathname, ...body });
      return db.telegramOk ? reply(200, { ok: true }) : reply(500, { ok: false });
    }
    const [, , , table, recordId] = url.pathname.split('/');       // /v0/base/table[/rec]
    const method = init.method || 'GET';
    db.calls.push({ method, table, recordId, query: url.search });

    if (db.rateLimited > 0) { db.rateLimited--; return reply(429, { error: 'rate' }); }

    if (table === 'tblMenu' && method === 'GET') {
      if (db.failMenu) return reply(500, { error: 'boom' });
      const start = Number(url.searchParams.get('offset') || 0);
      const page = db.menu.slice(start, start + db.pageSize);
      const next = start + db.pageSize;
      return reply(200, { records: page, ...(next < db.menu.length ? { offset: String(next) } : {}) });
    }
    if (table === 'tblOrders' && method === 'GET') {
      if (db.failOrdersGet) return reply(500, { error: 'boom' });
      const f = url.searchParams.get('filterByFormula') || '';
      const m = f.match(/\{WP Order ID\}='([^']+)'/);
      const recs = db.orders.filter((o) => !m || o.fields['WP Order ID'] === m[1]);
      return reply(200, { records: recs.slice(0, 1) });
    }
    if (table === 'tblOrders' && method === 'POST') {
      if (db.failOrderCreate) return reply(422, { error: 'bad' });
      const rec = { id: rid(++db.idSeq), fields: { ...body.fields, 'Order Number': ++db.orderSeq } };
      db.orders.push(rec);
      return reply(200, rec);
    }
    if (table === 'tblOrders' && method === 'DELETE') {
      db.orders = db.orders.filter((o) => o.id !== recordId);
      return reply(200, { id: recordId, deleted: true });
    }
    if (table === 'tblItems' && method === 'POST') {
      if (db.failItems) return reply(422, { error: 'bad' });
      const recs = body.records.map((r) => ({ id: rid(++db.idSeq), fields: r.fields }));
      db.items.push(...recs);
      return reply(200, { records: recs });
    }
    return reply(404, { error: 'unknown' });
  };
  db.restore = () => { globalThis.fetch = real; resetMenuCache(); };
  return db;
}

export const req = (body, raw) =>
  new Request('https://x.test/api/order', { method: 'POST', body: raw ?? JSON.stringify(body) });

export const goodKey = () => `k-${Math.random().toString(36).slice(2, 12)}${Date.now()}`;

export const dineIn = (over = {}) => ({
  type: 'Masada', table: 5, key: goodKey(),
  items: [{ id: rid(1), qty: 2 }, { id: rid(2), qty: 1 }], ...over,
});
