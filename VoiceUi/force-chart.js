(() => {
  "use strict";
  const root = document.getElementById("forcePanel");
  if (!root) return;
  const find = (name) => root.querySelector(`[data-force="${name}"]`);
  const svg = find("svg"), empty = find("empty"), connection = find("connection");
  const fields = ["requested_n", "target_n", "measured_n"];
  const labels = ["请求目标", "斜坡目标", "反馈力"];
  const classes = ["requested", "target", "measured"];
  const data = { samples: [], commands: [], connected: false, message: "等待力控数据接入" };
  let frozen = null, windowSeconds = 60, pending = false;
  const visible = new Set(fields);
  const numeric = (value) => typeof value === "number" && Number.isFinite(value);
  const numberLabel = (value) => numeric(value) ? value.toFixed(2) : "—";
  const timeLabel = (value) => new Date(value).toLocaleTimeString("zh-CN", { hour12: false });
  const node = (tag, attributes = {}, text = null) => {
    const result = document.createElementNS("http://www.w3.org/2000/svg", tag);
    Object.entries(attributes).forEach(([key, value]) => result.setAttribute(key, value));
    if (text !== null) result.textContent = text;
    return result;
  };
  function append(sample) {
    if (!sample || !numeric(sample.time_ms)) return;
    if (data.samples.at(-1)?.sequence === sample.sequence) return;
    data.samples.push(sample);
    if (data.samples.length > 1800) data.samples.splice(0, data.samples.length - 1800);
  }
  function schedule() {
    if (pending) return;
    pending = true;
    requestAnimationFrame(() => { pending = false; render(); });
  }
  function render() {
    const source = frozen || data;
    const latest = source.samples.at(-1);
    const fresh = source.connected && latest && (frozen || Date.now() - latest.time_ms < 2000);
    connection.textContent = frozen ? "显示已暂停 · 后台继续接收" : fresh ? source.message : "等待力控实时数据 · 当前无新读数";
    connection.classList.toggle("is-live", Boolean(fresh && !frozen));
    fields.forEach((field) => { find(field).textContent = numberLabel(fresh ? latest[field] : null); });
    find("error").textContent = numberLabel(fresh && numeric(latest.measured_n) && numeric(latest.target_n) ? latest.measured_n - latest.target_n : null);
    const end = frozen ? (latest?.time_ms || Date.now()) : Date.now();
    const start = end - windowSeconds * 1000;
    const samples = source.samples.filter((sample) => sample.time_ms >= start && sample.time_ms <= end);
    const hasData = samples.some((sample) => fields.some((field) => numeric(sample[field])));
    empty.hidden = hasData;
    find("measuredStatus").textContent = fresh && numeric(latest.measured_n) ? "反馈力已接入" : "反馈力未接入或已断流";
    const width = 900, height = 220, left = 48, right = 18, top = 18, bottom = 33;
    const x = (time) => left + (time - start) / (end - start) * (width - left - right);
    const values = samples.flatMap((sample) => fields.filter((field) => visible.has(field)).map((field) => sample[field]).filter(numeric));
    const min = Math.min(0, ...values), max = Math.max(10, ...values);
    const step = Math.max(2, Math.pow(10, Math.floor(Math.log10((max - min) / 4))));
    const low = Math.floor(min / step) * step, high = Math.ceil((max + step * .3) / step) * step;
    const y = (value) => height - bottom - (value - low) / (high - low) * (height - top - bottom);
    svg.replaceChildren();
    svg.append(node("title", {}, "按摩力度实时响应，横轴为时间，纵轴为牛顿。虚线为目标，实线为反馈力。"));
    for (let i = 0; i <= 4; i++) {
      const value = low + (high - low) * i / 4;
      svg.append(node("line", { x1: left, x2: width - right, y1: y(value), y2: y(value), class: "force-grid" }));
      svg.append(node("text", { x: left - 8, y: y(value) + 3, "text-anchor": "end", class: "force-axis" }, value.toFixed(1)));
      const time = start + (end - start) * i / 4;
      svg.append(node("text", { x: x(time), y: height - 12, "text-anchor": "middle", class: "force-axis" }, timeLabel(time)));
    }
    svg.append(node("text", { x: 4, y: 11, class: "force-axis" }, "力 / N"));
    svg.append(node("text", { x: width - right, y: height, class: "force-axis", "text-anchor": "end" }, "时间"));
    fields.forEach((field, index) => {
      if (!visible.has(field)) return;
      let path = "", previous = null;
      // 空点或超过 1.5 秒的采样间隔断线，禁止补齐或插值成实测响应。
      samples.forEach((sample) => {
        if (!numeric(sample[field])) { previous = null; return; }
        const px = x(sample.time_ms), py = y(sample[field]);
        if (!previous || sample.time_ms - previous.time_ms > 1500) path += `M${px},${py}`;
        else path += index === 0 ? `H${px}V${py}` : `L${px},${py}`;
        previous = sample;

      });
      svg.append(node("path", { d: path, class: `force-series force-series--${classes[index]}` }));
      if (previous) svg.append(node("circle", { cx: x(previous.time_ms), cy: y(previous[field]), r: 2, fill: ["#b48845", "#5c85a1", "#56794c"][index] }));
    });
    const commands = source.commands.filter((command) => command.time_ms >= start && command.time_ms <= end);
    commands.forEach((command) => {
      const line = node("line", { x1: x(command.time_ms), x2: x(command.time_ms), y1: top, y2: height - bottom, class: "force-marker" });
      line.append(node("title", {}, `${timeLabel(command.time_ms)} ${command.text} · ${command.action === "force_accepted" ? "已确认" : "未确认"}`));
      svg.append(line);
    });
    const command = source.commands.at(-1);
    find("command").textContent = command ? `最近指令 ${timeLabel(command.time_ms)} · ${command.text} · ${command.action === "force_accepted" ? "已确认" : command.action === "force_status" ? "已查询" : "未确认"}` : "等待语音调力指令 · 指令时刻将显示为竖线";
  }
  find("window").addEventListener("change", (event) => { windowSeconds = Number(event.target.value); schedule(); });
  find("pause").addEventListener("click", () => {
    frozen = frozen ? null : { ...data, samples: data.samples.slice(), commands: data.commands.slice() };
    find("pause").textContent = frozen ? "继续显示" : "暂停显示";
    find("pause").setAttribute("aria-pressed", String(Boolean(frozen)));
    schedule();
  });
  find("clear").addEventListener("click", () => { data.samples = []; data.commands = []; frozen = null; find("pause").textContent = "暂停显示"; find("pause").setAttribute("aria-pressed", "false"); schedule(); });
  root.querySelectorAll("[data-series]").forEach((checkbox) => checkbox.addEventListener("change", () => {
    if (checkbox.checked) visible.add(checkbox.dataset.series); else visible.delete(checkbox.dataset.series);
    schedule();
  }));
  find("export").addEventListener("click", () => {
    const source = frozen || data;
    const rows = ["time_utc,requested_N,target_N,measured_N", ...source.samples.map((sample) => [new Date(sample.time_ms).toISOString(), ...fields.map((field) => numeric(sample[field]) ? sample[field] : "")].join(","))];
    const url = URL.createObjectURL(new Blob(["\uFEFF" + rows.join("\n")], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a"); link.href = url; link.download = "force-response.csv"; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  find("plot").addEventListener("pointermove", (event) => {
    const samples = (frozen || data).samples;
    if (!samples.length) return;
    const bounds = svg.getBoundingClientRect();
    const end = frozen ? samples.at(-1).time_ms : Date.now();
    const at = end - windowSeconds * 1000 + Math.max(0, Math.min(1, ((event.clientX - bounds.left) / bounds.width * 900 - 48) / 834)) * windowSeconds * 1000;
    const sample = samples.reduce((best, item) => Math.abs(item.time_ms - at) < Math.abs(best.time_ms - at) ? item : best);
    find("hover").hidden = false;
    find("hover").textContent = `${timeLabel(sample.time_ms)}\n${fields.map((field, i) => `${labels[i]} ${numberLabel(sample[field])} N`).join(" · ")}`;
  });
  find("plot").addEventListener("pointerleave", () => { find("hover").hidden = true; });
  window.ForceChart = {
    snapshot(payload = {}) {
      Object.assign(data, { samples: (payload.samples || []).slice(-1800), commands: (payload.commands || []).slice(-100), connected: Boolean(payload.connected), message: payload.message || "等待力控数据接入" });
      schedule();
    },
    event(type, payload = {}) {
      if (type === "force.command") {
        data.commands.push({ ...payload, time_ms: payload.time_ms || Date.now() });
        data.commands = data.commands.slice(-100);
      } else {
        data.connected = Boolean(payload.connected); data.message = payload.message || "";
        append(payload.sample);
      }
      schedule();
    },
    disconnected() { data.connected = false; schedule(); }
  };
  setInterval(schedule, 500);
  schedule();
})();
