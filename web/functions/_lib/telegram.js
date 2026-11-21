/** Mətbəx/admin qrupuna bildiriş. Uğursuzluq sifarişi pozmur: yalnız false qaytarır. */
export async function notifyAdmin(env, text) {
  if (!env.TELEGRAM_BOT_TOKEN || !env.ADMIN_CHAT_ID) return false;
  try {
    const res = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chat_id: String(env.ADMIN_CHAT_ID), text }),
      signal: AbortSignal.timeout(5000),
    });
    return res.ok;
  } catch {
    return false;   // token loqa yazılmır
  }
}
