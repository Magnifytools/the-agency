// The Agency - Chrome Extension
// Popup script with Capture, Timer, and Tasks tabs

const API_URL = "https://agency.magnifytools.com";

const STORAGE_KEYS = {
  token: "am_token",
  email: "am_email",
};

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

// Tabs
const tabs = document.querySelectorAll(".tab");
const tabContents = {
  capture: document.getElementById("tab-capture"),
  timer: document.getElementById("tab-timer"),
  tasks: document.getElementById("tab-tasks"),
};

// Capture
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

// Timer
const timerActive = document.getElementById("timer-active");
const timerIdle = document.getElementById("timer-idle");
const timerElapsed = document.getElementById("timer-elapsed");
const timerTaskName = document.getElementById("timer-task-name");
const timerStopBtn = document.getElementById("timer-stop-btn");
const timerTaskSelect = document.getElementById("timer-task-select");
const timerStartBtn = document.getElementById("timer-start-btn");
const manualTaskSelect = document.getElementById("manual-task-select");
const manualHours = document.getElementById("manual-hours");
const manualMins = document.getElementById("manual-mins");
const manualNotes = document.getElementById("manual-notes");
const manualSaveBtn = document.getElementById("manual-save-btn");
const timerError = document.getElementById("timer-error");
const timerSuccess = document.getElementById("timer-success");

// Tasks
const tasksFilter = document.getElementById("tasks-filter");
const tasksRefresh = document.getElementById("tasks-refresh");
const tasksList = document.getElementById("tasks-list");
const tasksEmpty = document.getElementById("tasks-empty");

// ── State ─────────────────────────────────────────────────
let token = "";
let timerInterval = null;
let activeTimerStart = null;

// ── Init ──────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", async () => {
  const stored = await chrome.storage.local.get([
    STORAGE_KEYS.token,
    STORAGE_KEYS.email,
  ]);

  token = stored[STORAGE_KEYS.token] || "";
  if (stored[STORAGE_KEYS.email]) emailInput.value = stored[STORAGE_KEYS.email];

  if (token) {
    const valid = await verifyToken();
    if (valid) {
      showMainView();
      return;
    }
  }

  showLoginView();
});

// ── Views ─────────────────────────────────────────────────
function showLoginView() {
  loginView.classList.remove("hidden");
  mainView.classList.add("hidden");
  emailInput.focus();
}

function showMainView() {
  loginView.classList.add("hidden");
  mainView.classList.remove("hidden");
  noteText.focus();

  openInbox.href = `${API_URL}/inbox`;

  // Setup capture listeners
  noteText.addEventListener("input", () => {
    captureBtn.disabled = !noteText.value.trim();
  });

  noteText.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      if (noteText.value.trim()) captureNote();
    }
  });

  // Load data
  loadProjectsAndClients();
  loadInboxCount();
  loadActiveTimer();
  loadTasks();
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
  loginError.classList.add("hidden");

  try {
    const res = await fetch(`${API_URL}/api/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: emailInput.value,
        password: passwordInput.value,
      }),
    });

    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || "Credenciales invalidas");
    }

    const data = await res.json();
    token = data.access_token;

    await chrome.storage.local.set({
      [STORAGE_KEYS.token]: token,
      [STORAGE_KEYS.email]: emailInput.value,
    });

    chrome.runtime.sendMessage({ type: "AUTH_UPDATE", token });
    showMainView();
  } catch (err) {
    loginError.textContent = err.message;
    loginError.classList.remove("hidden");
  }
});

async function verifyToken() {
  try {
    const res = await fetch(`${API_URL}/api/auth/me`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    return res.ok;
  } catch {
    return false;
  }
}

// ── Projects + Clients (combined selector) ────────────────
async function loadProjectsAndClients() {
  try {
    const [projRes, clientRes] = await Promise.all([
      fetch(`${API_URL}/api/projects?limit=100&status=active`, {
        headers: { Authorization: `Bearer ${token}` },
      }),
      fetch(`${API_URL}/api/clients?limit=100&status=active`, {
        headers: { Authorization: `Bearer ${token}` },
      }),
    ]);

    // Projects group
    if (projRes.ok) {
      const projData = await projRes.json();
      const projects = projData.items || projData;
      if (projects.length > 0) {
        const grp = document.createElement("optgroup");
        grp.label = "Proyectos";
        projects.forEach((p) => {
          const opt = document.createElement("option");
          opt.value = `project:${p.id}`;
          opt.textContent = p.name;
          grp.appendChild(opt);
        });
        assignSelect.appendChild(grp);
      }
    }

    // Clients group
    if (clientRes.ok) {
      const clientData = await clientRes.json();
      const clients = clientData.items || clientData;
      if (clients.length > 0) {
        const grp = document.createElement("optgroup");
        grp.label = "Clientes";
        clients.forEach((c) => {
          const opt = document.createElement("option");
          opt.value = `client:${c.id}`;
          opt.textContent = c.name;
          grp.appendChild(opt);
        });
        assignSelect.appendChild(grp);
      }
    }
  } catch {
    // silently ignore — assignment is optional
  }
}

// ── Capture ───────────────────────────────────────────────
captureBtn.addEventListener("click", () => captureNote());

async function captureNote() {
  const text = noteText.value.trim();
  if (!text) return;

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
    if (type === "project") body.project_id = parseInt(id, 10);
    else if (type === "client") body.client_id = parseInt(id, 10);
  }

  try {
    const res = await fetch(`${API_URL}/api/inbox`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(body),
    });

    if (res.status === 401) {
      token = "";
      await chrome.storage.local.remove(STORAGE_KEYS.token);
      showLoginView();
      return;
    }

    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || `Error ${res.status}`);
    }

    // Success — reset form
    noteText.value = "";
    linkUrl.value = "";
    captureBtn.disabled = true;

    if (selected) {
      successText.textContent = "Nota capturada y asignada ✓";
    } else {
      successText.textContent = "Nota capturada — IA clasificando...";
    }
    successMsg.classList.remove("hidden");
    loadInboxCount();

    chrome.runtime.sendMessage({ type: "NOTE_CREATED" });

    setTimeout(() => {
      successMsg.classList.add("hidden");
    }, 3000);
  } catch (err) {
    captureError.textContent = err.message || "Error al enviar.";
    captureError.classList.remove("hidden");
  } finally {
    captureBtn.disabled = !noteText.value.trim();
    btnText.classList.remove("hidden");
    btnLoading.classList.add("hidden");
  }
}

// ── Inbox count ───────────────────────────────────────────
async function loadInboxCount() {
  try {
    const res = await fetch(`${API_URL}/api/inbox/count`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (res.ok) {
      const data = await res.json();
      if (data.count > 0) {
        inboxCount.textContent = data.count;
        inboxBar.classList.remove("hidden");
      } else {
        inboxBar.classList.add("hidden");
      }
    }
  } catch {
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
settingsBtn.addEventListener("click", async () => {
  token = "";
  await chrome.storage.local.remove(STORAGE_KEYS.token);
  chrome.runtime.sendMessage({ type: "AUTH_UPDATE", token: "" });
  showLoginView();
});

// ══════════════════════════════════════════════════════════
// TIMER TAB
// ══════════════════════════════════════════════════════════

async function loadActiveTimer() {
  try {
    const res = await fetch(`${API_URL}/api/timer/active`, {
      headers: { Authorization: `Bearer ${token}` },
    });

    if (res.ok) {
      const data = await res.json();
      if (data && data.started_at) {
        showActiveTimer(data);
        return;
      }
    }
  } catch {
    // no active timer
  }

  showIdleTimer();
}

function showActiveTimer(data) {
  timerActive.classList.remove("hidden");
  timerIdle.classList.add("hidden");

  activeTimerStart = new Date(data.started_at);
  timerTaskName.textContent = data.task_title || "Sin tarea";

  // Start interval
  if (timerInterval) clearInterval(timerInterval);
  updateTimerDisplay();
  timerInterval = setInterval(updateTimerDisplay, 1000);
}

function showIdleTimer() {
  timerActive.classList.add("hidden");
  timerIdle.classList.remove("hidden");

  activeTimerStart = null;
  if (timerInterval) {
    clearInterval(timerInterval);
    timerInterval = null;
  }

  // Load tasks for selectors
  loadTimerTasks();
}

function updateTimerDisplay() {
  if (!activeTimerStart) return;
  const now = new Date();
  const diff = Math.floor((now - activeTimerStart) / 1000);
  const h = Math.floor(diff / 3600);
  const m = Math.floor((diff % 3600) / 60);
  const s = diff % 60;
  timerElapsed.textContent = `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

async function loadTimerTasks() {
  try {
    const res = await fetch(`${API_URL}/api/tasks?assigned_to=me&status=in_progress&limit=50`, {
      headers: { Authorization: `Bearer ${token}` },
    });

    if (res.ok) {
      const data = await res.json();
      const tasks = data.items || data;

      // Populate both selectors
      [timerTaskSelect, manualTaskSelect].forEach((sel) => {
        // Keep first option
        while (sel.options.length > 1) sel.remove(1);
        tasks.forEach((t) => {
          const opt = document.createElement("option");
          opt.value = t.id;
          opt.textContent = t.title.length > 40 ? t.title.slice(0, 40) + "..." : t.title;
          sel.appendChild(opt);
        });
      });
    }
  } catch {
    // silently ignore
  }
}

// Start timer
timerStartBtn.addEventListener("click", async () => {
  timerStartBtn.disabled = true;
  timerStartBtn.textContent = "Iniciando...";
  timerError.classList.add("hidden");

  const body = {};
  if (timerTaskSelect.value) body.task_id = parseInt(timerTaskSelect.value, 10);

  try {
    const res = await fetch(`${API_URL}/api/timer/start`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(body),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Error al iniciar timer");
    }

    const data = await res.json();
    showActiveTimer(data);
  } catch (err) {
    timerError.textContent = err.message;
    timerError.classList.remove("hidden");
  } finally {
    timerStartBtn.disabled = false;
    timerStartBtn.textContent = "Iniciar Timer";
  }
});

// Stop timer
timerStopBtn.addEventListener("click", async () => {
  timerStopBtn.disabled = true;
  timerStopBtn.textContent = "Deteniendo...";

  try {
    const res = await fetch(`${API_URL}/api/timer/stop`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Error al detener timer");
    }

    showIdleTimer();
    showTimerSuccess("Timer detenido y registrado ✓");
  } catch (err) {
    timerError.textContent = err.message;
    timerError.classList.remove("hidden");
  } finally {
    timerStopBtn.disabled = false;
    timerStopBtn.textContent = "Detener";
  }
});

// Manual time entry
manualSaveBtn.addEventListener("click", async () => {
  const hours = parseInt(manualHours.value, 10) || 0;
  const mins = parseInt(manualMins.value, 10) || 0;
  const totalMinutes = hours * 60 + mins;

  timerError.classList.add("hidden");
  timerSuccess.classList.add("hidden");

  if (totalMinutes <= 0) {
    timerError.textContent = "Introduce un tiempo mayor a 0";
    timerError.classList.remove("hidden");
    return;
  }

  manualSaveBtn.disabled = true;
  manualSaveBtn.textContent = "Guardando...";

  const body = { minutes: totalMinutes };
  if (manualTaskSelect.value) body.task_id = parseInt(manualTaskSelect.value, 10);
  if (manualNotes.value.trim()) body.notes = manualNotes.value.trim();

  try {
    const res = await fetch(`${API_URL}/api/time-entries`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(body),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || "Error al guardar");
    }

    // Reset form
    manualHours.value = "0";
    manualMins.value = "0";
    manualNotes.value = "";
    manualTaskSelect.value = "";

    showTimerSuccess("Tiempo registrado ✓");
  } catch (err) {
    timerError.textContent = err.message;
    timerError.classList.remove("hidden");
  } finally {
    manualSaveBtn.disabled = false;
    manualSaveBtn.textContent = "Guardar registro";
  }
});

function showTimerSuccess(msg) {
  timerSuccess.textContent = msg;
  timerSuccess.classList.remove("hidden");
  setTimeout(() => timerSuccess.classList.add("hidden"), 3000);
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
  tasksList.innerHTML = '<div class="tasks-loading">Cargando tareas...</div>';
  tasksEmpty.classList.add("hidden");

  const status = tasksFilter.value;
  const params = new URLSearchParams({ assigned_to: "me", limit: "30" });
  if (status) params.set("status", status);

  try {
    const res = await fetch(`${API_URL}/api/tasks?${params}`, {
      headers: { Authorization: `Bearer ${token}` },
    });

    if (!res.ok) throw new Error("Error al cargar tareas");

    const data = await res.json();
    const tasks = data.items || data;

    if (tasks.length === 0) {
      tasksList.innerHTML = "";
      tasksEmpty.classList.remove("hidden");
      return;
    }

    tasksEmpty.classList.add("hidden");
    tasksList.innerHTML = tasks.map((t) => renderTaskCard(t)).join("");

    // Add click handlers to open tasks in webapp
    tasksList.querySelectorAll(".task-card").forEach((card) => {
      card.addEventListener("click", () => {
        const taskId = card.dataset.id;
        chrome.tabs.create({ url: `${API_URL}/tasks?task=${taskId}` });
        window.close();
      });
    });
  } catch (err) {
    tasksList.innerHTML = `<div class="tasks-error">${err.message}</div>`;
  }
}

function renderTaskCard(task) {
  const statusColor = STATUS_COLORS[task.status] || "#71717a";
  const statusLabel = STATUS_LABELS[task.status] || task.status;
  const priority = task.priority || "";
  const priorityIcon = priority === "high" ? "↑" : priority === "low" ? "↓" : "";
  const projectName = task.project_name ? `<span class="task-project">${escapeHtml(task.project_name)}</span>` : "";

  return `
    <div class="task-card" data-id="${task.id}">
      <div class="task-header">
        <span class="task-status-dot" style="background:${statusColor}"></span>
        <span class="task-title">${escapeHtml(task.title)}</span>
        ${priorityIcon ? `<span class="task-priority task-priority-${priority}">${priorityIcon}</span>` : ""}
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
