"""QNX 8 traceprinter export reader. Times are guest monotonic nanoseconds."""

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
import statistics


class CaptureError(ValueError):
    pass


@dataclass
class Event:
    line: int
    cycles: int
    cpu: int
    group: str
    kind: str
    text: str
    fields: dict
    marker: str | None = None


EVENT = re.compile(r"^c:([0-9a-fA-F]+) CPU:(\d+) (\w+):([^\s,]+)(.*)$")
FIELDS = re.compile(r"\b(pid|tid|priority|policy):(-?\d+)")
WORDS = re.compile(r"\bd(\d+):0x([0-9a-fA-F]{8})")


def require(condition, message):
    if not condition:
        raise CaptureError(message)


def user_string(text, endian):
    words = WORDS.findall(text)
    if words:
        require([int(n) for n, _ in words] == list(range(len(words))),
                "User event has missing data words")
        data = b"".join(int(word, 16).to_bytes(4, endian) for _, word in words)
        data = data.split(b"\0", 1)[0]
        return data.decode("ascii", errors="replace")
    match = re.search(r'STR:"([^"]*)"', text)
    return match[1] if match else ""


def read_export(path):
    path = Path(path)
    raw = path.read_bytes()
    lines = raw.decode("utf-8").splitlines()
    headers = {}
    for line in lines:
        match = re.match(r"\s*(TRACE_\w+)::\s*(.*)", line)
        if match:
            headers[match[1]] = match[2].strip()
    require(headers.get("TRACE_SYS_RELEASE") == "8.0.0", "Expected QNX 8.0.0")
    require(headers.get("TRACE_CPU_NUM") == "1", "This workload requires one guest CPU")
    require(headers.get("TRACE_CYCLES_PER_SEC", "").isdigit(), "Missing cycle frequency")
    require(int(headers["TRACE_CYCLES_PER_SEC"]) > 0, "Invalid cycle frequency")
    require(headers.get("TRACE_LITTLE_ENDIAN") in ("TRUE", "FALSE"), "Missing byte order")
    endian = "little" if headers["TRACE_LITTLE_ENDIAN"] == "TRUE" else "big"
    events = []
    for number, line in enumerate(lines, 1):
        match = EVENT.match(line)
        if not match:
            require(not line.startswith("c:"), f"Invalid event at line {number}")
            continue
        cycle, cpu, group, kind, tail = match.groups()
        event = Event(number, int(cycle, 16), int(cpu), group, kind, line,
                      {key: int(value) for key, value in FIELDS.findall(tail)})
        require(event.cpu == 0, f"Unexpected CPU at line {number}")
        if group == "USREVENT" and kind == "EVENT:100":
            value = user_string(tail, endian)
            if value.startswith("DD1 "):
                event.marker = value
        events.append(event)
    require(events, "No events found. Export with -p 'c:%c CPU:%C %Z:%z'")
    require(all(a.cycles <= b.cycles for a, b in zip(events, events[1:])),
            "Events are out of time order")
    sequences = [int(m[1]) for e in events if e.group == "CONTROL"
                 if (m := re.search(r"sequence = (\d+)", e.text))]
    require(sequences and sequences[0] == 1, "Missing initial trace buffer")
    require(all(b == a + 1 for a, b in zip(sequences, sequences[1:])),
            "Trace buffer sequence has a gap")
    return path, lines, headers, events, hashlib.sha256(raw).hexdigest()


def marker_fields(event):
    tokens = event.marker.split()[1:]
    kind = tokens.pop(0) if "=" not in tokens[0] else "worker"
    values = {}
    for token in tokens:
        require("=" in token, f"Malformed workload marker at line {event.line}")
        key, value = token.split("=", 1)
        require(key not in values, f"Duplicate marker field at line {event.line}")
        values[key] = int(value) if value.isdigit() else value
    return kind, values


def analyze(path):
    path, lines, headers, events, digest = read_export(path)
    markers = [(event, *marker_fields(event)) for event in events if event.marker]
    configs = [(e, f) for e, k, f in markers if k == "config"]
    syncs = [(e, f) for e, k, f in markers if k == "sync"]
    require(len(configs) == len(syncs) == 1, "Expected one workload and one clock reference")
    config_event, config = configs[0]
    sync_event, sync = syncs[0]
    require(config.get("mode") in ("fault", "fixed"), "Unknown workload mode")
    require(config.get("cpus") == 1, "Workload CPU setting differs from trace")
    require(all(isinstance(config.get(k), int) and config[k] > 0
                for k in ("jobs", "pid", "epoch_ns", "period_ns", "deadline_ns")),
            "Missing or invalid workload configuration")
    require(config["jobs"] <= 10000, "Workload job count too large")
    require(all(isinstance(sync.get(k), int) for k in ("now_ns", "cycles_before", "cycles_after")),
            "Incomplete clock reference")
    require(sync["cycles_before"] <= sync["cycles_after"] <= sync_event.cycles,
            "Invalid clock reference order")
    frequency = int(headers["TRACE_CYCLES_PER_SEC"])
    anchor_cycle = (sync["cycles_before"] + sync["cycles_after"]) / 2
    anchor_ns = sync["now_ns"]

    def ns(cycles):
        return round(anchor_ns + (cycles - anchor_cycle) * 1e9 / frequency)

    uncertainty = (sync["cycles_after"] - sync["cycles_before"]) * 1e9 / frequency / 2
    require(uncertainty < 1_000_000, "Clock reference spans more than 2 ms. Recapture.")
    workers = {}
    for event, kind, fields in markers:
        if kind != "worker":
            continue
        name = fields.get("worker")
        require(name in ("control", "background") and name not in workers, "Invalid worker marker")
        require(fields.get("pid") == config["pid"], "Worker process differs from configuration")
        require(all(isinstance(fields.get(k), int) for k in ("tid", "priority", "offset_ns", "work_ns")),
                "Incomplete worker configuration")
        workers[name] = {**fields, "line": event.line}
    require(set(workers) == {"control", "background"}, "Missing worker identity")
    require(workers["control"]["tid"] != workers["background"]["tid"], "Worker identities overlap")
    jobs = {}
    for event, kind, fields in markers:
        if kind not in ("start", "finish"):
            continue
        name, number = fields.get("worker"), fields.get("job")
        require(name in workers and isinstance(number, int) and 0 <= number < config["jobs"],
                f"Invalid job marker at line {event.line}")
        require(isinstance(fields.get("now_ns"), int), "Missing observed timestamp")
        key = name, number
        job = jobs.setdefault(key, {})
        require(kind not in job, "Duplicate job marker")
        job[kind] = (event, fields)
    require(len(jobs) == 2 * config["jobs"], "Capture has missing jobs")
    complete = [e for e, k, _ in markers if k == "complete"]
    require(len(complete) == 1, "Capture has no unique completion marker")
    require(complete[0].cycles > max(e.cycles for e, k, _ in markers if k == "finish"),
            "Completion precedes finished jobs")

    thread_events = [e for e in events if e.group == "THREAD"]
    schedule = []
    running = None
    for event in thread_events:
        if event.kind in ("THCREATE", "THDESTROY"):
            continue
        identity = event.fields.get("pid"), event.fields.get("tid")
        if running and (event.kind == "THRUNNING" or identity ==
                        (running.fields.get("pid"), running.fields.get("tid"))):
            if event.cycles > running.cycles:
                schedule.append({"start_ns": ns(running.cycles), "end_ns": ns(event.cycles),
                                 "line": running.line, "end_line": event.line, **running.fields})
            running = None
        if event.kind == "THRUNNING":
            require(all(k in event.fields for k in ("pid", "tid", "priority", "policy")),
                    "Missing wide thread fields. Capture with tracelogger -w")
            running = event
    result_jobs = []
    marker_delays = []
    for name in workers:
        worker = workers[name]
        state_events = [e for e in thread_events if e.fields.get("pid") == config["pid"]
                        and e.fields.get("tid") == worker["tid"]]
        for number in range(config["jobs"]):
            job = jobs[name, number]
            require(set(job) == {"start", "finish"}, f"Incomplete {name} job {number}")
            start, start_fields = job["start"]
            finish, finish_fields = job["finish"]
            release = config["epoch_ns"] + number * config["period_ns"] + worker["offset_ns"]
            deadline = release + config["deadline_ns"]
            require(start_fields.get("release_ns") == release and
                    start_fields.get("deadline_ns") == finish_fields.get("deadline_ns") == deadline,
                    "Job deadlines differ from configuration")
            start_ns, finish_ns = start_fields["now_ns"], finish_fields["now_ns"]
            require(release <= start_ns <= finish_ns and start.cycles < finish.cycles,
                    "Invalid job time order")
            marker_delays += [ns(start.cycles) - start_ns, ns(finish.cycles) - finish_ns]
            sleeps = [e for e in state_events if e.kind == "THNANOSLEEP" and e.cycles < start.cycles]
            require(sleeps, f"Missing sleep before {name} job {number}")
            sleep = sleeps[-1]
            ready = next((e for e in state_events if sleep.cycles < e.cycles <= start.cycles
                          and e.kind == "THREADY"), None)
            require(ready is not None, f"Missing ready event for {name} job {number}")
            first_run = next((e for e in state_events if ready.cycles <= e.cycles <= start.cycles
                              and e.kind == "THRUNNING"), None)
            require(first_run is not None, f"Missing running event for {name} job {number}")
            require(ready.fields.get("priority") == first_run.fields.get("priority") == worker["priority"]
                    and first_run.fields.get("policy") == 1, "Kernel priority or FIFO policy differs")
            require(ns(ready.cycles) >= release - uncertainty - 100_000,
                    "Clock reference and release disagree. Recapture.")
            spans = [s for s in schedule if s["end_ns"] > ns(ready.cycles)
                     and s["start_ns"] < ns(finish.cycles)]
            wait_start, wait_end = ns(ready.cycles), ns(first_run.cycles)
            background_ns = sum(max(0, min(s["end_ns"], wait_end) - max(s["start_ns"], wait_start))
                                for s in spans if s["pid"] == config["pid"]
                                and s["tid"] == workers["background"]["tid"])
            result_jobs.append({"worker": name, "job": number, "release_ns": release,
                                "deadline_ns": deadline, "start_ns": start_ns, "finish_ns": finish_ns,
                                "ready_ns": wait_start, "running_ns": wait_end,
                                "response_ns": finish_ns - release,
                                "dispatch_wait_ns": wait_end - wait_start,
                                "background_during_wait_ns": background_ns,
                                "late_ns": max(0, finish_ns - deadline),
                                "evidence": {"config": config_event.line, "clock": sync_event.line,
                                             "worker": worker["line"],
                                             "background": workers["background"]["line"], "ready": ready.line,
                                             "running": first_run.line, "start": start.line,
                                             "finish": finish.line}})
    require(min(marker_delays) >= -uncertainty - 100_000,
            "Clock reference disagrees with marker times")
    require(max(marker_delays) < 5_000_000, "Clock reference or marker latency exceeds 5 ms. Recapture.")
    control = [job for job in result_jobs if job["worker"] == "control"]
    return {"source": path.name, "sha256": digest, "headers": headers,
            "config": config, "workers": workers,
            "clock": {"uncertainty_ns": round(uncertainty), "line": sync_event.line,
                      "max_marker_delay_ns": max(marker_delays)},
            "summary": {"jobs": len(control), "misses": sum(job["late_ns"] > 0 for job in control),
                        "max_response_ns": max(job["response_ns"] for job in control),
                        "mean_response_ns": round(statistics.mean(job["response_ns"] for job in control)),
                        "max_dispatch_wait_ns": max(job["dispatch_wait_ns"] for job in control)},
            "jobs": result_jobs, "schedule": schedule, "raw": lines,
            "decoded_markers": {str(e.line): e.marker for e, _, _ in markers}}


def compare(fault, fixed):
    require(fault["config"]["mode"] == "fault" and fixed["config"]["mode"] == "fixed",
            "Comparison requires fault then fixed captures")
    for key in ("jobs", "period_ns", "deadline_ns", "cpus"):
        require(fault["config"][key] == fixed["config"][key], f"Comparison differs in {key}")
    for name in ("control", "background"):
        for key in ("offset_ns", "work_ns"):
            require(fault["workers"][name][key] == fixed["workers"][name][key],
                    f"Comparison differs in {name} {key}")
    require(fault["workers"]["control"]["priority"] == fixed["workers"]["control"]["priority"] == 20
            and fault["workers"]["background"]["priority"] == 30
            and fixed["workers"]["background"]["priority"] == 10, "Unexpected priority change")
    for key in ("TRACE_SYS_RELEASE", "TRACE_SYS_VERSION", "TRACE_MACHINE", "TRACE_CYCLES_PER_SEC"):
        require(fault["headers"][key] == fixed["headers"][key], f"Guest differs in {key}")
    return {"version": 1, "timing": "QEMU guest timings. No hardware real-time guarantee.",
            "runs": [fault, fixed]}
