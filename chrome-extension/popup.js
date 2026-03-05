// The Agency - Quick Capture Extension
// Popup script

const API_URL = "https://agency.magnifytools.com";

const STORAGE_KEYS = {
  token: "am_token",
  email: "am_email",
};

// ── DOM refs ──────────────────────────────────────────────
const loginView = document.getElementById("login-view");
const captureView = document.getElementById("capture-view");
const loginForm = document.getElementById("login-form");
const loginError = document.getElementById("login-error");
const emailInput = document.getElementById("email");
const passwordInput = document.getElementById("password");
const noteText = document.getElementById("note-text");
const captureBtn = document.getElementById("capture-btn");
const btnText = document.getElementById("btn-text");
const btnLoading = document.getElementById("btn-loading");
const assignSelect = document.getElementById("assign-select");
const successMsg = document.getElementById("success-msg");
const captureError = document.getElementById("capture-error");
const inboxBar = document.getElementById("inbox-bar");
const inboxCount = document.getElementById("inbox-count");
const openInbox = document.getElementById("open-inbox");
const settingsBtn = document.getElementById("settings-btn");

// ── State ─────────────────────────────────────────────────
let token = "";

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
      showCaptureView();
      return;
    }
  }

  showLoginView();
});

// ── Views ─────────────────────────────────────────────────
function showLoginView() {
  loginView.classList.remove("hidden");
  captureView.classList.add("hidden");
  emailInput.focus();
}

function showCaptureView() {
  loginView.classList.add("hidden");
  captureView.classList.remove("hidden");
  noteText.focus();

  openInbox.href = `${API_URL}/inbox`;

  noteText.addEventListener("input", () => {
    captureBtn.disabled = !noteText.value.trim();
  });

  noteText.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      if (noteText.value.trim()) captureNote();
    }
  });

  loadProjectsAndClients();
  loadInboxCount();
}

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
    showCaptureView();
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

    // Success — reset form but do NOT auto-close
    noteText.value = "";
    captureBtn.disabled = true;

    // Dynamic success text
    const successText = document.getElementById("success-text");
    if (selected) {
      successText.textContent = "Nota capturada y asignada ✓";
    } else {
      successText.textContent = "Nota capturada — IA clasificando...";
    }
    successMsg.classList.remove("hidden");
    loadInboxCount();

    chrome.runtime.sendMessage({ type: "NOTE_CREATED" });

    // Hide success after 3s so user can send another note
    setTimeout(() => {
      successMsg.classList.add("hidden");
    }, 3000);
  } catch (err) {
    captureError.textContent = err.message || "Error al enviar. Comprueba tu conexion.";
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
