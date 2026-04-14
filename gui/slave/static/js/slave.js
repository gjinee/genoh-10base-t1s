/* ===== 10BASE-T1S Slave Node — Frontend Logic ===== */

let ws = null;
let nodeId = '1';
let zone = 'front_left';
let plcaId = 1;
let role = 'sensor';
let registered = false;

// Sensor state
const sensors = {
  temperature: { value: 25.0, mode: 'auto', unit: '\u00B0C', min: -40, max: 150, history: [] },
  proximity:   { value: 100.0, mode: 'auto', unit: 'cm', min: 0, max: 500, history: [] },
  battery:     { value: 3.7, mode: 'auto', unit: 'V', min: 0, max: 4.2, history: [] },
};

const MAX_HISTORY = 60;
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
  ws.onmessage = (evt) => handleMessage(JSON.parse(evt.data));
}

function sendMsg(type, payload) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type, source: 'slave', payload, timestamp: Date.now() }));
  }
}

// ===== Message Handler =====
function handleMessage(msg) {
  switch (msg.type) {
    case 'init_state':
      initFromState(msg.payload);
      break;
    case 'actuator_cmd':
      if (msg.payload.node_id === nodeId) {
        receiveActuatorCmd(msg.payload);
      }
      break;
    case 'node_status':
      if (msg.payload.node_id === nodeId) {
        updateMyStatus(msg.payload);
      }
      break;
    case 'sensor_data':
      if (msg.payload.node_id === nodeId) {
        updateSensorFromEngine(msg.payload);
      }
      break;
    case 'ids_alert':
      if (msg.payload.source_node === nodeId) {
        addLog('atk', `IDS ALERT: ${msg.payload.rule_id} - ${msg.payload.description}`);
        document.getElementById('attack-status').textContent = `DETECTED: ${msg.payload.rule_id}`;
        document.getElementById('attack-status').className = 'attack-status active';
      }
      break;
    case 'node_offline':
      if (msg.payload.node_id === nodeId) {
        document.getElementById('st-alive').textContent = 'NO';
        document.getElementById('st-alive').className = 'indicator red';
      }
      break;
  }
}

function initFromState(state) {
  document.getElementById('mode-badge').textContent = state.mode === 'hw' ? 'HW' : 'SIM';
  // If our node already exists in state
  const n = (state.nodes || {})[nodeId];
  if (n) {
    registered = true;
    updateMyStatus(n);
    if (n.sensors) {
      for (const [k, v] of Object.entries(n.sensors)) {
        if (sensors[k]) {
          sensors[k].value = v;
          updateSensorDisplay(k);
        }
      }
    }
  }
}

// ===== Registration =====
function registerNode() {
  nodeId = document.getElementById('input-node-id').value || '1';
  zone = document.getElementById('input-zone').value;
  plcaId = parseInt(document.getElementById('input-plca').value) || 1;
  role = document.getElementById('input-role').value;

  sendMsg('node_register', { node_id: nodeId, zone, plca_id: plcaId, role });
  registered = true;

  document.getElementById('st-plca-id').textContent = plcaId;
  document.getElementById('st-role').textContent = role.toUpperCase();
  document.getElementById('st-zone').textContent = zone;
  document.getElementById('st-alive').textContent = 'YES';
  document.getElementById('st-alive').className = 'indicator green';

  addLog('tx', `Registered: Node ${nodeId}, Zone ${zone}, PLCA ${plcaId}, Role ${role}`);
  document.getElementById('btn-register').textContent = 'Re-register';
}

// ===== Sensor Controls =====
function onSlider(sensorType, value) {
  const v = parseFloat(value);
  sensors[sensorType].value = v;
  updateSensorDisplay(sensorType);

  // In manual mode, immediately send
  if (sensors[sensorType].mode === 'manual' && registered) {
    sendSensorData(sensorType, v);
  }
}

function setMode(sensorType, mode) {
  sensors[sensorType].mode = mode;
}

function updateSensorDisplay(sensorType) {
  const s = sensors[sensorType];
  document.getElementById('val-' + sensorType).textContent =
    s.value.toFixed(2) + ' ' + s.unit;
  document.getElementById('slider-' + sensorType).value = s.value;

  // History for chart
  s.history.push({ t: Date.now(), v: s.value });
  if (s.history.length > MAX_HISTORY) s.history.shift();
  drawChart(sensorType);
}

function sendSensorData(sensorType, value) {
  sendMsg('sensor_data', {
    node_id: nodeId,
    sensor_type: sensorType,
    value: value,
  });
  addLog('tx', `sensor/${sensorType} = ${value.toFixed(2)} ${sensors[sensorType].unit} [E2E]`);
}

function updateSensorFromEngine(p) {
  const sType = p.sensor_type;
  if (sensors[sType] && sensors[sType].mode === 'auto') {
    sensors[sType].value = p.value;
    updateSensorDisplay(sType);
  }
  // Update E2E counters
  document.getElementById('e2e-seq').textContent = p.seq || 0;
  if (p.e2e_status === 'VALID') {
    const el = document.getElementById('e2e-ok');
    el.textContent = parseInt(el.textContent) + 1;
    document.getElementById('e2e-status').textContent = 'VALID';
    document.getElementById('e2e-status').className = 'indicator green';
  }
}

// ===== Actuator =====
function receiveActuatorCmd(p) {
  const actType = p.actuator_type;
  const stateEl = document.getElementById('act-' + actType + '-state');
  if (stateEl) {
    stateEl.textContent = (p.action || '').toUpperCase();
    const item = document.getElementById('act-' + actType);
    if (item) item.classList.add('active');
    setTimeout(() => item && item.classList.remove('active'), 1000);
  }

  // SecOC counter
  if (p.secoc_status === 'AUTHENTICATED') {
    const el = document.getElementById('secoc-ok');
    el.textContent = parseInt(el.textContent) + 1;
  }

  addLog('rx', `actuator/${actType} = ${p.action} [SecOC:${p.secoc_status}]`);

  // Update RX count
  const rxEl = document.getElementById('st-rx');
  rxEl.textContent = parseInt(rxEl.textContent) + 1;
}

// ===== Status Update =====
function updateMyStatus(n) {
  document.getElementById('st-plca-id').textContent = n.plca_id;
  document.getElementById('st-role').textContent = (n.role || '').toUpperCase();
  document.getElementById('st-zone').textContent = n.zone;
  document.getElementById('st-alive').textContent = n.alive ? 'YES' : 'NO';
  document.getElementById('st-alive').className = 'indicator ' + (n.alive ? 'green' : 'red');
  if (n.uptime) {
    const h = Math.floor(n.uptime / 3600);
    const m = Math.floor((n.uptime % 3600) / 60);
    const s = Math.floor(n.uptime % 60);
    document.getElementById('st-uptime').textContent =
      `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
  }
  document.getElementById('st-tx').textContent = n.tx_count || 0;
  document.getElementById('st-rx').textContent = n.rx_count || 0;
  document.getElementById('st-errors').textContent = n.error_count || 0;

  if (n.e2e_ok !== undefined) document.getElementById('e2e-ok').textContent = n.e2e_ok;
  if (n.e2e_fail !== undefined) document.getElementById('e2e-fail').textContent = n.e2e_fail;
  if (n.seq_counter !== undefined) document.getElementById('e2e-seq').textContent = n.seq_counter;
  if (n.secoc_ok !== undefined) document.getElementById('secoc-ok').textContent = n.secoc_ok;
  if (n.secoc_fail !== undefined) document.getElementById('secoc-fail').textContent = n.secoc_fail;

  // Update sensor values from engine
  if (n.sensors) {
    for (const [k, v] of Object.entries(n.sensors)) {
      if (sensors[k] && sensors[k].mode === 'auto') {
        sensors[k].value = v;
        updateSensorDisplay(k);
      }
    }
  }
}

// ===== Attack Simulation =====
function doAttack(type) {
  sendMsg('cmd_attack', { attack_type: type, node_id: nodeId });
  document.getElementById('attack-status').textContent = 'EXECUTING: ' + type.toUpperCase();
  document.getElementById('attack-status').className = 'attack-status active';
  addLog('atk', `Attack executed: ${type}`);
  setTimeout(() => {
    document.getElementById('attack-status').textContent = 'IDLE';
    document.getElementById('attack-status').className = 'attack-status';
  }, 3000);
}

function goOffline() {
  sendMsg('cmd_inject_fault', { fault_type: 'NODE_OFFLINE', node_id: nodeId });
  document.getElementById('st-alive').textContent = 'NO';
  document.getElementById('st-alive').className = 'indicator red';
  addLog('tx', 'Node going OFFLINE');
}

function goOnline() {
  // Re-register to come back online
  sendMsg('node_register', { node_id: nodeId, zone, plca_id: plcaId, role });
  document.getElementById('st-alive').textContent = 'YES';
  document.getElementById('st-alive').className = 'indicator green';
  addLog('tx', 'Node coming ONLINE');
}

// ===== Chart Drawing =====
function drawChart(sensorType) {
  const canvas = document.getElementById('chart-' + sensorType);
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const s = sensors[sensorType];
  const w = canvas.width, h = canvas.height;

  ctx.clearRect(0, 0, w, h);

  if (s.history.length < 2) return;

  // Grid
  ctx.strokeStyle = '#1a1a3e';
  ctx.lineWidth = 0.5;
  for (let y = 0; y < h; y += 20) {
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
  }

  // Data line
  const minV = s.min, maxV = s.max;
  const range = maxV - minV || 1;
  const stepX = w / (MAX_HISTORY - 1);

  ctx.beginPath();
  ctx.strokeStyle = '#00e676';
  ctx.lineWidth = 1.5;

  const startIdx = Math.max(0, s.history.length - MAX_HISTORY);
  for (let i = startIdx; i < s.history.length; i++) {
    const x = (i - startIdx) * stepX;
    const y = h - ((s.history[i].v - minV) / range) * (h - 10) - 5;
    if (i === startIdx) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.stroke();

  // Current value label
  ctx.fillStyle = '#00e676';
  ctx.font = '10px monospace';
  ctx.fillText(s.value.toFixed(1) + ' ' + s.unit, w - 60, 12);
}

// ===== Log =====
function addLog(tag, text) {
  const container = document.getElementById('msg-stream');
  const ts = new Date().toLocaleTimeString('ko-KR', {hour12: false, fractionalSecondDigits: 3});
  const tagClass = {tx: 'tag-tx', rx: 'tag-rx', atk: 'tag-atk'}[tag] || 'tag-tx';
  const tagLabel = {tx: 'TX', rx: 'RX', atk: 'ATK'}[tag] || tag.toUpperCase();

  const line = document.createElement('div');
  line.className = 'log-line';
  line.innerHTML = `<span class="ts">${ts}</span> <span class="${tagClass}">[${tagLabel}]</span> ${text}`;
  container.appendChild(line);
  if (container.childElementCount > MAX_LOG) container.firstChild.remove();
  container.scrollTop = container.scrollHeight;
}

// ===== Init =====
document.addEventListener('DOMContentLoaded', connectWS);
