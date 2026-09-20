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

// Natural-language command mode
const captureCommandMode = document.getElementById("capture-command-mode");
const commandText = document.getElementById("command-text");
const commandSubmit = document.getElementById("command-submit");
const commandError = document.getElementById("command-error");
const commandPrompt = document.getElementById("command-prompt");
const commandReceipt = document.getElementById("command-receipt");
const meetingExtensionEnabled = document.getElementById("meeting-extension-enabled");
const meetingMinutesBefore = document.getElementById("meeting-minutes-before");
const meetingSettingsState = document.getElementById("meeting-settings-state");
const meetingSettingsError = document.getElementById("meeting-settings-error");
const meetingSettingsSave = document.getElementById("meeting-settings-save");

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
let commandInFlight = false;
let currentCommand = null;
let commandGeneration = 0;
let commandRequestKey = newRequestKey();
let commandStepKey = newRequestKey();
let commandStepPayload = null;
let commandStepUncertain = false;
let meetingPolicy = null;
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
meetingSettingsSave.addEventListener("click", saveMeetingSettings);

function newRequestKey() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `extension-${Date.now()}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`;
}

function isCurrentCommand(target) {
  return commandGeneration === target.generation && currentCommand?.id === target.receiptId;
}

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
  commandInFlight = false;
  currentCommand = null;
  commandGeneration++;
  commandRequestKey = newRequestKey();
  commandStepKey = newRequestKey();
  commandStepPayload = null;
  commandStepUncertain = false;
  taskCreateInFlight = false;
  sessionTimeouts.forEach(clearTimeout);
  sessionTimeouts.clear();
  clearInterval(timerInterval);
  timerInterval = null;
  activeTimerStart = null;
  timerIsPaused = false;
  timerAccumulatedSeconds = 0;
  draftFields.forEach(element => { element.value = element.type === "number" ? "0" : ""; });
  commandText.disabled = false;
  commandSubmit.textContent = "Hacer";
  [successMsg, captureError, taskCaptureError, commandError, commandPrompt, commandReceipt, timerError, timerSuccess, inboxBar,
   headerTimer, timerActive, timerBudget, qcTimerForm, qcManualForm].forEach(el => el.classList.add("hidden"));
  [timerIdle, qcTimerLink, qcManualLink, btnText, taskBtnText].forEach(el => el.classList.remove("hidden"));
  [btnLoading, taskBtnLoading].forEach(el => el.classList.add("hidden"));
  commandSubmit.disabled = captureBtn.disabled = taskCreateBtn.disabled = timerStartBtn.disabled = true;
  for (const [button, html] of sessionButtonMarkup) {
    button.innerHTML = html;
    button.disabled = button === timerStartBtn;
  }
  assignmentRetry.disabled = timerTasksRetry.disabled = false;
  timerTasksRetry.classList.add("hidden");
}
const draftFields = [commandText, noteText, linkUrl, taskTitle, qcTimerTitle, qcManualTitle,
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
  loadMeetingSettings();
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

// ── Natural-language commands ────────────────────────────
commandText.addEventListener("input", () => {
  commandSubmit.disabled = commandInFlight || !commandText.value.trim();
});
commandText.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
    event.preventDefault();
    if (commandText.value.trim()) submitCommand();
  }
});
commandSubmit.addEventListener("click", () => submitCommand());

function commandEntityUrl(entity) {
  if (entity.type === "incident") {
    const target = typeof entity.href === "string" && entity.href.startsWith("/") && !entity.href.startsWith("//") ? entity.href : "/incidents";
    return `${API_URL}${target}`;
  }
  if (entity.type === "task") return `${API_URL}/tasks?id=${entity.id}`;
  if (entity.type === "project") return `${API_URL}/projects/${entity.id}`;
  if (entity.type === "client") return `${API_URL}/clients/${entity.id}`;
  return `${API_URL}/timesheet`;
}

function commandButton(label, handler, variant = "secondary-btn small") {
  const button = document.createElement("button");
  button.type = "button";
  button.className = variant;
  button.textContent = label;
  button.addEventListener("click", handler);
  return button;
}

const appliedFieldLabels = {
  project_name: "Nuevo proyecto", task_title: "Primera tarea",
  project_id: "Proyecto", client_id: "Cliente", owner_id: "Responsable del proyecto",
  assigned_to: "Responsable de la tarea", scheduled_date: "Fecha planificada",
  target_date: "Fecha objetivo", entry_date: "Fecha del registro",
  minutes: "Tiempo registrado", user_id: "Persona", status: "Estado", priority: "Prioridad",
};
const appliedStatusLabels = {
  backlog: "Backlog", pending: "Pendiente", in_progress: "En curso", waiting: "En espera",
  in_review: "En revisión", advanced: "Avanzada", completed: "Completada",
};
const appliedPriorityLabels = { low: "Baja", medium: "Media", high: "Alta", urgent: "Urgente" };
const reviewFieldOrder = ["project_name", "client_id", "owner_id", "target_date", "task_title", "assigned_to", "scheduled_date"];

function formatAppliedValue(field, value, labels) {
  if (["project_id", "client_id", "owner_id", "assigned_to", "user_id"].includes(field)) {
    if (value == null) return ["project_id", "client_id"].includes(field) ? "Sin vincular" : "Sin asignar";
    return labels[field] || "Vinculado";
  }
  if (["scheduled_date", "target_date", "entry_date"].includes(field)) {
    if (!value) return "Sin fecha";
    const [year, month, day] = value.slice(0, 10).split("-").map(Number);
    return new Date(year, month - 1, day, 12).toLocaleDateString("es-ES", { day: "numeric", month: "long", year: "numeric" });
  }
  if (field === "minutes") return `${value} min`;
  if (field === "status") return appliedStatusLabels[value] || value;
  if (field === "priority") return appliedPriorityLabels[value] || value;
  return String(value ?? "Sin valor");
}

function renderApplied(result) {
  if (!result?.applied) return null;
  const list = document.createElement("dl");
  list.className = "command-applied";
  const entries = Object.entries(result.applied).sort(([left], [right]) => {
    const leftIndex = reviewFieldOrder.indexOf(left);
    const rightIndex = reviewFieldOrder.indexOf(right);
    return (leftIndex < 0 ? reviewFieldOrder.length : leftIndex) - (rightIndex < 0 ? reviewFieldOrder.length : rightIndex);
  });
  for (const [field, value] of entries) {
    const row = document.createElement("div");
    const term = document.createElement("dt");
    const description = document.createElement("dd");
    term.textContent = appliedFieldLabels[field] || field;
    description.textContent = formatAppliedValue(field, value, result.applied_labels || {});
    row.append(term, description);
    list.append(row);
  }
  return list;
}

function renderCommand(data) {
  currentCommand = data;
  commandPrompt.replaceChildren();
  commandReceipt.replaceChildren();
  commandPrompt.classList.add("hidden");
  commandReceipt.classList.add("hidden");
  commandError.classList.add("hidden");

  if (data.status === "needs_input") {
    commandPrompt.classList.remove("hidden");
    const answers = new Map();
    for (const question of data.prompt?.questions || []) {
      const label = document.createElement("p");
      label.textContent = question.label;
      commandPrompt.append(label);
      for (const choice of question.choices || []) {
        const choiceButton = commandButton(choice.label, () => {
          answers.set(question.field, choice.id);
          commandPrompt.querySelectorAll(`[data-field="${question.field}"]`).forEach(node => node.classList.remove("selected"));
          choiceButton.classList.add("selected");
        }, "command-choice");
        choiceButton.dataset.field = question.field;
        choiceButton.disabled = commandStepUncertain;
        if (choice.subtitle) choiceButton.title = choice.subtitle;
        commandPrompt.append(choiceButton);
      }
    }
    const actionable = (data.prompt?.questions || []).filter(question => question.kind !== "notice");
    if (actionable.length) {
      const actions = document.createElement("div");
      actions.className = "command-actions";
      actions.append(commandButton(commandStepUncertain ? "Reintentar la misma respuesta" : "Continuar", () => {
        if (commandStepUncertain) {
          resolveCommand(null);
          return;
        }
        if (!actionable.every(question => answers.has(question.field))) return;
        resolveCommand([...answers].map(([field, choice_id]) => ({ field, choice_id })));
      }, "primary-btn small"));
      actions.append(commandButton("Escribir otra petición", resetCommand));
      commandPrompt.append(actions);
    }
    return;
  }

  if (data.status === "failed") {
    commandError.textContent = data.error?.detail || "No se ha podido realizar la petición.";
    commandError.classList.remove("hidden");
    commandReceipt.classList.remove("hidden");
    commandReceipt.append(commandButton("Editar petición", editCommand));
    return;
  }

  commandReceipt.classList.remove("hidden");
  const message = document.createElement("p");
  message.textContent = data.result?.message || "Petición preparada";
  commandReceipt.append(message);
  const applied = renderApplied(data.result);
  if (applied) commandReceipt.append(applied);
  if (data.result?.query?.kind === "decisions") {
    const explanation = document.createElement("p");
    explanation.textContent = "Avisos activos que requieren atención. Los pospuestos quedan fuera hasta que vuelvan a activarse.";
    commandReceipt.append(explanation);
  }
  const entities = data.result?.query?.items || data.result?.entities || [];
  for (const entity of entities) {
    const link = document.createElement("a");
    link.href = commandEntityUrl(entity);
    link.className = "command-entity";
    link.textContent = entity.label;
    if (entity.type === "incident") {
      if (entity.message) { const detail = document.createElement("span"); detail.textContent = ` — ${entity.message}`; link.append(detail); }
      if (entity.recipient_name) { const recipient = document.createElement("small"); recipient.textContent = ` · Para ${entity.recipient_name}`; link.append(recipient); }
    }
    link.addEventListener("click", (event) => { event.preventDefault(); chrome.tabs.create({ url: link.href }); });
    commandReceipt.append(link);
  }
  if (data.result?.query?.has_more) {
    const more = commandButton(`Cargar más (${entities.length} de ${data.result.query.total})`, () => loadMoreCommandQuery(), "secondary-btn small");
    commandReceipt.append(more);
  }
  const actions = document.createElement("div");
  actions.className = "command-actions";
  if (data.status === "needs_review") actions.append(commandButton("Crear proyecto y tarea", () => executeCommand(), "primary-btn small"));
  if (data.status === "executed" && data.result?.undo_available && data.change_log_id) actions.append(commandButton("Deshacer", () => undoCommand(data.change_log_id)));
  actions.append(commandButton("Hacer otra cosa", resetCommand));
  commandReceipt.append(actions);
}

function resetCommand() {
  commandGeneration++;
  commandInFlight = false;
  currentCommand = null;
  commandRequestKey = newRequestKey();
  commandStepKey = newRequestKey();
  commandStepPayload = null;
  commandStepUncertain = false;
  commandText.value = "";
  commandText.disabled = false;
  commandSubmit.disabled = true;
  commandSubmit.textContent = "Hacer";
  commandPrompt.classList.add("hidden");
  commandReceipt.classList.add("hidden");
  commandError.classList.add("hidden");
  commandText.focus();
}

function editCommand() {
  commandGeneration++;
  commandInFlight = false;
  currentCommand = null;
  commandRequestKey = newRequestKey();
  commandStepKey = newRequestKey();
  commandStepPayload = null;
  commandStepUncertain = false;
  commandText.disabled = false;
  commandSubmit.disabled = !commandText.value.trim();
  commandSubmit.textContent = "Hacer";
  commandReceipt.classList.add("hidden");
  commandError.classList.add("hidden");
  commandText.focus();
}

async function commandRequest(path, body, session) {
  const response = await sessionFetch(session, `${API_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${session.token}` },
    body: JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(getDetail(data, `Error ${response.status}`));
    error.status = response.status;
    throw error;
  }
  return data;
}

async function getCommandReceipt(id, session) {
  const response = await sessionFetch(session, `${API_URL}/api/commands/${id}`, {
    headers: { Authorization: `Bearer ${session.token}` },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(getDetail(data, `Error ${response.status}`));
  return data;
}

async function submitCommand() {
  const session = captureSession();
  const generation = commandGeneration;
  const text = commandText.value.trim();
  if (!text || commandInFlight) return;
  commandInFlight = true;
  commandSubmit.disabled = true;
  commandSubmit.textContent = "Procesando…";
  commandError.classList.add("hidden");
  try {
    const data = await commandRequest("/api/commands", { request_key: commandRequestKey, text, channel: "extension" }, session);
    if (!isCurrentSession(session) || generation !== commandGeneration) return;
    renderCommand(data);
    commandText.disabled = true;
  } catch (error) {
    if (!isCurrentSession(session) || generation !== commandGeneration) return;
    const uncertain = !error.status || error.status >= 500;
    commandText.disabled = uncertain;
    if (!uncertain) commandRequestKey = newRequestKey();
    commandError.textContent = uncertain
      ? `No hemos recibido respuesta; la petición puede haberse completado. ${error.message || "No se ha podido conectar."}`
      : error.message;
    commandError.classList.remove("hidden");
    if (uncertain) {
      commandReceipt.replaceChildren(commandButton("Editar como petición nueva", editCommand));
      commandReceipt.classList.remove("hidden");
    }
  } finally {
    if (!isCurrentSession(session) || generation !== commandGeneration) return;
    commandInFlight = false;
    commandSubmit.textContent = currentCommand ? "Petición recibida" : "Reintentar";
    commandSubmit.disabled = Boolean(currentCommand) || !commandText.value.trim();
  }
}

async function resolveCommand(answers) {
  const session = captureSession();
  if (!currentCommand || commandInFlight) return;
  const target = { receiptId: currentCommand.id, revision: currentCommand.revision, generation: commandGeneration };
  commandInFlight = true;
  const payload = commandStepPayload || {
    receiptId: target.receiptId,
    revision: target.revision,
    answers,
  };
  commandStepPayload = payload;
  try {
    const data = await commandRequest(`/api/commands/${payload.receiptId}/resolve`, { request_key: commandStepKey, revision: payload.revision, answers: payload.answers }, session);
    if (!isCurrentSession(session) || !isCurrentCommand(target)) return;
    commandStepKey = newRequestKey();
    commandStepPayload = null;
    commandStepUncertain = false;
    renderCommand(data);
  } catch (error) {
    if (!isCurrentSession(session) || !isCurrentCommand(target)) return;
    if (error.status === 403 || error.status === 409) {
      try {
        const durable = await getCommandReceipt(payload.receiptId, session);
        if (!isCurrentSession(session) || !isCurrentCommand(target)) return;
        commandStepKey = newRequestKey();
        commandStepPayload = null;
        commandStepUncertain = false;
        renderCommand(durable);
        return;
      } catch (recoveryError) {
        commandError.textContent = recoveryError.message;
      }
    } else {
      commandError.textContent = error.message;
    }
    if (!error.status || error.status >= 500) {
      commandStepUncertain = true;
      renderCommand(currentCommand);
      commandError.textContent = "No hemos recibido respuesta. Reintenta la misma respuesta o recupera el recibo antes de cambiarla.";
    }
    commandError.classList.remove("hidden");
  } finally { if (isCurrentSession(session) && isCurrentCommand(target)) commandInFlight = false; }
}

async function executeCommand() {
  const session = captureSession();
  if (!currentCommand || commandInFlight) return;
  const target = { receiptId: currentCommand.id, revision: currentCommand.revision, generation: commandGeneration };
  commandInFlight = true;
  try {
    const data = await commandRequest(`/api/commands/${target.receiptId}/execute`, { request_key: commandStepKey, revision: target.revision }, session);
    if (!isCurrentSession(session) || !isCurrentCommand(target)) return;
    commandStepKey = newRequestKey();
    renderCommand(data);
  } catch (error) {
    if (!isCurrentSession(session) || !isCurrentCommand(target)) return;
    if (error.status === 403 || error.status === 409) {
      try {
        const durable = await getCommandReceipt(target.receiptId, session);
        if (!isCurrentSession(session) || !isCurrentCommand(target)) return;
        commandStepKey = newRequestKey();
        renderCommand(durable);
        return;
      } catch (recoveryError) { if (!isCurrentSession(session) || !isCurrentCommand(target)) return; }
    }
    commandError.textContent = error.message || "No se ha recibido confirmación. Reintenta sin duplicar el cambio.";
    commandError.classList.remove("hidden");
  } finally { if (isCurrentSession(session) && isCurrentCommand(target)) commandInFlight = false; }
}

async function loadMoreCommandQuery() {
  const session = captureSession();
  const query = currentCommand?.result?.query;
  if (!currentCommand || !query || commandInFlight) return;
  const target = { receiptId: currentCommand.id, generation: commandGeneration };
  commandInFlight = true;
  try {
    const page = (query.page || 1) + 1;
    const response = await sessionFetch(session, `${API_URL}/api/commands/${target.receiptId}/query?page=${page}&page_size=${query.page_size || 25}`, {
      headers: { Authorization: `Bearer ${session.token}` },
    });
    const next = await response.json();
    if (!response.ok) throw new Error(getDetail(next, `Error ${response.status}`));
    if (!isCurrentSession(session) || !isCurrentCommand(target)) return;
    currentCommand = { ...currentCommand, result: { ...currentCommand.result, query: { ...next, items: [...query.items, ...next.items] } } };
    renderCommand(currentCommand);
  } catch (error) {
    if (isCurrentSession(session) && isCurrentCommand(target)) { commandError.textContent = error.message; commandError.classList.remove("hidden"); }
  } finally { if (isCurrentSession(session) && isCurrentCommand(target)) commandInFlight = false; }
}

async function undoCommand(changeId) {
  const session = captureSession();
  const commandId = currentCommand?.id;
  try {
    const result = await commandRequest(`/api/changes/${changeId}/undo`, {}, session);
    if (!isCurrentSession(session)) return;
    if (currentCommand?.id === commandId) resetCommand();
    successText.textContent = result.warnings?.length || result.restored === 0
      ? `Deshecho con avisos: ${result.warnings?.join(" ") || "no había cambios que restaurar"}`
      : "Cambio deshecho";
    successMsg.classList.remove("hidden");
  } catch (error) {
    if (isCurrentSession(session)) { commandError.textContent = error.message; commandError.classList.remove("hidden"); }
  }
}

// ── Meeting notification preferences ─────────────────────
async function loadMeetingSettings({ preserveDraft = false } = {}) {
  const session = captureSession();
  const draft = preserveDraft ? { enabled: meetingExtensionEnabled.checked, minutes: meetingMinutesBefore.value } : null;
  try {
    const response = await sessionFetch(session, `${API_URL}/api/communication-schedules`, {
      headers: { Authorization: `Bearer ${session.token}` },
    });
    const data = await response.json();
    if (!response.ok) throw new Error(getDetail(data, `Error ${response.status}`));
    if (!isCurrentSession(session)) return;
    meetingPolicy = (data.policies || []).find(policy => policy.kind === "meeting") || null;
    if (draft) {
      meetingExtensionEnabled.checked = draft.enabled;
      meetingMinutesBefore.value = draft.minutes;
    } else if (meetingPolicy) {
      meetingExtensionEnabled.checked = meetingPolicy.channels.includes("extension");
      meetingMinutesBefore.value = String(meetingPolicy.minutes_before || 10);
    }
    meetingSettingsState.textContent = data.scheduler_enabled === false
      ? "Avisos pausados en la configuración general"
      : meetingPolicy?.reason || (meetingPolicy?.state === "ready" ? "Configurado" : "Revisa esta preferencia");
    meetingSettingsError.classList.add("hidden");
  } catch (error) {
    if (!isCurrentSession(session)) return;
    meetingSettingsError.textContent = error.message || "No se pudo cargar la configuración.";
    meetingSettingsError.classList.remove("hidden");
  }
}

async function saveMeetingSettings() {
  const session = captureSession();
  if (!meetingPolicy) return;
  meetingSettingsSave.disabled = true;
  meetingSettingsError.classList.add("hidden");
  const channels = new Set(meetingPolicy.channels || []);
  if (meetingExtensionEnabled.checked) channels.add("extension");
  else channels.delete("extension");
  try {
    const response = await sessionFetch(session, `${API_URL}/api/communication-schedules/meeting`, {
      method: "PUT",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${session.token}` },
      body: JSON.stringify({
        revision: meetingPolicy.revision,
        enabled: meetingPolicy.enabled,
        channels: [...channels],
        minutes_before: Number(meetingMinutesBefore.value),
        quiet_start: meetingPolicy.quiet_start,
        quiet_end: meetingPolicy.quiet_end,
        time: null,
      }),
    });
    if (response.status === 409) {
      await loadMeetingSettings({ preserveDraft: true });
      throw new Error("La configuración cambió en otro dispositivo. Revísala y vuelve a guardar.");
    }
    const policy = await response.json();
    if (!response.ok) throw new Error(getDetail(policy, `Error ${response.status}`));
    if (!isCurrentSession(session)) return;
    meetingPolicy = policy;
    meetingSettingsState.textContent = "Configuración guardada";
  } catch (error) {
    if (!isCurrentSession(session)) return;
    meetingSettingsError.textContent = error.message || "No se pudo guardar la configuración.";
    meetingSettingsError.classList.remove("hidden");
  } finally {
    if (isCurrentSession(session)) meetingSettingsSave.disabled = false;
  }
}

// ── Capture Mode Toggle ───────────────────────────────────
modeBtns.forEach((btn) => {
  btn.addEventListener("click", () => {
    modeBtns.forEach((b) => b.classList.remove("active"));
    modeBtns.forEach((b) => b.setAttribute("aria-selected", String(b === btn)));
    btn.classList.add("active");
    const mode = btn.dataset.mode;
    captureCommandMode.classList.toggle("hidden", mode !== "command");
    captureNoteMode.classList.toggle("hidden", mode !== "note");
    captureTaskMode.classList.toggle("hidden", mode !== "task");
    if (mode === "command") {
      commandText.focus();
    } else if (mode === "note") {
      noteText.focus();
    } else {
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
