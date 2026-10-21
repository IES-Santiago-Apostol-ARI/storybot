// The hidden reload gesture (hold the top-left corner) must fire only for a
// still finger inside the corner, held for the full duration.
//
// Prints one JSON line mapping each case name to how many reloads it caused.
const { sandbox } = require('./load.js');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const HOLD_MS = 50;
const ZONE_PX = 80;

function gesture() {
  const g = { reloads: 0 };
  g.handlers = sandbox.createReloadGesture({
    zonePx: ZONE_PX,
    holdMs: HOLD_MS,
    onTrigger: () => { g.reloads += 1; },
  });
  return g;
}

const ev = (pointerId, clientX, clientY) => ({ pointerId, clientX, clientY });

const cases = {
  async heldInCorner() {
    const g = gesture();
    g.handlers.down(ev(1, 10, 10));
    g.handlers.move(ev(1, 30, 20));
    await sleep(HOLD_MS * 2);
    return g.reloads;
  },
  async releasedEarly() {
    const g = gesture();
    g.handlers.down(ev(1, 10, 10));
    await sleep(HOLD_MS / 3);
    g.handlers.up(ev(1, 10, 10));
    await sleep(HOLD_MS * 2);
    return g.reloads;
  },
  async startedOutsideCorner() {
    const g = gesture();
    g.handlers.down(ev(1, 400, 300));
    await sleep(HOLD_MS * 2);
    return g.reloads;
  },
  async draggedOutOfCorner() {
    const g = gesture();
    g.handlers.down(ev(1, 10, 10));
    g.handlers.move(ev(1, 200, 10));
    await sleep(HOLD_MS * 2);
    return g.reloads;
  },
  async otherFingerLiftedElsewhere() {
    const g = gesture();
    g.handlers.down(ev(1, 10, 10));
    g.handlers.down(ev(2, 400, 300));
    g.handlers.up(ev(2, 400, 300));
    await sleep(HOLD_MS * 2);
    return g.reloads;
  },
  async cancelledByBrowser() {
    const g = gesture();
    g.handlers.down(ev(1, 10, 10));
    g.handlers.up(ev(1, 10, 10)); // pointercancel is wired to up()
    await sleep(HOLD_MS * 2);
    return g.reloads;
  },
};

(async () => {
  const out = {};
  for (const [name, run] of Object.entries(cases)) out[name] = await run();
  console.log(JSON.stringify(out));
  process.exit(0);
})();
