// app.js — VoiceTerm setup UI logic with i18n support
// Internationalization and application logic for the setup web interface

let T = {}; // Current translations
let currentLang = localStorage.getItem('vtLang') || 'en';

const state = {
  selectedSsid: '', audioChannel: 'builtin',
  outputDeviceIndex: null, inputDeviceIndex: null,
  btMac: '', samplesCount: 0, referenceFile: '', wakeword: ''
};

// --- i18n ---
async function loadLang(lang) {
  try {
    const r = await fetch('/static/i18n/' + lang + '.json');
    if (!r.ok) throw new Error('HTTP ' + r.status);
    T = await r.json();
    currentLang = lang;
    localStorage.setItem('vtLang', lang);
    applyTranslations();
  } catch (e) {
    console.error('i18n load error:', e);
    if (lang !== 'en') loadLang('en');
  }
}

function applyTranslations() {
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.getAttribute('data-i18n');
    if (T[key]) el.textContent = T[key];
  });
  document.querySelectorAll('[data-i18n-ph]').forEach(el => {
    const key = el.getAttribute('data-i18n-ph');
    if (T[key]) el.placeholder = T[key];
  });
  document.querySelectorAll('[data-i18n-title]').forEach(el => {
    const key = el.getAttribute('data-i18n-title');
    if (T[key]) document.title = T[key];
  });
  // Update language selector highlight
  document.querySelectorAll('.lang-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.lang === currentLang);
  });
  // Update dynamic texts
  updateSamplesUI();
}

function t(key, replacements) {
  let s = T[key] || key;
  if (replacements) {
    for (const [k, v] of Object.entries(replacements)) {
      s = s.replace('{' + k + '}', v);
    }
  }
  return s;
}

function switchLang(lang) { loadLang(lang); }

// --- Helpers ---
function status(id, msg, type) {
  type = type || 'info';
  const el = document.getElementById(id);
  if (!el) return;
  el.className = 'status ' + type;
  el.textContent = msg;
}

async function api(url, body) {
  const opts = body
    ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }
    : { method: 'GET' };
  const r = await fetch(url, opts);
  return r.json();
}

function showSection(id) { document.getElementById(id).classList.remove('hidden'); }

function updateSamplesUI() {
  const n = state.samplesCount;
  const info = document.getElementById('samples-info');
  if (info) info.textContent = t('samples_info', { n: n });
  const btn = document.getElementById('btn-record-sample');
  if (btn) {
    const span = btn.querySelector('#sample-count');
    if (span) span.textContent = Math.min(n + 1, 5);
  }
}

// --- WiFi ---
async function scanWifi() {
  const btn = document.getElementById('btn-scan-wifi');
  btn.textContent = t('s_scanning');
  btn.disabled = true;
  try {
    const data = await api('/api/wifi/scan');
    const ul = document.getElementById('net-list');
    ul.innerHTML = '';
    (data.networks || []).forEach(n => {
      const li = document.createElement('li');
      li.innerHTML = '<span>' + n.ssid + '</span><span class="signal">📶 ' + n.signal + '% ' + (n.security || 'Open') + '</span>';
      li.onclick = () => selectNetwork(n.ssid, li);
      ul.appendChild(li);
    });
    if (!data.networks.length) ul.innerHTML = '<li style="color:#94a3b8;padding:10px">' + t('s_no_networks') + '</li>';
  } catch (e) {
    status('wifi-status', t('s_scan_error'), 'err');
  }
  btn.textContent = t('btn_scan_wifi');
  btn.disabled = false;
}

function selectNetwork(ssid, el) {
  state.selectedSsid = ssid;
  document.querySelectorAll('#net-list li').forEach(l => l.classList.remove('selected'));
  el.classList.add('selected');
  document.getElementById('sel-ssid-label').textContent = ssid;
  document.getElementById('wifi-pass-row').classList.remove('hidden');
  document.getElementById('btn-wifi-connect').classList.remove('hidden');
}

async function connectWifi() {
  const pw = document.getElementById('wifi-password').value;
  status('wifi-status', t('s_connecting'), 'info');
  const r = await api('/api/wifi/connect', { ssid: state.selectedSsid, password: pw });
  if (r.status === 'ok') {
    status('wifi-status', r.message, 'ok');
    document.getElementById('sec-wifi').querySelector('h2').classList.add('step-done');
    showSection('sec-audio');
    loadDevices();
  } else {
    status('wifi-status', r.message || t('s_play_err'), 'err');
  }
}

// --- Audio ---
async function loadDevices() {
  const data = await api('/api/audio/devices');
  const outSel = document.getElementById('sel-output-dev');
  const inSel = document.getElementById('sel-input-dev');
  outSel.innerHTML = (data.output || []).map(d => '<option value="' + d.index + '">' + d.name + '</option>').join('');
  inSel.innerHTML = (data.input || []).map(d => '<option value="' + d.index + '">' + d.name + '</option>').join('');
  if (data.output.length) state.outputDeviceIndex = data.output[0].index;
  if (data.input.length) state.inputDeviceIndex = data.input[0].index;
  showSection('sec-audio-test');
}

function onAudioChannel(radio) {
  state.audioChannel = radio.value;
  document.querySelectorAll('.radio-label').forEach(l => l.classList.remove('selected'));
  radio.closest('.radio-label').classList.add('selected');
  document.getElementById('builtin-section').classList.toggle('hidden', radio.value !== 'builtin');
  document.getElementById('bt-section').classList.toggle('hidden', radio.value !== 'bluetooth');
  if (radio.value === 'builtin') loadDevices();
}

async function testPlayback() {
  status('audio-test-status', t('s_playing'), 'info');
  const idx = parseInt(document.getElementById('sel-output-dev').value) || null;
  state.outputDeviceIndex = idx;
  const r = await api('/api/audio/test_playback', { device_index: idx });
  status('audio-test-status', r.status === 'ok' ? t('s_play_ok') : t('s_play_err'), r.status);
}

async function testMic() {
  status('audio-test-status', t('s_mic_rec'), 'info');
  const idx = parseInt(document.getElementById('sel-input-dev').value) || null;
  state.inputDeviceIndex = idx;
  const r = await api('/api/audio/test_mic', { device_index: idx });
  status('audio-test-status', r.status === 'ok' ? t('s_mic_ok') : '❌ ' + r.message, r.status);
  if (r.status === 'ok') {
    document.getElementById('sec-audio-test').querySelector('h2').classList.add('step-done');
    showSection('sec-wakeword');
    showSection('sec-hermes');
    showSection('sec-system');
  }
}

// --- Bluetooth ---
function startBtScan() {
  document.getElementById('bt-list').innerHTML = '<li style="color:#94a3b8;padding:10px">' + t('s_bt_search') + '</li>';
  api('/api/bluetooth/scan/start');
  const evtSrc = new EventSource('/api/bluetooth/scan/devices');
  evtSrc.onmessage = e => {
    const dev = JSON.parse(e.data);
    if (dev.done) { evtSrc.close(); return; }
    const ul = document.getElementById('bt-list');
    if (ul.querySelector('li[style]')) ul.innerHTML = '';
    const li = document.createElement('li');
    li.innerHTML = '<span>' + dev.name + '<br><small style="color:#64748b">' + dev.mac + '</small></span>' +
      '<button class="btn btn-secondary" onclick="pairBt(\'' + dev.mac + '\',this)">' + t('pair_btn') + '</button>';
    ul.appendChild(li);
  };
  evtSrc.onerror = () => evtSrc.close();
}

async function pairBt(mac, btn) {
  btn.textContent = t('s_pairing');
  btn.disabled = true;
  const r = await api('/api/bluetooth/pair', { mac: mac });
  if (r.status === 'ok') {
    state.btMac = mac;
    status('bt-status', t('s_bt_ok'), 'ok');
    showSection('sec-audio-test');
    showSection('sec-wakeword');
    showSection('sec-hermes');
    showSection('sec-system');
  } else {
    status('bt-status', t('s_bt_err') + JSON.stringify(r.details), 'err');
    btn.textContent = t('s_retry');
    btn.disabled = false;
  }
}

// --- Wake word ---
async function recordSample() {
  const ww = document.getElementById('wakeword-text').value.trim();
  if (!ww) { alert(t('a_enter_ww')); return; }
  state.wakeword = ww;
  const btn = document.getElementById('btn-record-sample');
  btn.textContent = t('s_rec_2s');
  btn.disabled = true;
  const r = await api('/api/wakeword/record_sample', { device_index: state.inputDeviceIndex });
  btn.disabled = false;
  if (r.status === 'ok') {
    state.samplesCount = r.total_samples;
    updateSamplesUI();
    document.getElementById('samples-progress').style.width = (state.samplesCount / 5 * 100) + '%';
    document.getElementById('btn-gen-ww').disabled = state.samplesCount < 4;
    btn.textContent = t('sample_btn_n', { n: Math.min(state.samplesCount + 1, 5) });
  } else {
    alert(t('a_rec_err') + r.message);
    btn.textContent = t('sample_btn_n', { n: state.samplesCount + 1 });
  }
}

async function clearSamples() {
  await api('/api/wakeword/clear_samples');
  state.samplesCount = 0;
  updateSamplesUI();
  document.getElementById('samples-progress').style.width = '0%';
  document.getElementById('btn-gen-ww').disabled = true;
  document.getElementById('wakeword-gen-status').textContent = '';
}

async function generateWakeword() {
  const ww = document.getElementById('wakeword-text').value.trim();
  status('wakeword-gen-status', t('s_generating'), 'info');
  const r = await api('/api/wakeword/generate', { hotword: ww });
  if (r.status === 'ok') {
    state.referenceFile = r.reference_file;
    status('wakeword-gen-status', t('s_model_ok') + r.reference_file, 'ok');
    document.getElementById('wakeword-test-block').classList.remove('hidden');
  } else {
    status('wakeword-gen-status', '❌ ' + r.message, 'err');
  }
}

function testWakeword() {
  const ww = document.getElementById('wakeword-text').value.trim();
  const thr = document.getElementById('cfg-threshold').value || 0.8;
  status('ww-test-status', t('s_say_ww'), 'info');
  const url = '/api/wakeword/test?reference_file=' + encodeURIComponent(state.referenceFile) +
    '&hotword=' + encodeURIComponent(ww) + '&threshold=' + thr;
  const es = new EventSource(url);
  es.onmessage = e => {
    const d = JSON.parse(e.data);
    if (d.done) { es.close(); status('ww-test-status', t('s_test_done'), 'info'); return; }
    if (d.confidence !== undefined) {
      const pct = Math.round(d.confidence * 100);
      document.getElementById('conf-fill').style.width = pct + '%';
      document.getElementById('conf-fill').textContent = pct + '%';
    }
  };
  es.onerror = () => es.close();
}

// --- Hermes ---
async function checkHermes() {
  const url = document.getElementById('hermes-url').value.trim();
  if (!url) { alert(t('a_enter_url')); return; }
  status('hermes-status', t('s_checking'), 'info');
  const r = await api('/api/hermes/check', { url: url });
  status('hermes-status', r.message, r.status === 'ok' ? 'ok' : 'err');
}

// --- Save ---
async function saveAndLaunch() {
  const cfg = {
    setup_complete: true,
    wakeword: state.wakeword || document.getElementById('wakeword-text').value.trim(),
    reference_file_path: state.referenceFile,
    hotword_threshold: parseFloat(document.getElementById('cfg-threshold').value),
    relaxation_time: parseFloat(document.getElementById('cfg-relax').value),
    window_length_secs: parseFloat(document.getElementById('cfg-window').value),
    sliding_window_secs: parseFloat(document.getElementById('cfg-slide').value),
    audio_channel: state.audioChannel,
    audio_device_index: state.audioChannel === 'builtin' ? (parseInt(document.getElementById('sel-output-dev').value) || null) : null,
    bluetooth_mac: state.btMac,
    silence_threshold_rms: parseInt(document.getElementById('cfg-rms').value),
    silence_duration_ms: parseInt(document.getElementById('cfg-silence-ms').value),
    beep_enabled: document.getElementById('cfg-beep').checked,
    hermes_url: document.getElementById('hermes-url').value.trim(),
    stt_model: document.getElementById('cfg-stt').value,
    reconnect_interval_sec: 1
  };
  status('save-status', t('s_saving'), 'info');
  const r = await api('/api/config/save', cfg);
  if (r.status === 'ok') {
    status('save-status', t('s_saved'), 'ok');
    setTimeout(() => location.href = '/', 3000);
  } else {
    status('save-status', t('s_save_err') + (r.message ? ' ' + r.message : ''), 'err');
  }
}

// --- Init ---
document.addEventListener('DOMContentLoaded', () => loadLang(currentLang));
