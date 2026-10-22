// A story card tapped while another story is on screen (playing, paused, or
// on the thank-you page) must start the new story instead of being ignored.
//
// Prints one JSON line with the kiosk state after each step.
const vm = require('vm');
const { sandbox, calls } = require('./load.js');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const STORY_A = { id: 'story-a', nfc_uid: '04:AA:AA:AA', audio_file: 'audio.mp3', emoji: '🐻', led_color: '#ff0000' };
const STORY_B = { id: 'story-b', nfc_uid: '04:BB:BB:BB', audio_file: 'audio.mp3', emoji: '🐸', led_color: '#00ff00' };
const STORIES = { [STORY_A.nfc_uid]: STORY_A, [STORY_B.nfc_uid]: STORY_B };

const baseFetch = sandbox.fetch;
sandbox.fetch = async (url, opts) => {
  const m = String(url).match(/^\/api\/stories\/nfc\/(.+)$/);
  if (m) {
    calls.fetch.push({ url, method: 'GET' });
    const story = STORIES[decodeURIComponent(m[1])];
    return story ? { ok: true, json: async () => story } : { ok: false, json: async () => ({}) };
  }
  return baseFetch(url, opts);
};

const tap = async (story) => {
  await sandbox.handleNfcCardEvent({ data: JSON.stringify({ uid: story.nfc_uid, card_type: 'story' }) });
};
const snapshot = () => ({
  state: vm.runInContext('currentState', sandbox),
  story: vm.runInContext('currentStory && currentStory.id', sandbox),
  paused: vm.runInContext('isPaused', sandbox),
});

(async () => {
  await sleep(60);
  const out = {};

  // 1. Story A starts; retapping it pauses (existing behavior).
  await tap(STORY_A);
  await sleep(400);
  await tap(STORY_A);
  await sleep(50);
  out.pausedA = snapshot();

  // 2. Story B replaces the paused story A.
  await tap(STORY_B);
  await sleep(400);
  out.afterSwitch = snapshot();

  // 3. On the thank-you page, story A starts again, and the page's 4 s
  //    back-to-idle timer must not cut it off.
  sandbox.transitionTo('thankyou', STORY_B);
  await sleep(200);
  await tap(STORY_A);
  await sleep(4300);
  out.afterThankyou = snapshot();

  process.stdout.write(JSON.stringify(out) + '\n');
  process.exit(0);
})();
