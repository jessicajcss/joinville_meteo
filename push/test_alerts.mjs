import { heatIndexC, evaluateObserved, evaluateForecast } from './alerts.js';
import fs from 'node:fs';
let pass=0, fail=0; const ok=(n,c)=>{c?(pass++,console.log('  ✓',n)):(fail++,console.log('  ✗ FAIL',n));};

// heat index vs verified values
console.log('Heat index (NWS) vs verified [37.7, 40.4, 48.1, 13.5]:');
const cases=[[30,80,37.7],[32,70,40.4],[36,60,48.1],[14,80,13.5]];
for(const [t,rh,exp] of cases){ const v=heatIndexC(t,rh); ok(`T=${t} RH=${rh} -> ${v.toFixed(1)} (exp ${exp})`, Math.abs(v-exp)<0.15); }

// observed against the real local snapshot
console.log('Observed evaluator on real snapshot.json:');
const snap=JSON.parse(fs.readFileSync('../site/data/snapshot.json'));
const obs=evaluateObserved(snap);
console.log('   ->', JSON.stringify(obs));
ok('observed returns a level', ['ok','warn','alert'].includes(obs.level));
ok('observed matches snapshot rain warn (moderada 3.0)', obs.hazards.some(h=>h.txt.includes('chuva')&&h.level==='warn'));

// forecast against the real local wrf_forecast.json
console.log('Forecast evaluator on real wrf_forecast.json:');
const run=JSON.parse(fs.readFileSync('../site/data/wrf_forecast.json'));
const fc=evaluateForecast(run, Date.parse('2026-07-26T06:00:00Z'));
console.log('   ->', JSON.stringify(fc));
ok('forecast returns a level', ['ok','warn','alert'].includes(fc.level));
ok('forecast produced hazard detail or clean ok', fc.level==='ok' || fc.hazards.length>0);

console.log(`\nRESULT: ${pass} passed, ${fail} failed`);
process.exit(fail?1:0);
