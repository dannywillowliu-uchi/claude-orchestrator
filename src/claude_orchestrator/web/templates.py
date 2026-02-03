"""HTML/CSS/JS for the web dashboard - single page, no build step."""

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Claude Orchestrator Dashboard</title>
<style>
:root {
	--bg: #0d1117;
	--bg-card: #161b22;
	--bg-hover: #1c2128;
	--border: #30363d;
	--text: #c9d1d9;
	--text-dim: #8b949e;
	--text-bright: #f0f6fc;
	--accent: #58a6ff;
	--green: #3fb950;
	--red: #f85149;
	--yellow: #d29922;
	--mono: "SF Mono", "Cascadia Code", "Fira Code", Consolas, monospace;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
	background: var(--bg);
	color: var(--text);
	font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
	line-height: 1.5;
}
.header {
	display: flex;
	align-items: center;
	justify-content: space-between;
	padding: 16px 24px;
	border-bottom: 1px solid var(--border);
	background: var(--bg-card);
}
.header h1 {
	font-size: 18px;
	color: var(--text-bright);
	font-weight: 600;
}
.sse-status {
	display: flex;
	align-items: center;
	gap: 6px;
	font-size: 13px;
	color: var(--text-dim);
}
.sse-dot {
	width: 8px;
	height: 8px;
	border-radius: 50%;
	background: var(--red);
	transition: background 0.3s;
}
.sse-dot.connected { background: var(--green); }
.container { padding: 24px; max-width: 1400px; margin: 0 auto; }
.summary-cards {
	display: grid;
	grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
	gap: 16px;
	margin-bottom: 24px;
}
.card {
	background: var(--bg-card);
	border: 1px solid var(--border);
	border-radius: 8px;
	padding: 16px;
}
.card-label {
	font-size: 12px;
	text-transform: uppercase;
	letter-spacing: 0.5px;
	color: var(--text-dim);
	margin-bottom: 4px;
}
.card-value {
	font-size: 28px;
	font-weight: 600;
	color: var(--text-bright);
	font-family: var(--mono);
}
.panels {
	display: grid;
	grid-template-columns: 1fr 300px;
	gap: 16px;
}
@media (max-width: 900px) {
	.panels { grid-template-columns: 1fr; }
}
.panel {
	background: var(--bg-card);
	border: 1px solid var(--border);
	border-radius: 8px;
	overflow: hidden;
}
.panel-header {
	padding: 12px 16px;
	border-bottom: 1px solid var(--border);
	font-size: 14px;
	font-weight: 600;
	color: var(--text-bright);
	display: flex;
	justify-content: space-between;
	align-items: center;
}
.panel-body { max-height: 600px; overflow-y: auto; }
/* Tool Stats Table */
table {
	width: 100%;
	border-collapse: collapse;
	font-size: 13px;
	font-family: var(--mono);
}
th {
	text-align: left;
	padding: 8px 12px;
	border-bottom: 1px solid var(--border);
	color: var(--text-dim);
	font-weight: 500;
	font-size: 11px;
	text-transform: uppercase;
	letter-spacing: 0.5px;
	position: sticky;
	top: 0;
	background: var(--bg-card);
}
td {
	padding: 6px 12px;
	border-bottom: 1px solid var(--border);
}
tr:hover td { background: var(--bg-hover); }
.num { text-align: right; }
.rate-good { color: var(--green); }
.rate-warn { color: var(--yellow); }
.rate-bad { color: var(--red); }
/* Timeline */
.timeline-item {
	padding: 8px 16px;
	border-bottom: 1px solid var(--border);
	font-size: 13px;
	display: grid;
	grid-template-columns: 1fr auto;
	gap: 8px;
	animation: none;
}
.timeline-item.new {
	animation: flash 0.6s ease-out;
}
@keyframes flash {
	0% { background: #1f3a20; }
	100% { background: transparent; }
}
.timeline-tool {
	font-family: var(--mono);
	color: var(--accent);
	font-weight: 500;
}
.timeline-meta {
	color: var(--text-dim);
	font-size: 12px;
}
.timeline-duration {
	font-family: var(--mono);
	color: var(--text-dim);
	font-size: 12px;
	text-align: right;
}
.timeline-status {
	display: inline-block;
	width: 6px;
	height: 6px;
	border-radius: 50%;
	margin-right: 6px;
}
.timeline-status.ok { background: var(--green); }
.timeline-status.fail { background: var(--red); }
/* Sessions */
.session-item {
	padding: 10px 16px;
	border-bottom: 1px solid var(--border);
	cursor: pointer;
	font-size: 13px;
}
.session-item:hover { background: var(--bg-hover); }
.session-item.active { border-left: 3px solid var(--accent); }
.session-id {
	font-family: var(--mono);
	color: var(--accent);
	font-size: 12px;
}
.session-meta {
	color: var(--text-dim);
	font-size: 12px;
}
.clear-filter {
	font-size: 12px;
	color: var(--accent);
	cursor: pointer;
	display: none;
}
.clear-filter.visible { display: inline; }
/* Tool Stats section below panels */
.tool-stats-section {
	margin-top: 16px;
}
/* Unused tools */
.unused-tools-grid {
	display: flex;
	flex-wrap: wrap;
	gap: 8px;
	padding: 12px 16px;
}
.unused-chip {
	font-family: var(--mono);
	font-size: 12px;
	padding: 4px 10px;
	border-radius: 4px;
	background: var(--bg);
	border: 1px solid var(--border);
	color: var(--text-dim);
}
</style>
</head>
<body>
<div class="header">
	<h1>Claude Orchestrator</h1>
	<div class="sse-status">
		<div class="sse-dot" id="sseDot"></div>
		<span id="sseLabel">Connecting...</span>
	</div>
</div>
<div class="container">
	<div class="summary-cards">
		<div class="card">
			<div class="card-label">Total Calls</div>
			<div class="card-value" id="totalCalls">-</div>
		</div>
		<div class="card">
			<div class="card-label">Tools Used</div>
			<div class="card-value" id="toolsUsed">-</div>
		</div>
		<div class="card">
			<div class="card-label">Sessions</div>
			<div class="card-value" id="sessionsCount">-</div>
		</div>
		<div class="card">
			<div class="card-label">Success Rate</div>
			<div class="card-value" id="successRate">-</div>
		</div>
	</div>

	<div class="panels">
		<div>
			<div class="panel" style="margin-bottom:16px">
				<div class="panel-header">
					<span>Live Timeline</span>
					<span class="clear-filter" id="clearFilter" onclick="clearSessionFilter()">Clear filter</span>
				</div>
				<div class="panel-body" id="timeline"></div>
			</div>
			<div class="panel tool-stats-section">
				<div class="panel-header">Tool Stats</div>
				<div class="panel-body" id="toolStats"></div>
			</div>
		</div>
		<div class="panel">
			<div class="panel-header">Sessions</div>
			<div class="panel-body" id="sessions"></div>
		</div>
	</div>
	<div class="panel unused-tools-section" style="margin-top:16px" id="unusedPanel">
		<div class="panel-header">
			<span>Unused Tools</span>
			<span class="card-label" id="unusedCount" style="margin:0"></span>
		</div>
		<div class="panel-body" id="unusedTools" style="max-height:300px"></div>
	</div>
</div>

<script>
let activeSession = null;
let lastCallId = 0;
let evtSource = null;

function rateClass(rate) {
	if (rate >= 90) return "rate-good";
	if (rate >= 70) return "rate-warn";
	return "rate-bad";
}

function fmtDuration(sec) {
	if (sec < 0.01) return "<10ms";
	if (sec < 1) return (sec * 1000).toFixed(0) + "ms";
	return sec.toFixed(2) + "s";
}

function fmtTime(iso) {
	if (!iso) return "-";
	const d = new Date(iso);
	return d.toLocaleTimeString([], {hour:"2-digit", minute:"2-digit", second:"2-digit"});
}

function truncate(s, n) {
	if (!s) return "";
	return s.length > n ? s.slice(0, n) + "..." : s;
}

async function fetchJson(url) {
	const r = await fetch(url);
	return r.json();
}

async function loadStats() {
	const stats = await fetchJson("/api/stats");
	let totalCalls = 0, totalSuccess = 0;
	stats.forEach(s => { totalCalls += s.call_count; totalSuccess += s.call_count * s.success_rate / 100; });
	document.getElementById("totalCalls").textContent = totalCalls;
	document.getElementById("toolsUsed").textContent = stats.length;
	const rate = totalCalls > 0
		? (totalSuccess / totalCalls * 100).toFixed(0) + "%" : "-";
	document.getElementById("successRate").textContent = rate;

	let html = "<table><tr><th>Tool</th><th class='num'>Calls</th>"
		+ "<th class='num'>Avg</th><th class='num'>Rate</th></tr>";
	stats.forEach(s => {
		const rc = rateClass(s.success_rate);
		html += "<tr><td>" + s.tool_name + "</td>"
			+ "<td class='num'>" + s.call_count + "</td>"
			+ "<td class='num'>" + fmtDuration(s.avg_duration) + "</td>"
			+ "<td class='num " + rc + "'>" + s.success_rate.toFixed(0) + "%</td></tr>";
	});
	html += "</table>";
	document.getElementById("toolStats").innerHTML = html;
}

async function loadSessions() {
	const sessions = await fetchJson("/api/sessions");
	document.getElementById("sessionsCount").textContent = sessions.length;
	let html = "";
	sessions.forEach(s => {
		const active = activeSession === s.session_id ? " active" : "";
		html += '<div class="session-item' + active + '" onclick="filterSession(\\'' + s.session_id + '\\')">'
			+ '<div class="session-id">' + truncate(s.session_id, 24) + '</div>'
			+ '<div class="session-meta">' + s.call_count + ' calls &middot; ' + fmtTime(s.last_call) + '</div>'
			+ '</div>';
	});
	const empty = "<div style='padding:16px;color:var(--text-dim)'>No sessions</div>";
	document.getElementById("sessions").innerHTML = html || empty;
}

async function loadTimeline() {
	let url = "/api/calls?limit=50";
	if (activeSession) url += "&session_id=" + encodeURIComponent(activeSession);
	const calls = await fetchJson(url);
	renderTimeline(calls, false);
	if (calls.length > 0) lastCallId = calls[0].id || 0;
}

function renderTimeline(calls, prepend) {
	const el = document.getElementById("timeline");
	let html = "";
	calls.forEach(c => {
		const cls = prepend ? " new" : "";
		const statusCls = c.success ? "ok" : "fail";
		html += "<div class='timeline-item" + cls + "'>"
			+ "<div><span class='timeline-status " + statusCls + "'></span>"
			+ "<span class='timeline-tool'>" + c.tool_name + "</span>"
			+ "<span class='timeline-meta'> &middot; " + fmtTime(c.timestamp) + "</span>"
			+ (c.session_id ? "<span class='timeline-meta'> &middot; " + truncate(c.session_id, 12) + "</span>" : "")
			+ "</div>"
			+ "<div class='timeline-duration'>" + fmtDuration(c.duration_seconds) + "</div>"
			+ "</div>";
	});
	if (prepend) {
		el.innerHTML = html + el.innerHTML;
		// trim to 50
		while (el.children.length > 50) el.removeChild(el.lastChild);
	} else {
		el.innerHTML = html || "<div style='padding:16px;color:var(--text-dim)'>No calls yet</div>";
	}
}

function filterSession(sid) {
	activeSession = (activeSession === sid) ? null : sid;
	document.getElementById("clearFilter").classList.toggle("visible", !!activeSession);
	loadTimeline();
	loadSessions();
}

function clearSessionFilter() {
	activeSession = null;
	document.getElementById("clearFilter").classList.remove("visible");
	loadTimeline();
	loadSessions();
}

function setSSEStatus(on) {
	const dot = document.getElementById("sseDot");
	const label = document.getElementById("sseLabel");
	if (on) {
		dot.classList.add("connected");
		label.textContent = "Live";
	} else {
		dot.classList.remove("connected");
		label.textContent = "Reconnecting...";
	}
}

function connectSSE() {
	evtSource = new EventSource("/api/stream");
	evtSource.onopen = () => setSSEStatus(true);
	evtSource.addEventListener("connected", () => setSSEStatus(true));
	evtSource.addEventListener("new_calls", (e) => {
		setSSEStatus(true);
		const calls = JSON.parse(e.data);
		if (calls.length > 0) {
			if (!activeSession) renderTimeline(calls, true);
			loadStats();
			loadSessions();
		}
	});
	evtSource.onerror = () => {
		if (evtSource.readyState === EventSource.CLOSED) {
			setSSEStatus(false);
		}
	};
}

async function loadUnusedTools() {
	try {
		const tools = await fetchJson("/api/registered-tools");
		const unused = tools.filter(t => !t.called);
		const panel = document.getElementById("unusedPanel");
		const countEl = document.getElementById("unusedCount");
		if (unused.length === 0) {
			panel.style.display = "none";
			return;
		}
		panel.style.display = "";
		countEl.textContent = unused.length + " of " + tools.length + " registered";
		let html = '<div class="unused-tools-grid">';
		unused.forEach(t => {
			html += '<span class="unused-chip">' + t.tool_name + '</span>';
		});
		html += '</div>';
		document.getElementById("unusedTools").innerHTML = html;
	} catch (e) {
		console.error("Failed to load unused tools:", e);
	}
}

async function init() {
	try {
		await Promise.all([
			loadStats(), loadSessions(), loadTimeline(), loadUnusedTools()
		]);
	} catch (e) {
		console.error("Failed to load initial data:", e);
	}
	connectSSE();
}

init();
</script>
</body>
</html>"""
