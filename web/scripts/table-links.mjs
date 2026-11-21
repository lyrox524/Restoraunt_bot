// İstifadə: node scripts/table-links.mjs https://sifarisgo.pages.dev 12 MƏXFİ_AÇAR
// Hər masa üçün imzalı QR linki çıxarır. Bu linkləri QR koda çevirib masalara yapışdır.
import { tableSignature } from '../functions/_lib/order.js';

const [base, count, secret] = process.argv.slice(2);
if (!base || !count || !secret) {
  console.error('İstifadə: node scripts/table-links.mjs <sayt-ünvanı> <masa-sayı> <TABLE_SECRET>');
  process.exit(1);
}
for (let t = 1; t <= Number(count); t++) {
  console.log(`Masa ${t}: ${base.replace(/\/$/, '')}/?t=${t}&s=${await tableSignature(secret, t)}`);
}
