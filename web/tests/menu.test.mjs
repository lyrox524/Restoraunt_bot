import test, { afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { onRequestGet } from '../functions/api/menu.js';
import { ENV, install, menuRecord, rid, seedMenu } from './helpers.mjs';

let db;
afterEach(() => db?.restore());

const get = async (env = ENV) => {
  const res = await onRequestGet({ env });
  return { res, body: await res.json() };
};

test('menyu kateqoriyalara bölünür, aktiv olmayan və qiymətsiz məhsullar çıxarılır', async () => {
  db = install();
  const { res, body } = await get();
  assert.equal(res.status, 200);
  const names = body.categories.flatMap((c) => c.items.map((i) => i.name));
  assert.deepEqual([...names].sort(), ['Armudu çayı', 'Dolma', 'Qutab', 'Çoban salatı'].sort());
  assert.ok(!names.includes('Bitib') && !names.includes('Qiymətsiz'));
});

test('kateqoriya və məhsul sırası Sort Order-ə görədir', async () => {
  db = install();
  const { body } = await get();
  assert.deepEqual(body.categories.map((c) => c.name), ['Əsas yemək', 'Başlanğıc', 'Salat', 'İçki']);
});

test('məhsul sahələri düzgün çevrilir (şəkil, teq, seçilmiş)', async () => {
  db = install();
  const { body } = await get();
  const all = body.categories.flatMap((c) => c.items);
  const dolma = all.find((i) => i.name === 'Dolma');
  assert.equal(dolma.price, 12);
  assert.equal(dolma.featured, true);
  assert.equal(dolma.description, 'Yarpaq dolması');
  assert.deepEqual(all.find((i) => i.name === 'Çoban salatı').tags, ['Vegan']);
  assert.equal(all.find((i) => i.name === 'Armudu çayı').photo, 'https://x/l.jpg');
  assert.equal(all.find((i) => i.name === 'Qutab').photo, null);
});

test('səhifələmə: Airtable offset ilə bütün məhsullar oxunur', async () => {
  db = install(seedMenu(), { pageSize: 2 });
  const { body } = await get();
  assert.equal(body.categories.flatMap((c) => c.items).length, 4);
  assert.ok(db.calls.filter((c) => c.table === 'tblMenu').length >= 3);
});

test('keş: TTL daxilində ikinci sorğu Airtable-a getmir', async () => {
  db = install();
  await get({ ...ENV, MENU_CACHE_TTL: '60' });
  const n = db.calls.length;
  await get({ ...ENV, MENU_CACHE_TTL: '60' });
  assert.equal(db.calls.length, n);
});

test('429 olarsa təkrar cəhd edilir və menyu gəlir', async () => {
  db = install();
  db.rateLimited = 2;
  const { res } = await get();
  assert.equal(res.status, 200);
});

test('Airtable düşübsə və keş yoxdursa 503 qaytarır', async () => {
  db = install();
  db.failMenu = true;
  const { res, body } = await get();
  assert.equal(res.status, 503);
  assert.equal(body.error, 'menu_unavailable');
});

test('Airtable düşəndə köhnə keş istifadə olunur', async () => {
  db = install();
  const env = { ...ENV, MENU_CACHE_TTL: '0' };
  assert.equal((await get(env)).res.status, 200);
  db.failMenu = true;
  assert.equal((await get(env)).res.status, 200);
});

test('konfiqurasiya yoxdursa 500', async () => {
  db = install();
  const { res } = await get({});
  assert.equal(res.status, 500);
});

test('restoran adı, valyuta və bayraqlar cavabdadır', async () => {
  db = install();
  const { body } = await get({ ...ENV, RESTAURANT_NAME: 'Nuş', TABLE_SECRET: 's', ENABLE_DELIVERY: '0' });
  assert.equal(body.restaurant, 'Nuş');
  assert.equal(body.currency, 'AZN');
  assert.equal(body.tableSigRequired, true);
  assert.equal(body.delivery, false);
  assert.equal(body.pickup, true);
});

test('qiymət 0.1+0.2 kimi float xətası yaratmır (yuvarlaqlaşdırma)', async () => {
  db = install([menuRecord(1, { Price: 5.555 })]);
  const { body } = await get();
  assert.equal(body.categories[0].items[0].price, 5.56);
  assert.equal(rid(1).length, 17);
});
