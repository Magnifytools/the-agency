const { test: nodeTest } = require('node:test');
const test = (name, fn) => nodeTest(name, { timeout: 10000 }, fn);
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function setup() {
  const state = { token: 'session-a', notifications: [], badges: [], removes: 0, meetingStates: {} };
  let capture;
  const noop = () => {};
  const context = vm.createContext({
    chrome: {
      runtime: { onInstalled: { addListener: noop }, onStartup: { addListener: noop }, onMessage: { addListener: noop } },
      contextMenus: { create: noop, onClicked: { addListener: fn => { capture = fn; } } },
      storage: {
        local: {
          get: async key => key === 'am_meeting_notifications_v2' ? { am_meeting_notifications_v2: state.meetingStates } : ({ am_token: state.token }),
          set: async data => { if (data.am_meeting_notifications_v2) state.meetingStates = data.am_meeting_notifications_v2; },
          remove: async () => { state.removes++; state.token = ''; },
        },
        session: { get: async () => ({}), set: async () => {} },
      },
      notifications: { create: (id, info, callback) => { state.notifications.push({ id, ...info }); if (callback) callback(id); } },
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
  assert.deepEqual(h.state.meetingStates, {});
});

test('background current-account capture still notifies and updates the badge', async () => {
  const h = setup();
  h.context.fetch = async url => ({ ok: true, status: 201, json: async () => ({ count: 2 }) });
  await h.capture({ menuItemId: 'am-capture-page' }, { title: 'Synthetic', url: 'https://example.invalid' });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(h.state.notifications.length, 1);
  assert.deepEqual(h.state.badges, ['2']);
});

test('meeting occurrence is reserved durably and notified once for the current user', async () => {
  const h = setup();
  h.context.fetch = async () => ({ ok: true, json: async () => ({ user_id: 7, occurrences: [{ occurrence_id: 42, title: 'Reunión próxima', content: 'Empieza en 10 minutos' }] }) });
  await h.run('checkUpcomingMeetings("session-a")');
  await h.run('checkUpcomingMeetings("session-a")');
  assert.equal(h.state.notifications.length, 1);
  assert.equal(h.state.notifications[0].id, 'agency-meeting:7:42');
  assert.equal(h.state.meetingStates['7:42'], 'confirmed');
});

test('uncertain notification creation stays pending and is not replayed', async () => {
  const h = setup();
  h.context.chrome.notifications.create = (id, info) => { h.state.notifications.push({ id, ...info }); };
  h.context.fetch = async () => ({ ok: true, json: async () => ({ user_id: 7, occurrences: [{ occurrence_id: 99, title: 'Reunión', content: 'Ahora' }] }) });
  await h.run('checkUpcomingMeetings("session-a")');
  await h.run('checkUpcomingMeetings("session-a")');
  assert.equal(h.state.notifications.length, 1);
  assert.equal(h.state.meetingStates['7:99'], 'pending');
});
