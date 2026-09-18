// The Agency - Chrome Extension
// Background service worker — context menus + notifications

const API_URL = "https://agency.magnifytools.com";

const STORAGE_KEYS = {
  token: "am_token",
  meetingNotifications: "am_meeting_notifications_v2",
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
async function _getMeetingNotificationStates() {
  const data = await chrome.storage.local.get(STORAGE_KEYS.meetingNotifications);
  return data[STORAGE_KEYS.meetingNotifications] || {};
}

async function _reserveMeetingNotification(key, token) {
  const states = await _getMeetingNotificationStates();
  if (!await ownsSession(token) || states[key]) return false;
  states[key] = "pending";
  const keys = Object.keys(states);
  for (const oldKey of keys.slice(0, Math.max(0, keys.length - 499))) delete states[oldKey];
  await chrome.storage.local.set({ [STORAGE_KEYS.meetingNotifications]: states });
  return await ownsSession(token);
}

async function _confirmMeetingNotification(key, token) {
  const states = await _getMeetingNotificationStates();
  if (!await ownsSession(token) || states[key] !== "pending") return;
  states[key] = "confirmed";
  await chrome.storage.local.set({ [STORAGE_KEYS.meetingNotifications]: states });
}

async function checkUpcomingMeetings(token) {
  try {
    const res = await fetch(`${API_URL}/api/communication-schedules/extension-upcoming`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) return;
    const data = await res.json();
    if (!await ownsSession(token)) return;
    for (const occurrence of data.occurrences || []) {
      if (!await ownsSession(token)) return;
      const key = `${data.user_id}:${occurrence.occurrence_id}`;
      if (!await _reserveMeetingNotification(key, token)) continue;
      const notificationId = `agency-meeting:${key}`;
      chrome.notifications.create(notificationId, {
        type: "basic",
        iconUrl: "icons/icon48.png",
        title: occurrence.title,
        message: occurrence.content,
        priority: 2,
      }, () => { void _confirmMeetingNotification(key, token); });
    }
  } catch {
    // A pending reservation is deliberately not replayed: notification
    // creation may have succeeded even if its callback was interrupted.
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
