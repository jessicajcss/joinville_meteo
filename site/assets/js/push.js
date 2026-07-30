// Joinville Meteo — Web Push client.
// After deploying the Cloudflare Worker, set WORKER_URL and VAPID_PUBLIC_KEY below.
(function () {
  var WORKER_URL = 'https://joinville-push.YOUR-SUBDOMAIN.workers.dev'; // <-- your Worker URL
  var VAPID_PUBLIC_KEY = 'REPLACE_WITH_YOUR_VAPID_PUBLIC_KEY';          // <-- your VAPID public key

  var supported = ('serviceWorker' in navigator) && ('PushManager' in window) && ('Notification' in window);
  var unconfigured = VAPID_PUBLIC_KEY.indexOf('REPLACE') === 0 || WORKER_URL.indexOf('YOUR-SUBDOMAIN') !== -1;

  function b64ToU8(b) {
    var pad = '='.repeat((4 - b.length % 4) % 4);
    var s = (b + pad).replace(/-/g, '+').replace(/_/g, '/');
    var raw = atob(s), out = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
    return out;
  }
  async function currentSub() { var reg = await navigator.serviceWorker.ready; return reg.pushManager.getSubscription(); }

  async function subscribe() {
    var reg = await navigator.serviceWorker.ready;
    var perm = await Notification.requestPermission();
    if (perm !== 'granted') throw new Error('Permissão de notificação negada.');
    var sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToU8(VAPID_PUBLIC_KEY) });
    var r = await fetch(WORKER_URL + '/subscribe', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(sub) });
    if (!r.ok) throw new Error('Não foi possível registrar no servidor.');
    return sub;
  }
  async function unsubscribe() {
    var sub = await currentSub(); if (!sub) return;
    try { await fetch(WORKER_URL + '/unsubscribe', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ endpoint: sub.endpoint }) }); } catch (e) {}
    await sub.unsubscribe();
  }

  async function refresh(btn, note) {
    if (!supported) { btn.disabled = true; btn.textContent = '🔔 Alertas indisponíveis'; if (note) note.textContent = 'Este navegador não suporta notificações push.'; return; }
    if (unconfigured) { btn.disabled = true; btn.textContent = '🔔 Alertas (servidor a configurar)'; if (note) note.textContent = 'Falta configurar o Worker — veja CLOUDFLARE_PUSH_SETUP.md.'; return; }
    var standalone = window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
    var iOS = /iP(hone|ad|od)/.test(navigator.platform) || (navigator.userAgent.indexOf('Mac') !== -1 && navigator.maxTouchPoints > 1);
    var sub = await currentSub();
    if (sub) { btn.disabled = false; btn.dataset.on = '1'; btn.textContent = '🔔 Alertas ativados ✓'; if (note) note.textContent = 'Você receberá alertas de risco neste aparelho. Toque para desativar.'; }
    else {
      btn.dataset.on = ''; btn.textContent = '🔔 Receber alertas de risco';
      if (iOS && !standalone) { btn.disabled = true; if (note) note.textContent = 'No iPhone: use “Compartilhar → Adicionar à Tela de Início” e abra o app; depois ative aqui.'; }
      else { btn.disabled = false; if (note) note.textContent = 'Notificação no aparelho quando houver Alerta. Recurso em fase de teste.'; }
    }
  }
  function init() {
    var btn = document.getElementById('pushBtn'); if (!btn) return;
    var note = document.getElementById('pushNote');
    btn.addEventListener('click', async function () {
      btn.disabled = true;
      try { if (btn.dataset.on) await unsubscribe(); else await subscribe(); }
      catch (e) { if (note) note.textContent = '⚠️ ' + (e.message || e); }
      refresh(btn, note);
    });
    refresh(btn, note);
  }
  if (document.readyState !== 'loading') init(); else addEventListener('DOMContentLoaded', init);
})();
