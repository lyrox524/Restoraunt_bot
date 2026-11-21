// Sifarişin yoxlanması, qiymətləndirilməsi, masa imzası və admin mətni. Şəbəkədən asılı deyil.

export const TYPES = ['Masada', 'Çatdırılma', 'Özü götürür'];
export const MAX_QTY = 20;
export const MAX_LINES = 40;

export class OrderError extends Error {
  constructor(code, message, status = 400, details) {
    super(message);
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

const RECORD_ID = /^rec[A-Za-z0-9]{14}$/;
const KEY = /^[A-Za-z0-9-]{8,64}$/;

export function validPhone(text) {
  const t = String(text ?? '').trim();
  const digits = t.replace(/\D/g, '');
  return /^[+\d\s()\-]{7,20}$/.test(t) && digits.length >= 7 && digits.length <= 15;
}

const clean = (v, max) => String(v ?? '').replace(/[\u0000-\u001f\u007f]/g, ' ').trim().slice(0, max);

/** Müştəridən gələn məlumatı yoxlayır və normallaşdırır. Qiymət qəbul edilmir: yalnız id və miqdar. */
export function validatePayload(p) {
  if (!p || typeof p !== 'object' || Array.isArray(p)) throw new OrderError('bad_request', 'Sifariş məlumatı düzgün deyil.');
  if (p.website) throw new OrderError('bad_request', 'Sifariş məlumatı düzgün deyil.');   // honeypot

  if (!TYPES.includes(p.type)) throw new OrderError('bad_type', 'Sifariş növünü seçin.');
  if (!KEY.test(String(p.key ?? ''))) throw new OrderError('bad_request', 'Sifariş məlumatı düzgün deyil.');

  if (!Array.isArray(p.items) || p.items.length < 1) throw new OrderError('empty_cart', 'Səbət boşdur.');
  if (p.items.length > MAX_LINES) throw new OrderError('too_many_items', 'Səbətdə çox məhsul var.');
  const qty = new Map();
  for (const it of p.items) {
    const id = String(it?.id ?? '');
    const q = Number(it?.qty);
    if (!RECORD_ID.test(id) || !Number.isInteger(q) || q < 1 || q > MAX_QTY) {
      throw new OrderError('bad_item', `Bir məhsuldan ən çox ${MAX_QTY} ədəd sifariş etmək olar.`);
    }
    qty.set(id, Math.min(MAX_QTY, (qty.get(id) || 0) + q));
  }

  const out = {
    type: p.type,
    key: String(p.key),
    items: [...qty.entries()].map(([id, q]) => ({ id, qty: q })),
    name: clean(p.name, 80),
    phone: clean(p.phone, 30),
    address: clean(p.address, 300),
    note: clean(p.note, 300),
    table: null,
    sig: clean(p.sig, 64),
  };

  if (p.type === 'Masada') {
    const t = Number(p.table);
    if (!Number.isInteger(t) || t < 1 || t > 999) throw new OrderError('bad_table', 'Masa nömrəsini düzgün daxil edin.');
    out.table = t;
    out.phone = '';
    out.address = '';
  } else {
    if (out.name.length < 2) throw new OrderError('bad_name', 'Ad və soyadınızı daxil edin.');
    if (!validPhone(out.phone)) throw new OrderError('bad_phone', 'Telefon nömrəsini düzgün daxil edin (məsələn: 050 123 45 67).');
    if (p.type === 'Çatdırılma') {
      if (out.address.length < 5) throw new OrderError('bad_address', 'Tam ünvanı daxil edin.');
    } else {
      out.address = '';
    }
  }
  return out;
}

/** Sifariş sətirlərini cari menyu ilə üzləşdirir. Qiymət həmişə serverdəki menyudandır. */
export function priceOrder(order, menu) {
  const byId = new Map(menu.map((m) => [m.id, m]));
  const missing = [];
  const lines = [];
  for (const { id, qty } of order.items) {
    const m = byId.get(id);
    if (!m) { missing.push(id); continue; }
    lines.push({ id, name: m.name, qty, unit: m.price, sum: Math.round(m.price * qty * 100) / 100 });
  }
  if (missing.length) {
    throw new OrderError(
      'unavailable',
      'Bəzi məhsullar artıq mövcud deyil. Menyu yeniləndi, səbəti yoxlayın.',
      409,
      { missing },
    );
  }
  const total = Math.round(lines.reduce((s, l) => s + l.sum, 0) * 100) / 100;
  return { lines, total };
}

// ---- Masa QR imzası: qəsdən saxta masa sifarişinin qarşısı (TABLE_SECRET təyin olunubsa)
const enc = new TextEncoder();

export async function tableSignature(secret, table) {
  const key = await crypto.subtle.importKey('raw', enc.encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const mac = await crypto.subtle.sign('HMAC', key, enc.encode(`table:${Number(table)}`));
  return [...new Uint8Array(mac)].map((b) => b.toString(16).padStart(2, '0')).join('').slice(0, 16);
}

export async function verifyTable(secret, table, sig) {
  if (!sig) return false;
  const expected = await tableSignature(secret, table);
  if (expected.length !== sig.length) return false;
  let diff = 0;
  for (let i = 0; i < expected.length; i++) diff |= expected.charCodeAt(i) ^ sig.charCodeAt(i);   // sabit vaxtlı müqayisə
  return diff === 0;
}

export function adminText(order, priced, orderNumber, currency = 'AZN') {
  const lines = [`🆕 Yeni sifariş${orderNumber ? ` №${orderNumber}` : ''}`, `Növ: ${order.type}`];
  if (order.table !== null) lines.push(`📍 Masa: ${order.table}`);
  if (order.name) lines.push(`👤 ${order.name}`);
  if (order.phone) lines.push(`📞 ${order.phone}`);
  if (order.address) lines.push(`🏠 ${order.address}`);
  lines.push('');
  for (const l of priced.lines) lines.push(`• ${l.name} × ${l.qty}`);
  if (order.note) lines.push('', `📝 ${order.note}`);
  lines.push('', `💰 ${priced.total.toFixed(2)} ${currency}`);
  return lines.join('\n');
}
