const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const ui = {
  loginLayer: $("#loginLayer"), loginForm: $("#loginForm"), tokenInput: $("#tokenInput"), loginError: $("#loginError"),
  appShell: $("#appShell"), runtimePill: $("#runtimePill"), userStage: $("#userStage"), assistantStage: $("#assistantStage"),
  phaseTitle: $("#phaseTitle"), phaseHint: $("#phaseHint"), orbWrap: $("#orbWrap"), phaseTrack: $("#phaseTrack"),
  startBtn: $("#startBtn"), stopBtn: $("#stopBtn"), clearBtn: $("#clearBtn"), controlMessage: $("#controlMessage"),
  conversation: $("#conversation"), emptyConversation: $("#emptyConversation"), turnCount: $("#turnCount"),
  resourceList: $("#resourceList"), safetyCard: $("#safetyCard"), audioDevice: $("#audioDevice"), logs: $("#logs"), clearLogsBtn: $("#clearLogsBtn")
};

const state = { runtime: "offline", phase: "stopped", socket: null, csrfToken: "", messages: new Map(), turns: new Set(), reconnectTimer: null };
const phaseCopy = {
  starting: ["正在唤醒系统", "模型与音频设备正在初始化"],
  waiting_wake_word: ["在等你叫我", "说“小西小西”开始对话"],
  waiting_speech: ["我在听", "请说出你的问题或指令"],
  followup_listening: ["继续说吧", "当前会话无需再次说唤醒词"],
  recording: ["正在聆听", "保持自然语速，说完后稍等片刻"],
  asr: ["正在识别", "小西正在把声音转换成文字"],
  processing: ["正在理解", "正在查询知识并规划回复"],
  speaking: ["小西正在回答", "你可以在播报结束后继续说话"],
  stopped: ["等待启动", "启动后，说“小西小西”开始对话"]
};

function timeLabel(timestamp) {
  try { return new Date(timestamp).toLocaleTimeString("zh-CN", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" }); }
  catch { return ""; }
}

function setRuntime(status, error = "") {
  if (!["offline", "starting", "running", "stopping", "error"].includes(status)) status = "error";
  state.runtime = status;
  const labels = { offline: "后端离线", starting: "正在启动", running: "运行中", stopping: "正在停止", error: "运行异常" };
  ui.runtimePill.className = `runtime-pill is-${status}`;
  ui.runtimePill.querySelector("span").textContent = labels[status] || status;
  const busy = status === "starting" || status === "stopping";
  ui.startBtn.disabled = busy || status === "running";
  ui.stopBtn.disabled = busy || status === "offline" || status === "error";
  if (error) ui.controlMessage.textContent = error;
}

function setPhase(phase) {
  if (!Object.hasOwn(phaseCopy, phase)) phase = "stopped";
  state.phase = phase;
  const copy = phaseCopy[phase] || phaseCopy.stopped;
  ui.phaseTitle.textContent = copy[0];
  ui.phaseHint.textContent = copy[1];
  ui.orbWrap.className = `orb-wrap is-${phase}`;
  ui.userStage.textContent = phase === "recording" || phase === "waiting_speech" || phase === "followup_listening" ? "用户 · 正在说话" : "用户 · 等待唤醒";
  ui.assistantStage.textContent = phase === "speaking" ? "小西 · 正在回答" : phase === "processing" || phase === "asr" ? "小西 · 正在思考" : "小西 · 空闲";
  const group = phase === "waiting_wake_word" ? "waiting" : phase === "waiting_speech" || phase === "followup_listening" ? "recording" : phase;
  $$("#phaseTrack span").forEach((node) => node.classList.toggle("is-active", node.dataset.phase === group));
}

function renderStatus(data) {
  setRuntime(data.runtime || "offline", data.error || "");
  setPhase(data.phase || "stopped");
  const labels = { wake: "唤醒模型", asr: "语音识别", vad: "语音检测", tts: "语音合成", dify: "Dify 服务" };
  ui.resourceList.replaceChildren(...Object.entries(labels).map(([key, label]) => {
    const ok = Boolean(data.resources?.[key]);
    const row = document.createElement("div"); row.className = "resource";
    const name = document.createElement("span"); name.textContent = label;
    const result = document.createElement("b"); result.classList.toggle("ok", ok); result.textContent = ok ? "READY" : "CHECK";
    row.append(name, result); return row;
  }));
  const safety = data.safety || {};
  const safetyRow = (label, value, className = "") => {
    const row = document.createElement("div"); row.className = "safety-row";
    const name = document.createElement("span"); name.textContent = label;
    const result = document.createElement("b"); result.textContent = value; if (className) result.className = className;
    row.append(name, result); return row;
  };
  ui.safetyCard.replaceChildren(
    safetyRow("机械臂执行", safety.robot_command_enabled ? "已开启" : "安全关闭", safety.robot_command_enabled ? "warn" : "safe"),
    safetyRow("按摩控制", safety.massage_enabled ? "已开启" : "安全关闭", safety.massage_enabled ? "warn" : "safe"),
    safetyRow("按摩 Dry-run", safety.massage_dry_run ? "模拟" : "实机模式")
  );
  ui.audioDevice.textContent = data.resources?.audio_device || "default";
}

function messageNode(id, role, timestamp) {
  let node = document.getElementById(id);
  if (node) return node;
  ui.emptyConversation.hidden = true;
  node = document.createElement("article");
  node.id = id;
  node.className = `message message--${role}`;
  const meta = document.createElement("div"); meta.className = "message__meta";
  const author = document.createElement("strong"); author.textContent = role === "user" ? "你" : role === "assistant" ? "小西" : "动作";
  const time = document.createElement("time"); time.textContent = timeLabel(timestamp);
  const body = document.createElement("div"); body.className = "message__body";
  meta.append(author, time); node.append(meta, body);
  ui.conversation.appendChild(node);
  return node;
}

function updateConversation(event) {
  const turn = event.turn_id || `event-${event.sequence}`;
  const payload = event.payload || {};
  if (event.type === "conversation.user") {
    state.turns.add(turn);
    const node = messageNode(`user-${turn}`, "user", event.timestamp);
    node.querySelector(".message__body").textContent = payload.text || "未识别到有效语音";
  } else if (event.type === "conversation.assistant.delta") {
    const node = messageNode(`assistant-${turn}`, "assistant", event.timestamp);
    node.classList.add("is-streaming");
    node.querySelector(".message__body").textContent += payload.text || "";
  } else if (event.type === "conversation.assistant.done") {
    const node = messageNode(`assistant-${turn}`, "assistant", event.timestamp);
    node.classList.remove("is-streaming");
    if (payload.text) node.querySelector(".message__body").textContent = payload.text;
    if (!node.querySelector(".message__body").textContent) node.remove();
  } else if (event.type === "action.result") {
    const action = payload.action || "action";
    const node = messageNode(`action-${turn}-${event.sequence}`, "action", event.timestamp);
    const details = Object.entries(payload).filter(([key]) => !["reply"].includes(key)).map(([key, value]) => `${key}: ${typeof value === "object" ? JSON.stringify(value) : value}`).join(" · ");
    node.querySelector(".message__body").textContent = `动作结果 · ${action}${details ? `\n${details}` : ""}`;
  }
  ui.turnCount.textContent = `${state.turns.size} 轮`;
  ui.conversation.scrollTop = ui.conversation.scrollHeight;
}

function addLog(event) {
  const line = document.createElement("div");
  line.className = "log-line";
  const time = document.createElement("time"); time.textContent = timeLabel(event.timestamp); line.append(time);
  const timing = event.type === "voice.timing"
    ? `耗时 · ${event.payload?.stage || "stage"} · ${JSON.stringify(event.payload || {})}`
    : "";
  line.append(document.createTextNode(event.payload?.message || timing || JSON.stringify(event.payload || {})));
  ui.logs.appendChild(line);
  while (ui.logs.children.length > 500) ui.logs.firstChild.remove();
  ui.logs.scrollTop = ui.logs.scrollHeight;
}

function resetConversation() {
  $$(".conversation .message").forEach((node) => node.remove());
  state.turns.clear();
  ui.turnCount.textContent = "0 轮";
  ui.emptyConversation.hidden = false;
}

function handleEvent(event) {
  if (event.type === "dashboard.snapshot") {
    resetConversation(); ui.logs.replaceChildren();
    renderStatus(event.payload.status);
    (event.payload.conversation || []).forEach(updateConversation);
    (event.payload.logs || []).forEach(addLog);
  } else if (event.type === "runtime.status") {
    setRuntime(event.payload.status, event.payload.error);
  } else if (event.type === "voice.phase") {
    setPhase(event.payload.phase);
  } else if (event.type.startsWith("conversation.") || event.type === "action.result") {
    if (event.type === "conversation.cleared") resetConversation(); else updateConversation(event);
  } else if (event.type === "runtime.log" || event.type === "runtime.error" || event.type === "voice.timing") {
    addLog(event);
  } else if (event.type === "audio.level") {
    const bucket = Math.max(0, Math.min(6, Math.round(Number(event.payload.rms || 0) * 90)));
    document.documentElement.className = `audio-level-${bucket}`;
  }
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if ((options.method || "GET").toUpperCase() !== "GET" && state.csrfToken) headers.set("X-CSRF-Token", state.csrfToken);
  const response = await fetch(path, { credentials: "same-origin", ...options, headers });
  if (response.status === 401) { showLogin(); throw new Error("需要重新登录"); }
  const data = await response.json();
  if (!response.ok || data.ok === false) throw new Error(data.message || `HTTP ${response.status}`);
  return data;
}

function showLogin() {
  ui.loginLayer.classList.remove("is-hidden");
  ui.appShell.setAttribute("aria-hidden", "true");
  if (state.socket) state.socket.close();
}

function showApp() {
  ui.loginLayer.classList.add("is-hidden");
  ui.appShell.setAttribute("aria-hidden", "false");
}

function connectSocket() {
  clearTimeout(state.reconnectTimer);
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const socket = new WebSocket(`${protocol}//${location.host}/ws`);
  state.socket = socket;
  socket.onmessage = (message) => { try { handleEvent(JSON.parse(message.data)); } catch (error) { console.error(error); } };
  socket.onclose = (event) => {
    if (event.code === 1008 || event.code === 1003) return showLogin();
    state.reconnectTimer = setTimeout(connectSocket, 1500);
  };
}

ui.loginForm.addEventListener("submit", async (event) => {
  event.preventDefault(); ui.loginError.textContent = "";
  try {
    const response = await fetch("/api/auth", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token: ui.tokenInput.value }) });
    if (!response.ok) throw new Error(await response.text());
    const data = await response.json(); state.csrfToken = data.csrf_token || "";
    ui.tokenInput.value = ""; showApp(); renderStatus(await api("/api/status")); connectSocket();
  } catch (error) { ui.loginError.textContent = error.message || "登录失败"; }
});

ui.startBtn.addEventListener("click", async () => {
  ui.controlMessage.textContent = "正在启动语音模块…";
  try { const data = await api("/api/runtime/start", { method: "POST" }); ui.controlMessage.textContent = data.message; }
  catch (error) { ui.controlMessage.textContent = error.message; }
});
ui.stopBtn.addEventListener("click", async () => {
  ui.controlMessage.textContent = "正在停止语音模块…";
  try { const data = await api("/api/runtime/stop", { method: "POST" }); ui.controlMessage.textContent = data.message; }
  catch (error) { ui.controlMessage.textContent = error.message; }
});
ui.clearBtn.addEventListener("click", async () => {
  try { await api("/api/conversation/clear", { method: "POST" }); } catch (error) { ui.controlMessage.textContent = error.message; }
});
ui.clearLogsBtn.addEventListener("click", () => { ui.logs.replaceChildren(); });
$$('.tab').forEach((tab) => tab.addEventListener("click", () => {
  $$('.tab').forEach((node) => node.classList.toggle("is-active", node === tab));
  $$('.tab-view').forEach((node) => node.classList.toggle("is-active", node.dataset.view === tab.dataset.tab));
}));

(async () => {
  try { renderStatus(await api("/api/status")); showApp(); connectSocket(); }
  catch { showLogin(); }
})();
