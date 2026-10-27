const { test: nodeTest } = require('node:test');
const test = (name, fn) => nodeTest(name, { timeout: 10000 }, fn);
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

// background.js con un almacenamiento de verdad (en memoria) y una API simulada.
function setup({ prefs, store = {} } = {}) {
  const state = { store: { am_token: 'session-a', ...store }, notifications: [], badges: [], colors: [], tabs: [], cleared: [], requests: [] };
  if (prefs) state.store.am_desktop_prefs_v1 = prefs;
  const listeners = {};
  const noop = () => {};
  const context = vm.createContext({
    chrome: {
      runtime: { onInstalled: { addListener: noop }, onStartup: { addListener: noop }, onMessage: { addListener: noop } },
      contextMenus: { create: noop, onClicked: { addListener: noop } },
      storage: {
        local: {
          get: async (keys) => Object.fromEntries([].concat(keys).filter((k) => k in state.store).map((k) => [k, structuredClone(state.store[k])])),
          set: async (data) => { Object.assign(state.store, structuredClone(data)); },
          remove: async () => {},
        },
      },
      notifications: {
        create: (id, info) => { state.notifications.push({ id, ...info }); },
        clear: (id) => { state.cleared.push(id); },
        onClicked: { addListener: (fn) => { listeners.click = fn; } },
      },
      tabs: { create: (info) => { state.tabs.push(info.url); } },
      action: { setBadgeText: (info) => state.badges.push(info.text), setBadgeBackgroundColor: (info) => state.colors.push(info.color), setTitle: noop },
      alarms: { create: noop, onAlarm: { addListener: noop } },
    },
    structuredClone,
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../background.js'), 'utf8'), context);
  const respond = (body) => {
    context.fetch = async (url) => { state.requests.push(url); return { ok: true, json: async () => (typeof body === 'function' ? body(url) : body) }; };
  };
  return { state, context, listeners, respond, run: (code) => vm.runInContext(code, context) };
}

const feed = (extra = {}) => ({ user_id: 2, next_after_id: 50, alerts: 0, activity: [], critical: [], ...extra });
const mention = (id) => ({ id, type: 'task_mention', title: `David te ha mencionado ${id}`, message: 'Mira esto', link_url: `/tasks?task=${id}` });

test('la primera vez en un navegador sólo marca desde dónde seguir', async () => {
  const h = setup({ prefs: { enabled: true, quietStart: '', quietEnd: '' } });
  h.respond(feed({ activity: [mention(40)], critical: [{ id: 7, fingerprint: 'a', title: 'Web caída', link_url: '/incidents' }] }));
  await h.run('checkDesktopNotices("session-a")');
  assert.deepEqual(h.state.notifications, []);
  assert.equal(h.state.store.am_desktop_notices_v1.afterId, 50);
  assert.deepEqual(h.state.store.am_desktop_notices_v1.seenCritical, ['7:a']);
  assert.ok(h.state.requests[0].endsWith('/api/notifications/desktop'));
});

test('avisa de lo nuevo y de cada alerta crítica una sola vez; al pulsar abre la app', async () => {
  const h = setup({ prefs: { enabled: true, quietStart: '', quietEnd: '' }, store: { am_desktop_notices_v1: { userId: 2, afterId: 30, seenCritical: ['7:a'] } } });
  h.respond(feed({ activity: [mention(41)], critical: [
    { id: 7, fingerprint: 'a', title: 'Ya avisada', link_url: '/incidents' },
    { id: 8, fingerprint: 'b', title: 'Web caída', message: 'Desde las 10:02', link_url: '/clients/3?tab=web' },
  ] }));
  await h.run('checkDesktopNotices("session-a")');
  assert.ok(h.state.requests[0].endsWith('/api/notifications/desktop?after_id=30'));
  assert.deepEqual(h.state.notifications.map((n) => n.title), ['Web caída', 'David te ha mencionado 41']);

  h.listeners.click(h.state.notifications[1].id);
  assert.deepEqual(h.state.tabs, ['https://agency.magnifytools.com/tasks?task=41']);

  h.respond(feed({ next_after_id: 60, critical: [{ id: 8, fingerprint: 'b', title: 'Web caída', link_url: '/x' }] }));
  await h.run('checkDesktopNotices("session-a")');
  assert.equal(h.state.notifications.length, 2);
  // Si la alerta cambia (otra huella), vuelve a avisar.
  h.respond(feed({ next_after_id: 60, critical: [{ id: 8, fingerprint: 'c', title: 'Web caída otra vez', link_url: '/x' }] }));
  await h.run('checkDesktopNotices("session-a")');
  assert.equal(h.state.notifications.at(-1).title, 'Web caída otra vez');
});

test('una ráfaga se resume y un enlace ajeno no abre nada', async () => {
  const h = setup({ prefs: { enabled: true, quietStart: '', quietEnd: '' }, store: { am_desktop_notices_v1: { userId: 2, afterId: 0, seenCritical: [] } } });
  h.respond(feed({ activity: [1, 2, 3, 4, 5].map(mention) }));
  await h.run('checkDesktopNotices("session-a")');
  assert.equal(h.state.notifications.length, 4);
  assert.equal(h.state.notifications[3].title, '2 novedades más');
  h.listeners.click('agency-notice:activity:9|//evil.example/x');
  h.listeners.click('agency-meeting:1:2');
  assert.deepEqual(h.state.tabs, []);
});

test('en horas de silencio no avisa ni avanza; desactivado avanza sin avisar', async () => {
  const quiet = setup({ prefs: { enabled: true, quietStart: '00:00', quietEnd: '23:59' }, store: { am_desktop_notices_v1: { userId: 2, afterId: 30, seenCritical: [] } } });
  quiet.respond(feed({ activity: [mention(41)] }));
  await quiet.run('checkDesktopNotices("session-a")');
  assert.deepEqual(quiet.state.notifications, []);
  assert.equal(quiet.state.store.am_desktop_notices_v1.afterId, 30);

  const off = setup({ prefs: { enabled: false, quietStart: '', quietEnd: '' }, store: { am_desktop_notices_v1: { userId: 2, afterId: 30, seenCritical: [] } } });
  off.respond(feed({ activity: [mention(41)] }));
  await off.run('checkDesktopNotices("session-a")');
  assert.deepEqual(off.state.notifications, []);
  assert.equal(off.state.store.am_desktop_notices_v1.afterId, 50);
});

test('otra cuenta en el mismo navegador empieza de cero', async () => {
  const h = setup({ prefs: { enabled: true, quietStart: '', quietEnd: '' }, store: { am_desktop_notices_v1: { userId: 1, afterId: 30, seenCritical: [] } } });
  h.respond(feed({ activity: [mention(41)] }));
  await h.run('checkDesktopNotices("session-a")');
  assert.deepEqual(h.state.notifications, []);
  assert.equal(h.state.store.am_desktop_notices_v1.userId, 2);
});

test('las horas de silencio pueden cruzar la medianoche', () => {
  const h = setup();
  const at = (hh, mm) => `new Date(2026, 9, 27, ${hh}, ${mm})`;
  assert.equal(h.run(`inQuietHours({ quietStart: "20:00", quietEnd: "08:00" }, ${at(23, 30)})`), true);
  assert.equal(h.run(`inQuietHours({ quietStart: "20:00", quietEnd: "08:00" }, ${at(7, 59)})`), true);
  assert.equal(h.run(`inQuietHours({ quietStart: "20:00", quietEnd: "08:00" }, ${at(8, 0)})`), false);
  assert.equal(h.run(`inQuietHours({ quietStart: "13:00", quietEnd: "15:00" }, ${at(14, 0)})`), true);
  assert.equal(h.run(`inQuietHours({ quietStart: "", quietEnd: "" }, ${at(14, 0)})`), false);
});

test('la insignia cuenta alertas en rojo y, sin ellas, las notas por aclarar', async () => {
  const h = setup();
  h.respond((url) => ({ count: url.includes('/incidents/') ? 3 : 5 }));
  await h.run('updateBadge("session-a")');
  assert.deepEqual([h.state.badges.at(-1), h.state.colors.at(-1)], ['3', '#EF4444']);
  h.respond((url) => ({ count: url.includes('/incidents/') ? 0 : 5 }));
  await h.run('updateBadge("session-a")');
  assert.deepEqual([h.state.badges.at(-1), h.state.colors.at(-1)], ['5', '#6366f1']);
});
