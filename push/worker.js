// Joinville Meteo — Web Push server on Cloudflare Workers (free plan).
// Endpoints: /subscribe /unsubscribe /vapidPublicKey /test
// Cron (scheduled): reads the published alert JSON, dedupes, pushes on Alerta.
import { sendPush } from './webpush.js';
import { evaluateObserved, evaluateForecast } from './alerts.js';

const RANK = { ok: 0, warn: 1, alert: 2 };
const NOTIFY_LEVEL = 'alert';   // notify when worst hazard >= this. Set to 'warn' to also push Atenção.

const cors = (env) => ({
  'Access-Control-Allow-Origin': env.ALLOWED_ORIGIN || '*',
  'Access-Control-Allow-Methods': 'GET,POST,OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type,x-send-secret',
});
const json = (obj, status, env) => new Response(JSON.stringify(obj), {
  status: status || 200, headers: { 'Content-Type': 'application/json', ...cors(env) },
});

async function subKey(endpoint) {
  const h = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(endpoint));
  return 'sub:' + [...new Uint8Array(h)].map(b => b.toString(16).padStart(2, '0')).join('').slice(0, 40);
}

async function sendToAll(env, payload) {
  const vapid = { publicKey: env.VAPID_PUBLIC_KEY, privateKey: env.VAPID_PRIVATE_KEY, subject: env.VAPID_SUBJECT };
  let cursor, total = 0, sent = 0, pruned = 0, failed = 0;
  do {
    const list = await env.SUBSCRIPTIONS.list({ prefix: 'sub:', cursor });
    for (const k of list.keys) {
      total++;
      const raw = await env.SUBSCRIPTIONS.get(k.name); if (!raw) continue;
      let sub; try { sub = JSON.parse(raw); } catch (e) { continue; }
      try {
        const res = await sendPush(sub, payload, vapid);
        if (res.status === 404 || res.status === 410) { await env.SUBSCRIPTIONS.delete(k.name); pruned++; }
        else if (res.ok || res.status === 201 || res.status === 200) sent++;
        else failed++;
      } catch (e) { failed++; }
    }
    cursor = list.list_complete ? null : list.cursor;
  } while (cursor);
  return { total, sent, pruned, failed };
}

function messageFor(source, ev, base) {
  const top = ev.hazards.filter(h => h.level === 'alert');
  const list = (top.length ? top : ev.hazards).map(h => h.txt).join('; ');
  if (source === 'forecast')
    return { title: '⚠️ Joinville — alerta de previsão', body: `Próximas 24 h: ${list}.`, url: base + 'previsao.html', tag: 'joinville-forecast' };
  return { title: '⚠️ Joinville — alerta observado', body: `Agora: ${list}.`, url: base + 'index.html', tag: 'joinville-observed' };
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const p = url.pathname.replace(/\/+$/, '') || '/';
    if (request.method === 'OPTIONS') return new Response(null, { headers: cors(env) });
    try {
      if (p === '/vapidPublicKey' && request.method === 'GET')
        return json({ publicKey: env.VAPID_PUBLIC_KEY }, 200, env);

      if (p === '/subscribe' && request.method === 'POST') {
        const sub = await request.json();
        if (!sub || !sub.endpoint || !sub.keys || !sub.keys.p256dh || !sub.keys.auth)
          return json({ error: 'invalid subscription' }, 400, env);
        await env.SUBSCRIPTIONS.put(await subKey(sub.endpoint), JSON.stringify(sub));
        return json({ ok: true }, 201, env);
      }

      if (p === '/unsubscribe' && request.method === 'POST') {
        const b = await request.json();
        if (!b || !b.endpoint) return json({ error: 'no endpoint' }, 400, env);
        await env.SUBSCRIPTIONS.delete(await subKey(b.endpoint));
        return json({ ok: true }, 200, env);
      }

      if (p === '/test' && request.method === 'POST') {
        const secret = request.headers.get('x-send-secret') || url.searchParams.get('key');
        if (!env.SEND_SECRET || secret !== env.SEND_SECRET) return json({ error: 'unauthorized' }, 401, env);
        const base = (env.SITE_BASE_URL || '').replace(/\/?$/, '/');
        const r = await sendToAll(env, { title: '🔔 Joinville — teste', body: 'Notificações de risco ativadas. Este é um teste.', url: base + 'index.html', tag: 'joinville-test' });
        return json({ ok: true, ...r }, 200, env);
      }

      return json({ error: 'not found' }, 404, env);
    } catch (e) {
      return json({ error: String((e && e.message) || e) }, 500, env);
    }
  },

  async scheduled(event, env, ctx) {
    ctx.waitUntil((async () => {
      const base = (env.SITE_BASE_URL || '').replace(/\/?$/, '/');
      const bust = '?t=' + Date.now();
      const grab = async (u) => { try { const r = await fetch(base + u + bust, { cf: { cacheTtl: 0 } }); return r.ok ? await r.json() : null; } catch (e) { return null; } };
      const [snap, run] = await Promise.all([grab('data/snapshot.json'), grab('data/wrf_forecast.json')]);
      const sources = [];
      if (snap) sources.push(['observed', evaluateObserved(snap)]);
      if (run) sources.push(['forecast', evaluateForecast(run, Date.now())]);
      for (const [source, ev] of sources) {
        const fp = `${ev.level}|${ev.stamp}|${ev.hazards.map(h => h.txt).join('|')}`;
        const prev = await env.SUBSCRIPTIONS.get('state:' + source);
        if (RANK[ev.level] >= RANK[NOTIFY_LEVEL] && fp !== prev) {
          await sendToAll(env, messageFor(source, ev, base));
        }
        await env.SUBSCRIPTIONS.put('state:' + source, fp);
      }
    })());
  },
};
