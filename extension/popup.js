const DEFAULT_API_BASE_URL = "http://localhost:8080/api";

const form = document.querySelector("#settings-form");
const apiBaseUrlInput = document.querySelector("#api-base-url");
const extensionTokenInput = document.querySelector("#extension-token");
const status = document.querySelector("#status");

loadSettings().catch(showError);
form.addEventListener("submit", saveSettings);

async function loadSettings() {
  const settings = await chrome.storage.local.get(["apiBaseUrl", "extensionToken"]);
  apiBaseUrlInput.value = settings.apiBaseUrl || DEFAULT_API_BASE_URL;
  extensionTokenInput.value = settings.extensionToken || "";
}

async function saveSettings(event) {
  event.preventDefault();
  status.textContent = "";
  status.className = "";

  try {
    const apiBaseUrl = normalizeApiBaseUrl(apiBaseUrlInput.value);
    const extensionToken = extensionTokenInput.value.trim();
    if (!extensionToken) throw new Error("Extension token is required.");

    await chrome.storage.local.set({ apiBaseUrl, extensionToken });
    apiBaseUrlInput.value = apiBaseUrl;
    status.textContent = "Settings saved.";
    status.className = "success";
  } catch (error) {
    showError(error);
  }
}

function normalizeApiBaseUrl(value) {
  const url = new URL(value.trim());
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new Error("API URL must use HTTP or HTTPS.");
  }
  return url.toString().replace(/\/$/, "");
}

function showError(error) {
  status.textContent = error.message || "Unable to save settings.";
  status.className = "error";
}
