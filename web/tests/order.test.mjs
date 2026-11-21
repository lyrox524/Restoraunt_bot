import test, { afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { onRequestPost } from '../functions/api/order.js';
import { tableSignature, validatePayload } from '../functions/_lib/order.js';
import { ENV, install, req, dineIn, goodKey, rid } from './helpers.mjs';

let db;
afterEach(() => db?.restore());

const post = async (body, env = ENV, raw) => {
  const res = await onRequestPost({ request: req(body, raw), env });
  return { res, body: await res.json() };
};

test('masada sifariş: Airtable-a yazılır, qiymət serverdən, Telegram-a gedir', async () => {
  db = install();
  const { res, body } = await post(dineIn());
  assert.equal(res.status, 200);
  assert.equal(body.ok, true);
  assert.equal(body.total, 30);               // 2*12 + 6
  assert.equal(body.notified, true);
  assert.equal(db.orders.length, 1);
  assert.equal(db.orders[0].fields['Table Number'], 5);
  assert.equal(db.orders[0].fields.Status, 'Yeni');
  assert.equal(db.items.length, 2);
  assert.equal(db.telegram.length, 1);
  assert.match(db.telegram[0].text, /Masa: 5/);
});

test('müştərinin göndərdiyi qiymət nəzərə alınmır', async () => {
  db = install();
  const { body } = await post(dineIn({ items: [{ id: rid(1), qty: 1, price: 0.01 }] }));
  assert.equal(body.total, 12);
});

test('çatdırılma: ad, telefon, ünvan tələb olunur', async () => {
  db = install();
  const base = { type: 'Çatdırılma', key: goodKey(), items: [{ id: rid(1), qty: 1 }] };
  assert.equal((await post(base)).body.error, 'bad_name');
  assert.equal((await post({ ...base, name: 'Əli' })).body.error, 'bad_phone');
  assert.equal((await post({ ...base, name: 'Əli', phone: '0506018515' })).body.error, 'bad_address');
  const ok = await post({ ...base, name: 'Əli', phone: '050 601 85 15', address: 'Heydər Əliyev pr. 5' });
  assert.equal(ok.res.status, 200);
  assert.equal(db.orders[0].fields['Delivery Address'], 'Heydər Əliyev pr. 5');
});

test('özü götürür: ünvan tələb olunmur', async () => {
  db = install();
  const { res } = await post({ type: 'Özü götürür', key: goodKey(), name: 'Leyla', phone: '0501234567', items: [{ id: rid(3), qty: 1 }] });
  assert.equal(res.status, 200);
  assert.equal(db.orders[0].fields['Delivery Address'], undefined);
});

test('doğrulama xətaları', async () => {
  db = install();
  const cases = [
    [dineIn({ type: 'Yanlış' }), 'bad_type'],
    [dineIn({ items: [] }), 'empty_cart'],
    [dineIn({ items: [{ id: 'abc', qty: 1 }] }), 'bad_item'],
    [dineIn({ items: [{ id: rid(1), qty: 0 }] }), 'bad_item'],
    [dineIn({ items: [{ id: rid(1), qty: 21 }] }), 'bad_item'],
    [dineIn({ items: [{ id: rid(1), qty: 1.5 }] }), 'bad_item'],
    [dineIn({ table: 0 }), 'bad_table'],
    [dineIn({ table: 1000 }), 'bad_table'],
    [dineIn({ key: 'q' }), 'bad_request'],
    [dineIn({ website: 'spam' }), 'bad_request'],
  ];
  for (const [payload, code] of cases) {
    const { res, body } = await post(payload);
    assert.equal(res.status, 400, code);
    assert.equal(body.error, code);
  }
  assert.equal(db.orders.length, 0);
});

test('eyni məhsul iki sətirdə birləşir, 20-dən çox olarsa 20 qalır', () => {
  const v = validatePayload(dineIn({ items: [{ id: rid(1), qty: 15 }, { id: rid(1), qty: 10 }] }));
  assert.deepEqual(v.items, [{ id: rid(1), qty: 20 }]);
});

test('mövcud olmayan məhsul → 409 unavailable', async () => {
  db = install();
  const { res, body } = await post(dineIn({ items: [{ id: rid(4), qty: 1 }] }));   // Available:false
  assert.equal(res.status, 409);
  assert.equal(body.error, 'unavailable');
  assert.deepEqual(body.details.missing, [rid(4)]);
  assert.equal(db.orders.length, 0);
});

test('təkrar göndərmə (eyni key) dublikat yaratmır', async () => {
  db = install();
  const payload = dineIn();
  const a = await post(payload);
  const b = await post(payload);
  assert.equal(b.body.duplicate, true);
  assert.equal(b.body.orderNumber, a.body.orderNumber);
  assert.equal(db.orders.length, 1);
  assert.equal(db.telegram.length, 1);
});

test('dublikat yoxlaması Airtable xətasında 502 verir (ikiqat sifariş riski yoxdur)', async () => {
  db = install();
  db.failOrdersGet = true;
  const { res } = await post(dineIn());
  assert.equal(res.status, 502);
  assert.equal(db.orders.length, 0);
});

test('sətirlər yazılmasa sifariş geri silinir və 502', async () => {
  db = install();
  db.failItems = true;
  const { res } = await post(dineIn());
  assert.equal(res.status, 502);
  assert.equal(db.orders.length, 0);
});

test('sifariş yaradılmasa 502', async () => {
  db = install();
  db.failOrderCreate = true;
  assert.equal((await post(dineIn())).res.status, 502);
});

test('Telegram düşsə də sifariş uğurlu olur (notified:false)', async () => {
  db = install();
  db.telegramOk = false;
  const { res, body } = await post(dineIn());
  assert.equal(res.status, 200);
  assert.equal(body.notified, false);
  assert.equal(db.orders.length, 1);
});

test('Telegram konfiqurasiyası yoxdursa bildiriş getmir, sifariş işləyir', async () => {
  db = install();
  const { TELEGRAM_BOT_TOKEN, ...env } = ENV;
  const { res, body } = await post(dineIn(), env);
  assert.equal(res.status, 200);
  assert.equal(body.notified, false);
  assert.equal(db.telegram.length, 0);
});

test('sifariş anında menyu oxunmursa 503 (köhnə keşlə sifariş verilmir)', async () => {
  db = install();
  await onRequestPost({ request: req(dineIn()), env: ENV });     // keşi doldur
  db.failMenu = true;
  const { res } = await post(dineIn());
  assert.equal(res.status, 503);
});

test('TABLE_SECRET: düzgün imza qəbul, səhv/yox imza 403', async () => {
  db = install();
  const env = { ...ENV, TABLE_SECRET: 'gizli' };
  const sig = await tableSignature('gizli', 5);
  assert.equal((await post(dineIn({ sig }), env)).res.status, 200);
  assert.equal((await post(dineIn({ sig: 'a'.repeat(16) }), env)).body.error, 'bad_table_qr');
  assert.equal((await post(dineIn(), env)).res.status, 403);
  const other = await tableSignature('gizli', 6);
  assert.equal((await post(dineIn({ table: 5, sig: other }), env)).res.status, 403);
});

test('TABLE_SECRET çatdırılmaya təsir etmir', async () => {
  db = install();
  const env = { ...ENV, TABLE_SECRET: 'gizli' };
  const { res } = await post({ type: 'Özü götürür', key: goodKey(), name: 'Əli', phone: '0501234567', items: [{ id: rid(1), qty: 1 }] }, env);
  assert.equal(res.status, 200);
});

test('xarab JSON, həddindən böyük gövdə və konfiqurasiya xətası', async () => {
  db = install();
  assert.equal((await post(null, ENV, '{bad')).res.status, 400);
  assert.equal((await post(null, ENV, JSON.stringify({ note: 'x'.repeat(30000) }))).res.status, 413);
  assert.equal((await post(dineIn(), {})).res.status, 500);
});

test('qeyd 300 simvola kəsilir, idarəedici simvollar təmizlənir', async () => {
  db = install();
  await post(dineIn({ note: 'a\u0000b' + 'x'.repeat(400) }));
  const note = db.orders[0].fields.Notes;
  assert.equal(note.length, 300);
  assert.ok(!note.includes('\u0000'));
});
