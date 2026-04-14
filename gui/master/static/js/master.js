/* ===== 10BASE-T1S Master Controller — Frontend Logic ===== */

let ws = null;
let state = {};
const MAX_LOG = 200;

// ===== WebSocket =====
function connectWS() {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  ws = new WebSocket(`${proto}//${location.host}/ws`);

  ws.onopen = () => {
    document.getElementById('conn-badge').textContent = 'CONNECTED';
    document.getElementById('conn-badge').classList.add('connected');
  };

  ws.onclose = () => {
    document.getElementById('conn-badge').textContent = 'DISCONNECTED';
    document.getElementById('conn-badge').classList.remove('connected');
    setTimeout(connectWS, 2000);
  };

  ws.onmessage = (evt) => {
    const msg = JSON.parse(evt.data);
    handleMessage(msg);
  };
}

function sendMsg(type, payload) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({
      type, source: 'master', payload, timestamp: Date.now()
    }));
  }
}

// ===== Message Handler =====
function handleMessage(msg) {
  switch (msg.type) {
    case 'init_state':
      state = msg.payload;
      renderFullState();
      break;
    case 'sensor_data':
      updateSensorData(msg.payload);
      addBusLog('PUB', `vehicle/${msg.payload.node_id}/sensor/${msg.payload.sensor_type}`,
        `${msg.payload.value} ${msg.payload.unit} [E2E:${msg.payload.e2e_status}]`);
      break;
    case 'actuator_cmd':
      updateActuatorState(msg.payload);
      addBusLog('CMD', `vehicle/${msg.payload.node_id}/actuator/${msg.payload.actuator_type}`,
        `${msg.payload.action} [SecOC:${msg.payload.secoc_status}]`);
      break;
    case 'safety_state':
      updateSafety(msg.payload);
      break;
    case 'ids_alert':
      addIDSAlert(msg.payload);
      break;
    case 'node_status':
      updateNodeStatus(msg.payload);
      break;
    case 'node_register':
      addNode(msg.payload);
      break;
    case 'plca_status':
      updatePLCA(msg.payload);
      break;
    case 'agent_log':
      addAgentLog(msg.payload);
      break;
    case 'scenario_load':
      addAgentLog({agent_name: 'orchestrator', message: `Scenario loaded: ${msg.payload.name}`});
      break;
    case 'node_offline':
      markNodeOffline(msg.payload.node_id);
      break;
  }
}

// ===== Render Full State =====
function renderFullState() {
  document.getElementById('mode-badge').textContent = state.mode === 'hw' ? 'HW' : 'SIM';

  // Scenarios
  const sel = document.getElementById('scenario-select');
  sel.innerHTML = '<option value="">-- Scenario --</option>';
  (state.scenarios_available || []).forEach(s => {
    sel.innerHTML += `<option value="${s}">${s}</option>`;
  });
  if (state.scenario) sel.value = state.scenario;

  // Safety
  updateSafety({
    state: state.safety_state,
    watchdog_remaining: state.watchdog_remaining,
    flow: [],
    dtc_count: (state.dtc_active || []).length,
  });

  // PLCA
  if (state.plca) updatePLCA(state.plca);

  // Nodes
  const nodes = state.nodes || {};
  for (const [nid, n] of Object.entries(nodes)) {
    addNode(n);
    updateNodeStatus(n);
  }

  // Fault node selector
  updateFaultNodeSelect();
}

// ===== Safety =====
function updateSafety(p) {
  const fsm = document.getElementById('safety-fsm');
  const st = (p.state || 'NORMAL').toUpperCase();
  fsm.textContent = st;
  fsm.className = 'fsm-display ' + st.toLowerCase();

  if (p.watchdog_remaining !== undefined) {
    const pct = Math.max(0, Math.min(100, (p.watchdog_remaining / 5.0) * 100));
    const fill = document.getElementById('watchdog-fill');
    fill.style.width = pct + '%';
    fill.className = 'watchdog-fill' +
      (pct < 30 ? ' danger' : pct < 60 ? ' warning' : '');
    document.getElementById('watchdog-timer').textContent = p.watchdog_remaining.toFixed(1) + 's';
  }

  if (p.flow) {
    document.querySelectorAll('.flow-step').forEach(el => {
      el.classList.toggle('active', p.flow.includes(el.dataset.cp));
    });
  }

  if (p.dtc_count !== undefined) {
    const dtcEl = document.getElementById('dtc-count');
    dtcEl.textContent = p.dtc_count;
    dtcEl.className = 'big-num' + (p.dtc_count > 0 ? ' alert' : '');
  }
}

// ===== PLCA =====
function updatePLCA(p) {
  const beacon = document.getElementById('plca-beacon');
  beacon.className = 'indicator ' + (p.beacon_active ? 'green' : 'red');
  beacon.textContent = p.beacon_active ? 'BEACON' : 'NO BEACON';

  document.getElementById('plca-count').textContent = p.node_count;
  document.getElementById('plca-collisions').textContent = p.collisions;

  // Render slots
  const container = document.getElementById('plca-slots');
  container.innerHTML = '';
  for (let i = 0; i < 8; i++) {
    const slot = document.createElement('div');
    slot.className = 'plca-slot';
    if (i === 0) {
      slot.className += ' master';
      slot.textContent = 'M';
    } else if (i < p.node_count) {
      slot.className += ' active';
      slot.textContent = i;
    } else {
      slot.className += ' empty';
      slot.textContent = '-';
    }
    container.appendChild(slot);
  }
}

// ===== Nodes =====
function addNode(n) {
  const cards = document.getElementById('node-cards');
  let card = document.getElementById('node-card-' + n.node_id);
  if (!card) {
    card = document.createElement('div');
    card.className = 'node-card';
    card.id = 'node-card-' + n.node_id;
    card.innerHTML = `
      <div class="node-header">
        <span class="node-id">Node ${n.node_id}</span>
        <span class="node-alive on" id="alive-${n.node_id}"></span>
      </div>
      <div class="node-role">PLCA:${n.plca_id} | ${n.zone} | ${n.role}</div>
      <div class="sensors" id="sensors-${n.node_id}"></div>
      <div class="actuators" id="actuators-${n.node_id}"></div>
      <div class="stats" id="stats-${n.node_id}"></div>
    `;
    cards.appendChild(card);
  }

  // Add to vehicle SVG
  addNodeToZone(n);
  updateFaultNodeSelect();
}

function updateNodeStatus(n) {
  const card = document.getElementById('node-card-' + n.node_id);
  if (!card) { addNode(n); return; }

  card.className = 'node-card' + (n.alive === false ? ' offline' : '');

  const alive = document.getElementById('alive-' + n.node_id);
  if (alive) alive.className = 'node-alive ' + (n.alive === false ? 'off' : 'on');

  // Sensors
  const sensorsEl = document.getElementById('sensors-' + n.node_id);
  if (sensorsEl && n.sensors) {
    sensorsEl.innerHTML = Object.entries(n.sensors).map(([k, v]) =>
      `<div class="sensor-val"><span>${k}</span><span class="val">${typeof v === 'number' ? v.toFixed(2) : v}</span></div>`
    ).join('');
  }

  // Actuators
  const actEl = document.getElementById('actuators-' + n.node_id);
  if (actEl && n.actuators) {
    actEl.innerHTML = Object.entries(n.actuators).map(([k, v]) =>
      `<div class="sensor-val"><span>${k}</span><span class="val">${typeof v === 'object' ? v.state || JSON.stringify(v) : v}</span></div>`
    ).join('');
  }

  // Stats
  const statsEl = document.getElementById('stats-' + n.node_id);
  if (statsEl) {
    statsEl.innerHTML = `TX:${n.tx_count||0} RX:${n.rx_count||0} ERR:${n.error_count||0} SEQ:${n.seq_counter||0} E2E:${n.e2e_ok||0}/${n.e2e_fail||0}`;
  }
}

function updateSensorData(p) {
  // Update node sensor values in cards
  const sensorsEl = document.getElementById('sensors-' + p.node_id);
  if (!sensorsEl) return;
  // Just trigger node status update for the node
}

function updateActuatorState(p) {
  const actEl = document.getElementById('actuators-' + p.node_id);
  if (!actEl) return;
}

function markNodeOffline(nodeId) {
  const card = document.getElementById('node-card-' + nodeId);
  if (card) card.className = 'node-card offline';
  const alive = document.getElementById('alive-' + nodeId);
  if (alive) alive.className = 'node-alive off';

  // Update SVG
  const dot = document.getElementById('svg-node-' + nodeId);
  if (dot) dot.classList.add('offline');
}

function addNodeToZone(n) {
  const zoneMap = {
    'front_left': 'zone-fl-nodes',
    'front_right': 'zone-fr-nodes',
    'rear_left': 'zone-rl-nodes',
    'rear_right': 'zone-rr-nodes',
  };
  const containerId = zoneMap[n.zone] || 'zone-fl-nodes';
  const container = document.getElementById(containerId);
  if (!container) return;

  let existing = document.getElementById('svg-node-' + n.node_id);
  if (existing) return;

  const idx = container.childElementCount;
  const cx = 15 + (idx % 3) * 28;
  const cy = 32 + Math.floor(idx / 3) * 22;

  const circle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
  circle.setAttribute('id', 'svg-node-' + n.node_id);
  circle.setAttribute('cx', cx);
  circle.setAttribute('cy', cy);
  circle.setAttribute('r', 8);
  circle.setAttribute('fill', n.role === 'sensor' ? '#00e676' : n.role === 'actuator' ? '#ff9100' : '#00d4ff');
  circle.setAttribute('class', 'node-dot' + (n.alive === false ? ' offline' : ''));

  const title = document.createElementNS('http://www.w3.org/2000/svg', 'title');
  title.textContent = `Node ${n.node_id} (${n.role})`;
  circle.appendChild(title);

  const text = document.createElementNS('http://www.w3.org/2000/svg', 'text');
  text.setAttribute('x', cx);
  text.setAttribute('y', cy + 4);
  text.setAttribute('text-anchor', 'middle');
  text.setAttribute('fill', '#000');
  text.setAttribute('font-size', '9');
  text.setAttribute('font-weight', '700');
  text.textContent = n.node_id;

  container.appendChild(circle);
  container.appendChild(text);
}

function updateFaultNodeSelect() {
  const sel = document.getElementById('fault-node');
  const current = sel.value;
  sel.innerHTML = '<option value="">-- Node --</option>';
  const nodes = state.nodes || {};
  for (const nid of Object.keys(nodes)) {
    sel.innerHTML += `<option value="${nid}">${nid}</option>`;
  }
  sel.value = current;
}

// ===== IDS Alerts =====
function addIDSAlert(p) {
  const countEl = document.getElementById('ids-count');
  countEl.textContent = parseInt(countEl.textContent) + 1;
  countEl.className = 'big-num alert';

  // Add to alert list
  const list = document.getElementById('ids-alert-list');
  const item = document.createElement('div');
  item.className = 'alert-item';
  item.innerHTML = `
    <span class="severity severity-${p.severity}">${p.severity}</span>
    <span>${p.rule_id}</span>
    <span>${p.source_node}</span>
    <span>${p.description}</span>
  `;
  list.insertBefore(item, list.firstChild);
  if (list.childElementCount > 20) list.lastChild.remove();

  // IDS stream tab
  addLogLine('ids-stream', 'alert',
    `[${p.severity}] ${p.rule_id} from ${p.source_node}: ${p.description}`);
}

// ===== Bus Log =====
function addBusLog(tag, keyExpr, detail) {
  const ts = new Date().toLocaleTimeString('ko-KR', {hour12: false, fractionalSecondDigits: 3});
  const tagClass = {PUB:'tag-pub', SUB:'tag-sub', QRY:'tag-qry', CMD:'tag-cmd'}[tag] || 'tag-pub';
  addLogLine('msg-stream', tagClass,
    `<span class="ts">${ts}</span> <span class="${tagClass}">[${tag}]</span> <span class="ke">${keyExpr}</span> ${detail}`);
}

function addAgentLog(p) {
  const ts = new Date().toLocaleTimeString('ko-KR', {hour12: false});
  addLogLine('agent-stream', 'tag-sub',
    `<span class="ts">${ts}</span> <span class="tag-sub">[${p.agent_name || 'agent'}]</span> ${p.message || p.phase || ''}`);
}

function addLogLine(containerId, cls, html) {
  const container = document.getElementById(containerId);
  if (!container) return;
  const line = document.createElement('div');
  line.className = 'log-line';
  line.innerHTML = html;
  container.appendChild(line);
  if (container.childElementCount > MAX_LOG) container.firstChild.remove();
  container.scrollTop = container.scrollHeight;
}

// ===== Tabs =====
function showTab(name) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  event.target.classList.add('active');
}

// ===== Actions =====
async function startSim() {
  const scenario = document.getElementById('scenario-select').value;
  if (scenario) {
    await fetch(`/api/scenario/${scenario}`, {method: 'POST'});
  }
  await fetch('/api/start', {method: 'POST'});
  document.getElementById('btn-start').disabled = true;
}

async function stopSim() {
  await fetch('/api/stop', {method: 'POST'});
  document.getElementById('btn-start').disabled = false;
}

function injectFault(faultType) {
  const nodeId = document.getElementById('fault-node').value;
  sendMsg('cmd_inject_fault', {fault_type: faultType, node_id: nodeId});
}

function resetSafety() {
  sendMsg('cmd_reset_safety', {});
}

function kickWatchdog() {
  sendMsg('cmd_kick_watchdog', {});
}

// ===== Init =====
document.addEventListener('DOMContentLoaded', connectWS);
