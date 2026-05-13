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
  // Preserve baseline classes (e.g. kpi-value) — only swap the level token.
  el.classList.remove("ok", "warn", "bad");
  el.classList.add(level);
}

// Cached run count so SSE deltas (agent_run_complete) can bump the Memory KPI
// optimistically without waiting for the next full snapshot.
let memoryRunCount = 0;

function setMemoryRunCount(value) {
  memoryRunCount = value;
  setStatus(statusEls.memory, `${memoryRunCount} runs`, "ok");
}

// =====================================================================
// Step 6 — KPI staleness pills
// One small "Xs ago" pill per KPI card, updated every second, that turns
// red once the data is >60s old. Surfaces SSE stream liveness without
// needing a dedicated indicator. Injected from JS so index.html stays
// structurally untouched.
// =====================================================================

// Set by applyReady() on every successful SSE ready_snapshot or REST fallback.
let lastSnapshotAt = null;

// Probe window.dashboardEventSource (set when openEventStream runs) so the
// pill can know whether the stream is open or reconnecting.
function currentEventSource() {
  return typeof window !== "undefined" ? window.dashboardEventSource || null : null;
}

const stalenessPillEls = {};
function ensureStalenessPill(kpiValueEl, key) {
  if (!kpiValueEl) return null;
  if (stalenessPillEls[key]) return stalenessPillEls[key];
  const pill = document.createElement("span");
  pill.className = "kpi-staleness";
  pill.setAttribute("aria-live", "off");
  pill.textContent = "—";
  // Insert AFTER the value so setStatus()'s textContent writes don't clobber it.
  kpiValueEl.insertAdjacentElement("afterend", pill);
  stalenessPillEls[key] = pill;
  return pill;
}

function stalenessLabel(seconds) {
  if (seconds == null) return "—";
  if (seconds < 5) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  return "60s+ ago";
}

function stalenessLevel(seconds) {
  if (seconds == null) return "muted";
  if (seconds < 10) return "muted";
  if (seconds < 60) return "neutral";
  return "bad";
}

function updateStalenessPills() {
  ensureStalenessPill(statusEls.model, "model");
  ensureStalenessPill(statusEls.wabot, "wabot");
  ensureStalenessPill(statusEls.policy, "policy");
  ensureStalenessPill(statusEls.memory, "memory");

  const seconds =
    lastSnapshotAt == null ? null : Math.max(0, Math.floor((Date.now() - lastSnapshotAt) / 1000));
  const level = stalenessLevel(seconds);
  const label = stalenessLabel(seconds);

  const source = currentEventSource();
  const sseDown =
    source !== null && typeof EventSource !== "undefined" && source.readyState !== EventSource.OPEN;

  for (const key of Object.keys(stalenessPillEls)) {
    const pill = stalenessPillEls[key];
    if (!pill) continue;
    pill.textContent = label;
    pill.classList.remove("muted", "neutral", "bad");
    pill.classList.add(level);
    pill.dataset.reconnecting = sseDown && level === "bad" ? "true" : "false";
  }
}

function applyReady(data) {
  setStatus(statusEls.model, data.live_model ? data.model : "Offline", data.live_model ? "ok" : "warn");
  const wabotReady = data.wabot && data.wabot.ready;
  setStatus(statusEls.wabot, wabotReady ? "Ready" : "Not ready", wabotReady ? "ok" : "warn");
  // Policy level mapping is safety-critical: allow_all removes the recipient
  // guard, so it MUST render as destructive (red), not "ok" (green).
  const policyLevel = { dry_run: "warn", allowlist: "ok", allow_all: "bad" };
  const policyLabel = { dry_run: "Dry run", allowlist: "Allowlist", allow_all: "Allow all" };
  setStatus(
    statusEls.policy,
    policyLabel[data.send_policy] ?? data.send_policy,
    policyLevel[data.send_policy] ?? "warn",
  );
  setMemoryRunCount(data.memory.runs);
  // Step 6: any successful snapshot resets the staleness clock.
  lastSnapshotAt = Date.now();
  updateStalenessPills();
}

// Fallback path — only used when the SSE stream is closed (network blip,
// proxy timeout). On a healthy stream `ready_snapshot` repaints these tiles.
async function loadReady() {
  try {
    const res = await fetch("/ready");
    applyReady(await res.json());
  } catch {
    setStatus(statusEls.model, "Error", "bad");
    setStatus(statusEls.wabot, "Error", "bad");
  }
}

function paintPairing(data) {
  if (!data) return;
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
    // Cache-bust on the updated_at so a rotated QR forces a new image load.
    pairingQR.src = `/api/whatsapp/pairing.svg?t=${encodeURIComponent(data.updated_at || Date.now())}`;
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
}

// Fallback path — used by the refresh button. The SSE stream's pairing_changed
// event handles live updates; this only fires on manual operator action.
async function loadPairing() {
  try {
    const res = await fetch("/api/whatsapp/pairing");
    paintPairing(await res.json());
  } catch (error) {
    pairingDetail.textContent = `Pairing check failed: ${error.message}`;
    pairingQR.hidden = true;
    pairingEmpty.hidden = false;
    pairingEmpty.textContent = "Unavailable";
  }
}

const MAX_RUNS_IN_LIST = 8;

// =====================================================================
// Step 5 — Run cards
// Title: relative time + masked sender (or "Operator") + live/offline chip
// Body: final output, truncated by CSS line-clamp.
// =====================================================================

// Mask a phone number to "+1555…1234" style. Falls back to the original
// string if it's too short to mask meaningfully.
function maskSender(sender) {
  if (!sender) return null;
  const raw = String(sender).trim();
  if (!raw) return null;
  const digits = raw.replace(/[^\d]/g, "");
  if (digits.length < 6) return raw;
  const hasPlus = raw.startsWith("+");
  const head = digits.slice(0, Math.min(4, digits.length - 4));
  const tail = digits.slice(-4);
  return `${hasPlus ? "+" : ""}${head}…${tail}`;
}

// Buckets: <5s "just now"; <60s "Xs ago"; <60m "Xm ago"; <24h "Xh ago"; else "Xd ago".
function formatRelativeTime(ms) {
  if (ms == null || Number.isNaN(ms)) return "";
  const delta = Math.max(0, Date.now() - ms);
  const seconds = Math.floor(delta / 1000);
  if (seconds < 5) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function resolveRunTimestamp(run) {
  const candidates = [run.created_at, run.timestamp, run.started_at, run.completed_at];
  for (const value of candidates) {
    if (value == null) continue;
    if (typeof value === "number") return value > 1e12 ? value : value * 1000;
    const parsed = Date.parse(value);
    if (!Number.isNaN(parsed)) return parsed;
  }
  return Date.now();
}

function renderRunItem(run) {
  const item = document.createElement("article");
  item.className = "run-item";

  const ts = resolveRunTimestamp(run);
  item.dataset.ts = String(ts);

  const header = document.createElement("div");
  header.className = "run-item-header";

  const titleText = document.createElement("strong");
  titleText.className = "run-item-title";
  const masked = maskSender(run.sender);
  const who = masked || "Operator";
  const when = formatRelativeTime(ts);
  // Re-rendered every 30s by refreshRelativeTimes(); store who half statically.
  titleText.dataset.who = who;
  titleText.textContent = `${when} · ${who}`;
  header.append(titleText);

  // Live/offline pill — agent_run_complete carries live_model; legacy /api/runs
  // rows may not, default to "offline" rather than misleadingly showing "live".
  const chip = document.createElement("span");
  const live = run.live_model === true;
  chip.className = `run-chip ${live ? "run-chip-live" : "run-chip-offline"}`;
  chip.textContent = live ? "live" : "offline";
  header.append(chip);

  item.append(header);

  const body = document.createElement("p");
  body.textContent = run.final_output || run.user_input || "No output";
  item.append(body);

  return item;
}

function refreshRelativeTimes() {
  const titles = runsList.querySelectorAll(".run-item-title");
  for (const title of titles) {
    const card = title.closest(".run-item");
    if (!card) continue;
    const ts = Number(card.dataset.ts);
    if (!ts) continue;
    const who = title.dataset.who || "Operator";
    title.textContent = `${formatRelativeTime(ts)} · ${who}`;
  }
}

function paintRuns(runs) {
  runCount.textContent = `${runs.length}`;
  runsList.replaceChildren(...runs.map(renderRunItem));
}

function prependRun(run) {
  runsList.prepend(renderRunItem(run));
  // Trim to keep the list bounded; SSE deltas are append-only.
  while (runsList.children.length > MAX_RUNS_IN_LIST) {
    runsList.lastElementChild?.remove();
  }
  runCount.textContent = `${runsList.children.length}`;
}

async function loadRuns() {
  const res = await fetch(`/api/runs?limit=${MAX_RUNS_IN_LIST}`);
  paintRuns(await res.json());
}

function addMessage(role, text) {
  const item = document.createElement("div");
  item.className = `message ${role}`;
  item.textContent = text;
  messages.append(item);
  messages.scrollTop = messages.scrollHeight;
}

// Render a tool-call chip below the in-progress agent message. Chips show the
// tool name (and a redacted arg preview if present); the server has already
// passed args through redact(), so we just display whatever it sent.
function renderToolCallChip(after, event) {
  const chip = document.createElement("div");
  chip.className = "tool-chip";
  chip.dataset.callId = event.call_id || "";
  const label = document.createElement("span");
  label.className = "tool-chip-name";
  label.textContent = `${event.name}()`;
  chip.append(label);
  if (event.args_redacted && Object.keys(event.args_redacted).length > 0) {
    const args = document.createElement("span");
    args.className = "tool-chip-args";
    let preview;
    try {
      preview = JSON.stringify(event.args_redacted);
    } catch (_err) {
      preview = String(event.args_redacted);
    }
    if (preview.length > 120) preview = preview.slice(0, 117) + "…";
    args.textContent = preview;
    chip.append(args);
  }
  after.insertAdjacentElement("afterend", chip);
  messages.scrollTop = messages.scrollHeight;
  return chip;
}

function markToolChipDone(callId, ok) {
  if (!callId) return;
  const chip = messages.querySelector(`.tool-chip[data-call-id="${callId}"]`);
  if (chip) chip.classList.add(ok === false ? "tool-chip-error" : "tool-chip-done");
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = textarea.value.trim();
  if (!message) return;
  textarea.value = "";
  addMessage("operator", message);
  addMessage("agent", "Thinking...");
  const pending = messages.lastElementChild;
  let firstDeltaSeen = false;

  try {
    const res = await fetch("/api/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/x-ndjson" },
      body: JSON.stringify({ message, session_id: "operator-dashboard" }),
    });
    if (!res.ok || !res.body) {
      throw new Error(`HTTP ${res.status}`);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    // Read NDJSON one line at a time. Server emits {"type": ...}\n records.
    // The bubble's textContent accumulates streamed model output; tool-call
    // chips are siblings inserted directly after the bubble.
    // The SSE stream will push agent_run_complete for the runs panel, so no
    // explicit loadRuns/loadReady needed after the stream closes.
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let newlineIdx;
      while ((newlineIdx = buffer.indexOf("\n")) !== -1) {
        const line = buffer.slice(0, newlineIdx).trim();
        buffer = buffer.slice(newlineIdx + 1);
        if (!line) continue;
        let evt;
        try {
          evt = JSON.parse(line);
        } catch (_err) {
          continue;
        }
        if (evt.type === "delta") {
          if (!firstDeltaSeen) {
            pending.textContent = "";
            firstDeltaSeen = true;
          }
          pending.textContent += evt.text || "";
          messages.scrollTop = messages.scrollHeight;
        } else if (evt.type === "tool_call") {
          renderToolCallChip(pending, evt);
        } else if (evt.type === "tool_result") {
          markToolChipDone(evt.call_id, evt.ok !== false);
        } else if (evt.type === "final") {
          if (!firstDeltaSeen) pending.textContent = evt.output || "No output";
        } else if (evt.type === "error") {
          pending.textContent = `Request failed: ${evt.message || "unknown error"}`;
        }
      }
    }
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

let lastSettingsEtag = null;

async function loadSettings() {
  try {
    const headers = lastSettingsEtag ? { "If-None-Match": lastSettingsEtag } : {};
    const res = await fetch("/api/settings", { headers });
    // 304 means the view we already have is current — no work to do.
    if (res.status === 304) return;
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    lastSettingsEtag = res.headers.get("ETag");
    applySettingsView(await res.json());
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
// Sidebar nav + mobile tabs — active state, smooth scroll, drawer toggle
// =====================================================================

// Both desktop sidebar links and the mobile bottom tab bar share the same
// click-routing logic: links with data-drawer-toggle open the drawer;
// everything else smooth-scrolls to its anchor target.
const navLinks = document.querySelectorAll(".nav a[href^='#'], .mobile-tabs a[href^='#']");

function setActiveNav(hash) {
  for (const link of navLinks) {
    link.classList.toggle("active", link.getAttribute("href") === hash);
  }
}

// =====================================================================
// Step 7 — Settings drawer
// =====================================================================

const drawerEl = document.querySelector("#settings-drawer");
const drawerBackdropEl = document.querySelector("#drawer-backdrop");
const drawerCloseBtn = document.querySelector("#settings-close");

function openDrawer() {
  if (!drawerEl) return;
  drawerEl.hidden = false;
  if (drawerBackdropEl) drawerBackdropEl.hidden = false;
  // Defer the body-class flip a frame so the browser registers the initial
  // transform/opacity state and the transition actually plays.
  requestAnimationFrame(() => {
    document.body.classList.add("drawer-open");
    drawerEl.setAttribute("aria-hidden", "false");
    if (drawerBackdropEl) drawerBackdropEl.setAttribute("aria-hidden", "false");
  });
  setActiveNav("#settings");
}

function closeDrawer() {
  if (!drawerEl) return;
  document.body.classList.remove("drawer-open");
  drawerEl.setAttribute("aria-hidden", "true");
  if (drawerBackdropEl) drawerBackdropEl.setAttribute("aria-hidden", "true");
  // Hide after transition so it can't trap tab focus while sliding out.
  setTimeout(() => {
    if (!document.body.classList.contains("drawer-open")) {
      drawerEl.hidden = true;
      if (drawerBackdropEl) drawerBackdropEl.hidden = true;
    }
  }, 240);
}

drawerCloseBtn?.addEventListener("click", closeDrawer);
drawerBackdropEl?.addEventListener("click", closeDrawer);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && document.body.classList.contains("drawer-open")) {
    closeDrawer();
  }
});

for (const link of navLinks) {
  link.addEventListener("click", (event) => {
    const href = link.getAttribute("href");
    // Drawer-toggle links: open the drawer instead of scrolling.
    if (link.dataset.drawerToggle) {
      event.preventDefault();
      openDrawer();
      history.replaceState(null, "", href);
      return;
    }
    const target = document.querySelector(href);
    if (!target) return;
    event.preventDefault();
    setActiveNav(href);
    target.scrollIntoView({ behavior: "smooth", block: "start" });
    history.replaceState(null, "", href);
  });
}

// Sync the active item to whichever section is currently most visible.
// #settings is intentionally excluded — it lives in the drawer now, not in
// the main scroll flow, and its "active" state is owned by openDrawer.
if ("IntersectionObserver" in window) {
  const sections = ["#status", "#chat", "#whatsapp", "#runs"]
    .map((id) => document.querySelector(id))
    .filter(Boolean);
  const observer = new IntersectionObserver(
    (entries) => {
      // Skip syncing while the drawer is open — keeps Settings highlighted.
      if (document.body.classList.contains("drawer-open")) return;
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
// Server-sent events — live readiness + runs + settings deltas
// =====================================================================

let eventSource = null;

function handleSseEvent(name, data) {
  // Any event from the hub proves the stream is alive — feed the staleness
  // clock here so the pill measures liveness, not full-snapshot age.
  lastSnapshotAt = Date.now();
  switch (name) {
    case "ready_snapshot":
      applyReady(data);
      paintRuns(data.runs || []);
      if (data.pairing) paintPairing(data.pairing);
      break;
    case "pairing_changed":
      paintPairing(data);
      break;
    case "agent_run_complete":
      // The event carries enough to render the run inline. Bump the runs KPI
      // optimistically too — the next ready_snapshot will reconcile.
      prependRun({
        run_id: data.run_id,
        sender: data.sender,
        user_input: data.user_input,
        final_output: data.final_output,
      });
      setMemoryRunCount(memoryRunCount + 1);
      break;
    case "inbound_message":
      // Visible hint that something just arrived from WhatsApp. The follow-up
      // agent_run_complete will append the actual run card.
      runCount.classList.add("pulse");
      setTimeout(() => runCount.classList.remove("pulse"), 1500);
      break;
    case "settings_updated":
      loadSettings();
      break;
  }
}

function openEventStream() {
  if (eventSource) eventSource.close();
  eventSource = new EventSource("/api/stream");
  // Exported so the Step 6 staleness pills can probe readyState without
  // needing a module import (this script loads as type="module").
  window.dashboardEventSource = eventSource;
  // Named events dispatched server-side via `event:` lines.
  for (const name of ["ready_snapshot", "agent_run_start", "agent_run_complete", "inbound_message", "settings_updated", "pairing_changed", "heartbeat"]) {
    eventSource.addEventListener(name, (ev) => {
      try {
        handleSseEvent(name, JSON.parse(ev.data));
      } catch (err) {
        console.error("SSE parse failed", name, err);
      }
    });
  }
  eventSource.onerror = () => {
    // EventSource auto-reconnects with Last-Event-ID. While disconnected,
    // run a one-shot fallback so the operator sees fresh readiness even if
    // the stream stays broken (e.g. proxy is down).
    if (eventSource.readyState === EventSource.CLOSED) loadReady();
  };
}

// Pause the stream when the tab is hidden — saves OpenRouter health-probe
// budget and avoids piling up backlog on the server's ring buffer.
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") {
    if (!eventSource || eventSource.readyState === EventSource.CLOSED) openEventStream();
  } else if (eventSource) {
    eventSource.close();
    eventSource = null;
  }
});

// =====================================================================
// Boot
// =====================================================================

addMessage("agent", "Ready. Send policy is fail-closed unless the VPS is configured otherwise.");
openEventStream();
loadSettings();
// Pairing arrives via the SSE `pairing_changed` event (and the initial
// ready_snapshot.pairing field) — no client timer needed. The refresh
// button still calls loadPairing() as a manual escape hatch.

// Step 5: keep run-card relative timestamps fresh.
setInterval(refreshRelativeTimes, 30000);

// Step 6: tick the staleness pills every second. Render once immediately so
// the pills exist (with placeholder text) before the first ready_snapshot.
updateStalenessPills();
setInterval(updateStalenessPills, 1000);
