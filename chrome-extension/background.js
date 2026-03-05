// Agency Manager - Quick Capture Extension
// Background service worker — context menus + notifications

const API_URL = "https://agency.magnifytools.com";

const STORAGE_KEYS = {
  token: "am_token",
};

// ── Context menu setup ────────────────────────────────────
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "am-capture-selection",
    title: "Capturar al Inbox de Agency Manager",
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
    const res = await fetch(`${apiUrl}/api/inbox`, {
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

    if (res.ok) {
      showNotification("Nota capturada", "IA clasificando en segundo plano...");
      // Update badge
      updateBadge(apiUrl, token);
    } else if (res.status === 401) {
      showNotification(
        "Sesion expirada",
        "Abre la extension para reconectar."
      );
      await chrome.storage.local.remove(STORAGE_KEYS.token);
    } else {
      showNotification("Error", "No se pudo enviar la nota.");
    }
  } catch (err) {
    showNotification("Error de conexion", "No se pudo conectar al servidor.");
  }
});

// ── Auth update from popup ────────────────────────────────
chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === "AUTH_UPDATE") {
    updateBadge(msg.token);
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

chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name === "refresh-badge") {
    const stored = await chrome.storage.local.get([STORAGE_KEYS.token]);
    if (stored[STORAGE_KEYS.token]) {
      updateBadge(stored[STORAGE_KEYS.token]);
    }
  }
});

// ── Startup badge ─────────────────────────────────────────
chrome.runtime.onStartup.addListener(async () => {
  const stored = await chrome.storage.local.get([STORAGE_KEYS.token]);
  if (stored[STORAGE_KEYS.token]) {
    updateBadge(stored[STORAGE_KEYS.token]);
  }
});

// ── Notifications helper ──────────────────────────────────
function showNotification(title, message) {
  // Use a self-closing notification approach via the popup badge
  // Since chrome.notifications requires the "notifications" permission,
  // we keep it lightweight with badge + console
  console.log(`[Agency Manager] ${title}: ${message}`);

  // Flash badge briefly
  chrome.action.setBadgeText({ text: "!" });
  chrome.action.setBadgeBackgroundColor({ color: "#22c55e" });
  setTimeout(() => {
    chrome.action.setBadgeText({ text: "" });
  }, 3000);
}
