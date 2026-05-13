const statusEls = {
  model: document.querySelector("#model-state"),
  wabot: document.querySelector("#wabot-state"),
  policy: document.querySelector("#policy-state"),
  memory: document.querySelector("#memory-state"),
};

const messages = document.querySelector("#messages");
const runsList = document.querySelector("#runs-list");
const runCount = document.querySelector("#run-count");
const form = document.querySelector("#chat-form");
const textarea = document.querySelector("#message");
const refresh = document.querySelector("#refresh");
const refreshQR = document.querySelector("#refresh-qr");
const pairingDetail = document.querySelector("#pairing-detail");
const pairingQR = document.querySelector("#pairing-qr");
const pairingEmpty = document.querySelector("#pairing-empty");

function setStatus(el, text, level = "warn") {
  el.textContent = text;
  el.className = level;
}

async function loadReady() {
  try {
    const res = await fetch("/ready");
    const data = await res.json();
    setStatus(statusEls.model, data.live_model ? data.model : "Offline", data.live_model ? "ok" : "warn");
    const wabotReady = data.wabot && data.wabot.ready;
    setStatus(statusEls.wabot, wabotReady ? "Ready" : "Not ready", wabotReady ? "ok" : "warn");
    setStatus(
      statusEls.policy,
      data.send_policy,
      data.send_policy === "dry_run" ? "warn" : "ok",
    );
    setStatus(statusEls.memory, `${data.memory.runs} runs`, "ok");
  } catch (error) {
    setStatus(statusEls.model, "Error", "bad");
    setStatus(statusEls.wabot, "Error", "bad");
  }
}

async function loadPairing() {
  try {
    const res = await fetch("/api/whatsapp/pairing");
    const data = await res.json();
    if (!data.supported) {
      pairingDetail.textContent = data.detail || "Upgrade wabot to enable browser pairing.";
      pairingQR.hidden = true;
      pairingEmpty.hidden = false;
      pairingEmpty.textContent = "Upgrade wabot";
      return;
    }
    if (data.logged_in && data.connected) {
      pairingDetail.textContent = "WhatsApp is linked and connected.";
      pairingQR.hidden = true;
      pairingEmpty.hidden = false;
      pairingEmpty.textContent = "Connected";
      return;
    }
    if (data.qr_available) {
      pairingDetail.textContent = "Open WhatsApp on your phone and scan this linked-device QR.";
      pairingQR.src = `/api/whatsapp/pairing.svg?t=${Date.now()}`;
      pairingQR.hidden = false;
      pairingEmpty.hidden = true;
      return;
    }
    pairingDetail.textContent = data.detail || "Waiting for a fresh pairing QR.";
    pairingQR.hidden = true;
    pairingEmpty.hidden = false;
    pairingEmpty.textContent = data.detail && data.detail.includes("WABOT_TOKEN")
      ? "Needs token"
      : data.reachable ? "Waiting for QR" : "wabot offline";
  } catch (error) {
    pairingDetail.textContent = `Pairing check failed: ${error.message}`;
    pairingQR.hidden = true;
    pairingEmpty.hidden = false;
    pairingEmpty.textContent = "Unavailable";
  }
}

async function loadRuns() {
  const res = await fetch("/api/runs?limit=8");
  const runs = await res.json();
  runCount.textContent = `${runs.length}`;
  runsList.innerHTML = "";
  for (const run of runs) {
    const item = document.createElement("article");
    item.className = "run-item";
    const title = document.createElement("strong");
    title.textContent = run.run_id.slice(0, 8);
    const body = document.createElement("p");
    body.textContent = run.final_output || run.user_input || "No output";
    item.append(title, body);
    runsList.append(item);
  }
}

function addMessage(role, text) {
  const item = document.createElement("div");
  item.className = `message ${role}`;
  item.textContent = text;
  messages.append(item);
  messages.scrollTop = messages.scrollHeight;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = textarea.value.trim();
  if (!message) return;
  textarea.value = "";
  addMessage("operator", message);
  addMessage("agent", "Thinking...");
  const pending = messages.lastElementChild;
  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, session_id: "operator-dashboard" }),
    });
    const data = await res.json();
    pending.textContent = data.output || "No output";
    await loadRuns();
    await loadReady();
  } catch (error) {
    pending.textContent = `Request failed: ${error.message}`;
  }
});

textarea.addEventListener("keydown", (event) => {
  if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
    event.preventDefault();
    form.requestSubmit();
  }
});

refresh.addEventListener("click", () => {
  loadReady();
  loadPairing();
  loadRuns();
});

refreshQR.addEventListener("click", () => {
  loadPairing();
  loadReady();
});

// =====================================================================
// Settings panel
// =====================================================================

const settingsForm = document.querySelector("#settings-form");
const settingsStatus = document.querySelector("#settings-status");
const settingsSave = document.querySelector("#settings-save");
const settingsReset = document.querySelector("#settings-reset");
const settingsSource = document.querySelector("#settings-source");
const openrouterKeyInput = document.querySelector("#setting-openrouter-key");
const openrouterKeyState = document.querySelector("#setting-openrouter-key-state");
const openrouterModelInput = document.querySelector("#setting-openrouter-model");
const openrouterBaseInput = document.querySelector("#setting-openrouter-base");
const wabotEndpointInput = document.querySelector("#setting-wabot-endpoint");
const wabotTokenInput = document.querySelector("#setting-wabot-token");
const wabotTokenState = document.querySelector("#setting-wabot-token-state");
const recipientsInput = document.querySelector("#setting-recipients");
const openrouterTestBtn = document.querySelector("#setting-openrouter-test");
const wabotTestBtn = document.querySelector("#setting-wabot-test");

let lastSettingsView = null;

function setSettingsStatus(text, level = "") {
  settingsStatus.textContent = text;
  settingsStatus.className = `settings-status ${level}`.trim();
}

function setFieldHint(el, text, level = "") {
  el.textContent = text;
  el.className = `field-hint ${level}`.trim();
}

function describeSecret(field) {
  if (!field || !field.set) return { text: "Not configured", level: "warn" };
  return { text: `Configured · ${field.preview}`, level: "ok" };
}

function applySettingsView(view) {
  lastSettingsView = view;
  if (settingsSource && view.env_source) settingsSource.textContent = view.env_source;

  // Inputs reflect current effective config. Secret inputs are intentionally empty —
  // an empty input means "leave unchanged"; an explicit empty submit (after focusing
  // and clearing) clears the secret.
  openrouterKeyInput.value = "";
  openrouterModelInput.value = view.openrouter.model || "";
  openrouterBaseInput.value = view.openrouter.base_url || "";
  wabotEndpointInput.value = view.wabot.endpoint || "";
  wabotTokenInput.value = "";
  recipientsInput.value = (view.allowed_recipients || []).join(", ");

  const keyState = describeSecret(view.openrouter.api_key);
  setFieldHint(openrouterKeyState, keyState.text, keyState.level);
  const tokenState = describeSecret(view.wabot.token);
  setFieldHint(wabotTokenState, tokenState.text, tokenState.level);

  for (const radio of settingsForm.querySelectorAll('input[name="send_policy"]')) {
    radio.checked = radio.value === view.send_policy;
  }
}

async function loadSettings() {
  try {
    const res = await fetch("/api/settings");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const view = await res.json();
    applySettingsView(view);
  } catch (error) {
    setSettingsStatus(`Failed to load settings: ${error.message}`, "bad");
  }
}

function parseRecipients(value) {
  return value
    .split(/[,\n]/)
    .map((part) => part.trim())
    .filter(Boolean);
}

function buildPatch() {
  const patch = {};

  // Only send fields that the operator actually edited. Empty secret inputs
  // mean "no change". To clear a secret, type a single space — see help text.
  const key = openrouterKeyInput.value;
  if (key !== "") patch.openrouter_api_key = key.trim();

  const model = openrouterModelInput.value.trim();
  if (model && (!lastSettingsView || model !== lastSettingsView.openrouter.model)) {
    patch.openrouter_model = model;
  }

  const baseUrl = openrouterBaseInput.value.trim();
  if (baseUrl && (!lastSettingsView || baseUrl !== lastSettingsView.openrouter.base_url)) {
    patch.openrouter_base_url = baseUrl;
  }

  const wabotEndpoint = wabotEndpointInput.value.trim();
  if (wabotEndpoint && (!lastSettingsView || wabotEndpoint !== lastSettingsView.wabot.endpoint)) {
    patch.wabot_endpoint = wabotEndpoint;
  }

  const wabotToken = wabotTokenInput.value;
  if (wabotToken !== "") patch.wabot_token = wabotToken.trim();

  const checkedPolicy = settingsForm.querySelector('input[name="send_policy"]:checked');
  if (checkedPolicy && (!lastSettingsView || checkedPolicy.value !== lastSettingsView.send_policy)) {
    patch.send_policy = checkedPolicy.value;
  }

  const recipients = parseRecipients(recipientsInput.value);
  const existing = (lastSettingsView && lastSettingsView.allowed_recipients) || [];
  if (recipients.join(",") !== existing.join(",")) {
    patch.allowed_recipients = recipients;
  }

  return patch;
}

settingsForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const patch = buildPatch();
  if (Object.keys(patch).length === 0) {
    setSettingsStatus("Nothing to save.", "warn");
    return;
  }
  if (patch.send_policy === "allow_all") {
    const ok = window.confirm(
      "Send policy 'allow_all' removes the recipient guard. Continue?",
    );
    if (!ok) return;
    patch.confirm_allow_all = true;
  }
  settingsSave.disabled = true;
  setSettingsStatus("Saving…", "");
  try {
    const res = await fetch("/api/settings", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    const data = await res.json();
    if (!res.ok) {
      const detail = data.detail || `HTTP ${res.status}`;
      setSettingsStatus(`Save failed: ${detail}`, "bad");
      return;
    }
    applySettingsView(data);
    setSettingsStatus("Saved.", "ok");
    await loadReady();
  } catch (error) {
    setSettingsStatus(`Save failed: ${error.message}`, "bad");
  } finally {
    settingsSave.disabled = false;
  }
});

settingsReset.addEventListener("click", () => {
  if (lastSettingsView) {
    applySettingsView(lastSettingsView);
    setSettingsStatus("Reverted to current config.", "warn");
  } else {
    loadSettings();
  }
});

openrouterTestBtn.addEventListener("click", async () => {
  openrouterTestBtn.disabled = true;
  setFieldHint(openrouterKeyState, "Testing…", "");
  try {
    const res = await fetch("/api/settings/test/openrouter", { method: "POST" });
    const data = await res.json();
    setFieldHint(openrouterKeyState, data.detail || (data.ok ? "OK" : "Failed"), data.ok ? "ok" : "bad");
  } catch (error) {
    setFieldHint(openrouterKeyState, `Test failed: ${error.message}`, "bad");
  } finally {
    openrouterTestBtn.disabled = false;
  }
});

wabotTestBtn.addEventListener("click", async () => {
  wabotTestBtn.disabled = true;
  setFieldHint(wabotTokenState, "Testing…", "");
  try {
    const res = await fetch("/api/settings/test/wabot", { method: "POST" });
    const data = await res.json();
    setFieldHint(wabotTokenState, data.detail || (data.ok ? "OK" : "Failed"), data.ok ? "ok" : "warn");
  } catch (error) {
    setFieldHint(wabotTokenState, `Test failed: ${error.message}`, "bad");
  } finally {
    wabotTestBtn.disabled = false;
  }
});

// =====================================================================
// Sidebar nav — active state + smooth scroll
// =====================================================================

const navLinks = document.querySelectorAll(".nav a[href^='#']");

function setActiveNav(hash) {
  for (const link of navLinks) {
    link.classList.toggle("active", link.getAttribute("href") === hash);
  }
}

for (const link of navLinks) {
  link.addEventListener("click", (event) => {
    const href = link.getAttribute("href");
    const target = document.querySelector(href);
    if (!target) return;
    event.preventDefault();
    setActiveNav(href);
    target.scrollIntoView({ behavior: "smooth", block: "start" });
    history.replaceState(null, "", href);
  });
}

// Sync the active item to whichever section is currently most visible.
if ("IntersectionObserver" in window) {
  const sections = ["#status", "#settings", "#chat", "#whatsapp", "#runs"]
    .map((id) => document.querySelector(id))
    .filter(Boolean);
  const observer = new IntersectionObserver(
    (entries) => {
      const visible = entries
        .filter((entry) => entry.isIntersecting)
        .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
      if (visible) setActiveNav(`#${visible.target.id}`);
    },
    { rootMargin: "-30% 0px -55% 0px", threshold: [0, 0.25, 0.5, 0.75, 1] },
  );
  for (const section of sections) observer.observe(section);
}

// =====================================================================
// Boot
// =====================================================================

addMessage("agent", "Ready. Send policy is fail-closed unless the VPS is configured otherwise.");
loadReady();
loadPairing();
loadRuns();
loadSettings();
setInterval(() => {
  loadReady();
  loadPairing();
}, 10000);
