// The Agency - Chrome Extension
// Background service worker — context menus + notifications

const API_URL = "https://agency.magnifytools.com";

const STORAGE_KEYS = {
  token: "am_token",
};

// Do not let a response sent for an old account affect the new one.
async function ownsSession(token) {
  const stored = await chrome.storage.local.get([STORAGE_KEYS.token]);
  return Boolean(token) && stored[STORAGE_KEYS.token] === token;
}

// ── Context menu setup ────────────────────────────────────
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "am-capture-selection",
    title: "Capturar al Inbox de The Agency",
    contexts: ["selection"],
  });

  chrome.contextMenus.create({
    id: "am-capture-page",
    title: "Capturar esta pagina al Inbox",
    contexts: ["page"],
  });
});

// ── Context menu handler ──────────────────────────────────
chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  const stored = await chrome.storage.local.get([STORAGE_KEYS.token]);
  const token = stored[STORAGE_KEYS.token];

  if (!token) {
    // Show notification to login first
    showNotification(
      "Inicia sesion primero",
      "Abre la extension y conecta tu cuenta."
    );
    return;
  }

  let rawText = "";

  if (info.menuItemId === "am-capture-selection") {
    // Capture selected text + page context
    rawText = info.selectionText || "";
    if (tab?.url) {
      rawText += `\n\n[Seleccion de: ${tab.title || tab.url}]\n${tab.url}`;
    }
  } else if (info.menuItemId === "am-capture-page") {
    // Capture page title + URL
    rawText = `${tab?.title || "Pagina sin titulo"}\n${tab?.url || ""}`;
  }

  if (!rawText.trim()) return;

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

    if (!await ownsSession(token)) return;
    if (res.ok) {
      showNotification("✓ Nota capturada", "IA clasificando en segundo plano...");
      updateBadge(token);
    } else if (res.status === 401) {
      showNotification(
        "Sesion expirada",
        "Abre la extension para reconectar."
      );
      // The popup owns session expiry; never remove a possibly newer token here.
    } else {
      showNotification("Error", "No se pudo enviar la nota.");
    }
  } catch (err) {
    if (!await ownsSession(token)) return;
    showNotification("Error de conexion", "No se pudo conectar al servidor.");
  }
});

// ── Messages from popup ───────────────────────────────────
chrome.runtime.onMessage.addListener(async (msg) => {
  if (msg.type === "AUTH_UPDATE") {
    if (msg.token) {
      updateBadge(msg.token);
    } else if (!(await chrome.storage.local.get([STORAGE_KEYS.token]))[STORAGE_KEYS.token]) {
      chrome.action.setBadgeText({ text: "" });
    }
  }
  if (msg.type === "NOTE_CREATED" || msg.type === "TIMER_UPDATED") {
    const stored = await chrome.storage.local.get([STORAGE_KEYS.token]);
    if (stored[STORAGE_KEYS.token]) {
      updateBadge(stored[STORAGE_KEYS.token]);
    }
  }
});

// ── Badge with inbox count ────────────────────────────────
async function updateBadge(token) {
  try {
    const res = await fetch(`${API_URL}/api/inbox/count`, {
      headers: { Authorization: `Bearer ${token}` },
    });

    if (res.ok) {
      const data = await res.json();
      if (!await ownsSession(token)) return;
      const count = data.count || 0;
      chrome.action.setBadgeText({
        text: count > 0 ? String(count) : "",
      });
      chrome.action.setBadgeBackgroundColor({ color: "#6366f1" });
    }
  } catch {
    // silently ignore
  }
}

// ── Periodic badge refresh (every 2 minutes) ──────────────
chrome.alarms.create("refresh-badge", { periodInMinutes: 2 });
chrome.alarms.create("check-meetings", { periodInMinutes: 1 });

chrome.alarms.onAlarm.addListener(async (alarm) => {
  const stored = await chrome.storage.local.get([STORAGE_KEYS.token]);
  if (!stored[STORAGE_KEYS.token]) return;

  if (alarm.name === "refresh-badge") {
    updateBadge(stored[STORAGE_KEYS.token]);
  }
  if (alarm.name === "check-meetings") {
    checkUpcomingMeetings(stored[STORAGE_KEYS.token]);
  }
});

// ── Startup badge ─────────────────────────────────────────
chrome.runtime.onStartup.addListener(async () => {
  const stored = await chrome.storage.local.get([STORAGE_KEYS.token]);
  if (stored[STORAGE_KEYS.token]) {
    updateBadge(stored[STORAGE_KEYS.token]);
  }
});

// ── Meeting check ────────────────────────────────────────
async function _getNotifiedMeetings() {
  const data = await chrome.storage.session.get("notifiedMeetings");
  return new Set(data.notifiedMeetings || []);
}

async function _addNotifiedMeeting(id, token) {
  const notified = await _getNotifiedMeetings();
  if (!await ownsSession(token)) return;
  notified.add(id);
  await chrome.storage.session.set({ notifiedMeetings: [...notified] });
}

async function checkUpcomingMeetings(token) {
  try {
    const res = await fetch(`${API_URL}/api/calendar/upcoming?minutes=35`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) return;
    const meetings = await res.json();
    const notified = await _getNotifiedMeetings();
    if (!await ownsSession(token)) return;
    for (const m of meetings) {
      if (!await ownsSession(token)) return;
      if (notified.has(m.id)) continue;
      if (m.minutes_until <= 30) {
        showNotification(
          `📅 Reunión en ${m.minutes_until} min`,
          m.title
        );
        await _addNotifiedMeeting(m.id, token);
      }
    }
  } catch {
    // silently ignore
  }
}

// ── Notifications helper ──────────────────────────────────
function showNotification(title, message) {
  chrome.notifications.create({
    type: "basic",
    iconUrl: "icons/icon48.png",
    title,
    message,
    priority: 2,
  });
}
