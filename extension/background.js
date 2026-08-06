const DEFAULT_API_BASE_URL = "http://localhost:8080/api";
const DEDUPE_STORAGE_KEY = "sentCaptureKeys";
const inFlightCaptures = new Set();

chrome.runtime.onInstalled.addListener(async () => {
  const { apiBaseUrl } = await chrome.storage.local.get("apiBaseUrl");
  if (!apiBaseUrl) {
    await chrome.storage.local.set({ apiBaseUrl: DEFAULT_API_BASE_URL });
  }
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type === "INJECT_MAIN_HELPER" && sender.tab?.id != null) {
    injectMainWorldHelper(sender.tab.id)
      .then(() => sendResponse({ ok: true }))
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }

  if (message?.type === "CAPTURE_SOLUTION") {
    postCapture(message.payload)
      .then(sendResponse)
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }

  return false;
});

async function injectMainWorldHelper(tabId) {
  await chrome.scripting.executeScript({
    target: { tabId },
    world: "MAIN",
    func: installSourceBridge
  });
}

function installSourceBridge() {
  if (window.__dsaSolutionCaptureBridgeInstalled) return;
  window.__dsaSolutionCaptureBridgeInstalled = true;

  window.addEventListener("message", (event) => {
    if (event.source !== window || event.data?.type !== "DSA_CAPTURE_REQUEST_SOURCE") return;

    const candidates = [];
    const add = (source, value) => {
      if (typeof value === "string" && value.trim()) candidates.push({ source, value });
    };

    try {
      const models = window.monaco?.editor?.getModels?.() || [];
      for (const model of models) add("monaco", model.getValue?.());
    } catch (_) {}

    try {
      for (const element of document.querySelectorAll(".CodeMirror")) {
        add("codemirror", element.CodeMirror?.getValue?.());
      }
    } catch (_) {}

    try {
      if (window.ace?.edit) {
        for (const element of document.querySelectorAll(".ace_editor")) {
          add("ace", window.ace.edit(element).getValue());
        }
      }
    } catch (_) {}

    window.postMessage({
      type: "DSA_CAPTURE_SOURCE_RESPONSE",
      requestId: event.data.requestId,
      candidates
    }, "*");
  });
}

async function postCapture(payload) {
  if (!payload || typeof payload !== "object") {
    throw new Error("Invalid capture payload.");
  }

  const { apiBaseUrl = DEFAULT_API_BASE_URL, extensionToken = "" } =
    await chrome.storage.local.get(["apiBaseUrl", "extensionToken"]);
  const token = extensionToken.trim();
  if (!token) throw new Error("Configure an extension token in the popup.");

  const baseUrl = normalizeApiBaseUrl(apiBaseUrl);
  const captureKey = [payload.platform, payload.problemId, payload.sourceHash].join(":");
  if (!payload.sourceHash || inFlightCaptures.has(captureKey)) {
    return { ok: true, duplicate: true };
  }

  const stored = await chrome.storage.local.get(DEDUPE_STORAGE_KEY);
  const sentKeys = Array.isArray(stored[DEDUPE_STORAGE_KEY]) ? stored[DEDUPE_STORAGE_KEY] : [];
  if (sentKeys.includes(captureKey)) return { ok: true, duplicate: true };

  inFlightCaptures.add(captureKey);
  try {
    const response = await fetch(`${baseUrl}/github/captures`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-DSA-Extension-Token": token
      },
      credentials: "omit",
      referrerPolicy: "no-referrer",
      body: JSON.stringify(payload)
    });

    if (!response.ok) {
      throw new Error(`Capture API returned HTTP ${response.status}.`);
    }

    const updatedKeys = [...sentKeys.filter((key) => key !== captureKey), captureKey].slice(-500);
    await chrome.storage.local.set({ [DEDUPE_STORAGE_KEY]: updatedKeys });
    return { ok: true, status: response.status };
  } finally {
    inFlightCaptures.delete(captureKey);
  }
}

function normalizeApiBaseUrl(value) {
  const url = new URL(String(value || DEFAULT_API_BASE_URL).trim());
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new Error("The configured API URL must use HTTP or HTTPS.");
  }
  return url.toString().replace(/\/$/, "");
}
