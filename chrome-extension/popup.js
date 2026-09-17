// The Agency - Chrome Extension
// Popup script with Capture, Timer, and Tasks tabs

const API_URL = "https://agency.magnifytools.com";

const STORAGE_KEYS = {
  token: "am_token",
  email: "am_email",
};

// Every async operation belongs to one popup session, including JSON parsing.
function captureSession() { return { token, epoch: sessionEpoch }; }
function isCurrentSession(session) { return session.epoch === sessionEpoch && session.token === token; }
function requireCurrentSession(session) {
  if (!isCurrentSession(session)) throw new Error("La sesión ha cambiado");
}
async function sessionFetch(session, url, options) {
  requireCurrentSession(session);
  const response = await fetch(url, options);
  requireCurrentSession(session);
  if (response.status === 401) {
    endSession();
    throw new Error("La sesión ha caducado. Vuelve a conectar.");
  }
  return {
    ok: response.ok, status: response.status,
    json: async () => {
      const data = await response.json();
      requireCurrentSession(session);
      return data;
    },
  };
}
function scheduleForSession(callback, delay) {
  const session = captureSession();
  const id = setTimeout(() => {
    sessionTimeouts.delete(id);
    if (isCurrentSession(session)) callback();
  }, delay);
  sessionTimeouts.add(id);
}
function persistSession(session) {
  const email = accountEmail;
  // Serialize writes from this popup: an old remove cannot finish after a new set.
  storageWrites = storageWrites.catch(() => {}).then(() => {
    if (!isCurrentSession(session)) return;
    return session.token
      ? chrome.storage.local.set({ [STORAGE_KEYS.token]: session.token, [STORAGE_KEYS.email]: email })
      : chrome.storage.local.remove(STORAGE_KEYS.token);
  });
  return storageWrites;
}

// Helper: extract error message from API response
function getDetail(err, fallback) {
  if (typeof err.detail === "string") return err.detail;
  if (Array.isArray(err.detail)) return err.detail.map((d) => d.msg || d).join(", ");
  if (err.detail && typeof err.detail === "object") return JSON.stringify(err.detail);
  return fallback;
}

function endSession() {
  showLoginView();
  const session = captureSession();
  persistSession(session).then(() => {
    if (isCurrentSession(session)) chrome.runtime.sendMessage({ type: "AUTH_UPDATE", token: "" });
  }).catch(() => {});
}

// ── DOM refs ──────────────────────────────────────────────
// Views
const loginView = document.getElementById("login-view");
const mainView = document.getElementById("main-view");

// Login
const loginForm = document.getElementById("login-form");
const loginError = document.getElementById("login-error");
const emailInput = document.getElementById("email");
const passwordInput = document.getElementById("password");

// Header
const settingsBtn = document.getElementById("settings-btn");
const headerTimer = document.getElementById("header-timer");
const headerTimerText = document.getElementById("header-timer-text");

// Tabs
const tabs = document.querySelectorAll(".tab");
const tabContents = {
  capture: document.getElementById("tab-capture"),
  timer: document.getElementById("tab-timer"),
  tasks: document.getElementById("tab-tasks"),
};

// Capture — Note mode
const noteText = document.getElementById("note-text");
const linkUrl = document.getElementById("link-url");
const captureBtn = document.getElementById("capture-btn");
const btnText = document.getElementById("btn-text");
const btnLoading = document.getElementById("btn-loading");
const assignSelect = document.getElementById("assign-select");
const successMsg = document.getElementById("success-msg");
const successText = document.getElementById("success-text");
const captureError = document.getElementById("capture-error");
const inboxBar = document.getElementById("inbox-bar");
const inboxCount = document.getElementById("inbox-count");
const openInbox = document.getElementById("open-inbox");

// Capture — Task mode
const captureNoteMode = document.getElementById("capture-note-mode");
const captureTaskMode = document.getElementById("capture-task-mode");
const modeBtns = document.querySelectorAll(".mode-btn");
const taskTitle = document.getElementById("task-title");
const taskClientSelect = document.getElementById("task-client-select");
const taskProjectSelect = document.getElementById("task-project-select");
const taskStartTimer = document.getElementById("task-start-timer");
const taskCreateBtn = document.getElementById("task-create-btn");
const taskBtnText = document.getElementById("task-btn-text");
const taskBtnLoading = document.getElementById("task-btn-loading");
const taskCaptureError = document.getElementById("task-capture-error");

// Timer
const timerActive = document.getElementById("timer-active");
const timerIdle = document.getElementById("timer-idle");
const timerElapsed = document.getElementById("timer-elapsed");
const timerTaskName = document.getElementById("timer-task-name");
const timerStopBtn = document.getElementById("timer-stop-btn");
const timerPauseBtn = document.getElementById("timer-pause-btn");
const timerResumeBtn = document.getElementById("timer-resume-btn");
const timerTaskSelect = document.getElementById("timer-task-select");
const timerStartBtn = document.getElementById("timer-start-btn");
const manualTaskSelect = document.getElementById("manual-task-select");
const manualHours = document.getElementById("manual-hours");
const manualMins = document.getElementById("manual-mins");
const manualNotes = document.getElementById("manual-notes");
const manualSaveBtn = document.getElementById("manual-save-btn");
const timerError = document.getElementById("timer-error");
const timerSuccess = document.getElementById("timer-success");

// Project hours budget panel
const timerBudget = document.getElementById("timer-budget");
const budgetProject = document.getElementById("budget-project");
const budgetWeekRow = document.getElementById("budget-week-row");
const budgetWeekLabel = document.getElementById("budget-week-label");
const budgetWeek = document.getElementById("budget-week");
const budgetWeekBarWrap = document.getElementById("budget-week-bar-wrap");
const budgetWeekBar = document.getElementById("budget-week-bar");
const budgetMonthRow = document.getElementById("budget-month-row");
const budgetMonthLabel = document.getElementById("budget-month-label");
const budgetMonth = document.getElementById("budget-month");

// Quick create (timer)
const qcTimerLink = document.getElementById("quick-create-timer-link");
const qcTimerForm = document.getElementById("quick-create-timer-form");
const qcTimerTitle = document.getElementById("qc-timer-title");
const qcTimerClient = document.getElementById("qc-timer-client");
const qcTimerCancel = document.getElementById("qc-timer-cancel");
const qcTimerSave = document.getElementById("qc-timer-save");

// Quick create (manual)
const qcManualLink = document.getElementById("quick-create-manual-link");
const qcManualForm = document.getElementById("quick-create-manual-form");
const qcManualTitle = document.getElementById("qc-manual-title");
const qcManualClient = document.getElementById("qc-manual-client");
const qcManualCancel = document.getElementById("qc-manual-cancel");
const qcManualSave = document.getElementById("qc-manual-save");

// Tasks
const tasksFilter = document.getElementById("tasks-filter");
const tasksRefresh = document.getElementById("tasks-refresh");
const tasksList = document.getElementById("tasks-list");
const tasksEmpty = document.getElementById("tasks-empty");

// ── State ─────────────────────────────────────────────────
let token = "";
let sessionEpoch = 0;
let accountEmail = "";
let storageWrites = Promise.resolve();
const sessionTimeouts = new Set();
const accountDrafts = new Map();
let taskCreateInFlight = false;
let captureInFlight = false;
let timerInterval = null;
let activeTimerStart = null;
let timerIsPaused = false;
let timerAccumulatedSeconds = 0;
let clientsList = []; // cached for quick-create forms
let projectsList = []; // cached for task mode
let assignmentLoadId = 0;
let timerTasksLoadId = 0;
let taskListLoadId = 0;
const assignmentLoadError = document.getElementById("assignment-load-error");
const assignmentErrorText = document.getElementById("assignment-error-text");
const assignmentRetry = document.getElementById("assignment-retry");
const timerTasksRetry = document.getElementById("timer-tasks-retry");
assignmentRetry.addEventListener("click", loadProjectsAndClients);
timerTasksRetry.addEventListener("click", loadTimerTasks);

// ── Init ──────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", async () => {
  const initializing = captureSession();
  const stored = await chrome.storage.local.get([
    STORAGE_KEYS.token,
    STORAGE_KEYS.email,
  ]);

  if (!isCurrentSession(initializing)) return;
  accountEmail = stored[STORAGE_KEYS.email] || "";
  token = stored[STORAGE_KEYS.token] || "";
  if (accountEmail) emailInput.value = accountEmail;

  if (token) {
    // Show main view immediately — verify in background
    showMainView();
    verifyToken();
    return;
  }

  showLoginView();
});

// ── Views ─────────────────────────────────────────────────
function resetSessionUi() {
  if (token && accountEmail) {
    accountDrafts.set(accountEmail.toLowerCase(), draftFields.map((element) => ({
      value: element.value, label: element.selectedOptions?.[0]?.textContent,
    })));
  }
  sessionEpoch++;
  captureInFlight = false;
  taskCreateInFlight = false;
  sessionTimeouts.forEach(clearTimeout);
  sessionTimeouts.clear();
  clearInterval(timerInterval);
  timerInterval = null;
  activeTimerStart = null;
  timerIsPaused = false;
  timerAccumulatedSeconds = 0;
  draftFields.forEach(element => { element.value = element.type === "number" ? "0" : ""; });
  [successMsg, captureError, taskCaptureError, timerError, timerSuccess, inboxBar,
   headerTimer, timerActive, timerBudget, qcTimerForm, qcManualForm].forEach(el => el.classList.add("hidden"));
  [timerIdle, qcTimerLink, qcManualLink, btnText, taskBtnText].forEach(el => el.classList.remove("hidden"));
  [btnLoading, taskBtnLoading].forEach(el => el.classList.add("hidden"));
  captureBtn.disabled = taskCreateBtn.disabled = timerStartBtn.disabled = true;
  for (const [button, html] of sessionButtonMarkup) {
    button.innerHTML = html;
    button.disabled = button === timerStartBtn;
  }
  assignmentRetry.disabled = timerTasksRetry.disabled = false;
  timerTasksRetry.classList.add("hidden");
}
const draftFields = [noteText, linkUrl, taskTitle, qcTimerTitle, qcManualTitle,
  manualHours, manualMins, manualNotes, assignSelect, taskClientSelect,
  taskProjectSelect, qcTimerClient, qcManualClient, timerTaskSelect, manualTaskSelect];
const sessionButtonMarkup = [timerStartBtn, timerStopBtn, timerPauseBtn, timerResumeBtn,
  manualSaveBtn, qcTimerSave, qcManualSave].map(button => [button, button.innerHTML]);
function acceptSession(nextToken, email) {
  resetSessionUi();
  token = nextToken;
  accountEmail = email;
  const draft = accountDrafts.get(email.toLowerCase());
  if (draft) draftFields.forEach((element, index) => {
    if (element.tagName === "SELECT") restoreSelection(element, draft[index]);
    else element.value = draft[index].value;
  });
  captureBtn.disabled = !noteText.value.trim();
  updateTaskCreateBtn();
}
function showLoginView() {
  resetSessionUi();
  token = "";
  // A pending response must not restore selectors from a previous account.
  assignmentLoadId++;
  timerTasksLoadId++;
  taskListLoadId++;
  clientsList = [];
  projectsList = [];
  [assignSelect, taskClientSelect, taskProjectSelect, qcTimerClient, qcManualClient,
   timerTaskSelect, manualTaskSelect].forEach(clearSelect);
  assignmentLoadError.classList.add("hidden");
  tasksList.replaceChildren();
  loginView.classList.remove("hidden");
  mainView.classList.add("hidden");
  emailInput.focus();
}

// Setup capture listeners
noteText.addEventListener("input", () => {
  captureBtn.disabled = captureInFlight || !noteText.value.trim();
});

noteText.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
    e.preventDefault();
    if (noteText.value.trim()) captureNote();
  }
});

// Click header timer indicator to switch to Timer tab
headerTimer.addEventListener("click", () => switchToTab("timer"));


function showMainView() {
  const session = captureSession();
  loginView.classList.add("hidden");
  mainView.classList.remove("hidden");
  noteText.focus();

  openInbox.href = `${API_URL}/inbox`;

  // Load data
  loadProjectsAndClients();
  loadInboxCount();
  loadActiveTimer().then(() => {
    // Auto-select Timer tab when a timer is running
    if (isCurrentSession(session) && activeTimerStart) switchToTab("timer");
  });
  loadTasks();
}

function switchToTab(target) {
  tabs.forEach((t) => {
    if (t.dataset.tab === target) t.classList.add("active");
    else t.classList.remove("active");
  });
  Object.entries(tabContents).forEach(([key, el]) => {
    if (key === target) el.classList.remove("hidden");
    else el.classList.add("hidden");
  });
}

// ── Tab Navigation ────────────────────────────────────────
tabs.forEach((tab) => {
  tab.addEventListener("click", () => {
    const target = tab.dataset.tab;

    // Update active tab
    tabs.forEach((t) => t.classList.remove("active"));
    tab.classList.add("active");

    // Show target content, hide others
    Object.entries(tabContents).forEach(([key, el]) => {
      if (key === target) el.classList.remove("hidden");
      else el.classList.add("hidden");
    });

    // Focus on relevant element
    if (target === "capture") noteText.focus();
    if (target === "tasks") loadTasks();
  });
});

// ── Auth ──────────────────────────────────────────────────
loginForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const attempt = ++sessionEpoch;
  let activeAttempt = attempt;
  const email = emailInput.value.trim();
  loginError.classList.add("hidden");
  try {
    const res = await fetch(`${API_URL}/api/auth/login`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password: passwordInput.value }),
    });
    if (attempt !== sessionEpoch) return;
    const data = await res.json();
    if (attempt !== sessionEpoch) return;
    if (!res.ok) throw new Error(getDetail(data, "Credenciales inválidas"));
    acceptSession(data.access_token, email);
    activeAttempt = sessionEpoch;
    const session = captureSession();
    await persistSession(session);
    if (!isCurrentSession(session)) return;
    passwordInput.value = "";
    chrome.runtime.sendMessage({ type: "AUTH_UPDATE", token });
    showMainView();
  } catch (err) {
    if (activeAttempt !== sessionEpoch) return;
    loginError.textContent = err.message;
    loginError.classList.remove("hidden");
  }
});

async function verifyToken() {
  const session = captureSession();
  // Only an explicit 401 means the token is actually invalid. A network blip,
  // timeout, or 5xx (e.g. backend redeploy / cold start) must NOT wipe the
  // session — otherwise a momentary server hiccup logs the user out and forces
  // them to re-enter the password even though their token is still valid.
  try {
    const res = await sessionFetch(session, `${API_URL}/api/auth/me`, {
      headers: { Authorization: `Bearer ${session.token}` },
    });
    if (!isCurrentSession(session)) return;
    if (res.status === 401) return false;
    return true;
  } catch {
    if (!isCurrentSession(session)) return;
    // Network error / server unreachable → keep the session, don't force login.
    return true;
  }
}

// ── Paginated lists ───────────────────────────────────────
async function fetchAllPages(path, filters, session) {
  const rows = [];
  const ids = new Set();
  for (let page = 1; ; page++) {
    if (!isCurrentSession(session)) throw new Error("La sesión ha cambiado");
    const params = new URLSearchParams({ ...filters, page: String(page), page_size: "100" });
    const res = await sessionFetch(session, `${API_URL}${path}?${params}`, {
      headers: { Authorization: `Bearer ${session.token}` },
    });
    if (!isCurrentSession(session)) return;
    if (!isCurrentSession(session)) throw new Error("La sesión ha cambiado");
    if (!res.ok) {
      const error = await res.json().catch(() => ({}));
      if (!isCurrentSession(session)) return;
      throw new Error(getDetail(error, `Error ${res.status}`));
    }
    const data = await res.json();
    if (!isCurrentSession(session)) return;
    if (!Array.isArray(data.items) || data.page !== page ||
        !Number.isInteger(data.total) || data.total < 0 ||
        !Number.isInteger(data.page_size) || data.page_size < 1 ||
        data.items.length > data.page_size) {
      throw new Error("Respuesta de lista incompleta. Reintenta.");
    }
    for (const item of data.items) {
      if (!Number.isInteger(item.id) || ids.has(item.id)) {
        throw new Error("La lista ha cambiado mientras se cargaba. Reintenta.");
      }
      ids.add(item.id);
      rows.push(item);
    }
    if (page * data.page_size >= data.total) {
      if (rows.length !== data.total) throw new Error("Respuesta de lista incompleta. Reintenta.");
      return rows;
    }
    if (data.items.length !== data.page_size) {
      throw new Error("Respuesta de lista incompleta. Reintenta.");
    }
  }
}

function clearSelect(select) {
  select.replaceChildren(select.options[0].cloneNode(true));
}

function rememberSelection(select) {
  return { value: select.value, label: select.selectedOptions[0]?.textContent };
}

function restoreSelection(select, previous) {
  if (!previous.value) return;
  select.value = previous.value;
  if (select.value !== previous.value) {
    // Never silently turn an explicitly assigned draft into an AI assignment.
    const option = document.createElement("option");
    option.value = previous.value;
    option.textContent = `${previous.label} (ya no disponible)`;
    option.disabled = true;
    option.selected = true;
    select.appendChild(option);
  }
}

function hasUnavailableSelection(...selects) {
  return selects.some(select => select.value &&
    (!select.options[select.selectedIndex] || select.options[select.selectedIndex].disabled));
}

function populateSelect(select, rows, label) {
  const previous = rememberSelection(select);
  clearSelect(select);
  rows.forEach((row) => {
    const option = document.createElement("option");
    option.value = row.id;
    option.textContent = label(row);
    select.appendChild(option);
  });
  restoreSelection(select, previous);
}

// ── Projects + Clients (combined selector) ────────────────
async function loadProjectsAndClients() {
  const session = captureSession();
  const loadId = ++assignmentLoadId;
  assignmentRetry.disabled = true;
  try {
    const [projects, clients] = await Promise.all([
      fetchAllPages("/api/projects", { status: "active" }, session),
      fetchAllPages("/api/clients", { status: "active" }, session),
    ]);
    if (!isCurrentSession(session)) return;
    if (loadId !== assignmentLoadId || !isCurrentSession(session)) return;
    // Commit both complete lists together. A failed page leaves the last
    // successful lists, active selections, and unsent drafts intact.
    projectsList = projects;
    clientsList = clients;
    const previous = rememberSelection(assignSelect);
    clearSelect(assignSelect);
    for (const [label, type, rows] of [["Proyectos", "project", projects], ["Clientes", "client", clients]]) {
      if (!rows.length) continue;
      const group = document.createElement("optgroup");
      group.label = label;
      rows.forEach((row) => {
        const option = document.createElement("option");
        option.value = `${type}:${row.id}`;
        option.textContent = row.name;
        group.appendChild(option);
      });
      assignSelect.appendChild(group);
    }
    restoreSelection(assignSelect, previous);
    populateQuickCreateClients();
    populateTaskModeSelects();
    assignmentLoadError.classList.add("hidden");
  } catch (error) {
    if (!isCurrentSession(session)) return;
    if (loadId !== assignmentLoadId || !isCurrentSession(session)) return;
    assignmentErrorText.textContent = `No se pudieron cargar clientes y proyectos. ${error.message}${clientsList.length || projectsList.length ? " Se conserva la lista anterior." : ""}`;
    assignmentLoadError.classList.remove("hidden");
  } finally {
    if (!isCurrentSession(session)) return;
    if (loadId === assignmentLoadId) assignmentRetry.disabled = false;
  }
}

function populateQuickCreateClients() {
  [qcTimerClient, qcManualClient].forEach((select) => populateSelect(select, clientsList, (client) => client.name));
}

// ── Capture ───────────────────────────────────────────────
captureBtn.addEventListener("click", () => captureNote());

async function captureNote() {
  const session = captureSession();
  const text = noteText.value.trim();
  if (!text || captureInFlight) return;
  if (hasUnavailableSelection(assignSelect)) {
    captureError.textContent = "Elige un cliente o proyecto disponible antes de capturar.";
    captureError.classList.remove("hidden");
    return;
  }

  captureInFlight = true;
  captureBtn.disabled = true;
  btnText.classList.add("hidden");
  btnLoading.classList.remove("hidden");
  successMsg.classList.add("hidden");
  captureError.classList.add("hidden");

  // Build body
  const body = {
    raw_text: text,
    source: "chrome_extension",
  };

  // Parse link
  const link = linkUrl.value.trim();
  if (link) body.link_url = link;

  // Parse selector value: "project:123" or "client:456"
  const selected = assignSelect.value;
  if (selected) {
    const [type, id] = selected.split(":");
    if (type === "project") {
      body.project_id = parseInt(id, 10);
      const project = projectsList.find((item) => item.id === body.project_id);
      if (project?.client_id) body.client_id = project.client_id;
    }
    else if (type === "client") body.client_id = parseInt(id, 10);
  }

  try {
    const res = await sessionFetch(session, `${API_URL}/api/inbox`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${session.token}`,
      },
      body: JSON.stringify(body),
    });
    if (!isCurrentSession(session)) return;


    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      if (!isCurrentSession(session)) return;
      throw new Error(errData.detail || `Error ${res.status}`);
    }

    // Clear only the submitted draft, never edits made while it was sending.
    if (noteText.value.trim() === text && linkUrl.value.trim() === link && assignSelect.value === selected) {
      noteText.value = "";
      linkUrl.value = "";
      assignSelect.value = "";
    }

    if (selected) {
      successText.textContent = "Nota capturada y asignada ✓";
    } else {
      successText.textContent = "Nota capturada — IA clasificando...";
    }
    successMsg.classList.remove("hidden");
    loadInboxCount();

    chrome.runtime.sendMessage({ type: "NOTE_CREATED" });

    scheduleForSession(() => {
      successMsg.classList.add("hidden");
    }, 3000);
  } catch (err) {
    if (!isCurrentSession(session)) return;
    captureError.textContent = err.message || "Error al enviar.";
    captureError.classList.remove("hidden");
  } finally {
    if (!isCurrentSession(session)) return;
    captureInFlight = false;
    captureBtn.disabled = !noteText.value.trim();
    btnText.classList.remove("hidden");
    btnLoading.classList.add("hidden");
  }
}

// ── Capture Mode Toggle (Note vs Task) ───────────────────
modeBtns.forEach((btn) => {
  btn.addEventListener("click", () => {
    modeBtns.forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    const mode = btn.dataset.mode;
    if (mode === "note") {
      captureNoteMode.classList.remove("hidden");
      captureTaskMode.classList.add("hidden");
      noteText.focus();
    } else {
      captureNoteMode.classList.add("hidden");
      captureTaskMode.classList.remove("hidden");
      taskTitle.focus();
    }
    // Hide any previous success/error
    successMsg.classList.add("hidden");
    taskCaptureError.classList.add("hidden");
    captureError.classList.add("hidden");
  });
});

// ── Task Mode: populate selects ──────────────────────────
function populateTaskModeSelects() {
  populateSelect(taskClientSelect, clientsList, (client) => client.name);
  populateSelect(taskProjectSelect, projectsList, (project) => project.name);
  updateTaskCreateBtn();
}

// ── Task Mode: enable/disable button ─────────────────────
function updateTaskCreateBtn() {
  taskCreateBtn.disabled = taskCreateInFlight || hasUnavailableSelection(taskClientSelect, taskProjectSelect) || !(taskTitle.value.trim() && taskClientSelect.value);
}

taskTitle.addEventListener("input", updateTaskCreateBtn);
taskClientSelect.addEventListener("change", updateTaskCreateBtn);
taskProjectSelect.addEventListener("change", updateTaskCreateBtn);

// ── Task Mode: button text based on timer checkbox ───────
taskStartTimer.addEventListener("change", () => {
  taskBtnText.textContent = taskStartTimer.checked ? "Crear tarea + Timer" : "Crear tarea";
});

// ── Task Mode: Cmd+Enter ─────────────────────────────────
taskTitle.addEventListener("keydown", (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
    e.preventDefault();
    if (taskTitle.value.trim() && taskClientSelect.value) createTaskDirect();
  }
});

// ── Task Mode: create task + optional timer ──────────────
taskCreateBtn.addEventListener("click", () => createTaskDirect());

async function createTaskDirect() {
  const session = captureSession();
  const title = taskTitle.value.trim();
  const clientId = taskClientSelect.value;
  if (!title || !clientId || taskCreateInFlight) return;
  if (hasUnavailableSelection(taskClientSelect, taskProjectSelect)) {
    taskCaptureError.textContent = "Elige un cliente y proyecto disponibles antes de crear.";
    taskCaptureError.classList.remove("hidden");
    return;
  }

  taskCreateInFlight = true;
  taskCreateBtn.disabled = true;
  taskBtnText.classList.add("hidden");
  taskBtnLoading.classList.remove("hidden");
  taskCaptureError.classList.add("hidden");
  successMsg.classList.add("hidden");

  try {
    // 1. Create task
    const body = {
      title,
      client_id: parseInt(clientId, 10),
      status: "in_progress",
    };
    const projectId = taskProjectSelect.value;
    if (projectId) body.project_id = parseInt(projectId, 10);

    const res = await sessionFetch(session, `${API_URL}/api/tasks`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${session.token}`,
      },
      body: JSON.stringify(body),
    });
    if (!isCurrentSession(session)) return;

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      if (!isCurrentSession(session)) return;
      throw new Error(getDetail(err, "Error al crear tarea"));
    }

    const task = await res.json();
    if (!isCurrentSession(session)) return;

    // 2. Optionally start timer
    if (taskStartTimer.checked) {
      const timerRes = await sessionFetch(session, `${API_URL}/api/timer/start`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${session.token}`,
        },
        body: JSON.stringify({ task_id: task.id }),
      });
      if (!isCurrentSession(session)) return;

      if (timerRes.ok) {
        const timerData = await timerRes.json();
        if (!isCurrentSession(session)) return;
        showActiveTimer(timerData);
      } else {
        const timerErr = await timerRes.json().catch(() => ({}));
        if (!isCurrentSession(session)) return;
        taskCaptureError.textContent = "Tarea creada, pero error al iniciar timer: " + getDetail(timerErr, `Error ${timerRes.status}`);
        taskCaptureError.classList.remove("hidden");
      }
    }

    // 3. Success — reset form
    taskTitle.value = "";
    taskClientSelect.value = "";
    taskProjectSelect.value = "";
    updateTaskCreateBtn();

    if (taskStartTimer.checked) {
      successText.textContent = "Tarea creada — timer iniciado";
      successMsg.classList.remove("hidden");
      // Switch to timer tab after brief delay
      scheduleForSession(() => switchToTab("timer"), 1200);
    } else {
      successText.textContent = "Tarea creada";
      successMsg.classList.remove("hidden");
    }

    scheduleForSession(() => successMsg.classList.add("hidden"), 3000);
  } catch (err) {
    if (!isCurrentSession(session)) return;
    taskCaptureError.textContent = err.message || "Error al crear tarea.";
    taskCaptureError.classList.remove("hidden");
  } finally {
    if (!isCurrentSession(session)) return;
    taskCreateInFlight = false;
    taskBtnText.classList.remove("hidden");
    taskBtnLoading.classList.add("hidden");
    updateTaskCreateBtn();
  }
}

// ── Inbox count ───────────────────────────────────────────
async function loadInboxCount() {
  const session = captureSession();
  try {
    const res = await sessionFetch(session, `${API_URL}/api/inbox/count`, {
      headers: { Authorization: `Bearer ${session.token}` },
    });
    if (!isCurrentSession(session)) return;
    if (res.ok) {
      const data = await res.json();
      if (!isCurrentSession(session)) return;
      if (data.count > 0) {
        inboxCount.textContent = data.count;
        inboxBar.classList.remove("hidden");
      } else {
        inboxBar.classList.add("hidden");
      }
    }
  } catch {
    if (!isCurrentSession(session)) return;
    // silently ignore
  }
}

// ── Open inbox link ───────────────────────────────────────
openInbox.addEventListener("click", (e) => {
  e.preventDefault();
  chrome.tabs.create({ url: `${API_URL}/inbox` });
  window.close();
});

// ── Settings (logout) ─────────────────────────────────────
settingsBtn.addEventListener("click", endSession);

// ══════════════════════════════════════════════════════════
// TIMER TAB
// ══════════════════════════════════════════════════════════

function parseApiInstant(value) {
  // New API responses include Z. Legacy naive values were also stored as UTC,
  // so make that convention explicit instead of letting the browser use local time.
  return new Date(/(?:Z|[+-]\d{2}:?\d{2})$/i.test(value) ? value : `${value}Z`);
}

function elapsedSeconds(startedAt, accumulatedSeconds = 0, paused = false, nowMs = Date.now()) {
  if (paused) return Math.max(0, accumulatedSeconds);
  return Math.max(0, accumulatedSeconds + Math.floor((nowMs - startedAt.getTime()) / 1000));
}

async function loadActiveTimer() {
  const session = captureSession();
  try {
    const res = await sessionFetch(session, `${API_URL}/api/timer/active`, {
      headers: { Authorization: `Bearer ${session.token}` },
    });
    if (!isCurrentSession(session)) return;

    if (res.ok) {
      const data = await res.json();
      if (!isCurrentSession(session)) return;
      if (data && data.started_at) {
        showActiveTimer(data);
        return;
      }
    }
  } catch {
    if (!isCurrentSession(session)) return;
    // no active timer
  }

  showIdleTimer();
}

function showActiveTimer(data) {
  timerActive.classList.remove("hidden");
  timerIdle.classList.add("hidden");

  activeTimerStart = parseApiInstant(data.started_at);
  timerAccumulatedSeconds = data.accumulated_seconds || 0;
  timerIsPaused = data.is_paused || false;
  timerTaskName.textContent = data.task_title || "Sin tarea";

  // Show/hide pause/resume buttons
  if (timerIsPaused) {
    timerPauseBtn.classList.add("hidden");
    timerResumeBtn.classList.remove("hidden");
    timerActive.classList.add("timer-paused");
  } else {
    timerPauseBtn.classList.remove("hidden");
    timerResumeBtn.classList.add("hidden");
    timerActive.classList.remove("timer-paused");
  }

  // Show header timer indicator
  headerTimer.classList.remove("hidden");

  // Project hours budget (weekly remaining + alert)
  loadProjectBudget(data.project_id, data.project_name);

  // Start interval
  if (timerInterval) clearInterval(timerInterval);
  updateTimerDisplay();
  timerInterval = setInterval(updateTimerDisplay, 1000);
}

// ── Project hours budget ──────────────────────────────────
function fmtHours(h) {
  if (h == null) return "—";
  const r = Math.round(h * 10) / 10;
  return (Number.isInteger(r) ? r : r.toFixed(1)) + "h";
}

async function loadProjectBudget(projectId, projectName) {
  const session = captureSession();
  // No project on the active task → hide panel
  if (!projectId) {
    timerBudget.classList.add("hidden");
    return;
  }
  try {
    const res = await sessionFetch(session, `${API_URL}/api/timer/project-budget/${projectId}`, {
      headers: { Authorization: `Bearer ${session.token}` },
    });
    if (!isCurrentSession(session)) return;
    if (!res.ok) {
      timerBudget.classList.add("hidden");
      return;
    }
    const data = await res.json();
    if (!isCurrentSession(session)) return;
    renderProjectBudget(data, projectName);
  } catch {
    if (!isCurrentSession(session)) return;
    timerBudget.classList.add("hidden");
  }
}

function renderProjectBudget(data, projectName) {
  budgetProject.textContent = data.project_name || projectName || "Proyecto";
  if (data.kind === "fixed") {
    renderClosingBudget(data.closing);
  } else {
    renderRecurringBudget(data.week || {}, data.month || {});
  }
}

function renderRecurringBudget(week, month) {
  // Nothing budgeted on either window → nothing useful to show
  if (week.budget_hours == null && month.budget_hours == null) {
    timerBudget.classList.add("hidden");
    return;
  }

  // Weekly (informativo + guía visual)
  if (week.budget_hours != null) {
    const remaining = week.remaining_hours;
    const remTxt = remaining >= 0
      ? `quedan ${fmtHours(remaining)}`
      : `pasado ${fmtHours(Math.abs(remaining))}`;
    budgetWeekLabel.textContent = "Esta semana";
    budgetWeek.textContent = `${fmtHours(week.used_hours)} / ${fmtHours(week.budget_hours)} · ${remTxt}`;
    budgetWeek.className = "budget-value" + statusClass(week.status);
    budgetWeekBarWrap.classList.remove("hidden");
    budgetWeekBar.style.width = `${Math.min(100, (week.pct || 0) * 100)}%`;
    budgetWeekBar.className = "budget-bar-fill" + statusClass(week.status);
    budgetWeekRow.classList.remove("hidden");
  } else {
    budgetWeekRow.classList.add("hidden");
    budgetWeekBarWrap.classList.add("hidden");
  }

  // Monthly (techo que dispara la alerta)
  if (month.budget_hours != null) {
    budgetMonthLabel.textContent = "Este mes";
    budgetMonth.textContent = `${fmtHours(month.used_hours)} / ${fmtHours(month.budget_hours)} (${Math.round((month.pct || 0) * 100)}%)`;
    budgetMonth.className = "budget-value" + statusClass(month.status);
    budgetMonthRow.classList.remove("hidden");
  } else {
    budgetMonthRow.classList.add("hidden");
  }

  applyPanelStatus(worstStatus(week.status, month.status));
}

function renderClosingBudget(closing) {
  if (!closing) {
    timerBudget.classList.add("hidden");
    return;
  }

  // Row 1 → cierre (días restantes / vencido)
  let when;
  if (closing.overdue) when = `vencido hace ${Math.abs(closing.days_left)}d`;
  else if (closing.days_left === 0) when = "cierra hoy";
  else when = `cierra en ${closing.days_left}d`;
  budgetWeekLabel.textContent = "Cierre";
  budgetWeek.textContent = when;
  budgetWeek.className = "budget-value" + statusClass(closing.status);

  // Bar reflects hours consumption against the total budget (if any)
  if (closing.budget_hours != null) {
    budgetWeekBarWrap.classList.remove("hidden");
    budgetWeekBar.style.width = `${Math.min(100, (closing.hours_pct || 0) * 100)}%`;
    budgetWeekBar.className = "budget-bar-fill" + statusClass(closing.status);
  } else {
    budgetWeekBarWrap.classList.add("hidden");
  }
  budgetWeekRow.classList.remove("hidden");

  // Row 2 → horas vs presupuesto total
  if (closing.budget_hours != null) {
    const remaining = closing.remaining_hours;
    const remTxt = remaining >= 0
      ? `quedan ${fmtHours(remaining)}`
      : `pasado ${fmtHours(Math.abs(remaining))}`;
    budgetMonthLabel.textContent = "Horas";
    budgetMonth.textContent = `${fmtHours(closing.used_hours)} / ${fmtHours(closing.budget_hours)} · ${remTxt}`;
    budgetMonth.className = "budget-value" + statusClass(closing.status);
    budgetMonthRow.classList.remove("hidden");
  } else {
    budgetMonthRow.classList.add("hidden");
  }

  applyPanelStatus(closing.status);
}

function applyPanelStatus(status) {
  timerBudget.classList.remove("hidden", "budget-alert", "budget-over");
  if (status === "over") timerBudget.classList.add("budget-over");
  else if (status === "warning") timerBudget.classList.add("budget-alert");
}

function statusClass(status) {
  if (status === "over") return " is-over";
  if (status === "warning") return " is-warning";
  return "";
}

function worstStatus(...statuses) {
  if (statuses.includes("over")) return "over";
  if (statuses.includes("warning")) return "warning";
  return "ok";
}

function showIdleTimer() {
  timerActive.classList.add("hidden");
  timerIdle.classList.remove("hidden");
  if (timerBudget) timerBudget.classList.add("hidden");

  activeTimerStart = null;
  headerTimer.classList.add("hidden");
  if (timerInterval) {
    clearInterval(timerInterval);
    timerInterval = null;
  }

  // Load tasks for selectors
  loadTimerTasks();
}

function updateTimerDisplay() {
  if (!activeTimerStart) return;
  const diff = elapsedSeconds(activeTimerStart, timerAccumulatedSeconds, timerIsPaused);
  const h = Math.floor(diff / 3600);
  const m = Math.floor((diff % 3600) / 60);
  const s = diff % 60;
  timerElapsed.textContent = `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  headerTimerText.textContent = timerIsPaused ? `⏸ ${h}:${String(m).padStart(2, "0")}` : `${h}:${String(m).padStart(2, "0")}`;
}

async function loadTimerTasks() {
  const session = captureSession();
  const loadId = ++timerTasksLoadId;
  timerTasksRetry.disabled = true;
  try {
    const tasks = await fetchAllPages("/api/tasks", {
      assigned_to: "me", status: "pending,in_progress,waiting,in_review",
    }, session);
    if (!isCurrentSession(session)) return;
    if (loadId !== timerTasksLoadId || !isCurrentSession(session)) return;
    [timerTaskSelect, manualTaskSelect].forEach((select) => {
      populateSelect(select, tasks, (task) => task.title.length > 40 ? task.title.slice(0, 40) + "..." : task.title);
    });
    timerStartBtn.disabled = !timerTaskSelect.value || hasUnavailableSelection(timerTaskSelect);
    timerTasksRetry.classList.add("hidden");
    timerError.classList.add("hidden");
  } catch (error) {
    if (!isCurrentSession(session)) return;
    if (loadId !== timerTasksLoadId || !isCurrentSession(session)) return;
    timerError.textContent = `No se pudieron cargar las tareas. ${error.message}`;
    timerError.classList.remove("hidden");
    timerTasksRetry.classList.remove("hidden");
  } finally {
    if (!isCurrentSession(session)) return;
    if (loadId === timerTasksLoadId) timerTasksRetry.disabled = false;
  }
}

// ── Task selection required for timer ─────────────────────
timerTaskSelect.addEventListener("change", () => {
  timerStartBtn.disabled = !timerTaskSelect.value || hasUnavailableSelection(timerTaskSelect);
});

// Start timer (task_id is now required)
timerStartBtn.addEventListener("click", async () => {
  const session = captureSession();
  if (!timerTaskSelect.value || hasUnavailableSelection(timerTaskSelect)) {
    timerError.textContent = "Selecciona una tarea para iniciar el timer";
    timerError.classList.remove("hidden");
    return;
  }

  timerStartBtn.disabled = true;
  timerStartBtn.textContent = "Iniciando...";
  timerError.classList.add("hidden");

  const body = { task_id: parseInt(timerTaskSelect.value, 10) };

  try {
    const res = await sessionFetch(session, `${API_URL}/api/timer/start`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${session.token}`,
      },
      body: JSON.stringify(body),
    });
    if (!isCurrentSession(session)) return;

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      if (!isCurrentSession(session)) return;
      throw new Error(getDetail(err, "Error al iniciar timer"));
    }

    const data = await res.json();
    showActiveTimer(data);
  } catch (err) {
    if (!isCurrentSession(session)) return;
    timerError.textContent = err.message;
    timerError.classList.remove("hidden");
  } finally {
    if (!isCurrentSession(session)) return;
    timerStartBtn.disabled = !timerTaskSelect.value || hasUnavailableSelection(timerTaskSelect);
    timerStartBtn.textContent = "Iniciar Timer";
  }
});

// Stop timer
timerStopBtn.addEventListener("click", async () => {
  const session = captureSession();
  timerStopBtn.disabled = true;
  timerStopBtn.textContent = "Deteniendo...";

  try {
    const res = await sessionFetch(session, `${API_URL}/api/timer/stop`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${session.token}`,
      },
      body: JSON.stringify({}),
    });
    if (!isCurrentSession(session)) return;

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      if (!isCurrentSession(session)) return;
      throw new Error(getDetail(err, "Error al detener timer"));
    }

    showIdleTimer();
    showTimerSuccess("Timer detenido y registrado ✓");
  } catch (err) {
    if (!isCurrentSession(session)) return;
    timerError.textContent = err.message;
    timerError.classList.remove("hidden");
  } finally {
    if (!isCurrentSession(session)) return;
    timerStopBtn.disabled = false;
    timerStopBtn.textContent = "Detener";
  }
});

// Pause timer
timerPauseBtn.addEventListener("click", async () => {
  const session = captureSession();
  timerPauseBtn.disabled = true;
  timerError.classList.add("hidden");

  try {
    const res = await sessionFetch(session, `${API_URL}/api/timer/pause`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${session.token}`,
      },
    });
    if (!isCurrentSession(session)) return;

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      if (!isCurrentSession(session)) return;
      throw new Error(getDetail(err, "Error al pausar timer"));
    }

    const data = await res.json();
    if (!isCurrentSession(session)) return;
    showActiveTimer(data);
    showTimerSuccess("Timer en pausa ⏸");
  } catch (err) {
    if (!isCurrentSession(session)) return;
    timerError.textContent = err.message;
    timerError.classList.remove("hidden");
  } finally {
    if (!isCurrentSession(session)) return;
    timerPauseBtn.disabled = false;
  }
});

// Resume timer
timerResumeBtn.addEventListener("click", async () => {
  const session = captureSession();
  timerResumeBtn.disabled = true;
  timerError.classList.add("hidden");

  try {
    const res = await sessionFetch(session, `${API_URL}/api/timer/resume`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${session.token}`,
      },
    });
    if (!isCurrentSession(session)) return;

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      if (!isCurrentSession(session)) return;
      throw new Error(getDetail(err, "Error al reanudar timer"));
    }

    const data = await res.json();
    if (!isCurrentSession(session)) return;
    showActiveTimer(data);
    showTimerSuccess("Timer reanudado ▶");
  } catch (err) {
    if (!isCurrentSession(session)) return;
    timerError.textContent = err.message;
    timerError.classList.remove("hidden");
  } finally {
    if (!isCurrentSession(session)) return;
    timerResumeBtn.disabled = false;
  }
});

// Manual time entry (task required)
manualSaveBtn.addEventListener("click", async () => {
  const session = captureSession();
  const hours = Math.max(0, parseInt(manualHours.value, 10) || 0);
  const mins = Math.max(0, Math.min(59, parseInt(manualMins.value, 10) || 0));
  const totalMinutes = hours * 60 + mins;

  timerError.classList.add("hidden");
  timerSuccess.classList.add("hidden");

  if (!manualTaskSelect.value || hasUnavailableSelection(manualTaskSelect)) {
    timerError.textContent = "Selecciona una tarea para el registro";
    timerError.classList.remove("hidden");
    return;
  }

  if (totalMinutes <= 0) {
    timerError.textContent = "Introduce un tiempo mayor a 0";
    timerError.classList.remove("hidden");
    return;
  }

  manualSaveBtn.disabled = true;
  manualSaveBtn.textContent = "Guardando...";

  const body = { minutes: totalMinutes, task_id: parseInt(manualTaskSelect.value, 10) };
  if (manualNotes.value.trim()) body.notes = manualNotes.value.trim();

  try {
    const res = await sessionFetch(session, `${API_URL}/api/time-entries`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${session.token}`,
      },
      body: JSON.stringify(body),
    });
    if (!isCurrentSession(session)) return;

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      if (!isCurrentSession(session)) return;
      throw new Error(getDetail(err, "Error al guardar"));
    }

    // Reset form
    manualHours.value = "0";
    manualMins.value = "0";
    manualNotes.value = "";
    manualTaskSelect.value = "";

    showTimerSuccess("Tiempo registrado ✓");
  } catch (err) {
    if (!isCurrentSession(session)) return;
    timerError.textContent = err.message;
    timerError.classList.remove("hidden");
  } finally {
    if (!isCurrentSession(session)) return;
    manualSaveBtn.disabled = false;
    manualSaveBtn.textContent = "Guardar registro";
  }
});

function showTimerSuccess(msg) {
  timerSuccess.textContent = msg;
  timerSuccess.classList.remove("hidden");
  scheduleForSession(() => timerSuccess.classList.add("hidden"), 3000);
}

// ══════════════════════════════════════════════════════════
// TASKS TAB
// ══════════════════════════════════════════════════════════

const STATUS_LABELS = {
  backlog: "Backlog",
  pending: "Pendiente",
  in_progress: "En curso",
  in_review: "En revisión",
  waiting: "En espera",
  completed: "Completada",
};

const STATUS_COLORS = {
  backlog: "#71717a",
  pending: "#eab308",
  in_progress: "#3b82f6",
  in_review: "#a855f7",
  waiting: "#f97316",
  completed: "#22c55e",
};

async function loadTasks() {
  const session = captureSession();
  const loadId = ++taskListLoadId;
  tasksList.querySelector(".tasks-error")?.remove();
  if (!tasksList.children.length) tasksList.innerHTML = '<div class="tasks-loading">Cargando tareas...</div>';
  tasksEmpty.classList.add("hidden");
  const filters = { assigned_to: "me" };
  if (tasksFilter.value) filters.status = tasksFilter.value;
  try {
    const tasks = await fetchAllPages("/api/tasks", filters, session);
    if (!isCurrentSession(session)) return;
    if (loadId !== taskListLoadId || !isCurrentSession(session)) return;

    if (tasks.length === 0) {
      tasksList.innerHTML = "";
      tasksEmpty.classList.remove("hidden");
      return;
    }

    tasksEmpty.classList.add("hidden");
    tasksList.innerHTML = tasks.map((t) => renderTaskCard(t)).join("");

    // Check button: toggle task completion
    tasksList.querySelectorAll(".task-check-btn").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        const session = captureSession();
        e.stopPropagation();
        const taskId = parseInt(btn.dataset.taskId, 10);
        const currentStatus = btn.dataset.status;
        const newStatus = currentStatus === "completed" ? "pending" : "completed";
        btn.disabled = true;
        try {
          const res = await sessionFetch(session, `${API_URL}/api/tasks/${taskId}`, {
            method: "PUT",
            headers: { "Content-Type": "application/json", Authorization: `Bearer ${session.token}` },
            body: JSON.stringify({ status: newStatus }),
          });
          if (!isCurrentSession(session)) return;
                if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            if (!isCurrentSession(session)) return;
            throw new Error(getDetail(err, "Error al actualizar"));
          }
          loadTasks(); // Reload task list
        } catch (err) {
          if (!isCurrentSession(session)) return;
          timerError.textContent = err.message;
          timerError.classList.remove("hidden");
        } finally {
          if (!isCurrentSession(session)) return;
          btn.disabled = false;
        }
      });
    });

    // Add click handlers to open tasks in webapp
    tasksList.querySelectorAll(".task-card").forEach((card) => {
      card.addEventListener("click", (e) => {
        // Don't navigate if play button or check button was clicked
        if (e.target.closest(".task-play-btn") || e.target.closest(".task-check-btn")) return;
        const taskId = card.dataset.id;
        chrome.tabs.create({ url: `${API_URL}/tasks?edit=${taskId}` });
        window.close();
      });
    });

    // Play button: start timer on this task
    tasksList.querySelectorAll(".task-play-btn").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        const session = captureSession();
        e.stopPropagation();
        const taskId = parseInt(btn.dataset.taskId, 10);
        btn.disabled = true;
        try {
          const res = await sessionFetch(session, `${API_URL}/api/timer/start`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              Authorization: `Bearer ${session.token}`,
            },
            body: JSON.stringify({ task_id: taskId }),
          });
          if (!isCurrentSession(session)) return;
                if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            if (!isCurrentSession(session)) return;
            throw new Error(getDetail(err, "Error al iniciar timer"));
          }
          const data = await res.json();
          if (!isCurrentSession(session)) return;
          showActiveTimer(data);
          switchToTab("timer");
        } catch (err) {
          if (!isCurrentSession(session)) return;
          timerError.textContent = err.message;
          timerError.classList.remove("hidden");
        } finally {
          if (!isCurrentSession(session)) return;
          btn.disabled = false;
        }
      });
    });
  } catch (err) {
    if (!isCurrentSession(session)) return;
    if (loadId !== taskListLoadId || !isCurrentSession(session)) return;
    tasksList.querySelector(".tasks-loading")?.remove();
    tasksList.insertAdjacentHTML("afterbegin", `<div class="tasks-error" role="alert">${escapeHtml(err.message)} Pulsa actualizar para reintentar.</div>`);
  }
}

function renderTaskCard(task) {
  const statusColor = STATUS_COLORS[task.status] || "#71717a";
  const statusLabel = STATUS_LABELS[task.status] || task.status;
  const priority = task.priority || "";
  const priorityIcon = priority === "high" ? "↑" : priority === "low" ? "↓" : "";
  const projectName = task.project_name ? `<span class="task-project">${escapeHtml(task.project_name)}</span>` : "";

  const isCompleted = task.status === "completed";
  return `
    <div class="task-card ${isCompleted ? "task-completed" : ""}" data-id="${task.id}">
      <div class="task-header">
        <button class="task-check-btn ${isCompleted ? "checked" : ""}" data-task-id="${task.id}" data-status="${task.status}" title="${isCompleted ? "Reabrir" : "Completar"}">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="20 6 9 17 4 12"/></svg>
        </button>
        <span class="task-title">${escapeHtml(task.title)}</span>
        ${priorityIcon ? `<span class="task-priority task-priority-${priority}">${priorityIcon}</span>` : ""}
        <button class="task-play-btn" data-task-id="${task.id}" title="Iniciar timer">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg>
        </button>
      </div>
      <div class="task-meta">
        <span class="task-status-label" style="color:${statusColor}">${statusLabel}</span>
        ${projectName}
      </div>
    </div>
  `;
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

// Task filter change
tasksFilter.addEventListener("change", () => loadTasks());
tasksRefresh.addEventListener("click", () => loadTasks());

// ══════════════════════════════════════════════════════════
// QUICK CREATE TASK (from Timer tab)
// ══════════════════════════════════════════════════════════

function setupQuickCreate(linkEl, formEl, titleEl, clientEl, cancelEl, saveEl, targetSelect) {
  linkEl.addEventListener("click", (e) => {
    e.preventDefault();
    formEl.classList.remove("hidden");
    linkEl.classList.add("hidden");
    titleEl.focus();
  });

  cancelEl.addEventListener("click", () => {
    formEl.classList.add("hidden");
    linkEl.classList.remove("hidden");
    titleEl.value = "";
    clientEl.value = "";
  });

  saveEl.addEventListener("click", async () => {
    const session = captureSession();
    const title = titleEl.value.trim();
    const clientId = clientEl.value;

    if (!title || !clientId || hasUnavailableSelection(clientEl)) {
      timerError.textContent = "Titulo y cliente son obligatorios";
      timerError.classList.remove("hidden");
      return;
    }

    saveEl.disabled = true;
    saveEl.textContent = "Creando...";
    timerError.classList.add("hidden");

    try {
      const res = await sessionFetch(session, `${API_URL}/api/tasks`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${session.token}`,
        },
        body: JSON.stringify({
          title,
          client_id: parseInt(clientId, 10),
          status: "in_progress",
        }),
      });
      if (!isCurrentSession(session)) return;

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        if (!isCurrentSession(session)) return;
        throw new Error(getDetail(err, "Error al crear tarea"));
      }

      const task = await res.json();
      if (!isCurrentSession(session)) return;

      // Add to both selectors and auto-select in target
      [timerTaskSelect, manualTaskSelect].forEach((sel) => {
        const opt = document.createElement("option");
        opt.value = task.id;
        opt.textContent = task.title.length > 40 ? task.title.slice(0, 40) + "..." : task.title;
        sel.appendChild(opt);
      });

      targetSelect.value = String(task.id);
      targetSelect.dispatchEvent(new Event("change"));

      // Reset and hide form
      formEl.classList.add("hidden");
      linkEl.classList.remove("hidden");
      titleEl.value = "";
      clientEl.value = "";

      showTimerSuccess("Tarea creada y seleccionada");
    } catch (err) {
      if (!isCurrentSession(session)) return;
      timerError.textContent = err.message;
      timerError.classList.remove("hidden");
    } finally {
      if (!isCurrentSession(session)) return;
      saveEl.disabled = false;
      saveEl.textContent = "Crear";
    }
  });
}

setupQuickCreate(qcTimerLink, qcTimerForm, qcTimerTitle, qcTimerClient, qcTimerCancel, qcTimerSave, timerTaskSelect);
setupQuickCreate(qcManualLink, qcManualForm, qcManualTitle, qcManualClient, qcManualCancel, qcManualSave, manualTaskSelect);
