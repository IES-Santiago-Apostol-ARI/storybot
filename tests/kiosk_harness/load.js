const fs = require('fs');
const vm = require('vm');
const path = require('path');
const { document, El, getEl } = require('./dom.js');

const REPO = path.resolve(__dirname, '..', '..');
const calls = { fetch: [], generation: [] };

const sandbox = {
  document,
  console,
  setTimeout, clearTimeout, setInterval, clearInterval,
  Promise, JSON, Math, Date, Set, Map, Array, Object, String, Number, Error,
  AbortController, TextDecoder, TextEncoder, URL,
  encodeURIComponent,
  Audio: function(){ return new El('audio'); },
  AudioContext: function(){ return { createGain: ()=>({connect(){},gain:{value:0}}), createBufferSource: ()=>({connect(){},start(){},buffer:null}), decodeAudioData: ()=>Promise.resolve({}), destination:{}, state:'running', resume:()=>Promise.resolve() }; },
  EventSource: function(){ return { addEventListener(){}, close(){}, onerror:null }; },
  fetch: async (url, opts) => {
    calls.fetch.push({ url, method: (opts&&opts.method)||'GET' });
    if (url === '/api/capabilities')
      return { ok:true, json: async()=>({ ai_enabled:true, tts_available:true, cover_gen:true, printer:true }) };
    if (url === '/api/stories')
      return { ok:true, json: async()=>({ stories: [] }) };
    if (String(url).startsWith('/api/generate/story')) {
      calls.generation.push(opts ? JSON.parse(opts.body) : null);
      return { ok:true, body:{ getReader: ()=>({ read: async()=>({done:true,value:undefined}) }) } };
    }
    return { ok:true, json: async()=>({}), text: async()=>'', arrayBuffer: async()=>new ArrayBuffer(8) };
  },
};
sandbox.addEventListener = ()=>{};
sandbox.removeEventListener = ()=>{};
sandbox.requestAnimationFrame = (cb)=>setTimeout(cb,0);
sandbox.cancelAnimationFrame = (id)=>clearTimeout(id);
sandbox.performance = { now: ()=>Date.now() };
sandbox.localStorage = { getItem:()=>null, setItem:()=>{}, removeItem:()=>{} };
sandbox.navigator = { userAgent:'harness' };
sandbox.location = { href:'http://localhost/', origin:'http://localhost' };
sandbox.window = sandbox;
sandbox.globalThis = sandbox;
sandbox.self = sandbox;

// /shared/sse.js provides createReconnectingEventSource
const ssePath = path.join(REPO, 'static/shared/sse.js');
if (fs.existsSync(ssePath)) {
  vm.createContext(sandbox);
  try { vm.runInContext(fs.readFileSync(ssePath,'utf8'), sandbox); } catch(e){ console.error('sse.js:', e.message); }
} else {
  vm.createContext(sandbox);
}
sandbox.createReconnectingEventSource = sandbox.createReconnectingEventSource || function(){ return { close(){} }; };

const src = fs.readFileSync(path.join(REPO,'static/children/script.js'),'utf8');
vm.runInContext(src, sandbox);

module.exports = { sandbox, calls, getEl, El };
