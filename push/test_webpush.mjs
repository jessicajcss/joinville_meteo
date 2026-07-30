import crypto from 'node:crypto';
import ece from 'http_ece';
import webpush from 'web-push';
import * as jose from 'jose';
import { encryptPayload, vapidHeader, b64urlToBytes, bytesToB64url } from './webpush.js';

const b64url = (buf) => Buffer.from(buf).toString('base64url');
let pass = 0, fail = 0;
const ok = (name, cond) => { if (cond) { pass++; console.log('  ✓', name); } else { fail++; console.log('  ✗ FAIL', name); } };

// ---- 1) Payload encryption round-trips through the reference ECE decryptor ----
console.log('AES128GCM payload encryption vs reference http_ece:');
for (const msg of ['{"title":"Joinville","body":"Alerta de chuva forte"}', 'x', 'á'.repeat(500)]) {
  const ecdh = crypto.createECDH('prime256v1'); ecdh.generateKeys();
  const p256dh = ecdh.getPublicKey();            // 65-byte UA public
  const auth = crypto.randomBytes(16);
  const sub = { endpoint: 'https://push.example.com/xyz', keys: { p256dh: b64url(p256dh), auth: b64url(auth) } };
  const payload = Buffer.from(msg, 'utf8');
  const body = await encryptPayload(sub, new Uint8Array(payload));   // MY encryption
  // reference decrypt (this is exactly what a browser/push service does)
  const dec = ece.decrypt(Buffer.from(body), { version: 'aes128gcm', privateKey: ecdh, authSecret: auth });
  ok(`round-trip len=${payload.length}`, Buffer.compare(dec, payload) === 0);
}

// ---- 2) VAPID JWT is a valid ES256 token with correct claims ----
console.log('VAPID ES256 JWT:');
const vk = webpush.generateVAPIDKeys();               // { publicKey, privateKey } base64url
const endpoint = 'https://fcm.googleapis.com/fcm/send/abc123';
const { jwt, authorization } = await vapidHeader(endpoint, vk.publicKey, vk.privateKey, 'mailto:jessica.jcss@gmail.com');
// verify signature with the PUBLIC key, independently, via jose
const pub = b64urlToBytes(vk.publicKey);
const spkiJwk = { kty: 'EC', crv: 'P-256', x: bytesToB64url(pub.slice(1,33)), y: bytesToB64url(pub.slice(33,65)) };
const pubKey = await jose.importJWK(spkiJwk, 'ES256');
let verified = null;
try { verified = await jose.jwtVerify(jwt, pubKey, { audience: 'https://fcm.googleapis.com' }); } catch(e){ verified = null; }
ok('JWT signature verifies with VAPID public key', !!verified);
ok('aud = endpoint origin', verified && verified.payload.aud === 'https://fcm.googleapis.com');
ok('sub present', verified && verified.payload.sub === 'mailto:jessica.jcss@gmail.com');
ok('exp within ~12h', verified && verified.payload.exp - Math.floor(Date.now()/1000) > 11*3600 && verified.payload.exp - Math.floor(Date.now()/1000) <= 12*3600);
ok('Authorization header shape "vapid t=..., k=..."', /^vapid t=[\w-]+\.[\w-]+\.[\w-]+, k=[\w-]+$/.test(authorization));

// ---- 3) full sendPush request body also decrypts (uses generateRequestDetails as oracle for header shape) ----
console.log('Interop sanity — reference web-push builds an equivalent request:');
const ecdh2 = crypto.createECDH('prime256v1'); ecdh2.generateKeys();
const sub2 = { endpoint, keys: { p256dh: b64url(ecdh2.getPublicKey()), auth: b64url(crypto.randomBytes(16)) } };
webpush.setVapidDetails('mailto:jessica.jcss@gmail.com', vk.publicKey, vk.privateKey);
const ref = webpush.generateRequestDetails(sub2, Buffer.from('{"title":"t","body":"b"}'), { contentEncoding: 'aes128gcm' });
ok('reference body decrypts with http_ece (confirms our decrypt oracle)',
   (() => { const d = ece.decrypt(ref.body, { version:'aes128gcm', privateKey: ecdh2, authSecret: b64urlToBytes(sub2.keys.auth) }); return d.toString()==='{"title":"t","body":"b"}'; })());

console.log(`\nRESULT: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
