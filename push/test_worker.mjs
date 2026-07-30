import crypto from 'node:crypto';
import webpush from 'web-push';
import worker from './worker.js';
let pass=0, fail=0; const ok=(n,c)=>{c?(pass++,console.log('  ✓',n)):(fail++,console.log('  ✗ FAIL',n));};

// --- mock KV ---
function mockKV(){ const m=new Map(); return {
  async get(k){ return m.has(k)?m.get(k):null; },
  async put(k,v){ m.set(k,v); },
  async delete(k){ m.delete(k); },
  async list({prefix,cursor}={}){ const keys=[...m.keys()].filter(k=>!prefix||k.startsWith(prefix)).map(name=>({name})); return {keys,list_complete:true,cursor:null}; },
  _map:m };
}
const vk = webpush.generateVAPIDKeys();
const SITE='https://jessicajcss.github.io/joinville_meteo/';
function makeEnv(kv){ return { SUBSCRIPTIONS:kv, VAPID_PUBLIC_KEY:vk.publicKey, VAPID_PRIVATE_KEY:vk.privateKey,
  VAPID_SUBJECT:'mailto:jessica.jcss@gmail.com', SITE_BASE_URL:SITE, ALLOWED_ORIGIN:'https://jessicajcss.github.io', SEND_SECRET:'s3cret' }; }
function fakeSub(){ const e=crypto.createECDH('prime256v1'); e.generateKeys();
  return { endpoint:'https://push.example.com/'+crypto.randomBytes(6).toString('hex'),
    keys:{ p256dh:e.getPublicKey().toString('base64url'), auth:crypto.randomBytes(16).toString('base64url') } }; }

// --- mock global fetch: site JSON GETs + push endpoint POSTs ---
let pushCalls=0; const state={snap:null,run:null};
globalThis.fetch = async (u, opts)=>{
  u=String(u);
  if(u.startsWith(SITE)){
    if(u.includes('snapshot.json')) return new Response(JSON.stringify(state.snap),{status:state.snap?200:404});
    if(u.includes('wrf_forecast.json')) return new Response(JSON.stringify(state.run),{status:state.run?200:404});
    return new Response('{}',{status:404});
  }
  if(u.startsWith('https://push.example.com/')){ pushCalls++; return new Response(null,{status:201}); }
  return new Response(null,{status:404});
};
const req=(path,method,body,headers)=>new Request('https://w.dev'+path,{method,headers:{'Content-Type':'application/json',...(headers||{})},body:body?JSON.stringify(body):undefined});
const ctx={ _p:[], waitUntil(p){ this._p.push(p); } };
const runCron=async(env)=>{ ctx._p=[]; await worker.scheduled({},env,ctx); await Promise.all(ctx._p); };

// 1) subscribe + vapidPublicKey
{ const kv=mockKV(), env=makeEnv(kv);
  const r=await worker.fetch(req('/vapidPublicKey','GET'),env); const j=await r.json();
  ok('GET /vapidPublicKey returns key', j.publicKey===vk.publicKey);
  const sub=fakeSub();
  const r2=await worker.fetch(req('/subscribe','POST',sub),env);
  ok('POST /subscribe -> 201', r2.status===201);
  ok('subscription stored in KV', [...kv._map.keys()].some(k=>k.startsWith('sub:')));
  const r3=await worker.fetch(req('/subscribe','POST',{bad:1}),env);
  ok('invalid subscribe -> 400', r3.status===400);
  // unsubscribe
  const r4=await worker.fetch(req('/unsubscribe','POST',{endpoint:sub.endpoint}),env);
  ok('POST /unsubscribe -> ok', r4.status===200 && ![...kv._map.keys()].some(k=>k.startsWith('sub:')));
}

// 2) /test auth + fan-out
{ const kv=mockKV(), env=makeEnv(kv); pushCalls=0;
  await worker.fetch(req('/subscribe','POST',fakeSub()),env);
  await worker.fetch(req('/subscribe','POST',fakeSub()),env);
  const bad=await worker.fetch(req('/test','POST',{}),env);
  ok('/test without secret -> 401', bad.status===401);
  const good=await worker.fetch(req('/test?key=s3cret','POST',{}),env); const gj=await good.json();
  ok('/test sends to all subscribers (2)', gj.sent===2 && pushCalls===2);
}

// 3) scheduled cron: alert fires once, then deduped
{ const kv=mockKV(), env=makeEnv(kv); pushCalls=0;
  await worker.fetch(req('/subscribe','POST',fakeSub()),env);
  state.snap={ generated_at:'2026-07-30T12:00:00Z', alert:{ active:true,
     rain:{value_mmph:22,station:'Morro do Meio',class:'forte',level:'alert'},
     temp:{min:20,max:24,heat_level:'ok',cold_level:'ok'}, wind:{value_ms:5,level:'ok'}, heat:{app_c:25,level:'ok'} } };
  state.run=null;
  await runCron(env);
  ok('cron sends on new Alerta', pushCalls===1);
  await runCron(env);
  ok('cron deduped (same fingerprint -> no resend)', pushCalls===1);
  // level drops to ok, then a NEW alerta later -> notifies again
  state.snap={ generated_at:'2026-07-30T13:00:00Z', alert:{ active:false, rain:{value_mmph:1,level:'ok'}, temp:{heat_level:'ok',cold_level:'ok'}, wind:{level:'ok'}, heat:{level:'ok'} } };
  await runCron(env);
  state.snap={ generated_at:'2026-07-30T20:00:00Z', alert:{ active:true, rain:{value_mmph:30,station:'Centro',class:'forte',level:'alert'}, temp:{heat_level:'ok',cold_level:'ok'}, wind:{level:'ok'}, heat:{level:'ok'} } };
  await runCron(env);
  ok('cron re-notifies a new later Alerta', pushCalls===2);
}

console.log(`\nRESULT: ${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
