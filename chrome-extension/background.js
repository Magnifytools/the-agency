// The Agency - Chrome Extension
// Background service worker — context menus + notifications

const API_URL = "https://agency.magnifytools.com";

const STORAGE_KEYS = {
  token: "am_token",
  meetingNotifications: "am_meeting_notifications_v2",
  // Por navegador: desde qué aviso seguir y qué alertas críticas ya se enseñaron.
  desktopNotices: "am_desktop_notices_v1",
  // Preferencia de este navegador (la escribe el popup).
  desktopPrefs: "am_desktop_prefs_v1",
};

const DEFAULT_DESKTOP_PREFS = { enabled: true, quietStart: "20:00", quietEnd: "08:00" };
// Más de esto en una pasada se resume en un solo aviso.
const DESKTOP_MAX_SHOWN = 3;

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
      checkDesktopNotices(msg.token);
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

// ── Badge: alertas activas (rojo) y, sin alertas, notas por aclarar ──
async function _count(path, token) {
  try {
    const res = await fetch(`${API_URL}${path}`, { headers: { Authorization: `Bearer ${token}` } });
    return res.ok ? (await res.json()).count || 0 : null;
  } catch {
    return null;
  }
}

async function updateBadge(token) {
  const [alerts, inbox] = await Promise.all([_count("/api/incidents/count", token), _count("/api/inbox/count", token)]);
  if (alerts === null && inbox === null) return;
  if (!await ownsSession(token)) return;
  if (alerts > 0) {
    chrome.action.setBadgeText({ text: alerts > 99 ? "99+" : String(alerts) });
    chrome.action.setBadgeBackgroundColor({ color: "#EF4444" });
  } else {
    chrome.action.setBadgeText({ text: inbox > 0 ? String(inbox) : "" });
    chrome.action.setBadgeBackgroundColor({ color: "#6366f1" });
  }
  chrome.action.setTitle?.({
    title: `The Agency${alerts ? ` · ${alerts} alerta${alerts === 1 ? "" : "s"}` : ""}${inbox ? ` · ${inbox} por aclarar` : ""}`,
  });
}

// ── Periodic badge refresh (every 2 minutes) ──────────────
chrome.alarms.create("refresh-badge", { periodInMinutes: 2 });
chrome.alarms.create("check-meetings", { periodInMinutes: 1 });
chrome.alarms.create("check-desktop-notices", { periodInMinutes: 1 });

chrome.alarms.onAlarm.addListener(async (alarm) => {
  const stored = await chrome.storage.local.get([STORAGE_KEYS.token]);
  if (!stored[STORAGE_KEYS.token]) return;

  if (alarm.name === "refresh-badge") {
    updateBadge(stored[STORAGE_KEYS.token]);
  }
  if (alarm.name === "check-meetings") {
    checkUpcomingMeetings(stored[STORAGE_KEYS.token]);
  }
  if (alarm.name === "check-desktop-notices") {
    checkDesktopNotices(stored[STORAGE_KEYS.token]);
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

function _meetingMessage(occurrence, agencyTimeZone) {
  const instant = new Date(occurrence.start_time);
  if (!occurrence.start_time || Number.isNaN(instant.getTime())) return occurrence.content;
  const localTimeZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const format = timeZone => new Intl.DateTimeFormat("es-ES", {
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    timeZone,
  }).format(instant);
  const local = format(localTimeZone);
  const agency = agencyTimeZone && agencyTimeZone !== localTimeZone
    ? ` · Agencia (${agencyTimeZone}): ${format(agencyTimeZone)}`
    : "";
  return `Hora local: ${local}${agency}\n${occurrence.content}`;
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
        message: _meetingMessage(occurrence, data.timezone),
        priority: 2,
      }, () => { void _confirmMeetingNotification(key, token); });
    }
  } catch {
    // A pending reservation is deliberately not replayed: notification
    // creation may have succeeded even if its callback was interrupted.
  }
}

// ── Avisos del escritorio ────────────────────────────────
// Sólo lo que pide hacer algo: asignaciones, menciones, revisión y alertas
// críticas (lo decide GET /api/notifications/desktop). La primera vez en un
// navegador sólo se marca el punto de partida: nunca se vuelca el historial.

function _clock(date) {
  return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

// Hora del ordenador. Un tramo que cruza la medianoche (20:00-08:00) también vale.
function inQuietHours(prefs, now = new Date()) {
  const { quietStart: start, quietEnd: end } = prefs;
  if (!start || !end || start === end) return false;
  const clock = _clock(now);
  return start < end ? clock >= start && clock < end : clock >= start || clock < end;
}

async function desktopPrefs() {
  const stored = (await chrome.storage.local.get(STORAGE_KEYS.desktopPrefs))[STORAGE_KEYS.desktopPrefs];
  return { ...DEFAULT_DESKTOP_PREFS, ...(stored || {}) };
}

function _noticeId(kind, key, link) {
  // El enlace va en el id: el service worker puede dormirse entre crear el aviso y pulsarlo.
  return `agency-notice:${kind}:${key}|${link || ""}`;
}

function _showNotices(items, { kind, singular, plural }) {
  items.slice(0, DESKTOP_MAX_SHOWN).forEach((item) => {
    chrome.notifications.create(_noticeId(kind, item.key, item.link_url), {
      type: "basic",
      iconUrl: "icons/icon48.png",
      title: item.title,
      message: item.message || "",
      priority: kind === "critical" ? 2 : 1,
    });
  });
  const rest = items.length - DESKTOP_MAX_SHOWN;
  if (rest > 0) {
    chrome.notifications.create(_noticeId(kind, `more-${Date.now()}`, kind === "critical" ? "/incidents" : "/tasks?view=my_day"), {
      type: "basic",
      iconUrl: "icons/icon48.png",
      title: `${rest} ${rest === 1 ? singular : plural} más`,
      message: "Ábrelas en The Agency.",
      priority: 1,
    });
  }
}

async function checkDesktopNotices(token) {
  try {
    const prefs = await desktopPrefs();
    const state = (await chrome.storage.local.get(STORAGE_KEYS.desktopNotices))[STORAGE_KEYS.desktopNotices] || {};
    const query = Number.isInteger(state.afterId) ? `?after_id=${state.afterId}` : "";
    const res = await fetch(`${API_URL}/api/notifications/desktop${query}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (!res.ok) return;
    const data = await res.json();
    if (!await ownsSession(token)) return;
    const critical = (data.critical || []).map((item) => ({ ...item, key: `${item.id}:${item.fingerprint}` }));
    const next = { userId: data.user_id, afterId: data.next_after_id, seenCritical: critical.map((item) => item.key) };
    const firstRun = state.userId !== data.user_id || !Number.isInteger(state.afterId);
    // En horas de silencio no se avanza: lo pendiente sale al terminar.
    if (!firstRun && prefs.enabled && inQuietHours(prefs)) return;
    // Se guarda antes de avisar: mejor perder un aviso que repetirlo.
    await chrome.storage.local.set({ [STORAGE_KEYS.desktopNotices]: next });
    if (firstRun || !prefs.enabled || !await ownsSession(token)) return;
    const seen = new Set(state.seenCritical || []);
    _showNotices(critical.filter((item) => !seen.has(item.key)), { kind: "critical", singular: "alerta crítica", plural: "alertas críticas" });
    _showNotices((data.activity || []).map((item) => ({ ...item, key: item.id })), { kind: "activity", singular: "novedad", plural: "novedades" });
  } catch {
    // Sin red o sin sesión: se reintenta en la siguiente pasada.
  }
}

chrome.notifications.onClicked?.addListener((notificationId) => {
  if (!notificationId.startsWith("agency-notice:")) return;
  const link = notificationId.slice(notificationId.indexOf("|") + 1);
  // Sólo rutas de la propia app.
  if (link.startsWith("/") && !link.startsWith("//")) chrome.tabs.create({ url: `${API_URL}${link}` });
  chrome.notifications.clear(notificationId);
});

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
