const { test: nodeTest } = require('node:test');
const test = (name, fn) => nodeTest(name, { timeout: 10000 }, fn);
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { JSDOM } = require('jsdom');
const extension = path.resolve(__dirname, '..');
const tick = () => new Promise(resolve => setImmediate(resolve));
const projects = Array.from({ length: 128 }, (_, n) => ({ id: n + 1, name: `Proyecto ${n + 1}`, client_id: n + 1 }));
const clients = Array.from({ length: 135 }, (_, n) => ({ id: n + 1, name: `Cliente ${n + 1}` }));
const tasks = Array.from({ length: 126 }, (_, n) => ({ id: n + 1, title: `Tarea ${n + 1}`, status: 'pending' }));

async function setup(t) {
  const dom = new JSDOM(fs.readFileSync(path.join(extension, 'popup.html'), 'utf8'), { runScripts: 'outside-only', url: 'https://extension.invalid/popup.html' });
  t.after(() => dom.window.close());
  const requests = [];
  const state = { failPath: null, failPage: 2, status: 503, posted: null };
  dom.window.chrome = {
    storage: { local: { get: async () => ({}), set: async () => {}, remove: async () => {} } },
    runtime: { sendMessage: () => {} }, tabs: { create: () => {} },
  };
  dom.window.fetch = async (url, options = {}) => {
    const u = new URL(url);
    requests.push({ url: u, options });
    const page = Number(u.searchParams.get('page') || 1);
    const pageSize = Number(u.searchParams.get('page_size') || 25);
    let status = 200, data;
    if (options.method === 'POST' && u.pathname === '/api/inbox') {
      state.posted = JSON.parse(options.body);
      status = state.captureStatus || 201;
      data = { id: 1, detail: 'Captura no disponible' };
    } else if (u.pathname === state.failPath && page === state.failPage) {
      status = state.status; data = { detail: 'No disponible temporalmente' };
    } else if (['/api/clients', '/api/projects', '/api/tasks'].includes(u.pathname)) {
      const rows = state.rows?.[u.pathname] || { '/api/clients': clients, '/api/projects': projects, '/api/tasks': tasks }[u.pathname];
      data = { items: rows.slice((page - 1) * pageSize, page * pageSize), total: rows.length, page, page_size: pageSize };
      if (state.malformed && page === 2) data = { items: [] };
    } else if (u.pathname === '/api/inbox/count') data = { count: 0 };
    else if (u.pathname === '/api/timer/active') data = null;
    else throw new Error(`Unexpected network request: ${url}`);
    return { ok: status >= 200 && status < 300, status, json: async () => data };
  };
  const context = dom.getInternalVMContext();
  vm.runInContext(fs.readFileSync(path.join(extension, 'popup.js'), 'utf8'), context);
  await tick();
  const run = code => vm.runInContext(code, context);
  run('token = "synthetic-token"');
  const get = id => dom.window.document.getElementById(id);
  return { dom, run, get, requests, state };
}

test('all selector pages use page/page_size, including clients/projects beyond 25 and 100', async t => {
  const { run, get, requests } = await setup(t);
  await run('loadProjectsAndClients()');
  assert.equal(get('assign-select').options.length, 1 + clients.length + projects.length);
  for (const id of ['task-client-select', 'qc-timer-client', 'qc-manual-client']) assert.equal(get(id).options.length, clients.length + 1);
  assert.equal(get('task-project-select').options.length, projects.length + 1);
  for (const req of requests) {
    assert.equal(req.url.searchParams.has('limit'), false);
    assert.ok(req.url.searchParams.has('page_size'));
  }
  assert.ok(requests.some(r => r.url.pathname === '/api/projects' && r.url.searchParams.get('page') === '2'));
});

test('intermediate page failure leaves every previous selector and selection intact; retry restores data', async t => {
  const { run, get, state } = await setup(t);
  await run('loadProjectsAndClients()');
  get('assign-select').value = 'project:128';
  get('task-client-select').value = '128';
  get('task-project-select').value = '128';
  get('qc-timer-client').value = '135';
  const before = get('assign-select').innerHTML;
  state.failPath = '/api/projects';
  await run('loadProjectsAndClients()');
  assert.equal(get('assign-select').innerHTML, before);
  assert.equal(get('assign-select').value, 'project:128');
  assert.equal(get('task-client-select').value, '128');
  assert.equal(get('task-project-select').value, '128');
  assert.equal(get('qc-timer-client').value, '135');
  assert.equal(get('assignment-load-error').classList.contains('hidden'), false);
  state.failPath = null;
  get('assignment-retry').click();
  for (let n = 0; n < 10 && !get('assignment-load-error').classList.contains('hidden'); n++) await tick();
  assert.equal(get('assignment-load-error').classList.contains('hidden'), true);
  assert.equal(get('assign-select').value, 'project:128');
});

test('first-load failure is visible and does not publish a partial page', async t => {
  const { run, get, state } = await setup(t);
  state.failPath = '/api/clients';
  await run('loadProjectsAndClients()');
  assert.equal(get('assign-select').options.length, 1);
  assert.equal(get('assignment-load-error').classList.contains('hidden'), false);
});

for (const [selection, assignment] of [['project:128', { project_id: 128, client_id: 128 }], ['client:135', { client_id: 135 }]]) {
  test(`DOM Inbox capture preserves explicit ${selection} and link`, async t => {
    const { run, get, state } = await setup(t);
    run('showMainView()');
    await run('loadProjectsAndClients()');
    get('assign-select').value = selection;
    get('note-text').value = 'Nota sintética';
    get('link-url').value = 'https://example.com/context';
    get('note-text').dispatchEvent(new (get('note-text').ownerDocument.defaultView.Event)('input'));
    get('capture-btn').click();
    await tick();
    assert.deepEqual(state.posted, { raw_text: 'Nota sintética', source: 'chrome_extension', link_url: 'https://example.com/context', ...assignment });
    assert.equal(get('success-msg').classList.contains('hidden'), false);
  });
}

test('failed Inbox capture retains the draft and assignment for retry', async t => {
  const { run, get, state, dom } = await setup(t);
  run('showMainView()');
  await run('loadProjectsAndClients()');
  state.captureStatus = 503;
  get('assign-select').value = 'project:128';
  get('note-text').value = 'No perder borrador';
  get('note-text').dispatchEvent(new dom.window.Event('input'));
  get('capture-btn').click();
  await tick();
  assert.equal(get('note-text').value, 'No perder borrador');
  assert.equal(get('assign-select').value, 'project:128');
  assert.equal(get('capture-error').classList.contains('hidden'), false);
  assert.equal(get('capture-btn').disabled, false);
});

test('timer and manual task selectors load all pages and preserve selection on a page error', async t => {
  const { run, get, state } = await setup(t);
  await run('loadTimerTasks()');
  assert.equal(get('timer-task-select').options.length, tasks.length + 1);
  get('timer-task-select').value = '126';
  get('manual-task-select').value = '125';
  state.failPath = '/api/tasks';
  await run('loadTimerTasks()');
  assert.equal(get('timer-task-select').value, '126');
  assert.equal(get('manual-task-select').value, '125');
  assert.equal(get('timer-error').classList.contains('hidden'), false);
});

test('malformed later page is an error, never a successful partial list', async t => {
  const { run, get, state } = await setup(t);
  state.malformed = true;
  await run('loadProjectsAndClients()');
  assert.equal(get('assign-select').options.length, 1);
  assert.equal(get('assignment-load-error').classList.contains('hidden'), false);
});

test('forbidden list exposes an error without clearing the previous selection', async t => {
  const { run, get, state } = await setup(t);
  await run('loadProjectsAndClients()');
  get('assign-select').value = 'client:135';
  state.failPath = '/api/clients'; state.failPage = 1; state.status = 403;
  await run('loadProjectsAndClients()');
  assert.equal(get('assign-select').value, 'client:135');
  assert.equal(get('assignment-load-error').classList.contains('hidden'), false);
});

test('expired session clears cached choices and opens login', async t => {
  const { run, get, state } = await setup(t);
  await run('loadProjectsAndClients()');
  state.failPath = '/api/projects'; state.status = 401;
  await run('loadProjectsAndClients()');
  assert.equal(get('assign-select').options.length, 1);
  assert.equal(get('task-client-select').options.length, 1);
  assert.equal(get('login-view').classList.contains('hidden'), false);
});

test('response arriving after logout cannot restore previous-account selectors', async t => {
  const { run, get, dom } = await setup(t);
  await run('loadProjectsAndClients()');
  const originalFetch = dom.window.fetch;
  let release, reached;
  const gate = new Promise(resolve => { release = resolve; });
  const started = new Promise(resolve => { reached = resolve; });
  dom.window.fetch = async (...args) => {
    const url = new URL(args[0]);
    if (url.pathname === '/api/projects' && url.searchParams.get('page') === '2') { reached(); await gate; }
    return originalFetch(...args);
  };
  const loading = run('loadProjectsAndClients()');
  await started;
  run('token = ""; showLoginView()');
  release();
  await loading;
  assert.equal(get('assign-select').options.length, 1);
  assert.equal(get('task-project-select').options.length, 1);
});

test('task tab paginates and retains previously rendered cards on intermediate failure', async t => {
  const { run, get, state } = await setup(t);
  await run('loadTasks()');
  assert.equal(get('tasks-list').querySelectorAll('.task-card').length, tasks.length);
  state.failPath = '/api/tasks';
  await run('loadTasks()');
  assert.equal(get('tasks-list').querySelectorAll('.task-card').length, tasks.length);
  assert.ok(get('tasks-list').querySelector('.tasks-error[role="alert"]'));
});

test('capture finishing does not erase a draft or assignment edited while sending', async t => {
  const { run, get, state, dom } = await setup(t);
  run('showMainView()');
  await run('loadProjectsAndClients()');
  get('note-text').value = 'Primera nota';
  get('assign-select').value = 'project:128';
  const originalFetch = dom.window.fetch;
  let release, reached;
  const gate = new Promise(resolve => { release = resolve; });
  const started = new Promise(resolve => { reached = resolve; });
  let captures = 0;
  dom.window.fetch = async (...args) => {
    const response = await originalFetch(...args);
    if (args[1]?.method === 'POST' && new URL(args[0]).pathname === '/api/inbox') {
      captures++; reached(); await gate;
    }
    return response;
  };
  const capturing = run('captureNote()');
  await started;
  get('note-text').value = 'Segunda nota';
  get('assign-select').value = 'client:135';
  get('note-text').dispatchEvent(new dom.window.Event('input'));
  await run('captureNote()'); // keyboard shortcut must not submit twice
  release();
  await capturing;
  assert.equal(captures, 1);
  assert.equal(state.posted.project_id, 128);
  assert.equal(state.posted.client_id, 128);
  assert.equal(get('note-text').value, 'Segunda nota');
  assert.equal(get('assign-select').value, 'client:135');
  assert.equal(get('capture-btn').disabled, false);
  await run('captureNote()');
  assert.equal(captures, 2);
  assert.equal(state.posted.client_id, 135);
  assert.equal(state.posted.project_id, undefined);
});


test('a removed selected project never silently becomes an unassigned capture', async t => {
  const { run, get, state } = await setup(t);
  await run('loadProjectsAndClients()');
  get('assign-select').value = 'project:128';
  get('note-text').value = 'Asignación explícita';
  state.rows = { '/api/projects': projects.filter(project => project.id !== 128) };
  await run('loadProjectsAndClients()');
  assert.equal(get('assign-select').value, 'project:128');
  assert.equal(get('assign-select').selectedOptions[0].disabled, true);
  await run('captureNote()');
  assert.equal(state.posted, null);
  assert.equal(get('capture-error').classList.contains('hidden'), false);
});

// Real popup login/logout events, with all server and Chrome APIs mocked.
async function loginAs(h, token, email) {
  const fetch = h.dom.window.fetch;
  h.dom.window.fetch = async (url, options) => new URL(url).pathname === '/api/auth/login'
    ? { ok: true, status: 200, json: async () => ({ access_token: token }) }
    : fetch(url, options);
  h.get('email').value = email;
  h.get('password').value = 'synthetic-password';
  h.get('login-form').dispatchEvent(new h.dom.window.Event('submit', { bubbles: true, cancelable: true }));
  for (let n = 0; n < 20 && h.run('token') !== token; n++) await tick();
  await tick();
  assert.equal(h.run('token'), token);
}
function deferred() {
  let resolve, reject;
  const promise = new Promise((a, b) => { resolve = a; reject = b; });
  return { promise, resolve, reject };
}

for (const outcome of [201, 401, 'network-error']) {
  test(`late capture ${outcome} cannot change a newer session, draft or pending request`, async t => {
    const h = await setup(t);
    await loginAs(h, 'session-a', 'a@example.test');
    const a = deferred(), b = deferred(), reachedA = deferred(), reachedB = deferred();
    const fetch = h.dom.window.fetch;
    h.dom.window.fetch = async (url, options = {}) => {
      if (new URL(url).pathname === '/api/inbox' && options.method === 'POST') {
        const old = options.headers.Authorization === 'Bearer session-a';
        (old ? reachedA : reachedB).resolve();
        await (old ? a : b).promise;
        if (old && outcome === 'network-error') throw new Error('old network error');
        const status = old ? outcome : 201;
        return { ok: status === 201, status, json: async () => ({}) };
      }
      return fetch(url, options);
    };
    h.get('note-text').value = 'A pending';
    const first = h.run('captureNote()');
    await reachedA.promise;
    h.get('settings-btn').click();
    await loginAs(h, 'session-b', 'b@example.test');
    h.get('note-text').value = 'B pending';
    const second = h.run('captureNote()');
    await reachedB.promise;
    a.resolve(); await first;
    assert.equal(h.run('token'), 'session-b');
    assert.equal(h.get('note-text').value, 'B pending');
    assert.equal(h.get('capture-btn').disabled, true);
    assert.equal(h.get('capture-error').classList.contains('hidden'), true);
    assert.equal(h.get('success-msg').classList.contains('hidden'), true);
    assert.equal(h.get('main-view').classList.contains('hidden'), false);
    b.resolve(); await second;
    assert.equal(h.get('note-text').value, '');
  });
}

test('late timer JSON from previous login cannot replace the new active timer', async t => {
  const h = await setup(t);
  await loginAs(h, 'session-a', 'a@example.test');
  const body = deferred(), reached = deferred();
  const fetch = h.dom.window.fetch;
  h.dom.window.fetch = async (url, options = {}) => {
    if (new URL(url).pathname === '/api/timer/active') {
      const old = options.headers.Authorization === 'Bearer session-a';
      return { ok: true, status: 200, json: async () => {
        if (old) { reached.resolve(); await body.promise; }
        return { started_at: '2026-09-17T10:00:00Z', task_title: old ? 'Old timer' : 'New timer' };
      } };
    }
    return fetch(url, options);
  };
  const pending = h.run('loadActiveTimer()'); await reached.promise;
  h.get('settings-btn').click();
  await loginAs(h, 'session-b', 'b@example.test');
  await h.run('loadActiveTimer()');
  body.resolve(); await pending;
  assert.equal(h.get('timer-task-name').textContent, 'New timer');
  assert.equal(h.get('timer-active').classList.contains('hidden'), false);
  assert.equal(h.run('token'), 'session-b');
});

test('late timer stop cannot hide a newer account timer or reset its pending button', async t => {
  const h = await setup(t);
  await loginAs(h, 'session-a', 'a@example.test');
  const response = deferred(), reached = deferred();
  const fetch = h.dom.window.fetch;
  h.dom.window.fetch = async (url, options = {}) => {
    if (new URL(url).pathname === '/api/timer/stop') { reached.resolve(); await response.promise; return { ok: true, status: 200 }; }
    return fetch(url, options);
  };
  h.get('timer-stop-btn').click(); await reached.promise;
  h.get('settings-btn').click(); await loginAs(h, 'session-b', 'b@example.test');
  h.run('showActiveTimer({started_at:"2026-09-17T10:00:00Z", task_title:"New timer"})');
  h.get('timer-stop-btn').disabled = true;
  response.resolve(); await tick(); await tick();
  assert.equal(h.get('timer-task-name').textContent, 'New timer');
  assert.equal(h.get('timer-active').classList.contains('hidden'), false);
  assert.equal(h.get('timer-stop-btn').disabled, true);
});

test('drafts stay with their authenticated email and restore safely after reconnecting', async t => {
  const h = await setup(t);
  await loginAs(h, 'session-a', 'a@example.test'); await h.run('loadProjectsAndClients()');
  h.get('note-text').value = 'A draft'; h.get('assign-select').value = 'project:128';
  h.get('settings-btn').click(); await loginAs(h, 'session-b', 'b@example.test');
  assert.equal(h.get('note-text').value, '');
  h.get('note-text').value = 'B draft';
  h.get('settings-btn').click(); await loginAs(h, 'session-a2', 'a@example.test');
  await h.run('loadProjectsAndClients()');
  assert.equal(h.get('note-text').value, 'A draft');
  assert.equal(h.get('assign-select').value, 'project:128');
});

test('repeated main view setup does not attach additional capture listeners', async t => {
  const h = await setup(t);
  let attached = 0;
  const original = h.get('note-text').addEventListener;
  h.get('note-text').addEventListener = function(...args) { attached++; return original.apply(this, args); };
  h.run('showMainView(); showMainView(); showMainView()');
  await tick();
  assert.equal(attached, 0);
});

test('epoch rejects an old response even when the token string is reused', async t => {
  const h = await setup(t);
  await loginAs(h, 'same-token', 'a@example.test');
  const response = deferred(), reached = deferred();
  const fetch = h.dom.window.fetch;
  h.dom.window.fetch = async (url, options = {}) => {
    if (new URL(url).pathname === '/api/inbox' && options.method === 'POST') {
      reached.resolve(); await response.promise; return { ok: true, status: 201 };
    }
    return fetch(url, options);
  };
  h.get('note-text').value = 'Sent before logout';
  const pending = h.run('captureNote()'); await reached.promise;
  h.get('settings-btn').click(); await loginAs(h, 'same-token', 'a@example.test');
  h.get('note-text').value = 'New login draft';
  response.resolve(); await pending;
  assert.equal(h.get('note-text').value, 'New login draft');
  assert.equal(h.get('success-msg').classList.contains('hidden'), true);
});

test('a pending storage removal is serialized before the newer login token write', async t => {
  const h = await setup(t), remove = deferred(), removing = deferred();
  let stored = '';
  h.dom.window.chrome.storage.local.set = async values => { stored = values.am_token; };
  h.dom.window.chrome.storage.local.remove = async () => { removing.resolve(); await remove.promise; stored = ''; };
  await loginAs(h, 'session-a', 'a@example.test');
  h.get('settings-btn').click(); await removing.promise;
  await loginAs(h, 'session-b', 'b@example.test');
  remove.resolve();
  for (let n = 0; n < 20 && stored !== 'session-b'; n++) await tick();
  assert.equal(stored, 'session-b');
  assert.equal(h.run('token'), 'session-b');
});

test('reconnected task drafts cannot submit unavailable assignments before selectors finish loading', async t => {
  const h = await setup(t);
  await loginAs(h, 'session-a', 'a@example.test'); await h.run('loadProjectsAndClients()');
  h.get('task-title').value = 'Task draft';
  h.get('task-client-select').value = '128';
  h.get('task-project-select').value = '128';
  h.get('settings-btn').click();
  h.state.failPath = '/api/projects'; h.state.failPage = 1;
  await loginAs(h, 'session-a2', 'a@example.test');
  await h.run('createTaskDirect()');
  assert.equal(h.requests.some(r => r.url.pathname === '/api/tasks' && r.options.method === 'POST'), false);
  assert.equal(h.get('task-create-btn').disabled, true);
  assert.equal(h.get('task-title').value, 'Task draft');
});
