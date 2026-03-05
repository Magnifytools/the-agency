// Agency Manager - Quick Capture Extension
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
const includeUrl = document.getElementById("include-url");
const pageInfo = document.getElementById("page-info");
const successMsg = document.getElementById("success-msg");
const inboxBar = document.getElementById("inbox-bar");
const inboxCount = document.getElementById("inbox-count");
const openInbox = document.getElementById("open-inbox");
const settingsBtn = document.getElementById("settings-btn");

// ── State ─────────────────────────────────────────────────
let currentTab = null;
let token = "";

// ── Init ──────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", async () => {
  // Get current tab info
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  currentTab = tab;

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

  // Show page info
  if (currentTab) {
    const host = new URL(currentTab.url || "about:blank").hostname || "nueva pestana";
    pageInfo.textContent = host;
  }

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

  // Load inbox count
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

// ── Capture ───────────────────────────────────────────────
captureBtn.addEventListener("click", () => captureNote());

async function captureNote() {
  const text = noteText.value.trim();
  if (!text) return;

  // Build raw_text with optional URL context
  let rawText = text;
  if (includeUrl.checked && currentTab?.url) {
    rawText += `\n\n[Fuente: ${currentTab.title || currentTab.url}]\n${currentTab.url}`;
  }

  // UI loading state
  captureBtn.disabled = true;
  btnText.classList.add("hidden");
  btnLoading.classList.remove("hidden");
  successMsg.classList.add("hidden");

  try {
    const res = await fetch(`${API_URL}/api/inbox`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        raw_text: rawText,
        source: "chrome_extension",
      }),
    });

    if (res.status === 401) {
      // Token expired
      token = "";
      await chrome.storage.local.remove(STORAGE_KEYS.token);
      showLoginView();
      return;
    }

    if (!res.ok) throw new Error("Error al enviar");

    // Success
    noteText.value = "";
    successMsg.classList.remove("hidden");
    loadInboxCount();

    // Auto-close after 2s
    setTimeout(() => window.close(), 2000);
  } catch (err) {
    loginError.textContent = err.message;
    loginError.classList.remove("hidden");
  } finally {
    captureBtn.disabled = false;
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
  showLoginView();
});
