import { getMenu, groupMenu } from '../_lib/airtable.js';
import { json } from '../_lib/http.js';

export async function onRequestGet({ env }) {
  if (!env.AIRTABLE_TOKEN || !env.AIRTABLE_BASE_ID) {
    return json(500, { ok: false, error: 'config', message: 'Sistem hələ qurulmayıb.' });
  }
  const items = await getMenu(env);
  if (!items) {
    return json(503, { ok: false, error: 'menu_unavailable', message: 'Menyu hazırda yüklənmir. Bir az sonra yenidən cəhd edin.' });
  }
  return json(200, {
    ok: true,
    restaurant: env.RESTAURANT_NAME || '',
    currency: env.CURRENCY || 'AZN',
    tableSigRequired: !!env.TABLE_SECRET,
    delivery: env.ENABLE_DELIVERY !== '0',
    pickup: env.ENABLE_PICKUP !== '0',
    categories: groupMenu(items),
  }, { 'Cache-Control': 'public, max-age=15' });
}
