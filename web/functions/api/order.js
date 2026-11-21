import { at, getMenu, tables } from '../_lib/airtable.js';
import { json } from '../_lib/http.js';
import { OrderError, adminText, priceOrder, validatePayload, verifyTable } from '../_lib/order.js';
import { notifyAdmin } from '../_lib/telegram.js';

const dedupeKey = (key) => `web-${key}`;

/** Eyni açarla artıq yaradılmış sifariş. Tapılmasa null, Airtable xətasında undefined. */
async function findExisting(env, key) {
  const r = await at(env, 'GET', tables(env).orders, {
    query: [['filterByFormula', `{WP Order ID}='${dedupeKey(key)}'`], ['maxRecords', '1'], ['fields[]', 'Order Number']],
  });
  if (!r.ok) return undefined;
  return (r.json.records || [])[0] || null;
}

export async function onRequestPost({ request, env }) {
  try {
    if (!env.AIRTABLE_TOKEN || !env.AIRTABLE_BASE_ID) {
      return json(500, { ok: false, error: 'config', message: 'Sistem hələ qurulmayıb.' });
    }

    const text = await request.text();
    if (text.length > 20000) throw new OrderError('too_large', 'Sifariş çox böyükdür.', 413);
    let payload;
    try { payload = JSON.parse(text); } catch { throw new OrderError('bad_json', 'Sifariş məlumatı düzgün deyil.'); }

    const order = validatePayload(payload);

    if (order.type === 'Masada' && env.TABLE_SECRET && !(await verifyTable(env.TABLE_SECRET, order.table, order.sig))) {
      throw new OrderError('bad_table_qr', 'Masa QR kodu etibarsızdır. Masadakı QR kodu yenidən oxudun.', 403);
    }

    const menu = await getMenu(env, { force: true });
    if (!menu) throw new OrderError('menu_unavailable', 'Menyu yoxlanıla bilmir. Bir az sonra yenidən cəhd edin.', 503);
    const priced = priceOrder(order, menu);

    const existing = await findExisting(env, order.key);
    if (existing === undefined) throw new OrderError('airtable', 'Sifariş göndərilmədi. Bir az sonra yenidən cəhd edin.', 502);
    if (existing) {
      return json(200, { ok: true, duplicate: true, orderNumber: existing.fields?.['Order Number'] ?? null, total: priced.total });
    }

    const t = tables(env);
    const fields = {
      'Order Type': order.type,
      'Customer Name': order.name || 'Müştəri',
      Status: 'Yeni',
      'WP Order ID': dedupeKey(order.key),
    };
    if (order.table !== null) fields['Table Number'] = order.table;
    if (order.phone) fields.Phone = order.phone;
    if (order.address) fields['Delivery Address'] = order.address;
    if (order.note) fields.Notes = order.note;

    const created = await at(env, 'POST', t.orders, { body: { fields } });
    const orderId = created.json?.id;
    if (!created.ok || !orderId) throw new OrderError('airtable', 'Sifariş göndərilmədi. Bir az sonra yenidən cəhd edin.', 502);

    const records = priced.lines.map((l) => ({ fields: { Order: [orderId], 'Menu Item': [l.id], Quantity: l.qty } }));
    for (let i = 0; i < records.length; i += 10) {           // Airtable: sorğuda maks. 10 record
      const r = await at(env, 'POST', t.items, { body: { records: records.slice(i, i + 10) } });
      if (!r.ok) {
        await at(env, 'DELETE', t.orders, { recordId: orderId });   // yarımçıq sifariş qalmasın
        throw new OrderError('airtable', 'Sifariş göndərilmədi. Bir az sonra yenidən cəhd edin.', 502);
      }
    }

    const orderNumber = created.json.fields?.['Order Number'] ?? null;
    const notified = await notifyAdmin(env, adminText(order, priced, orderNumber, env.CURRENCY || 'AZN'));
    return json(200, { ok: true, orderNumber, total: priced.total, notified });
  } catch (e) {
    if (e instanceof OrderError) {
      return json(e.status, { ok: false, error: e.code, message: e.message, details: e.details });
    }
    console.error('order error', e?.message);
    return json(500, { ok: false, error: 'server', message: 'Gözlənilməz xəta. Bir az sonra yenidən cəhd edin.' });
  }
}
