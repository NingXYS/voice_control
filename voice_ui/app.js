const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const ui = {
  loginLayer: $("#loginLayer"), loginForm: $("#loginForm"), tokenInput: $("#tokenInput"), loginError: $("#loginError"),
  appShell: $("#appShell"), runtimePill: $("#runtimePill"), userStage: $("#userStage"), assistantStage: $("#assistantStage"),
  phaseTitle: $("#phaseTitle"), phaseHint: $("#phaseHint"), orbWrap: $("#orbWrap"), phaseTrack: $("#phaseTrack"),
  startBtn: $("#startBtn"), stopBtn: $("#stopBtn"), clearBtn: $("#clearBtn"), controlMessage: $("#controlMessage"),
  conversation: $("#conversation"), emptyConversation: $("#emptyConversation"), turnCount: $("#turnCount"),
  resourceList: $("#resourceList"), safetyCard: $("#safetyCard"), audioDevice: $("#audioDevice"), logs: $("#logs"), clearLogsBtn: $("#clearLogsBtn"),
  speakerSummary: $("#speakerSummary"), speakerNameInput: $("#speakerNameInput"), speakerEnrollBtn: $("#speakerEnrollBtn"), speakerHelp: $("#speakerHelp"),
  enrollmentCard: $("#enrollmentCard"), enrollmentProgress: $("#enrollmentProgress"), enrollmentPrompt: $("#enrollmentPrompt"), enrollmentMessage: $("#enrollmentMessage"),
  enrollmentGroup: $("#enrollmentGroup"),
  captureSpeakerSampleBtn: $("#captureSpeakerSampleBtn"), commitSpeakerBtn: $("#commitSpeakerBtn"), cancelSpeakerBtn: $("#cancelSpeakerBtn"), speakerList: $("#speakerList"),
  probeSpeakerSelect: $("#probeSpeakerSelect"), probeBatchInput: $("#probeBatchInput"), captureProbeBtn: $("#captureProbeBtn"), probeResult: $("#probeResult"), evaluationCard: $("#evaluationCard"),
  rebuildExperimentsBtn: $("#rebuildExperimentsBtn"), rollbackLegacyBtn: $("#rollbackLegacyBtn"), experimentHelp: $("#experimentHelp"), experimentCard: $("#experimentCard"),
  speakerThresholdForm: $("#speakerThresholdForm"), speakerThresholdInput: $("#speakerThresholdInput"),
  speakerThresholdBtn: $("#speakerThresholdBtn"), speakerThresholdRange: $("#speakerThresholdRange"),
  speakerThresholdHelp: $("#speakerThresholdHelp")
};

const state = {
  runtime: "offline",
  phase: "stopped",
  socket: null,
  authenticated: false,
  csrfToken: "",
  messages: new Map(),
  turns: new Set(),
  reconnectTimer: null,
  speakerData: null,
  enrollment: null,
  enrollmentBusy: false,
  enrollmentOperationToken: 0,
  probeBusy: false,
  experimentBusy: false,
  notices: { speaker: "", enrollment: "", experiment: "" }
};
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
  if (state.speakerData) renderSpeaker(state.speakerData);
}

function summaryRow(label, value, className = "speaker-summary-row") {
  const row = document.createElement("div"); row.className = className;
  const name = document.createElement("span"); name.textContent = label;
  const result = document.createElement("b"); result.textContent = value;
  row.append(name, result); return row;
}

function percentLabel(value) {
  return value === null || value === undefined ? "样本不足" : `${(Number(value) * 100).toFixed(1)}%`;
}

function setNotice(area, message) {
  state.notices[area] = String(message || "");
  if (area === "speaker") ui.speakerHelp.textContent = state.notices[area];
  if (area === "enrollment") ui.enrollmentMessage.textContent = state.notices[area];
  if (area === "experiment") ui.experimentHelp.textContent = state.notices[area];
}

function finiteNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const result = Number(value);
  return Number.isFinite(result) ? result : null;
}

function sameReportActivation(activeBundle, experiments, model) {
  if (!activeBundle || activeBundle.legacy || activeBundle.model_id !== model.model_id) return false;
  const reportGeneratedAt = model.report_generated_at || experiments.generated_at || "";
  const activeGeneratedAt = activeBundle.report_generated_at || "";
  const reportThreshold = finiteNumber(model.threshold);
  const activeThreshold = finiteNumber(activeBundle.threshold);
  return Boolean(reportGeneratedAt)
    && reportGeneratedAt === activeGeneratedAt
    && reportThreshold !== null
    && activeThreshold !== null
    && Math.abs(reportThreshold - activeThreshold) < 1e-9;
}

function evaluationRows(evaluation, { legacy = false } = {}) {
  const rows = [];
  if (legacy) {
    const heading = document.createElement("div");
    heading.className = "evaluation-subhead";
    heading.textContent = "历史 CAM++ 评估（只读参考）";
    rows.push(heading);
  }
  rows.push(
    summaryRow(legacy ? "历史本人样本" : "本人样本", `${evaluation.genuine_count || 0} / 30`, "evaluation-row"),
    summaryRow(legacy ? "历史非本人样本" : "非本人样本", `${evaluation.impostor_count || 0} / 100`, "evaluation-row"),
    summaryRow(legacy ? "历史误拒率 FRR" : "误拒率 FRR", percentLabel(evaluation.false_reject_rate), "evaluation-row"),
    summaryRow(legacy ? "历史误接收率 FAR" : "误接收率 FAR", percentLabel(evaluation.false_accept_rate), "evaluation-row"),
    summaryRow(legacy ? "历史 P95 延迟" : "P95 延迟", evaluation.p95_latency_ms == null ? "样本不足" : `${evaluation.p95_latency_ms} ms`, "evaluation-row")
  );
  if (!legacy) {
    rows.push(
      summaryRow("部署阈值", evaluation.threshold == null && evaluation.recommended_threshold == null ? "样本不足" : Number(evaluation.threshold ?? evaluation.recommended_threshold).toFixed(2), "evaluation-row"),
      summaryRow("强制门控条件", evaluation.ready ? "已达标" : "未达标", "evaluation-row")
    );
  }
  return rows;
}

function renderSpeaker(data) {
  state.speakerData = data || {};
  const profiles = Array.isArray(data?.profiles) ? data.profiles : [];
  const evaluation = data?.evaluation || {};
  const legacyEvaluation = data?.legacy_evaluation || null;
  const drafts = Array.isArray(data?.drafts) ? data.drafts : [];
  const experiments = data?.experiments || {};
  const activeBundle = data?.active_bundle || null;
  const modelRows = Array.isArray(experiments.models) ? experiments.models : [];
  const configuredModels = Array.isArray(data?.models) ? data.models : [];
  const activeModelId = activeBundle?.model_id || data?.effective_model_id || data?.active_model_id || (data?.model_ready ? "campplus" : "");
  const activeModel = modelRows.concat(configuredModels).find((model) => model.model_id === activeModelId);
  const activeModelLabel = activeModel?.label || (activeModelId === "campplus" ? "CAM++" : activeModelId || "缺失");
  const modeLabels = { off: "关闭", shadow: "影子验证", enforce: "强制门控" };
  const effectiveThreshold = finiteNumber(
    data?.threshold ?? activeBundle?.operator_threshold ?? activeBundle?.threshold ?? evaluation?.threshold
  );
  const thresholdMin = finiteNumber(data?.threshold_min ?? activeBundle?.threshold_min);
  const thresholdMax = finiteNumber(data?.threshold_max ?? activeBundle?.threshold_max);
  const thresholdDefault = finiteNumber(data?.threshold_default ?? activeBundle?.threshold);
  const thresholdSourceLabels = { report: "报告默认", operator: "手动调整", legacy: "旧版", env: "环境变量" };
  const thresholdSource = thresholdSourceLabels[data?.threshold_source] || data?.threshold_source || "-";
  ui.speakerSummary.replaceChildren(
    summaryRow("当前生效模型", activeModelLabel),
    summaryRow("当前模式", modeLabels[data?.mode] || data?.mode || "关闭"),
    summaryRow("生效阈值", effectiveThreshold == null ? "-" : effectiveThreshold.toFixed(4)),
    summaryRow("阈值来源", thresholdSource),
    summaryRow("当前授权用户", `${profiles.length} 位`)
  );

  const runtimeOffline = state.runtime === "offline" || state.runtime === "error";
  const experimentBusy = state.experimentBusy || Boolean(data?.experiment_busy);
  const manageable = runtimeOffline && Boolean(data?.model_ready) && !state.enrollment && !state.enrollmentBusy && !experimentBusy;
  const thresholdEditable = Boolean(data?.threshold_editable) && manageable && thresholdMin != null && thresholdMax != null;
  if (ui.speakerThresholdForm) {
    ui.speakerThresholdForm.hidden = !Boolean(data?.threshold_editable);
    if (ui.speakerThresholdInput && document.activeElement !== ui.speakerThresholdInput) {
      ui.speakerThresholdInput.value = effectiveThreshold == null ? "" : String(Number(effectiveThreshold.toFixed(4)));
      ui.speakerThresholdInput.min = thresholdMin == null ? "0" : String(thresholdMin);
      ui.speakerThresholdInput.max = thresholdMax == null ? "1" : String(thresholdMax);
    }
    if (ui.speakerThresholdRange) {
      ui.speakerThresholdRange.textContent = (thresholdMin != null && thresholdMax != null)
        ? `安全区间 ${thresholdMin.toFixed(4)} – ${thresholdMax.toFixed(4)}${thresholdDefault != null ? `（默认 ${thresholdDefault.toFixed(4)}）` : ""}`
        : "";
    }
    if (ui.speakerThresholdBtn) ui.speakerThresholdBtn.disabled = !thresholdEditable;
    if (ui.speakerThresholdInput) ui.speakerThresholdInput.disabled = !thresholdEditable;
    if (ui.speakerThresholdHelp && !state.notices.threshold) {
      ui.speakerThresholdHelp.textContent = data?.threshold_editable
        ? (runtimeOffline
          ? "可在安全区间内下调阈值以提高本人通过率；改完后需重新启动语音模块。"
          : "调整阈值前请先停止语音模块。")
        : "";
    }
  }
  ui.speakerEnrollBtn.disabled = !manageable;
  ui.speakerNameInput.disabled = !manageable;
  const defaultSpeakerHelp = data?.error
    ? data.error
    : !data?.model_ready
      ? "请先安装 CAM++ 声纹模型。"
      : !runtimeOffline
        ? "登记和评估前请先停止语音模块。"
        : experimentBusy
          ? "三模型评测或模型切换正在进行，请等待完成。"
        : "每位用户登记3组×8条；新录音保存为本机私有FLAC，生产声纹在评测通过前保持不变。";
  ui.speakerHelp.textContent = state.notices.speaker || defaultSpeakerHelp;

  const draftBySpeaker = new Map(drafts.map((draft) => [draft.speaker_id, draft]));
  const profileIds = new Set(profiles.map((profile) => profile.speaker_id));
  const cards = profiles.map((profile) => ({ profile, draft: draftBySpeaker.get(profile.speaker_id) || null, active: true }));
  drafts.filter((draft) => !profileIds.has(draft.speaker_id)).forEach((draft) => cards.push({
    profile: { speaker_id: draft.speaker_id, display_name: draft.display_name, sample_count: 0 }, draft, active: false
  }));
  if (!cards.length) {
    const empty = document.createElement("div"); empty.className = "speaker-empty"; empty.textContent = "尚未登记授权用户";
    ui.speakerList.replaceChildren(empty);
  } else {
    ui.speakerList.replaceChildren(...cards.map(({ profile, draft, active }) => {
      const item = document.createElement("article"); item.className = "speaker-item";
      const head = document.createElement("header");
      const name = document.createElement("strong"); name.textContent = profile.display_name;
      const groupCount = draft?.groups?.length || 0;
      const count = document.createElement("span"); count.textContent = `${active ? `生效模板 ${profile.sample_count} 条` : "尚未激活"} · 草稿 ${groupCount}/3 组`;
      head.append(name, count);
      const foot = document.createElement("footer");
      const rerecord = document.createElement("button"); rerecord.textContent = groupCount >= 3 ? "三组已完成" : "追加登记一组"; rerecord.disabled = !manageable || groupCount >= 3;
      rerecord.addEventListener("click", () => startEnrollment(profile.display_name, profile.speaker_id));
      const remove = document.createElement("button"); remove.textContent = "撤销授权"; remove.disabled = !manageable;
      remove.addEventListener("click", () => deleteSpeaker(profile));
      foot.append(rerecord); if (active) foot.append(remove); item.append(head, foot); return item;
    }));
  }

  const selected = ui.probeSpeakerSelect.value;
  const completeDraftProfiles = drafts.filter((draft) => (draft.groups?.length || 0) >= 3).map((draft) => ({ speaker_id: draft.speaker_id, display_name: draft.display_name }));
  const optionMap = new Map(profiles.concat(completeDraftProfiles).map((profile) => [profile.speaker_id, profile]));
  const options = [{ speaker_id: "", display_name: "未登记人员" }, ...optionMap.values()];
  ui.probeSpeakerSelect.replaceChildren(...options.map((profile) => {
    const option = document.createElement("option"); option.value = profile.speaker_id; option.textContent = profile.display_name; return option;
  }));
  if (options.some((option) => option.speaker_id === selected)) ui.probeSpeakerSelect.value = selected;
  const hasEvaluationSpeaker = options.length > 1;
  ui.probeSpeakerSelect.disabled = !manageable || !hasEvaluationSpeaker || state.probeBusy;
  ui.captureProbeBtn.disabled = !manageable || !hasEvaluationSpeaker || state.probeBusy;
  ui.probeBatchInput.disabled = !manageable || !hasEvaluationSpeaker || state.probeBusy;

  const evaluationContent = evaluationRows(evaluation);
  if (legacyEvaluation && activeModelId !== "campplus") evaluationContent.push(...evaluationRows(legacyEvaluation, { legacy: true }));
  ui.evaluationCard.replaceChildren(...evaluationContent);

  if (!modelRows.length) {
    const empty = document.createElement("div"); empty.className = "speaker-empty"; empty.textContent = "完成3组登记并采集新评估录音后运行三模型报告";
    ui.experimentCard.replaceChildren(empty);
  } else {
    ui.experimentCard.replaceChildren(...modelRows.map((model) => {
      const item = document.createElement("article"); item.className = "model-result";
      const head = document.createElement("header");
      const name = document.createElement("strong"); name.textContent = model.label || model.model_id;
      const reportStale = Boolean(experiments.stale || model.stale);
      const status = document.createElement("b"); status.textContent = reportStale ? "报告已过期" : !model.available ? "模型缺失" : model.ready ? "安全达标" : "未达标";
      head.append(name, status);
      const detail = document.createElement("p");
      detail.textContent = reportStale
        ? (experiments.stale_reason || model.stale_reason || "录音、声纹模板或推理配置已变化，请重新计算报告后再激活。")
        : model.reason || `阈值 ${Number(model.threshold || 0).toFixed(4)}${model.threshold_max != null && Number(model.threshold_max) !== Number(model.threshold) ? `–${Number(model.threshold_max).toFixed(4)}` : ""} · FAR ${percentLabel(model.false_accept_rate)} · FRR ${percentLabel(model.false_reject_rate)} · 路人 ${model.impostor_count || 0}/100 · 批次 ${model.impostor_batch_count || 0}/3 · P95 ${model.p95_latency_ms ?? "-"}ms`;
      item.append(head, detail);
      if (model.ready) {
        const alreadyActive = sameReportActivation(activeBundle, experiments, model);
        const sameModel = activeBundle && !activeBundle.legacy && activeBundle.model_id === model.model_id;
        const activate = document.createElement("button");
        activate.textContent = reportStale
          ? "报告过期，禁止激活"
          : alreadyActive
            ? "当前报告已激活"
            : sameModel
              ? "重新激活最新报告"
              : "激活这个模型";
        activate.disabled = reportStale || alreadyActive || !manageable || experimentBusy;
        activate.addEventListener("click", () => activateExperiment(model.model_id)); item.append(activate);
      }
      return item;
    }));
  }
  ui.rebuildExperimentsBtn.disabled = !manageable || experimentBusy || !drafts.some((draft) => (draft.groups?.length || 0) >= 3);
  ui.rollbackLegacyBtn.hidden = !activeBundle || Boolean(activeBundle.legacy);
  const rollbackManageable = runtimeOffline
    && Boolean(data?.legacy_rollback_ready)
    && !state.enrollment
    && !state.enrollmentBusy
    && !experimentBusy;
  ui.rollbackLegacyBtn.disabled = !rollbackManageable;
  const defaultExperimentHelp = experimentBusy
    ? "三模型评测或模型切换正在进行，请勿关闭页面。"
    : experiments.stale
      ? `三模型报告已过期${experiments.stale_reason ? `：${experiments.stale_reason}` : ""}，请重新计算后再激活。`
      : experiments.recommended_model_id
        ? `安全优先建议：${experiments.recommended_model_id}；切换后仍保留当前CAM++供回滚。`
        : "新录音会以本机私有 FLAC 长期保存；历史 CAM++ 分数只读归档。";
  ui.experimentHelp.textContent = state.notices.experiment || defaultExperimentHelp;
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

function currentEnrollmentField(payload) {
  if (payload && Object.hasOwn(payload, "current_enrollment")) {
    return { present: true, value: payload.current_enrollment };
  }
  if (payload?.speaker && Object.hasOwn(payload.speaker, "current_enrollment")) {
    return { present: true, value: payload.speaker.current_enrollment };
  }
  return { present: false, value: null };
}

function syncCurrentEnrollment(payload) {
  const current = currentEnrollmentField(payload);
  if (!current.present) return;
  const wasMissing = !state.enrollment;
  renderEnrollment(current.value);
  if (current.value && wasMissing && !state.notices.enrollment) {
    setNotice("enrollment", "已恢复未完成的登记会话，可以继续录制或取消本组。");
  }
}

function renderStatus(data) {
  setRuntime(data.runtime || "offline", data.error || "");
  setPhase(data.phase || "stopped");
  const labels = { wake: "唤醒模型", asr: "语音识别", vad: "语音检测", tts: "语音合成", speaker: "声纹模型", dify: "Dify 服务" };
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
  renderSpeaker(data.speaker || {});
  syncCurrentEnrollment(data);
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
    : event.type === "voice.speaker"
      ? `声纹 · ${event.payload?.accepted ? "匹配" : "未匹配"} · ${event.payload?.display_name || "无"} · score=${event.payload?.score}${event.payload?.threshold != null ? ` / thr=${event.payload.threshold}` : ""} · ${event.payload?.duration_ms}ms`
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
  } else if (event.type === "speaker.updated") {
    refreshSpeakers().catch((error) => { setNotice("speaker", error.message); });
  } else if (event.type === "voice.phase") {
    setPhase(event.payload.phase);
  } else if (event.type.startsWith("conversation.") || event.type === "action.result") {
    if (event.type === "conversation.cleared") resetConversation(); else updateConversation(event);
  } else if (event.type === "runtime.log" || event.type === "runtime.error" || event.type === "voice.timing" || event.type === "voice.speaker") {
    addLog(event);
  } else if (event.type === "audio.level") {
    const bucket = Math.max(0, Math.min(6, Math.round(Number(event.payload.rms || 0) * 90)));
    document.documentElement.className = `audio-level-${bucket}`;
  }
}

async function responsePayload(response) {
  const text = await response.text();
  if (!text) return {};
  try { return JSON.parse(text); }
  catch { return { message: text.trim() || response.statusText || `HTTP ${response.status}` }; }
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if ((options.method || "GET").toUpperCase() !== "GET" && state.csrfToken) headers.set("X-CSRF-Token", state.csrfToken);
  const response = await fetch(path, { credentials: "same-origin", ...options, headers });
  const data = await responsePayload(response);
  if (response.status === 401 || response.status === 403) {
    const message = response.status === 403 ? "登录会话的安全校验已失效，请重新登录" : "登录会话已失效，请重新登录";
    state.csrfToken = "";
    showLogin(message);
    throw new Error(message);
  }
  if (!response.ok || data?.ok === false) throw new Error(data?.message || `HTTP ${response.status}`);
  return data;
}

async function restoreSession() {
  const session = await api("/api/session");
  if (!session?.csrf_token) throw new Error("登录会话缺少安全令牌，请重新登录");
  state.csrfToken = session.csrf_token;
  return session;
}

function showLogin(message = "") {
  state.authenticated = false;
  state.csrfToken = "";
  clearTimeout(state.reconnectTimer);
  if (message) ui.loginError.textContent = message;
  ui.loginLayer.classList.remove("is-hidden");
  ui.appShell.setAttribute("aria-hidden", "true");
  const socket = state.socket;
  state.socket = null;
  if (socket) socket.close();
}

function showApp() {
  state.authenticated = true;
  ui.loginLayer.classList.add("is-hidden");
  ui.appShell.setAttribute("aria-hidden", "false");
}

function connectSocket() {
  if (!state.authenticated) return;
  if (state.socket && [WebSocket.CONNECTING, WebSocket.OPEN].includes(state.socket.readyState)) return;
  clearTimeout(state.reconnectTimer);
  const protocol = location.protocol === "https:" ? "wss:" : "ws:";
  const socket = new WebSocket(`${protocol}//${location.host}/ws`);
  state.socket = socket;
  socket.onmessage = (message) => { try { handleEvent(JSON.parse(message.data)); } catch (error) { console.error(error); } };
  socket.onclose = (event) => {
    if (state.socket !== socket) return;
    state.socket = null;
    if (event.code === 1008 || event.code === 1003) return showLogin("实时连接会话已失效，请重新登录");
    if (!state.authenticated) return;
    state.reconnectTimer = setTimeout(connectSocket, 1500);
  };
}

function renderEnrollment(enrollment, { renderSpeakerData = true } = {}) {
  state.enrollment = enrollment;
  ui.enrollmentCard.hidden = !enrollment;
  if (!enrollment) {
    ui.enrollmentMessage.textContent = state.notices.enrollment;
    if (renderSpeakerData && state.speakerData) renderSpeaker(state.speakerData);
    return;
  }
  ui.enrollmentProgress.textContent = `${enrollment.sample_count} / ${enrollment.required_samples}`;
  ui.enrollmentGroup.textContent = `${enrollment.group_label} · 已完成 ${enrollment.completed_groups} / ${enrollment.required_groups} 组 · ${enrollment.group_instruction}`;
  ui.enrollmentPrompt.textContent = enrollment.complete ? "样本已足够，可以保存声纹" : `请朗读：${enrollment.prompt}`;
  ui.enrollmentMessage.textContent = state.notices.enrollment;
  ui.captureSpeakerSampleBtn.disabled = state.enrollmentBusy || Boolean(enrollment.complete);
  ui.commitSpeakerBtn.disabled = state.enrollmentBusy || !enrollment.complete;
  ui.cancelSpeakerBtn.disabled = state.enrollmentBusy;
  if (renderSpeakerData) renderSpeaker(state.speakerData || {});
}

function beginEnrollmentOperation() {
  if (state.enrollmentBusy) return null;
  state.enrollmentBusy = true;
  state.enrollmentOperationToken += 1;
  renderEnrollment(state.enrollment, { renderSpeakerData: false });
  if (state.speakerData) renderSpeaker(state.speakerData);
  return state.enrollmentOperationToken;
}

function enrollmentOperationIsCurrent(token) {
  return token !== null && token === state.enrollmentOperationToken;
}

function finishEnrollmentOperation(token) {
  if (!enrollmentOperationIsCurrent(token)) return;
  state.enrollmentBusy = false;
  renderEnrollment(state.enrollment, { renderSpeakerData: false });
  if (state.speakerData) renderSpeaker(state.speakerData);
}

async function refreshSpeakers() {
  const data = await api("/api/speakers");
  renderSpeaker(data);
  syncCurrentEnrollment(data);
  return data;
}

async function startEnrollment(displayName, replaceSpeakerId = null) {
  const name = String(displayName || "").trim();
  if (!name) { setNotice("speaker", "请先输入用户名称。"); return; }
  const operationToken = beginEnrollmentOperation();
  if (operationToken === null) return;
  setNotice("speaker", "正在创建声纹登记会话…");
  try {
    const data = await api("/api/speakers/enrollments", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ display_name: name, replace_speaker_id: replaceSpeakerId })
    });
    if (!enrollmentOperationIsCurrent(operationToken)) return;
    ui.speakerNameInput.value = "";
    setNotice("speaker", "登记进行中；请完成或取消当前这一组后再进行其他声纹操作。");
    setNotice("enrollment", "登记会话已就绪，点击录制后开始朗读。");
    renderEnrollment(data);
  } catch (error) {
    if (enrollmentOperationIsCurrent(operationToken)) setNotice("speaker", error.message);
    await refreshSpeakers().catch(() => {});
  } finally {
    finishEnrollmentOperation(operationToken);
  }
}

async function deleteSpeaker(profile) {
  if (!window.confirm(`确认撤销“${profile.display_name}”的当前声纹授权吗？历史原始录音不会被删除。`)) return;
  try {
    await api(`/api/speakers/${encodeURIComponent(profile.speaker_id)}`, { method: "DELETE" });
    setNotice("speaker", "当前生产授权已撤销；历史原始录音仍按保留策略保存，评估结果已失效。");
    await refreshSpeakers();
  } catch (error) { setNotice("speaker", error.message); }
}

ui.speakerEnrollBtn.addEventListener("click", () => startEnrollment(ui.speakerNameInput.value));
ui.captureSpeakerSampleBtn.addEventListener("click", async () => {
  const enrollment = state.enrollment;
  if (!enrollment) return;
  const operationToken = beginEnrollmentOperation();
  if (operationToken === null) return;
  const previousRejected = Number(enrollment.quality_rejected || 0);
  setNotice("enrollment", "正在收音，请自然朗读提示句，读完后停顿一下…");
  try {
    const data = await api(`/api/speakers/enrollments/${encodeURIComponent(enrollment.session_id)}/samples`, { method: "POST" });
    if (!enrollmentOperationIsCurrent(operationToken)) return;
    renderEnrollment(data);
    const accepted = data.sample?.accepted !== false;
    const reason = String(data.sample?.reason || "").trim();
    const newlyRejected = Math.max(0, Number(data.quality_rejected || 0) - previousRejected);
    if (!accepted) {
      setNotice("enrollment", `本条未计入有效样本${reason ? `：${reason}` : "，请重新录制"}。原始音频已保留供审计。`);
    } else if (newlyRejected > 0) {
      setNotice("enrollment", `质量检查剔除了 ${newlyRejected} 条离群样本；原始音频仍已保留，请按当前提示继续补录。`);
    } else {
      const seconds = finiteNumber(data.sample?.audio_ms);
      setNotice("enrollment", seconds === null ? "本条录制有效。" : `本条录制有效：${(seconds / 1000).toFixed(1)} 秒。`);
    }
  } catch (error) {
    if (enrollmentOperationIsCurrent(operationToken)) setNotice("enrollment", `本条未计入：${error.message}`);
    await refreshSpeakers().catch(() => {});
  } finally {
    finishEnrollmentOperation(operationToken);
  }
});
ui.commitSpeakerBtn.addEventListener("click", async () => {
  const enrollment = state.enrollment;
  if (!enrollment) return;
  const operationToken = beginEnrollmentOperation();
  if (operationToken === null) return;
  setNotice("enrollment", "正在保存这一组声纹…");
  try {
    const data = await api(`/api/speakers/enrollments/${encodeURIComponent(enrollment.session_id)}/commit`, { method: "POST" });
    if (!enrollmentOperationIsCurrent(operationToken)) return;
    setNotice("enrollment", "");
    renderEnrollment(null);
    setNotice("speaker", data.profile.draft_complete
      ? `“${data.profile.display_name}”的3组草稿已完成，请采集新评估录音并运行三模型报告。`
      : `已保存第 ${data.profile.group_count} / ${data.profile.required_groups} 组，请继续追加下一组。`);
    await refreshSpeakers();
  } catch (error) {
    if (enrollmentOperationIsCurrent(operationToken)) setNotice("enrollment", error.message);
    await refreshSpeakers().catch(() => {});
  } finally {
    finishEnrollmentOperation(operationToken);
  }
});
ui.cancelSpeakerBtn.addEventListener("click", async () => {
  const enrollment = state.enrollment;
  if (!enrollment) return;
  const operationToken = beginEnrollmentOperation();
  if (operationToken === null) return;
  setNotice("enrollment", "正在取消本组登记…");
  try {
    await api(`/api/speakers/enrollments/${encodeURIComponent(enrollment.session_id)}`, { method: "DELETE" });
    if (!enrollmentOperationIsCurrent(operationToken)) return;
    setNotice("enrollment", "");
    renderEnrollment(null);
    setNotice("speaker", "已取消本组登记；已录音频按不删除策略标记为未采用。");
    await refreshSpeakers();
  } catch (error) {
    if (enrollmentOperationIsCurrent(operationToken)) setNotice("enrollment", error.message);
    await refreshSpeakers().catch(() => {});
  } finally {
    finishEnrollmentOperation(operationToken);
  }
});
ui.captureProbeBtn.addEventListener("click", async () => {
  if (state.probeBusy) return;
  state.probeBusy = true;
  if (state.speakerData) renderSpeaker(state.speakerData);
  ui.probeResult.textContent = "正在收音，请说一条真实使用场景中的指令…";
  try {
    const actual = ui.probeSpeakerSelect.value || null;
    const subjectBatch = String(ui.probeBatchInput.value || "").trim();
    if (!actual && !subjectBatch) throw new Error("录制路人样本前请填写匿名批次，例如“路人A”；正式评测至少需要3批。 ");
    const data = await api("/api/speakers/probes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ actual_speaker_id: actual, subject_batch: subjectBatch })
    });
    ui.probeResult.textContent = `${data.accepted ? "匹配" : "未匹配"} · ${data.display_name || "无"} · 得分 ${Number(data.score).toFixed(3)} · ${data.duration_ms} ms`;
    await refreshSpeakers();
  } catch (error) {
    ui.probeResult.textContent = error.message;
  } finally {
    state.probeBusy = false;
    if (state.speakerData) renderSpeaker(state.speakerData);
  }
});

ui.rebuildExperimentsBtn.addEventListener("click", async () => {
  if (state.experimentBusy) return;
  state.experimentBusy = true;
  setNotice("experiment", "正在用同一批私有FLAC计算三个模型，请稍候…");
  if (state.speakerData) renderSpeaker(state.speakerData);
  try {
    const data = await api("/api/speakers/experiments/rebuild", { method: "POST" });
    setNotice("experiment", data.recommended_model_id ? `报告完成，建议模型：${data.recommended_model_id}` : "报告完成，但尚无模型达到安全门槛。");
    await refreshSpeakers();
  } catch (error) { setNotice("experiment", error.message); }
  finally {
    state.experimentBusy = false;
    if (state.speakerData) renderSpeaker(state.speakerData);
  }
});

async function activateExperiment(modelId) {
  if (state.experimentBusy) return;
  if (!window.confirm(`确认激活 ${modelId} 吗？只有已通过零误接收门槛的模型可激活。`)) return;
  state.experimentBusy = true;
  setNotice("experiment", "正在生成并原子切换声纹模型包…");
  if (state.speakerData) renderSpeaker(state.speakerData);
  try {
    await api(`/api/speakers/experiments/${encodeURIComponent(modelId)}/activate`, { method: "POST" });
    setNotice("experiment", `已激活 ${modelId}，启动语音后生效。`);
    await refreshSpeakers();
  } catch (error) { setNotice("experiment", error.message); }
  finally {
    state.experimentBusy = false;
    if (state.speakerData) renderSpeaker(state.speakerData);
  }
}

ui.rollbackLegacyBtn.addEventListener("click", () => activateExperiment("legacy-v1"));

async function applySpeakerThreshold() {
  if (!ui.speakerThresholdInput) return;
  const value = Number(ui.speakerThresholdInput.value);
  if (!Number.isFinite(value)) {
    state.notices.threshold = "请输入有效的阈值数字";
    ui.speakerThresholdHelp.textContent = state.notices.threshold;
    return;
  }
  if (!window.confirm(`确认将生效阈值设为 ${value.toFixed(4)} 吗？改完后需重新启动语音模块。`)) return;
  ui.speakerThresholdBtn.disabled = true;
  try {
    const data = await api("/api/speakers/threshold", {
      method: "POST",
      body: JSON.stringify({ threshold: value }),
    });
    state.notices.threshold = `阈值已更新为 ${Number(data.threshold).toFixed(4)}，请重新启动语音模块后生效。`;
    ui.speakerThresholdHelp.textContent = state.notices.threshold;
    await refreshSpeakers();
  } catch (error) {
    state.notices.threshold = error.message;
    ui.speakerThresholdHelp.textContent = state.notices.threshold;
  } finally {
    if (state.speakerData) renderSpeaker(state.speakerData);
  }
}

if (ui.speakerThresholdBtn) {
  ui.speakerThresholdBtn.addEventListener("click", () => {
    state.notices.threshold = "";
    applySpeakerThreshold();
  });
}

ui.loginForm.addEventListener("submit", async (event) => {
  event.preventDefault(); ui.loginError.textContent = "";
  try {
    const response = await fetch("/api/auth", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token: ui.tokenInput.value }) });
    const data = await responsePayload(response);
    if (!response.ok || data?.ok === false) throw new Error(data?.message || `登录失败（HTTP ${response.status}）`);
    if (!data?.csrf_token) throw new Error("登录响应缺少安全令牌");
    state.csrfToken = data.csrf_token;
    const status = await api("/api/status");
    ui.tokenInput.value = "";
    renderStatus(status);
    showApp();
    connectSocket();
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
  try {
    await restoreSession();
    renderStatus(await api("/api/status"));
    showApp();
    connectSocket();
  } catch (error) { showLogin(error?.message || "请登录后继续"); }
})();
