const { test: nodeTest } = require('node:test');
const test = (name, fn) => nodeTest(name, { timeout: 10000 }, fn);
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function setup() {
  const state = { token: 'session-a', notifications: [], badges: [], removes: 0, meetings: [] };
  let capture;
  const noop = () => {};
  const context = vm.createContext({
    chrome: {
      runtime: { onInstalled: { addListener: noop }, onStartup: { addListener: noop }, onMessage: { addListener: noop } },
      contextMenus: { create: noop, onClicked: { addListener: fn => { capture = fn; } } },
      storage: {
        local: { get: async () => ({ am_token: state.token }), remove: async () => { state.removes++; state.token = ''; } },
        session: { get: async () => ({ notifiedMeetings: state.meetings }), set: async data => { state.meetings = data.notifiedMeetings; } },
      },
      notifications: { create: info => state.notifications.push(info) },
      action: { setBadgeText: info => state.badges.push(info.text), setBadgeBackgroundColor: noop },
      alarms: { create: noop, onAlarm: { addListener: noop } },
    },
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../background.js'), 'utf8'), context);
  return { state, context, capture, run: code => vm.runInContext(code, context) };
}
function deferred() { let resolve; const promise = new Promise(r => { resolve = r; }); return { promise, resolve }; }

for (const status of [201, 401]) {
  test(`background capture ${status} from an old token neither notifies nor clears the new identity`, async () => {
    const h = setup(), gate = deferred(), started = deferred();
    h.context.fetch = async () => { started.resolve(); await gate.promise; return { ok: status === 201, status }; };
    const pending = h.capture({ menuItemId: 'am-capture-page' }, { title: 'Synthetic', url: 'https://example.invalid' });
    await started.promise; h.state.token = 'session-b'; gate.resolve(); await pending;
    assert.equal(h.state.token, 'session-b');
    assert.equal(h.state.removes, 0);
    assert.deepEqual(h.state.notifications, []);
  });
}

test('background delayed count JSON cannot overwrite the current account badge', async () => {
  const h = setup(), gate = deferred(), started = deferred();
  h.context.fetch = async () => ({ ok: true, json: async () => { started.resolve(); await gate.promise; return { count: 99 }; } });
  const pending = h.run('updateBadge("session-a")');
  await started.promise; h.state.token = 'session-b'; gate.resolve(); await pending;
  assert.deepEqual(h.state.badges, []);
});

test('background delayed meetings cannot notify for the previous account', async () => {
  const h = setup(), gate = deferred(), started = deferred();
  h.context.fetch = async () => ({ ok: true, json: async () => { started.resolve(); await gate.promise; return [{ id: 1, title: 'Old meeting', minutes_until: 10 }]; } });
  const pending = h.run('checkUpcomingMeetings("session-a")');
  await started.promise; h.state.token = 'session-b'; gate.resolve(); await pending;
  assert.deepEqual(h.state.notifications, []);
  assert.deepEqual(h.state.meetings, []);
});

test('background current-account capture still notifies and updates the badge', async () => {
  const h = setup();
  h.context.fetch = async url => ({ ok: true, status: 201, json: async () => ({ count: 2 }) });
  await h.capture({ menuItemId: 'am-capture-page' }, { title: 'Synthetic', url: 'https://example.invalid' });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(h.state.notifications.length, 1);
  assert.deepEqual(h.state.badges, ['2']);
});
