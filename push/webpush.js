// Web Push (RFC 8291 aes128gcm + RFC 8292 VAPID) using only the Web Crypto API.
// Runs unchanged on Cloudflare Workers and in Node 18+ (globalThis.crypto.subtle).
// Verified against the reference http_ece decryptor — see push/test_webpush.mjs.

const enc = new TextEncoder();
export const b64urlToBytes = (s) => {
  s = s.replace(/-/g, '+').replace(/_/g, '/');
  s += '='.repeat((4 - (s.length % 4)) % 4);
  const bin = atob(s);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
};
export const bytesToB64url = (bytes) => {
  let bin = '';
  const b = new Uint8Array(bytes);
  for (let i = 0; i < b.length; i++) bin += String.fromCharCode(b[i]);
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
};
const concat = (...arrs) => {
  let n = 0; for (const a of arrs) n += a.length;
  const out = new Uint8Array(n); let o = 0;
  for (const a of arrs) { out.set(a, o); o += a.length; }
  return out;
};
const u32be = (n) => new Uint8Array([(n>>>24)&255,(n>>>16)&255,(n>>>8)&255,n&255]);

async function hkdf(salt, ikm, info, len) {
  const key = await crypto.subtle.importKey('raw', ikm, 'HKDF', false, ['deriveBits']);
  const bits = await crypto.subtle.deriveBits({ name: 'HKDF', hash: 'SHA-256', salt, info }, key, len * 8);
  return new Uint8Array(bits);
}

// Encrypt `payloadBytes` for a PushSubscription {keys:{p256dh, auth}}.
// Returns the aes128gcm message body (Uint8Array) to POST as the request body.
export async function encryptPayload(subscription, payloadBytes, saltOverride, asKeyOverride) {
  const uaPublic = b64urlToBytes(subscription.keys.p256dh);   // 65 bytes (0x04||X||Y)
  const authSecret = b64urlToBytes(subscription.keys.auth);   // 16 bytes

  const asKeys = asKeyOverride || await crypto.subtle.generateKey({ name: 'ECDH', namedCurve: 'P-256' }, true, ['deriveBits']);
  const asPublic = new Uint8Array(await crypto.subtle.exportKey('raw', asKeys.publicKey)); // 65 bytes
  const uaKey = await crypto.subtle.importKey('raw', uaPublic, { name: 'ECDH', namedCurve: 'P-256' }, false, []);
  const ecdh = new Uint8Array(await crypto.subtle.deriveBits({ name: 'ECDH', public: uaKey }, asKeys.privateKey, 256)); // 32 bytes

  // RFC 8291 §3.4 — derive the input keying material
  const keyInfo = concat(enc.encode('WebPush: info\0'), uaPublic, asPublic);
  const ikm = await hkdf(authSecret, ecdh, keyInfo, 32);

  const salt = saltOverride || crypto.getRandomValues(new Uint8Array(16));
  const cek = await hkdf(salt, ikm, enc.encode('Content-Encoding: aes128gcm\0'), 16);
  const nonce = await hkdf(salt, ikm, enc.encode('Content-Encoding: nonce\0'), 12);

  const plaintext = concat(payloadBytes, new Uint8Array([2])); // single final record → 0x02 delimiter
  const aesKey = await crypto.subtle.importKey('raw', cek, 'AES-GCM', false, ['encrypt']);
  const ct = new Uint8Array(await crypto.subtle.encrypt({ name: 'AES-GCM', iv: nonce, tagLength: 128 }, aesKey, plaintext));

  const rs = 4096;
  const header = concat(salt, u32be(rs), new Uint8Array([asPublic.length]), asPublic);
  return concat(header, ct);
}

// RFC 8292 — build the "Authorization: vapid t=<jwt>, k=<pub>" header value for one endpoint.
export async function vapidHeader(endpoint, vapidPublicKeyB64, vapidPrivateKeyB64, subject, nowSec) {
  const pub = b64urlToBytes(vapidPublicKeyB64);               // 65 bytes
  const jwk = { kty: 'EC', crv: 'P-256', d: vapidPrivateKeyB64,
                x: bytesToB64url(pub.slice(1, 33)), y: bytesToB64url(pub.slice(33, 65)), ext: true };
  const key = await crypto.subtle.importKey('jwk', jwk, { name: 'ECDSA', namedCurve: 'P-256' }, false, ['sign']);
  const header = bytesToB64url(enc.encode(JSON.stringify({ typ: 'JWT', alg: 'ES256' })));
  const now = nowSec || Math.floor(Date.now() / 1000);
  const claims = { aud: new URL(endpoint).origin, exp: now + 12 * 3600, sub: subject };
  const payload = bytesToB64url(enc.encode(JSON.stringify(claims)));
  const signingInput = header + '.' + payload;
  const sig = new Uint8Array(await crypto.subtle.sign({ name: 'ECDSA', hash: 'SHA-256' }, key, enc.encode(signingInput)));
  const jwt = signingInput + '.' + bytesToB64url(sig);
  return { authorization: `vapid t=${jwt}, k=${vapidPublicKeyB64}`, jwt };
}

// Send one notification. Returns the fetch Response. Caller prunes on 404/410.
export async function sendPush(subscription, payloadObj, vapid, opts = {}) {
  const payloadBytes = enc.encode(JSON.stringify(payloadObj));
  const body = await encryptPayload(subscription, payloadBytes);
  const { authorization } = await vapidHeader(subscription.endpoint, vapid.publicKey, vapid.privateKey, vapid.subject);
  return fetch(subscription.endpoint, {
    method: 'POST',
    headers: {
      'Authorization': authorization,
      'Content-Encoding': 'aes128gcm',
      'Content-Type': 'application/octet-stream',
      'TTL': String(opts.ttl || 86400),
      'Urgency': opts.urgency || 'high',
    },
    body,
  });
}
