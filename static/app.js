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

refresh.addEventListener("click", () => {
  loadReady();
  loadRuns();
});

addMessage("agent", "Ready. Send policy is fail-closed unless the VPS is configured otherwise.");
loadReady();
loadRuns();

