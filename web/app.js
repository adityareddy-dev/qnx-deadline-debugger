"use strict";

let report;
let selectedRun = 0;
let selectedJob = 0;
const $ = id => document.getElementById(id);
const ms = ns => (ns / 1e6).toFixed(2);
const node = (tag, text, className) => {
  const element = document.createElement(tag);
  if (text !== undefined) element.textContent = text;
  if (className) element.className = className;
  return element;
};
const controlJobs = run => run.jobs.filter(job => job.worker === "control");
const current = () => {
  const run = report.runs[selectedRun];
  return [run, controlJobs(run)[selectedJob]];
};

function metrics() {
  const [fault, fixed] = report.runs;
  const items = [
    ["FAULT · DEADLINES MISSED", `${fault.summary.misses} / ${fault.summary.jobs}`, "Background priority 30", "bad"],
    ["FIXED · DEADLINES MISSED", `${fixed.summary.misses} / ${fixed.summary.jobs}`, "Background priority 10", "good"],
    ["FAULT · WORST RESPONSE", ms(fault.summary.max_response_ns), "20 ms deadline", "bad", "ms"],
    ["FIXED · WORST RESPONSE", ms(fixed.summary.max_response_ns), "Same control work and period", "good", "ms"]
  ];
  $("metrics").replaceChildren(...items.map(([label, value, note, color, unit]) => {
    const card = node("div", undefined, "metric");
    const number = node("div", value, `metric-value ${color}`);
    if (unit) number.append(node("small", unit));
    card.append(node("div", label, "metric-label"), number, node("div", note, "metric-note"));
    return card;
  }));
}

function showSource(line) {
  const [run] = current();
  const start = Math.max(1, line - 2);
  const end = Math.min(run.raw.length, line + 3);
  $("source-location").textContent = `${run.source} · line ${line} · SHA-256 ${run.sha256.slice(0, 16)}…`;
  $("event-source").replaceChildren();
  for (let n = start; n <= end; n++) {
    const row = node("span", `${String(n).padStart(5)}  ${run.raw[n - 1]}\n`, n === line ? "selected" : undefined);
    $("event-source").append(row);
  }
  if (run.decoded_markers[String(line)]) {
    $("event-source").append(node("span", `\nDecoded user payload:\n${run.decoded_markers[String(line)]}\n`));
  }
  $("event-source").scrollLeft = 0;
  $("raw-link").href = `/sources/${run.config.mode}.trace`;
}

function explanation(run, job) {
  const wait = job.dispatch_wait_ns;
  const background = job.background_during_wait_ns;
  const share = wait > 0 ? (100 * background / wait).toFixed(1) : "0.0";
  const outcome = job.late_ns > 0
    ? `finished ${ms(job.late_ns)} ms late`
    : `finished ${ms(job.deadline_ns - job.finish_ns)} ms before its deadline`;
  const priority = run.workers.background.priority;
  return `Control job ${job.job} ${outcome}. After becoming ready, it waited ${ms(wait)} ms for its first CPU dispatch. During that wait, background occupied the CPU for ${ms(background)} ms (${share}%). Its FIFO priority was ${priority}, ${priority > 20 ? "above" : "below"} control’s priority of 20. The remaining wait includes other guest threads and scheduler or interrupt transitions. Response time was ${ms(job.response_ns)} ms against a ${ms(run.config.deadline_ns)} ms deadline.`;
}

function evidence(run, job) {
  $("explanation-title").textContent = job.late_ns > 0 ? "Ready, but outranked." : "Control preempts the background task.";
  $("explanation").textContent = explanation(run, job);
  const facts = [
    ["Ready → first CPU dispatch", `${ms(job.dispatch_wait_ns)} ms`],
    ["Background running during that wait", `${ms(job.background_during_wait_ns)} ms`],
    ["Release → observed completion", `${ms(job.response_ns)} ms`]
  ];
  $("facts").replaceChildren(...facts.map(([label, value]) => {
    const row = node("div", undefined, "fact");
    row.append(node("span", label), node("strong", value));
    return row;
  }));
  $("evidence-links").replaceChildren(...Object.entries(job.evidence).map(([label, line]) => {
    const button = node("button", `${label} · L${line}`);
    button.addEventListener("click", () => showSource(line));
    return button;
  }));
  $("clock-note").textContent = `Clock alignment: ±${(run.clock.uncertainty_ns / 1000).toFixed(1)} µs from a bracketed ClockCycles / CLOCK_MONOTONIC sample (line ${run.clock.line}). Completion uses the workload’s observed monotonic time. The largest sample-to-marker delay was ${(run.clock.max_marker_delay_ns / 1000).toFixed(1)} µs.`;
  showSource(job.evidence.ready);
}

function svgNode(tag, attrs = {}, text) {
  const element = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [key, value] of Object.entries(attrs)) element.setAttribute(key, value);
  if (text !== undefined) element.textContent = text;
  return element;
}

function timeline(run, job) {
  const svg = $("timeline");
  svg.replaceChildren();
  const left = 152;
  const right = 1075;
  const start = -7;
  const end = Number($("zoom").value);
  const x = time => left + ((time - job.release_ns) / 1e6 - start) / (end - start) * (right - left);
  const absolute = relative => job.release_ns + relative * 1e6;
  const labels = ["Control · ready", "Control · running", "Background · running", "Other guest threads"];
  const y = [80, 124, 168, 212];
  const increment = end > 45 ? 10 : end > 12 ? 5 : 2;
  for (let tick = -5; tick <= end; tick += increment) {
    const xpos = x(absolute(tick));
    svg.append(svgNode("line", {x1: xpos, x2: xpos, y1: 60, y2: 244, class: "grid"}));
    svg.append(svgNode("text", {x: xpos, y: 54, "text-anchor": "middle"}, `${tick > 0 ? "+" : ""}${tick} ms`));
  }
  labels.forEach((label, i) => {
    svg.append(svgNode("text", {x: left - 14, y: y[i] + 18, "text-anchor": "end", class: "lane-label"}, label));
    svg.append(svgNode("rect", {x: left, y: y[i], width: right - left, height: 28, rx: 3, fill: "#f3f6f2"}));
  });
  function span(begin, finish, lane, color, line, label) {
    const clippedStart = Math.max(left, x(begin));
    const clippedEnd = Math.min(right, x(finish));
    if (clippedEnd <= clippedStart) return;
    const rect = svgNode("rect", {x: clippedStart, y: y[lane], width: Math.max(.8, clippedEnd - clippedStart), height: 28, rx: 2, fill: color, class: "span", tabindex: 0, role: "button", "aria-label": `${label}, source line ${line}`});
    rect.append(svgNode("title", {}, `${label}\n${ms(begin - job.release_ns)} → ${ms(finish - job.release_ns)} ms\nSource line ${line}`));
    rect.addEventListener("click", () => showSource(line));
    rect.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); showSource(line); }
    });
    svg.append(rect);
  }
  span(job.ready_ns, job.running_ns, 0, "#e4b651", job.evidence.ready, `Control ready, waiting ${ms(job.dispatch_wait_ns)} ms`);
  for (const interval of run.schedule) {
    if (interval.end_ns < absolute(start) || interval.start_ns > absolute(end)) continue;
    const ours = interval.pid === run.config.pid;
    const control = ours && interval.tid === run.workers.control.tid;
    const background = ours && interval.tid === run.workers.background.tid;
    const lane = control ? 1 : background ? 2 : 3;
    const label = control ? "Control running" : background ? "Background running" : `Guest pid ${interval.pid}, tid ${interval.tid}, priority ${interval.priority}`;
    span(interval.start_ns, interval.end_ns, lane, control ? "#217e6b" : background ? "#6486a0" : "#cbd5d4", interval.line, label);
  }
  const releaseX = x(job.release_ns);
  svg.append(svgNode("line", {x1: releaseX, x2: releaseX, y1: 62, y2: 245, stroke: "#526b60", "stroke-dasharray": "2 3"}));
  svg.append(svgNode("text", {x: releaseX, y: 27, "text-anchor": "middle"}, "release"));
  const deadlineX = x(job.deadline_ns);
  if (deadlineX <= right) {
    svg.append(svgNode("line", {x1: deadlineX, x2: deadlineX, y1: 34, y2: 245, class: "deadline"}));
    svg.append(svgNode("text", {x: deadlineX + 6, y: 27, fill: "#b45539"}, "deadline +20 ms"));
  }
  const finishX = x(job.finish_ns);
  if (finishX <= right) {
    svg.append(svgNode("circle", {cx: finishX, cy: y[1] + 14, r: 4, fill: job.late_ns > 0 ? "#b45539" : "#217e6b"}));
    svg.append(svgNode("text", {x: finishX + 8, y: y[1] - 9}, `finish +${ms(job.finish_ns - job.release_ns)} ms`));
  }
  svg.append(svgNode("text", {x: right, y: 265, "text-anchor": "end"}, "QEMU guest monotonic time"));
}

function table() {
  const [fault, fixed] = report.runs.map(controlJobs);
  $("jobs-table").replaceChildren(...fault.map((job, index) => {
    const after = fixed[index];
    const row = node("tr", undefined, selectedJob === index ? "selected" : undefined);
    const first = node("td");
    const button = node("button", String(index).padStart(2, "0"));
    first.append(button);
    row.append(first, node("td", `${ms(job.response_ns)} ms`), node("td", `${ms(job.late_ns)} ms`, job.late_ns ? "bad" : "good"), node("td", `${ms(after.response_ns)} ms`), node("td", `${ms(after.late_ns)} ms`, after.late_ns ? "bad" : "good"));
    const result = node("td");
    result.append(node("span", after.late_ns ? "MISSED" : "WITHIN DEADLINE", "result-tag"));
    row.append(result);
    row.addEventListener("click", () => { selectedJob = index; render(); });
    return row;
  }));
}

function exportIncident() {
  const [run, job] = current();
  const other = controlJobs(report.runs[1 - selectedRun])[selectedJob];
  const lines = ["QNX deadline debugger", `Capture: ${run.config.mode}, control job ${job.job}`, "", explanation(run, job), "", report.timing, "", `The other run: ${ms(other.response_ns)} ms response, ${ms(other.late_ns)} ms late.`, `Control priority: ${run.workers.control.priority}. Background priority: ${run.workers.background.priority}.`, `Clock alignment uncertainty: ±${run.clock.uncertainty_ns} ns.`, "", `Source: ${run.source}`, `Text export SHA-256: ${run.sha256}`, "", "Underlying events:"];
  for (const [label, line] of Object.entries(job.evidence)) {
    lines.push(`\n${label}, line ${line}:\n${run.raw[line - 1]}`);
    if (run.decoded_markers[String(line)]) lines.push(`Decoded user payload: ${run.decoded_markers[String(line)]}`);
  }
  lines.push("\nBackground running intervals overlapping the initial dispatch wait:");
  for (const interval of run.schedule) {
    if (interval.pid !== run.config.pid || interval.tid !== run.workers.background.tid) continue;
    const begin = Math.max(interval.start_ns, job.ready_ns);
    const end = Math.min(interval.end_ns, job.running_ns);
    if (end <= begin) continue;
    lines.push(`\n${end - begin} ns within the wait, lines ${interval.line} to ${interval.end_line}:\n${run.raw[interval.line - 1]}\n${run.raw[interval.end_line - 1]}`);
  }
  const url = URL.createObjectURL(new Blob([lines.join("\n") + "\n"], {type: "text/plain;charset=utf-8"}));
  const link = node("a");
  link.href = url;
  link.download = `qnx-${run.config.mode}-job-${job.job}.txt`;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function render() {
  const [run, job] = current();
  for (const [index, mode] of ["fault", "fixed"].entries()) {
    $(`${mode}-tab`).classList.toggle("active", selectedRun === index);
    $(`${mode}-tab`).setAttribute("aria-pressed", String(selectedRun === index));
  }
  $("job").value = String(selectedJob);
  $("previous").disabled = selectedJob === 0;
  $("next").disabled = selectedJob === controlJobs(run).length - 1;
  $("job-status").textContent = job.late_ns ? `MISSED BY ${ms(job.late_ns)} ms` : `${ms(job.deadline_ns - job.finish_ns)} ms TO SPARE`;
  $("job-status").className = job.late_ns ? "bad" : "good";
  timeline(run, job);
  evidence(run, job);
  table();
}

async function start() {
  const response = await fetch("/report.json");
  if (!response.ok) throw new Error(`Report request failed (${response.status})`);
  report = await response.json();
  metrics();
  $("job").replaceChildren(...controlJobs(report.runs[0]).map((job, index) => {
    const option = node("option", `${String(job.job).padStart(2, "0")} of ${report.runs[0].summary.jobs - 1}`);
    option.value = String(index);
    return option;
  }));
  $("fault-tab").addEventListener("click", () => { selectedRun = 0; render(); });
  $("fixed-tab").addEventListener("click", () => { selectedRun = 1; render(); });
  $("job").addEventListener("change", event => { selectedJob = Number(event.target.value); render(); });
  $("zoom").addEventListener("change", render);
  $("previous").addEventListener("click", () => { selectedJob--; render(); });
  $("next").addEventListener("click", () => { selectedJob++; render(); });
  $("export").addEventListener("click", exportIncident);
  $("integrity").textContent = report.runs.map(run => `${run.source}: ${run.sha256}`).join("\n");
  render();
}

start().catch(error => {
  $("error").hidden = false;
  $("error").textContent = `Could not load the captures. ${error.message}`;
});
