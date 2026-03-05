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
const projectSelect = document.getElementById("project-select");
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
  // Load saved config
  const stored = await chrome.storage.local.get([
    STORAGE_KEYS.token,
    STORAGE_KEYS.email,
  ]);

  token = stored[STORAGE_KEYS.token] || "";
  if (stored[STORAGE_KEYS.email]) emailInput.value = stored[STORAGE_KEYS.email];

  // Check if we have a valid token
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

  // Enable/disable capture button based on text
  noteText.addEventListener("input", () => {
    captureBtn.disabled = !noteText.value.trim();
  });

  // Cmd+Enter to capture
  noteText.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
      e.preventDefault();
      if (noteText.value.trim()) captureNote();
    }
  });

  // Load projects and inbox count
  loadProjects();
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

    // Save
    await chrome.storage.local.set({
      [STORAGE_KEYS.token]: token,
      [STORAGE_KEYS.email]: emailInput.value,
    });

    // Notify background
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

// ── Projects ──────────────────────────────────────────────
async function loadProjects() {
  try {
    const res = await fetch(`${API_URL}/api/projects?limit=100&status=active`, {
      headers: { Authorization: `Bearer ${token}` },
    });

    if (!res.ok) return;

    const data = await res.json();
    // API returns paginated: { items: [...], total: N }
    const projects = data.items || data;

    projects.forEach((p) => {
      const opt = document.createElement("option");
      opt.value = p.id;
      opt.textContent = p.name;
      projectSelect.appendChild(opt);
    });
  } catch {
    // silently ignore — projects are optional
  }
}

// ── Capture ───────────────────────────────────────────────
captureBtn.addEventListener("click", () => captureNote());

async function captureNote() {
  const text = noteText.value.trim();
  if (!text) return;

  // UI loading state
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

  const selectedProject = projectSelect.value;
  if (selectedProject) {
    body.project_id = parseInt(selectedProject, 10);
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
      // Token expired
      token = "";
      await chrome.storage.local.remove(STORAGE_KEYS.token);
      showLoginView();
      return;
    }

    if (!res.ok) {
      const errData = await res.json().catch(() => ({}));
      throw new Error(errData.detail || `Error ${res.status}`);
    }

    // Success
    noteText.value = "";
    captureBtn.disabled = true;
    successMsg.classList.remove("hidden");
    loadInboxCount();

    // Notify background to update badge
    chrome.runtime.sendMessage({ type: "NOTE_CREATED" });

    // Auto-close after 2s
    setTimeout(() => window.close(), 2000);
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
