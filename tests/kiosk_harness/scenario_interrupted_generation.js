// A generation that never completes its audio queue (the child taps a
// pre-recorded story mid-generation) must not wedge the GO card forever.
//
// Prints one JSON line: {"posts": <number of /api/generate/story POSTs>}
const { sandbox, calls, getEl } = require('./load.js');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Generation whose SSE body never yields: onComplete never fires.
sandbox.fetch = async (url, opts) => {
  if (String(url).startsWith('/api/generate/story')) {
    calls.generation.push(JSON.parse(opts.body));
    return { ok: true, body: { getReader: () => ({ read: () => new Promise(() => {}) }) } };
  }
  if (url === '/api/capabilities') return { ok: true, json: async () => ({ ai_enabled: true }) };
  if (url === '/api/stories') return { ok: true, json: async () => ({ stories: [] }) };
  return { ok: true, json: async () => ({}), text: async () => '', arrayBuffer: async () => new ArrayBuffer(8) };
};

const PARAM_A = { uid: '23:C4:FB:02', card_type: 'parameter', category: 'lugar', value: 'castillo', emoji: '🏰', label: 'castillo' };
const PARAM_B = { uid: '04:38:9C:92:18:65:80', card_type: 'parameter', category: 'personaje', value: 'buho', emoji: '🦉', label: 'buho' };
const GO = { uid: '27:CB:B9:7A', card_type: 'go', parameters: [] };

const tap = async (p) => { try { await sandbox.handleNfcCardEvent({ data: JSON.stringify(p) }); } catch (_) { /* stub gaps */ } };

(async () => {
  sandbox.aiEnabled = true;
  sandbox.window.aiEnabled = true;
  await sleep(60);

  // 1. First generation starts and hangs.
  await tap(PARAM_A);
  await sleep(200);
  await tap(GO);
  await sleep(400);

  // 2. The generation is abandoned and the kiosk drops back to idle. On the
  //    device this was the audio-failure handler (the Bluetooth speaker), but
  //    a pre-recorded story and the interrupt button reach idle the same way.
  sandbox.transitionTo('idle');
  await sleep(200);

  // 3. A fresh collection + GO must generate again. PARAM_A's chip is still
  //    on screen: dropping to idle restores the previous generation's chips
  //    (D-09), and re-tapping it would toggle it back off.
  await tap(PARAM_B);
  await sleep(200);
  const chipsBeforeGo = getEl('parameter-chips').children.length;
  await tap(GO);
  await sleep(300);

  process.stdout.write(JSON.stringify({ posts: calls.generation.length, chipsBeforeGo }) + '\n');
  process.exit(0);
})();
