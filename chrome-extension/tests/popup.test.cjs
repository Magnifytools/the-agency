const { test } = require('node:test');
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
