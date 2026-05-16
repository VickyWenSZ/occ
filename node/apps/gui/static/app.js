'use strict';

// ── State ────────────────────────────────────────────────────────────────────

let currentChatId  = null;
let isStreaming    = false;
let allChats       = [];
let attachments    = [];   // [{name, type, data}]
let logsSource     = null; // EventSource for broker logs
let logLineCount   = 0;
let activeTab      = 'chat';
let activeView     = 'chat'; // 'chat' | 'forge'
let config         = {};

// Forge state
let forgeFiles   = [];   // [{name, data_b64}]
let forgeMode    = 'add';
let forgeRunning = false;

let _cmdIdx        = -1;
let _cmdMouseDown  = false;

// ── marked.js setup ──────────────────────────────────────────────────────────

const renderer = new marked.Renderer();

renderer.code = function(code, lang) {
  const language = lang && hljs.getLanguage(lang) ? lang : '';
  const highlighted = language
    ? hljs.highlight(code, {language}).value
    : hljs.highlightAuto(code).value;
  const langLabel = language || 'code';
  return `<div class="code-block-wrapper">
    <div class="code-block-header">
      <span class="code-lang">${langLabel}</span>
      <button class="copy-btn" onclick="copyCode(this)">copy</button>
    </div>
    <pre><code class="hljs language-${langLabel}">${highlighted}</code></pre>
  </div>`;
};

marked.setOptions({ renderer, gfm: true, breaks: true });

function renderMarkdown(text) {
  if (!text) return '';
  const raw = marked.parse(text);
  return DOMPurify.sanitize(raw, {
    ALLOWED_TAGS: [
      'p','br','strong','em','del','h1','h2','h3','h4','h5','h6',
      'ul','ol','li','code','pre','blockquote','table','thead','tbody',
      'tr','th','td','a','img','hr','div','span','button',
    ],
    ALLOWED_ATTR: ['href','src','alt','class','onclick','data-code'],
    ALLOW_DATA_ATTR: true,
  });
}

function copyCode(btn) {
  const pre = btn.closest('.code-block-wrapper').querySelector('pre code');
  if (!pre) return;
  navigator.clipboard.writeText(pre.innerText).then(() => {
    btn.textContent = 'copied!';
    btn.classList.add('copied');
    setTimeout(() => { btn.textContent = 'copy'; btn.classList.remove('copied'); }, 1500);
  });
}

// ── Init ─────────────────────────────────────────────────────────────────────

async function init() {
  setupEventListeners();
  await pollUntilReady();
  const cfg = await apiFetch('/api/config');
  if (cfg) { config = cfg; updateProviderBadge(!!cfg.openrouter_configured, cfg.openrouter_model); }
  await loadChats();
  showApp();
  initGpuIndicator();
}

// ── GPU indicator ─────────────────────────────────────────────────────────

let _gpuPollTimer = null;

async function initGpuIndicator() {
  const data = await apiFetch('/api/gpu_stats');
  if (!data || data.gpu_pct === null || data.gpu_pct === undefined) return;
  document.getElementById('gpu-indicator').classList.remove('hidden');
  _updateGpuBar(data.gpu_pct);
  _gpuPollTimer = setInterval(async () => {
    const d = await apiFetch('/api/gpu_stats');
    if (d && d.gpu_pct !== null && d.gpu_pct !== undefined) _updateGpuBar(d.gpu_pct);
  }, 2000);
}

function _updateGpuBar(pct) {
  const fill = document.getElementById('gpu-bar-fill');
  const text = document.getElementById('gpu-pct-text');
  if (!fill || !text) return;
  fill.style.width = pct + '%';
  fill.className = 'gpu-bar-fill' + (pct >= 85 ? ' crit' : pct >= 60 ? ' warn' : '');
  text.textContent = pct + '%';
}

async function pollUntilReady() {
  const statusEl = document.getElementById('loading-status');
  const errorDiv  = document.getElementById('loading-error');
  const errorMsg  = document.getElementById('loading-error-msg');
  const errorLink = document.getElementById('loading-error-link');
  const bar       = document.getElementById('loading-bar');

  const ERROR_MESSAGES = {
    ollama_missing: 'Ollama is not installed.\nOCC requires Ollama to run local models.',
    ollama_start_failed: 'Ollama is installed but could not start.\nTry running "ollama serve" in a terminal, then refresh.',
    model_download_failed: 'Model download failed.\nCheck your internet connection and try restarting OCC.',
  };

  while (true) {
    try {
      const r = await fetch('/api/status');
      const data = await r.json();
      statusEl.textContent = data.status || 'starting...';

      if (data.error) {
        bar.style.display = 'none';
        errorMsg.textContent = ERROR_MESSAGES[data.error] || data.error;
        if (data.error === 'ollama_missing' && data.ollama_download_url) {
          errorLink.href = data.ollama_download_url;
          errorLink.style.display = 'inline-block';
        } else {
          errorLink.style.display = 'none';
        }
        errorDiv.style.display = 'block';
        return;
      }

      if (data.ready) return;
    } catch (_) {}
    await sleep(800);
  }
}

function showApp() {
  const loading = document.getElementById('loading-screen');
  loading.classList.add('fade-out');
  setTimeout(() => loading.classList.add('hidden'), 400);
  document.getElementById('app').classList.remove('hidden');
  document.getElementById('message-input').focus();
}

// ── Event listeners ───────────────────────────────────────────────────────────

function setupEventListeners() {
  document.getElementById('btn-new-chat').addEventListener('click', () => newChat());
  document.getElementById('search-input').addEventListener('input', e => filterChats(e.target.value));

  document.getElementById('btn-settings').addEventListener('click', openSettings);
  document.getElementById('btn-forge').addEventListener('click', () => switchView('forge'));
  document.getElementById('btn-scout')?.addEventListener('click', () => switchView('scout'));
  document.getElementById('close-settings').addEventListener('click', () => closeModal('settings-modal'));
  document.getElementById('local-mode-toggle')?.addEventListener('change', e => setLocalMode(e.target.checked));
  document.getElementById('tab-chat').addEventListener('click', () => switchTab('chat'));
  document.getElementById('tab-logs').addEventListener('click', () => switchTab('logs'));

  document.getElementById('attach-btn').addEventListener('click', () => document.getElementById('file-input').click());
  document.getElementById('file-input').addEventListener('change', e => handleFiles(e.target.files));

  // Drag-and-drop: drop files anywhere on the page (only in chat view) to attach.
  // Uses a counter to handle dragenter/dragleave firing on every child element.
  const dropOverlay = document.getElementById('drop-overlay');
  let _dragCounter = 0;
  const _isFileDrag = e => e.dataTransfer && Array.from(e.dataTransfer.types || []).includes('Files');
  window.addEventListener('dragenter', e => {
    if (!_isFileDrag(e) || activeView !== 'chat') return;
    e.preventDefault();
    _dragCounter++;
    dropOverlay.classList.add('active');
  });
  window.addEventListener('dragleave', e => {
    if (!_isFileDrag(e)) return;
    _dragCounter--;
    if (_dragCounter <= 0) {
      _dragCounter = 0;
      dropOverlay.classList.remove('active');
    }
  });
  window.addEventListener('dragover', e => {
    if (!_isFileDrag(e) || activeView !== 'chat') return;
    e.preventDefault();
  });
  window.addEventListener('drop', e => {
    if (!_isFileDrag(e)) return;
    e.preventDefault();
    _dragCounter = 0;
    dropOverlay.classList.remove('active');
    if (activeView !== 'chat') return;
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFiles(e.dataTransfer.files);
    }
  });

  const textarea = document.getElementById('message-input');
  textarea.addEventListener('input', () => {
    autoResize(textarea);
    updateSendButton();
    updateCommandTooltip();
  });
  textarea.addEventListener('keydown', handleInputKeydown);
  textarea.addEventListener('blur', () => {
    if (!_cmdMouseDown) setTimeout(hideCommandTooltip, 100);
  });

  document.getElementById('send-btn').addEventListener('click', () => {
    if (isStreaming) stopChatStream();
    else             sendMessage();
  });

  document.getElementById('btn-save-or').addEventListener('click', saveOpenRouter);
  document.getElementById('or-active-toggle')?.addEventListener('change', e => setOrActive(e.target.checked));
  document.getElementById('btn-update').addEventListener('click', runUpdate);
  document.getElementById('btn-clear-all-chats').addEventListener('click', clearAllChats);

  // Close modals on overlay click
  document.querySelectorAll('.modal-overlay').forEach(overlay => {
    overlay.addEventListener('click', e => {
      if (e.target === overlay) overlay.classList.add('hidden');
    });
  });

  setupForgeListeners();
  setupScoutListeners();
}

// ── Forge ─────────────────────────────────────────────────────────────────────

function switchView(view) {
  activeView = view;
  const forgePanelEl = document.getElementById('panel-forge');
  const scoutPanelEl = document.getElementById('panel-scout');
  const chatPanelEl  = document.getElementById('panel-chat');
  const logsPanelEl  = document.getElementById('panel-logs');
  const tabsEl       = document.getElementById('main-tabs');
  const titleEl      = document.getElementById('chat-title');
  const forgeBtn     = document.getElementById('btn-forge');
  const scoutBtn     = document.getElementById('btn-scout');

  // Hide everything first
  chatPanelEl.classList.add('hidden');
  logsPanelEl.classList.add('hidden');
  forgePanelEl.classList.add('hidden');
  scoutPanelEl?.classList.add('hidden');
  forgeBtn.classList.remove('active-nav');
  scoutBtn?.classList.remove('active-nav');

  if (view === 'forge') {
    forgePanelEl.classList.remove('hidden');
    tabsEl.classList.add('hidden');
    titleEl.textContent = 'Forge';
    forgeBtn.classList.add('active-nav');
    loadForgePackInfo();
    loadLintPacks();
  } else if (view === 'scout') {
    scoutPanelEl?.classList.remove('hidden');
    tabsEl.classList.add('hidden');
    titleEl.textContent = 'Scout';
    scoutBtn?.classList.add('active-nav');
    scoutInit();
  } else {
    tabsEl.classList.remove('hidden');
    chatPanelEl.classList.toggle('hidden', activeTab !== 'chat');
    logsPanelEl.classList.toggle('hidden', activeTab !== 'logs');
    const chat = allChats.find(c => c.id === currentChatId);
    titleEl.textContent = chat?.title || 'New Chat';
    document.getElementById('message-input').focus();
  }
}

function setupForgeListeners() {
  const dropZone  = document.getElementById('forge-drop-zone');
  const fileInput = document.getElementById('forge-file-input');

  dropZone.addEventListener('click', e => {
    if (!e.target.closest('.forge-file-remove')) fileInput.click();
  });
  fileInput.addEventListener('change', e => {
    addForgeFiles(e.target.files);
    fileInput.value = '';
  });
  dropZone.addEventListener('dragover',  e => { e.preventDefault(); dropZone.classList.add('drag-over'); });
  dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
  dropZone.addEventListener('drop', e => {
    e.preventDefault();
    dropZone.classList.remove('drag-over');
    addForgeFiles(e.dataTransfer.files);
  });

  document.querySelectorAll('.forge-mode-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.forge-mode-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      forgeMode = btn.dataset.mode;
    });
  });

  const packNameInput = document.getElementById('forge-pack-name');
  let _packDebounce = null;
  packNameInput.addEventListener('input', () => {
    clearTimeout(_packDebounce);
    _packDebounce = setTimeout(loadForgePackInfo, 450);
  });

  document.getElementById('forge-run-btn').addEventListener('click', runForge);
  document.getElementById('forge-reset-btn').addEventListener('click', resetForge);
  document.getElementById('forge-lint-btn').addEventListener('click', () => runLint());
  document.getElementById('forge-clear-output-btn').addEventListener('click', () => {
    document.getElementById('forge-output-body').innerHTML =
      '<span class="log-line system">Waiting for Forge run...</span>';
    _lastLintReport = { packName: '', text: '' };
  });

  initForgeResizer();
}

function initForgeResizer() {
  const resizer = document.getElementById('forge-resizer');
  const formArea = document.querySelector('.forge-form-area');
  const layout = document.querySelector('.forge-layout');
  if (!resizer || !formArea || !layout) return;

  const STORAGE_KEY = 'occ_forge_form_height_px';
  const MIN_FORM = 120;
  const MIN_OUTPUT = 150;

  // Restore the saved height on load
  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved && !isNaN(parseFloat(saved))) {
    formArea.style.height = `${parseFloat(saved)}px`;
    formArea.style.maxHeight = 'none';
  }

  let dragging = false;
  let startY = 0;
  let startH = 0;

  const onDown = (e) => {
    dragging = true;
    startY = e.clientY;
    startH = formArea.getBoundingClientRect().height;
    resizer.classList.add('dragging');
    document.body.style.cursor = 'row-resize';
    document.body.style.userSelect = 'none';
    e.preventDefault();
  };

  const onMove = (e) => {
    if (!dragging) return;
    const layoutH = layout.getBoundingClientRect().height;
    const delta = e.clientY - startY;
    let newH = startH + delta;
    newH = Math.max(MIN_FORM, Math.min(newH, layoutH - MIN_OUTPUT));
    formArea.style.height = `${newH}px`;
    formArea.style.maxHeight = 'none';
  };

  const onUp = () => {
    if (!dragging) return;
    dragging = false;
    resizer.classList.remove('dragging');
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
    const h = parseFloat(formArea.style.height);
    if (!isNaN(h)) localStorage.setItem(STORAGE_KEY, String(h));
  };

  // Double-click resets to the CSS default (clears inline height + storage)
  const onDouble = () => {
    formArea.style.height = '';
    formArea.style.maxHeight = '';
    localStorage.removeItem(STORAGE_KEY);
  };

  resizer.addEventListener('mousedown', onDown);
  window.addEventListener('mousemove', onMove);
  window.addEventListener('mouseup', onUp);
  resizer.addEventListener('dblclick', onDouble);
}

function addForgeFiles(fileList) {
  Array.from(fileList).forEach(file => {
    if (forgeFiles.some(f => f.name === file.name)) return;
    const reader = new FileReader();
    reader.onload = e => {
      const data_b64 = e.target.result.split(',')[1];
      forgeFiles.push({ name: file.name, data_b64 });
      renderForgeFileList();
    };
    reader.readAsDataURL(file);
  });
}

function removeForgeFile(idx) {
  forgeFiles.splice(idx, 1);
  renderForgeFileList();
}

function renderForgeFileList() {
  const list        = document.getElementById('forge-file-list');
  const placeholder = document.getElementById('forge-drop-placeholder');
  list.innerHTML    = '';

  if (!forgeFiles.length) {
    placeholder.style.display = 'flex';
    return;
  }
  placeholder.style.display = 'none';

  forgeFiles.forEach((f, i) => {
    const item   = document.createElement('div');
    item.className = 'forge-file-item';

    const name   = document.createElement('span');
    name.className = 'forge-file-name';
    name.textContent = f.name;

    const remove = document.createElement('button');
    remove.className = 'forge-file-remove';
    remove.textContent = '×';
    remove.addEventListener('click', e => { e.stopPropagation(); removeForgeFile(i); });

    item.appendChild(name);
    item.appendChild(remove);
    list.appendChild(item);
  });
}

async function loadLintPacks() {
  const sel = document.getElementById('forge-lint-pack');
  const current = sel.value;
  const packs = await apiFetch('/api/forge/packs');
  if (!packs) return;
  sel.innerHTML = '<option value="">— select a pack —</option>';
  packs.forEach(p => {
    const opt = document.createElement('option');
    opt.value = p.name;
    opt.textContent = `${p.name}  (${p.source_count} source${p.source_count !== 1 ? 's' : ''})`;
    sel.appendChild(opt);
  });
  if (current && packs.find(p => p.name === current)) sel.value = current;
}

async function loadForgePackInfo() {
  const raw     = document.getElementById('forge-pack-name').value.trim().toLowerCase();
  const packName = raw.replace(/[^a-z0-9-]/g, '-').replace(/^-+|-+$/g, '');
  const infoEl  = document.getElementById('forge-pack-info');

  if (!packName) {
    infoEl.className = 'forge-pack-info';
    infoEl.textContent = '';
    return;
  }

  const packs = await apiFetch('/api/forge/packs');
  if (!packs) return;

  // populate datalist for autocomplete
  const dl = document.getElementById('forge-pack-list');
  if (dl) {
    dl.innerHTML = '';
    packs.forEach(p => {
      const opt = document.createElement('option');
      opt.value = p.name;
      dl.appendChild(opt);
    });
  }

  const pack = packs.find(p => p.name === packName);
  if (!pack) {
    infoEl.className = 'forge-pack-info';
    infoEl.textContent = 'New pack — will be created on first run.';
    return;
  }

  if (!pack.source_count) {
    infoEl.className = 'forge-pack-info';
    infoEl.textContent = pack.raw_count
      ? `● Pack exists — ${pack.raw_count} raw source${pack.raw_count !== 1 ? 's' : ''} ready (use Recompile from Raw).`
      : '● Pack exists — no sources yet.';
    return;
  }

  const lastFetched = pack.sources.length > 0 ? pack.sources[pack.sources.length - 1].fetched : null;
  infoEl.className = 'forge-pack-info has-content';
  infoEl.textContent =
    `● ${pack.source_count} source${pack.source_count !== 1 ? 's' : ''} ingested` +
    (lastFetched ? ` · last: ${lastFetched}` : '');
}

async function runForge() {
  if (forgeRunning) return;

  const packName = document.getElementById('forge-pack-name').value.trim();
  if (!packName) {
    appendForgeOutput('❌ Enter a pack name.', 'error');
    return;
  }

  const extractModel = document.getElementById('forge-extract-model').value;
  const model  = document.getElementById('forge-model').value;
  const fetchImagesEl = document.getElementById('forge-fetch-images');
  const fetchImages = !!(fetchImagesEl && fetchImagesEl.checked);
  const fetchMathEl = document.getElementById('forge-fetch-math');
  const fetchMath = !!(fetchMathEl && fetchMathEl.checked);
  const urls   = document.getElementById('forge-urls').value
    .split('\n').map(u => u.trim()).filter(Boolean);
  const text   = document.getElementById('forge-text').value.trim();

  const modeReusesDiskRaws = forgeMode === 'recompile' || forgeMode === 'resume';
  if (!modeReusesDiskRaws && !forgeFiles.length && !urls.length && !text) {
    appendForgeOutput('❌ No sources provided. Add files, URLs, or paste text.', 'error');
    return;
  }

  forgeRunning = true;
  const runBtn = document.getElementById('forge-run-btn');
  runBtn.disabled = true;
  runBtn.classList.add('running');
  runBtn.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg> Running...`;
  document.getElementById('forge-output-spinner').classList.add('active');

  document.getElementById('forge-output-body').innerHTML = '';

  try {
    const resp = await fetch('/api/forge/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pack_name: packName, mode: forgeMode, extract_model: extractModel, model, files: forgeFiles, urls, text, fetch_images: fetchImages, fetch_math: fetchMath }),
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      appendForgeOutput(`❌ ${err.detail || 'Server error'}`, 'error');
      return;
    }

    const reader  = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop();
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        let data;
        try { data = JSON.parse(line.slice(6)); } catch { continue; }
        if (data.type === 'run_started')      onRunStarted(data);
        else if (data.type === 'run_ended')   onRunEnded(data.status);
        else if (data.text !== undefined)     appendForgeOutput(data.text);
        else if (data.type === 'forge_complete') showForgeActions(data.pack_name);
      }
    }

    await loadForgePackInfo();

  } catch (err) {
    appendForgeOutput(`❌ ${err.message}`, 'error');
  } finally {
    forgeRunning = false;
    runBtn.disabled = false;
    runBtn.classList.remove('running');
    runBtn.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor"><polygon points="5 3 19 12 5 21 5 3"/></svg> Run Forge`;
    document.getElementById('forge-output-spinner').classList.remove('active');
  }
}

function resetForge() {
  document.getElementById('forge-pack-name').value = '';
  document.getElementById('forge-urls').value = '';
  document.getElementById('forge-text').value = '';
  forgeFiles = [];
  renderForgeFileList();
  forgeMode = 'add';
  document.querySelectorAll('.forge-mode-btn').forEach(b => b.classList.remove('active'));
  document.querySelector('.forge-mode-btn[data-mode="add"]').classList.add('active');
  const infoEl = document.getElementById('forge-pack-info');
  infoEl.className = 'forge-pack-info';
  infoEl.textContent = '';
  document.getElementById('forge-output-body').innerHTML =
    '<span class="log-line system">Waiting for Forge run...</span>';
}

function appendForgeOutput(text) {
  const body = document.getElementById('forge-output-body');
  const line = document.createElement('span');

  let cls = 'log-line system';
  if (text.includes('❌'))      cls = 'log-line error';
  else if (text.includes('✅') || text.includes('🎉')) cls = 'log-line ok';
  else if (text.includes('⚠️')) cls = 'log-line warn';
  else if (text.startsWith('\n━') || text.startsWith('━')) cls = 'log-line node';

  line.className   = cls;
  line.textContent = text;
  body.appendChild(line);
  body.appendChild(document.createTextNode('\n'));

  const nearBottom = body.scrollHeight - body.scrollTop - body.clientHeight < 80;
  if (nearBottom) body.scrollTop = body.scrollHeight;
}

function showForgeActions(packName) {
  const body = document.getElementById('forge-output-body');
  const panel = document.createElement('div');
  panel.className = 'forge-complete-panel';
  panel.innerHTML = `
    <div class="forge-complete-title">Pack <strong>${packName}</strong> ready.</div>
    <div class="forge-complete-btns">
      <button class="forge-act-btn forge-act-primary" onclick="forgeReloadPacks('${packName}', this)">↺ Load into Node</button>
      <button class="forge-act-btn" onclick="runLint('${packName}')">⊙ Lint this Pack</button>
      <button class="forge-act-btn" onclick="window.open('https://www.opencognitivecommons.org/packs','_blank')">↑ Submit to Community</button>
      <button class="forge-act-btn" onclick="forgeOpenFolder('${packName}')">⬚ Open Folder</button>
    </div>
    <div class="forge-complete-note">Submit: indicate which node you want to propose it under.</div>
    <div class="forge-complete-note">To query this pack locally, enable <strong>Local mode</strong> via <code>/local on</code> or in Settings.</div>
  `;
  body.appendChild(panel);
  body.scrollTop = body.scrollHeight;
}

async function forgeReloadPacks(packName, btn) {
  btn.disabled = true;
  btn.textContent = '↻ Loading...';
  const r = await apiFetch('/api/forge/reload-packs', { method: 'POST' });
  if (r && r.ok) {
    btn.textContent = `✓ Loaded (${r.packs} pack${r.packs !== 1 ? 's' : ''})`;
    btn.classList.add('forge-act-success');
  } else {
    btn.textContent = '❌ Failed';
    btn.disabled = false;
  }
}

async function forgeOpenFolder(packName) {
  await apiFetch(`/api/forge/open-folder/${encodeURIComponent(packName)}`, { method: 'POST' });
}

let _lastLintReport = { packName: '', text: '' };

async function runLint(packNameOverride = null) {
  const packName = packNameOverride || document.getElementById('forge-lint-pack').value;
  if (!packName) {
    appendForgeOutput('❌ Select a pack to lint.', 'error');
    return;
  }

  const lintModelSelect = document.getElementById('forge-lint-model');
  const model = (lintModelSelect && lintModelSelect.value)
    || document.getElementById('forge-model').value;  // fallback to writing model
  const fixCheckbox = document.getElementById('forge-lint-fix');
  const fix = !!(fixCheckbox && fixCheckbox.checked);
  const lintBtn = document.getElementById('forge-lint-btn');
  if (lintBtn) { lintBtn.disabled = true; lintBtn.textContent = 'Running...'; }

  document.getElementById('forge-output-body').innerHTML = '';
  document.getElementById('forge-output-spinner').classList.add('active');
  _lastLintReport = { packName, text: '' };
  appendForgeOutput(`🔍 Linting pack: ${packName} with ${model}${fix ? ' (auto-fix ON)' : ''}...`);

  try {
    const resp = await fetch('/api/forge/lint', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pack_name: packName, model, fix }),
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      appendForgeOutput(`❌ ${err.detail || 'Server error'}`, 'error');
      return;
    }

    const reader  = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop();
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        let data;
        try { data = JSON.parse(line.slice(6)); } catch { continue; }
        if (data.type === 'run_started')      onRunStarted(data);
        else if (data.type === 'run_ended')   onRunEnded(data.status);
        else if (data.text !== undefined) {
          appendForgeOutput(data.text);
          _lastLintReport.text += data.text + '\n';
        } else if (data.type === 'lint_complete') {
          showLintComplete(data.pack_name);
        }
      }
    }
  } catch (err) {
    appendForgeOutput(`❌ ${err.message}`, 'error');
  } finally {
    if (lintBtn) { lintBtn.disabled = false; lintBtn.innerHTML = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/></svg> Run Lint'; }
    document.getElementById('forge-output-spinner').classList.remove('active');
  }
}

function showLintComplete(packName) {
  const body = document.getElementById('forge-output-body');
  const panel = document.createElement('div');
  panel.className = 'forge-complete-panel';
  panel.innerHTML = `
    <div class="forge-complete-title">Lint complete for <strong>${packName}</strong>.</div>
    <div class="forge-complete-btns">
      <button class="forge-act-btn forge-act-primary" id="lint-download-act">📥 Download report</button>
      <button class="forge-act-btn" id="lint-rerun-act">↻ Re-run Lint</button>
      <button class="forge-act-btn" id="lint-open-folder-act">⬚ Open Pack Folder</button>
    </div>
    <div class="forge-complete-note">Download the report as Markdown to share with collaborators or attach to a community vote.</div>
  `;
  body.appendChild(panel);
  body.scrollTop = body.scrollHeight;

  const dl = document.getElementById('lint-download-act');
  if (dl) dl.addEventListener('click', downloadLintReport);
  const rerun = document.getElementById('lint-rerun-act');
  if (rerun) rerun.addEventListener('click', () => runLint(packName));
  const open = document.getElementById('lint-open-folder-act');
  if (open) open.addEventListener('click', () => forgeOpenFolder(packName));
}

function downloadLintReport() {
  const { packName, text } = _lastLintReport;
  if (!text.trim()) return;
  const stamp = new Date().toISOString().slice(0, 10);
  const { verdictMd, body } = _transformLintForDownload(text);
  const header =
    `# Lint Report — ${packName || 'pack'}\n` +
    `Date: ${stamp}\n` +
    `Generated by OCC Forge.\n\n`;
  const full = verdictMd
    ? `${header}${verdictMd}\n\n---\n\n${body.trim()}\n`
    : `${header}---\n\n${body.trim()}\n`;
  const blob = new Blob([full], { type: 'text/markdown;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `lint-${packName || 'pack'}-${stamp}.md`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// Extract the terminal-style verdict banner, render it as clean markdown for
// the top of the downloaded file, and strip it (plus the UI hint line) from
// the body. The live terminal stays as-is.
function _transformLintForDownload(text) {
  const bannerRe = /═{20,}[\s\S]*?VERDICT[\s\S]*?═{20,}/;
  const match = text.match(bannerRe);
  if (!match) return { verdictMd: '', body: text };

  const block = match[0];
  let verdictLine = '';
  const stats = [];
  for (const raw of block.split('\n')) {
    const line = raw.trim();
    const v = line.match(/^VERDICT\s+(.+)/i);
    if (v) { verdictLine = v[1].trim(); continue; }
    const s = line.match(/^(Mechanical|Semantic|Auto-fixed):\s*(.+)/i);
    if (s) stats.push(`- **${s[1]}:** ${s[2].trim()}`);
  }
  if (!verdictLine) return { verdictMd: '', body: text };

  const verdictMd =
    `## Verdict: ${verdictLine}\n\n` +
    (stats.length ? stats.join('\n') + '\n' : '');

  // Remove the banner from the body, plus the "Click download above" UI hint.
  let body = text.replace(bannerRe, '');
  body = body.replace(/^\s*→\s*Click\s+"download".*\n?/gim, '');
  return { verdictMd, body };
}

// ── Input / textarea ──────────────────────────────────────────────────────────

const INPUT_MIN_H = 26;

function autoResize(el) {
  el.style.height = INPUT_MIN_H + 'px';
  const newH = Math.min(el.scrollHeight, 200);
  el.style.height = newH + 'px';
  el.style.overflowY = el.scrollHeight > 200 ? 'auto' : 'hidden';
}

function resetInputHeight(el) {
  el.style.height = INPUT_MIN_H + 'px';
  el.style.overflowY = 'hidden';
}

function handleInputKeydown(e) {
  const t = document.getElementById('cmd-tooltip');
  const tooltipOpen = t && !t.classList.contains('hidden');

  if (tooltipOpen) {
    if (e.key === 'ArrowDown') { e.preventDefault(); navigateCmdTooltip(1); return; }
    if (e.key === 'ArrowUp')   { e.preventDefault(); navigateCmdTooltip(-1); return; }
    if (e.key === 'Tab')       { e.preventDefault(); navigateCmdTooltip(1); return; }
    if (e.key === 'Escape')    { e.preventDefault(); hideCommandTooltip(); return; }
    if (e.key === 'Enter' && selectCmdTooltip()) { e.preventDefault(); return; }
  }

  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    if (!isStreaming) sendMessage();
  }
}

function updateSendButton() {
  const textarea = document.getElementById('message-input');
  const btn = document.getElementById('send-btn');
  const hasContent = textarea.value.trim().length > 0 || attachments.length > 0;
  if (isStreaming) {
    // Show as STOP — always enabled, always clickable
    btn.disabled = false;
    btn.title = 'Stop generation';
  } else {
    btn.disabled = !hasContent;
    btn.title = 'Send (Enter)';
  }
}

function setStreamingState(active) {
  isStreaming = active;
  const btn = document.getElementById('send-btn');
  if (btn) btn.classList.toggle('is-stop', active);
  updateSendButton();
  const sidebar = document.querySelector('.sidebar');
  if (sidebar) sidebar.classList.toggle('is-streaming', active);
}

async function stopChatStream() {
  if (!currentChatId) return;
  const btn = document.getElementById('send-btn');
  if (btn) btn.disabled = true;          // brief disable while server cleans up
  try {
    await fetch(`/api/chats/${currentChatId}/stop`, { method: 'POST' });
  } catch (e) {
    // ignore — the stream may already be ending
  }
  // setStreamingState(false) will be called by the existing finally{} once the
  // server closes the stream cleanly with the partial answer saved.
}

// ── File attachments ─────────────────────────────────────────────────────────

function handleFiles(files) {
  Array.from(files).forEach(file => {
    const reader = new FileReader();
    reader.onload = e => {
      attachments.push({ name: file.name, type: file.type, data: e.target.result });
      renderAttachmentsPreview();
      updateSendButton();
    };
    reader.readAsDataURL(file);
  });
  document.getElementById('file-input').value = '';
}

function removeAttachment(idx) {
  attachments.splice(idx, 1);
  renderAttachmentsPreview();
  updateSendButton();
}

function renderAttachmentsPreview() {
  const container = document.getElementById('attachments-preview');
  container.innerHTML = '';
  attachments.forEach((att, i) => {
    const chip = document.createElement('div');
    chip.className = 'att-preview-chip';
    if (att.type.startsWith('image/')) {
      const img = document.createElement('img');
      img.src = att.data;
      img.className = 'att-preview-img';
      chip.appendChild(img);
    } else {
      chip.appendChild(icon('📄'));
    }
    const name = document.createElement('span');
    name.textContent = att.name;
    chip.appendChild(name);
    const del = document.createElement('button');
    del.className = 'att-remove';
    del.textContent = '×';
    del.addEventListener('click', () => removeAttachment(i));
    chip.appendChild(del);
    container.appendChild(chip);
  });
}

// ── Chat CRUD ─────────────────────────────────────────────────────────────────

async function loadChats() {
  const data = await apiFetch('/api/chats');
  if (!data) return;
  allChats = data;
  renderChatList(allChats);
}

async function newChat() {
  if (isStreaming) return;
  if (activeView !== 'chat') switchView('chat');
  const data = await apiFetch('/api/chats', { method: 'POST' });
  if (!data) return;
  await loadChats();
  await selectChat(data.id);
}

async function selectChat(id) {
  if (isStreaming) return;
  if (activeView !== 'chat') switchView('chat');
  currentChatId = id;

  // Update active state in sidebar
  document.querySelectorAll('.chat-item').forEach(el => {
    el.classList.toggle('active', el.dataset.id === id);
  });

  resetCtxBar();

  // Load chat title
  const chat = allChats.find(c => c.id === id);
  document.getElementById('chat-title').textContent = chat?.title || 'New Chat';

  // Load full chat with messages
  const full = await apiFetch(`/api/chats/${id}`);
  if (!full) return;

  // Activate chat in engine (restore history)
  await apiFetch(`/api/chats/${id}/activate`, { method: 'POST' });

  renderMessages(full.messages);
}

async function deleteChat(id, e) {
  e.stopPropagation();
  if (isStreaming) return;
  await apiFetch(`/api/chats/${id}`, { method: 'DELETE' });
  if (currentChatId === id) {
    currentChatId = null;
    clearMessages();
    document.getElementById('chat-title').textContent = 'New Chat';
  }
  await loadChats();
}

function filterChats(query) {
  const q = query.toLowerCase();
  const filtered = q
    ? allChats.filter(c => c.title.toLowerCase().includes(q))
    : allChats;
  renderChatList(filtered);
}

function startRename(id, currentTitle, titleSpan) {
  const input = document.createElement('input');
  input.value = currentTitle;
  input.style.cssText = 'flex:1;min-width:0;background:transparent;border:none;outline:1px solid var(--border-active);border-radius:2px;color:var(--text);font-size:0.8125rem;font-family:var(--font-sans);padding:0 2px;';

  let done = false;

  const save = async () => {
    if (done) return;
    done = true;
    const newTitle = input.value.trim() || currentTitle;
    if (newTitle !== currentTitle) {
      await apiFetch(`/api/chats/${id}`, {
        method: 'PATCH',
        body: JSON.stringify({ title: newTitle }),
      });
      if (id === currentChatId) {
        document.getElementById('chat-title').textContent = newTitle;
      }
    }
    await loadChats();
    document.querySelectorAll('.chat-item').forEach(el => {
      el.classList.toggle('active', el.dataset.id === currentChatId);
    });
  };

  const cancel = () => {
    if (done) return;
    done = true;
    const span = document.createElement('span');
    span.className = 'chat-item-title';
    span.textContent = currentTitle;
    input.replaceWith(span);
  };

  titleSpan.replaceWith(input);
  input.focus();
  input.select();

  input.addEventListener('keydown', e => {
    e.stopPropagation();
    if (e.key === 'Enter') { e.preventDefault(); input.blur(); }
    if (e.key === 'Escape') cancel();
  });
  input.addEventListener('blur', save);
  input.addEventListener('click', e => e.stopPropagation());
}

// ── Slash command tooltip ─────────────────────────────────────────────────────

const SLASH_COMMANDS = [
  { cmd: '/clear',          desc: 'Clear conversation history and reset context' },
  { cmd: '/status',         desc: 'Show current config' },
  { cmd: '/packs',          desc: 'List all loaded packs and domains' },
  { cmd: '/peers',          desc: 'Show active peer nodes on the broker' },
  { cmd: '/local on',       desc: 'Use local packs only — for private Forge packs' },
  { cmd: '/local off',      desc: 'Use server packs (default)' },
  { cmd: '/ollama',         desc: 'Toggle raw-Ollama mode: bypass OCC (no classifier, skills, retrieval, tools)' },
  { cmd: '/load',           desc: 'Reload model into VRAM' },
  { cmd: '/unload',         desc: 'Unload model from VRAM' },
  { cmd: '/openrouter on',  desc: 'Switch to OpenRouter (if configured)' },
  { cmd: '/openrouter off', desc: 'Switch to local model' },
];

function updateCommandTooltip() {
  const textarea = document.getElementById('message-input');
  const val = textarea.value;

  if (!val.startsWith('/')) { hideCommandTooltip(); return; }

  const query = val.toLowerCase();
  const matches = SLASH_COMMANDS.filter(c => c.cmd.toLowerCase().startsWith(query));

  if (!matches.length) { hideCommandTooltip(); return; }

  let t = document.getElementById('cmd-tooltip');
  if (!t) {
    t = document.createElement('div');
    t.id = 'cmd-tooltip';
    t.className = 'cmd-tooltip';
    document.querySelector('.input-area').appendChild(t);
  }
  t._matches = matches;
  t.innerHTML = '';
  _cmdIdx = -1;

  matches.forEach(item => {
    const row = document.createElement('div');
    row.className = 'cmd-tooltip-item';
    row.innerHTML = `<span class="cmd-tooltip-cmd">${escapeHtml(item.cmd.trim())}</span><span class="cmd-tooltip-desc">${escapeHtml(item.desc)}</span>`;
    row.addEventListener('mousedown', e => {
      _cmdMouseDown = true;
      e.preventDefault();
      applySlashCommand(item.cmd);
      setTimeout(() => { _cmdMouseDown = false; }, 100);
    });
    t.appendChild(row);
  });

  t.classList.remove('hidden');
}

function hideCommandTooltip() {
  const t = document.getElementById('cmd-tooltip');
  if (t) t.classList.add('hidden');
  _cmdIdx = -1;
}

function applySlashCommand(cmd) {
  const textarea = document.getElementById('message-input');
  textarea.value = cmd;
  autoResize(textarea);
  updateSendButton();
  hideCommandTooltip();
  textarea.focus();
  textarea.selectionStart = textarea.selectionEnd = cmd.length;
}

function navigateCmdTooltip(dir) {
  const t = document.getElementById('cmd-tooltip');
  if (!t || t.classList.contains('hidden') || !t._matches) return false;
  const items = t.querySelectorAll('.cmd-tooltip-item');
  if (!items.length) return false;
  items.forEach(el => el.classList.remove('active'));
  _cmdIdx = (_cmdIdx + dir + items.length) % items.length;
  items[_cmdIdx].classList.add('active');
  return true;
}

function selectCmdTooltip() {
  const t = document.getElementById('cmd-tooltip');
  if (!t || t.classList.contains('hidden') || !t._matches || _cmdIdx < 0) return false;
  applySlashCommand(t._matches[_cmdIdx].cmd);
  return true;
}

function renderChatList(chats) {
  const container = document.getElementById('chat-list');
  container.innerHTML = '';

  if (!chats.length) {
    container.innerHTML = '<div style="padding:0.75rem 1rem;font-size:0.8125rem;color:var(--text-ghost);">No chats yet</div>';
    return;
  }

  const grouped = groupByDate(chats);
  const order = ['Today', 'Yesterday', 'This week', 'Older'];

  order.forEach(label => {
    if (!grouped[label]?.length) return;
    const groupLabel = document.createElement('div');
    groupLabel.className = 'chat-group-label';
    groupLabel.textContent = label;
    container.appendChild(groupLabel);

    grouped[label].forEach(chat => {
      const item = document.createElement('div');
      item.className = 'chat-item' + (chat.id === currentChatId ? ' active' : '');
      item.dataset.id = chat.id;
      item.addEventListener('click', () => selectChat(chat.id));

      const title = document.createElement('span');
      title.className = 'chat-item-title';
      title.textContent = chat.title || 'New Chat';
      item.appendChild(title);

      const renameBtn = document.createElement('button');
      renameBtn.className = 'chat-item-rename';
      renameBtn.title = 'Rename chat';
      renameBtn.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>`;
      renameBtn.addEventListener('click', e => {
        e.stopPropagation();
        startRename(chat.id, chat.title || 'New Chat', title);
      });
      item.appendChild(renameBtn);

      const del = document.createElement('button');
      del.className = 'chat-item-delete';
      del.title = 'Delete chat';
      del.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4h6v2"/></svg>`;
      del.addEventListener('click', e => deleteChat(chat.id, e));
      item.appendChild(del);

      container.appendChild(item);
    });
  });
}

function groupByDate(chats) {
  const now = new Date();
  const today     = startOf(now, 0);
  const yesterday = startOf(now, 1);
  const weekAgo   = startOf(now, 7);

  const groups = { 'Today': [], 'Yesterday': [], 'This week': [], 'Older': [] };
  chats.forEach(c => {
    const d = new Date(c.created_at);
    if (d >= today)          groups['Today'].push(c);
    else if (d >= yesterday) groups['Yesterday'].push(c);
    else if (d >= weekAgo)   groups['This week'].push(c);
    else                     groups['Older'].push(c);
  });
  return groups;
}

function startOf(now, daysAgo) {
  const d = new Date(now);
  d.setDate(d.getDate() - daysAgo);
  d.setHours(0, 0, 0, 0);
  return d;
}

// ── Message rendering ────────────────────────────────────────────────────────

function clearMessages() {
  const container = document.getElementById('messages');
  container.innerHTML = `
    <div class="empty-state" id="empty-state">
      <div class="empty-logo">OCC</div>
      <div class="empty-tagline">Ask anything. The network is listening.</div>
    </div>`;
}

function hideEmptyState() {
  const el = document.getElementById('empty-state');
  if (el) el.remove();
}

function renderMessages(messages) {
  clearMessages();
  if (!messages?.length) return;
  messages.forEach(msg => appendMessageToUI(msg));
  scrollToBottom();
}

function appendMessageToUI(msg) {
  hideEmptyState();
  const container = document.getElementById('messages');

  if (msg.role === 'user') {
    const row = document.createElement('div');
    row.className = 'message-row user';
    const bubble = document.createElement('div');
    bubble.className = 'user-bubble';
    bubble.textContent = msg.content;

    if (msg.attachments?.length) {
      const chips = document.createElement('div');
      chips.className = 'attachment-chips';
      msg.attachments.forEach(att => {
        if (att.type?.startsWith('image/')) {
          const img = document.createElement('img');
          img.src = att.data;
          img.className = 'attachment-img-preview';
          bubble.appendChild(img);
        } else {
          const chip = document.createElement('span');
          chip.className = 'attachment-chip';
          chip.textContent = '📄 ' + att.name;
          chips.appendChild(chip);
        }
      });
      if (chips.children.length) bubble.appendChild(chips);
    }
    row.appendChild(bubble);
    container.appendChild(row);

  } else if (msg.role === 'assistant') {
    const row = createAssistantRow(msg.id || 'msg-' + Date.now(), msg.routing || '');
    row.querySelector('.assistant-body').innerHTML = renderMarkdown(msg.content);
    if (msg.tools?.length) {
      const header = row.querySelector('.assistant-header');
      msg.tools.forEach(label => {
        const badge = document.createElement('span');
        badge.className = 'tool-badge';
        badge.dataset.tool = label;
        badge.textContent = label;
        header.appendChild(badge);
      });
    }
    container.appendChild(row);
    if (msg.peer_answers) {
      addSourcesButton(msg.id || 'msg-' + Date.now(), msg.peer_answers);
    }
  }
}

function createAssistantRow(msgId, routing) {
  const row = document.createElement('div');
  row.className = 'message-row assistant';
  row.id = 'row-' + msgId;

  const content = document.createElement('div');
  content.className = 'assistant-content';

  const header = document.createElement('div');
  header.className = 'assistant-header';

  const label = document.createElement('span');
  label.className = 'assistant-label';
  label.textContent = 'OCC';
  header.appendChild(label);

  if (routing) {
    const badge = buildRoutingBadge(routing);
    header.appendChild(badge);
  }
  header.id = 'header-' + msgId;

  const body = document.createElement('div');
  body.className = 'assistant-body md-content';
  body.id = 'body-' + msgId;

  const actions = document.createElement('div');
  actions.className = 'msg-actions';

  const copyBtn = document.createElement('button');
  copyBtn.className = 'msg-action-btn';
  copyBtn.textContent = 'copy';
  copyBtn.addEventListener('click', () => {
    const bodyEl = content.querySelector('.assistant-body');
    if (!bodyEl) return;
    navigator.clipboard.writeText(bodyEl.innerText).then(() => {
      copyBtn.textContent = 'copied!';
      setTimeout(() => { copyBtn.textContent = 'copy'; }, 1500);
    });
  });
  actions.appendChild(copyBtn);

  content.appendChild(header);
  content.appendChild(body);
  content.appendChild(actions);
  row.appendChild(content);
  return row;
}

function buildRoutingBadge(routing) {
  const badge = document.createElement('span');
  badge.className = `routing-badge ${routing}`;
  const labels = {
    chat: 'chat',
    local: 'server + local',
    local_private: 'local · private',
    local_fallback: 'offline · no knowledge',
    distributed: 'network',
  };
  badge.textContent = labels[routing] || routing;
  return badge;
}

function addLoadingMessage(msgId) {
  hideEmptyState();
  const container = document.getElementById('messages');
  const row = createAssistantRow(msgId, '');

  const statusLine = document.createElement('div');
  statusLine.className = 'status-line';
  statusLine.id = 'status-' + msgId;
  statusLine.innerHTML = `<span class="status-dot"></span><span id="status-text-${msgId}">Thinking...</span>`;

  const logContainer = document.createElement('div');
  logContainer.className = 'status-log';
  logContainer.id = 'status-log-' + msgId;

  const body = row.querySelector('.assistant-body');
  body.appendChild(statusLine);
  body.appendChild(logContainer);
  container.appendChild(row);
  scrollToBottom();
  _startWordCycle(msgId, 'Thinking');
}

function appendStatusLog(msgId, text) {
  const log = document.getElementById('status-log-' + msgId);
  if (!log) return;
  const prev = log.querySelectorAll('.status-log-line');
  prev.forEach(l => l.classList.remove('active'));
  const line = document.createElement('div');
  line.className = 'status-log-line active';
  line.innerHTML = `<span class="status-log-connector">└─</span><span class="status-log-text">${escapeHtml(text.replace(/\.+$/, ''))}</span>`;
  log.appendChild(line);
  scrollToBottom();
}

const _OCC_WORDS = [
  'combombulating', 'hoolaballooing', 'noodling', 'percolating', 'cogitating',
  'ruminating', 'reticulating', 'deliberating', 'crystallizing', 'triangulating',
  'distilling', 'extrapolating', 'marinating', 'oscillating', 'synthesizing',
  'perambulating', 'discombobulating', 'flibbertigibeting', 'kerplunking',
  'bamboozling', 'hornswoggling', 'skedaddling', 'lollygagging', 'whiffling',
];
let _wordTimer = null;
let _wordIdx = 0;
let _wordMsgId = null;
let _statusLabel = '';

function _startWordCycle(msgId, label) {
  _stopWordCycle();
  _wordMsgId = msgId;
  _statusLabel = label;
  _wordIdx = Math.floor(Math.random() * _OCC_WORDS.length);
  function tick() {
    const el = document.getElementById('status-text-' + _wordMsgId);
    if (el) el.textContent = `${_OCC_WORDS[_wordIdx % _OCC_WORDS.length]}...`;
    _wordIdx++;
    _wordTimer = setTimeout(tick, 5000);
  }
  tick();
}

function _stopWordCycle() {
  if (_wordTimer) { clearTimeout(_wordTimer); _wordTimer = null; }
  _wordMsgId = null;
}

function updateStatusText(msgId, text) {
  const el = document.getElementById('status-text-' + msgId);
  if (el) el.textContent = text;
  _startWordCycle(msgId, text.replace(/\.*$/, '').trim());
}

function updateRoutingBadgeUI(msgId, routing) {
  const header = document.getElementById('header-' + msgId);
  if (!header) return;
  const existing = header.querySelector('.routing-badge');
  if (existing) existing.remove();
  if (routing) {
    const firstToolBadge = header.querySelector('.tool-badge');
    if (firstToolBadge) {
      header.insertBefore(buildRoutingBadge(routing), firstToolBadge);
    } else {
      header.appendChild(buildRoutingBadge(routing));
    }
  }
}

function addSourcesButton(msgId, peerData) {
  const row = document.getElementById('row-' + msgId);
  if (!row) return;
  const actions = row.querySelector('.msg-actions');
  if (!actions || actions.querySelector('.sources-btn')) return;

  const btn = document.createElement('button');
  btn.className = 'msg-action-btn sources-btn';
  btn.textContent = 'sources';
  btn.addEventListener('click', () => {
    const content = row.querySelector('.assistant-content');
    let panel = content.querySelector('.sources-panel');
    if (!panel) {
      panel = buildSourcesPanel(peerData);
      content.insertBefore(panel, actions);
    }
    const open = panel.classList.toggle('open');
    btn.classList.toggle('active', open);
  });
  actions.insertBefore(btn, actions.firstChild);
}

function buildSourcesPanel(data) {
  const panel = document.createElement('div');
  panel.className = 'sources-panel';

  // ── Web search sources ────────────────────────────────────────────────────
  if (data.mode === 'web') {
    if (Array.isArray(data.web_sources) && data.web_sources.length > 0) {
      panel.appendChild(buildWebSourcesBlock(data.web_sources));
    }
    return panel;
  }

  // ── Retrieved sources (collapsible) ──────────────────────────────────────
  if (Array.isArray(data.sources) && data.sources.length > 0) {
    panel.appendChild(buildRetrievedSourcesBlock(data.sources));
  }

  const expertLabel = data.mode === 'network' ? 'Expert — local' : 'Expert — draft';
  const criticLabel = data.mode === 'network'
    ? `Critic — peer (${data.peer_tier || 'remote'})`
    : 'Critic — review';

  [
    { label: expertLabel, text: data.expert_draft, role: 'local' },
    { label: criticLabel, text: data.critic_review, role: 'expert' },
  ].forEach(b => {
    const block = document.createElement('div');
    block.className = `source-block role-${b.role}`;
    const lbl = document.createElement('div');
    lbl.className = 'source-label';
    lbl.textContent = b.label;
    const body = document.createElement('div');
    body.className = 'source-body md-content';
    body.innerHTML = b.text
      ? renderMarkdown(b.text)
      : '<em style="opacity:0.45;font-size:0.85em">No output generated.</em>';
    block.appendChild(lbl);
    block.appendChild(body);
    panel.appendChild(block);
  });

  return panel;
}

function buildWebSourcesBlock(sources) {
  const block = document.createElement('div');
  block.className = 'source-block role-retrieved';

  const header = document.createElement('button');
  header.type = 'button';
  header.className = 'retrieved-sources-toggle';
  header.innerHTML =
    `<span class="caret">▸</span>` +
    `<span class="retrieved-sources-label">Web sources</span>` +
    `<span class="retrieved-sources-count">${sources.length} result${sources.length === 1 ? '' : 's'}</span>`;

  const list = document.createElement('div');
  list.className = 'retrieved-sources-list';

  sources.forEach(s => {
    const item = document.createElement('div');
    item.className = 'retrieved-source-item';
    const link = document.createElement('a');
    link.href = s.url;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.className = 'retrieved-source-path';
    link.textContent = s.url;
    item.appendChild(link);
    if (s.title && s.title !== s.url) {
      const title = document.createElement('div');
      title.className = 'retrieved-source-title';
      title.textContent = s.title;
      item.appendChild(title);
    }
    list.appendChild(item);
  });

  header.addEventListener('click', () => { block.classList.toggle('open'); });
  block.appendChild(header);
  block.appendChild(list);
  return block;
}

function buildRetrievedSourcesBlock(sources) {
  const block = document.createElement('div');
  block.className = 'source-block role-retrieved';

  const packs = new Set(sources.map(s => s.pack));
  const header = document.createElement('button');
  header.type = 'button';
  header.className = 'retrieved-sources-toggle';
  header.innerHTML =
    `<span class="caret">▸</span>` +
    `<span class="retrieved-sources-label">Sources from server</span>` +
    `<span class="retrieved-sources-count">${sources.length} page${sources.length === 1 ? '' : 's'}, ${packs.size} pack${packs.size === 1 ? '' : 's'}</span>`;

  const list = document.createElement('div');
  list.className = 'retrieved-sources-list';

  sources.forEach(s => {
    const item = document.createElement('div');
    item.className = 'retrieved-source-item';
    const path = document.createElement('div');
    path.className = 'retrieved-source-path';
    path.textContent = `${s.pack}/${s.file}`;
    const title = document.createElement('div');
    title.className = 'retrieved-source-title';
    title.textContent = s.title || s.file;
    const snippet = document.createElement('div');
    snippet.className = 'retrieved-source-snippet';
    snippet.textContent = (s.snippet || s.summary || '').trim();
    item.appendChild(path);
    item.appendChild(title);
    if (snippet.textContent) item.appendChild(snippet);
    list.appendChild(item);
  });

  header.addEventListener('click', () => {
    block.classList.toggle('open');
  });

  block.appendChild(header);
  block.appendChild(list);
  return block;
}

function addToolBadge(msgId, label) {
  const header = document.getElementById('header-' + msgId);
  if (!header) return;
  if (header.querySelector(`.tool-badge[data-tool="${label}"]`)) return;
  const badge = document.createElement('span');
  badge.className = 'tool-badge';
  badge.dataset.tool = label;
  badge.textContent = label;
  header.appendChild(badge);
}

function renderFileWrittenToast(msgId, filename, folder) {
  // Inserts a small inline card under the streaming message header,
  // telling the user a file landed and offering a one-click open.
  // The assistant message DOM tree is rooted at id `row-${msgId}`
  // (see createAssistantRow), with the body at `body-${msgId}`. The
  // toast goes between header and body so it reads as a status line.
  const row = document.getElementById('row-' + msgId);
  if (!row) return;
  const existing = row.querySelector(`.file-toast[data-fname="${CSS.escape(filename)}"]`);
  if (existing) return;
  const body = document.getElementById('body-' + msgId);
  const toast = document.createElement('div');
  toast.className = 'file-toast';
  toast.dataset.fname = filename;
  const safeFolder = folder === 'upload' ? 'upload' : 'workspace';
  toast.innerHTML = `
    <span class="file-toast-icon">📁</span>
    <span class="file-toast-text">
      <code>${escapeHtml(filename)}</code>
      saved to <strong>${safeFolder}</strong>
    </span>
    <button class="file-toast-btn" type="button">Open folder</button>
  `;
  toast.querySelector('.file-toast-btn').addEventListener('click', (e) => {
    e.preventDefault();
    openServiceFolder(safeFolder);
  });
  if (body && body.parentNode) {
    body.parentNode.insertBefore(toast, body);
  } else {
    row.appendChild(toast);
  }
  scrollToBottom();
}

function updateStreamingBody(msgId, tokens) {
  const body = document.getElementById('body-' + msgId);
  if (!body) return;
  const status = document.getElementById('status-' + msgId);
  if (status) status.remove();
  const log = document.getElementById('status-log-' + msgId);
  if (log) log.remove();
  body.innerHTML = renderMarkdown(tokens) + '<span class="cursor-blink"></span>';
  scrollToBottom();
}

function finalizeMessage(msgId, fullText, routing) {
  const body = document.getElementById('body-' + msgId);
  if (!body) return;
  body.innerHTML = renderMarkdown(fullText);
  const status = document.getElementById('status-' + msgId);
  if (status) status.remove();
  if (routing) updateRoutingBadgeUI(msgId, routing);
  scrollToBottom();
}

function scrollToBottom() {
  const msgs = document.getElementById('messages');
  msgs.scrollTop = msgs.scrollHeight;
}

// ── Send message ─────────────────────────────────────────────────────────────

async function sendMessage() {
  const textarea = document.getElementById('message-input');
  const message = textarea.value.trim();
  if (!message && !attachments.length) return;
  if (isStreaming) return;

  // ── Slash command ──────────────────────────────────────────────────────────
  if (message.startsWith('/')) {
    textarea.value = '';
    resetInputHeight(textarea);
    updateSendButton();
    appendCommandInput(message);
    const data = await apiFetch('/api/command', {
      method: 'POST',
      body: JSON.stringify({ command: message }),
    });
    appendCommandResult(data?.output ?? 'No response from server.');
    if (message === '/clear') resetCtxBar();
    if (message === '/openrouter on')  { const c = await apiFetch('/api/config'); if (c) { config = c; updateProviderBadge(!!c.openrouter_configured, c.openrouter_model); } }
    if (message === '/openrouter off') { if (config) config.openrouter_configured = false; updateProviderBadge(false); }
    return;
  }

  const sendAttachments = [...attachments];

  // ── Force-deliberate prefix (!) ────────────────────────────────────────────
  let forcedMode = 'auto';
  let actualMessage = message;
  if (message.startsWith('!')) {
    forcedMode = 'network';
    actualMessage = message.slice(1).trim();
  }

  // Clear input
  textarea.value = '';
  resetInputHeight(textarea);
  attachments = [];
  renderAttachmentsPreview();
  updateSendButton();

  // Ensure a chat exists
  if (!currentChatId) {
    const data = await apiFetch('/api/chats', { method: 'POST' });
    if (!data) return;
    currentChatId = data.id;
    await loadChats();
    // Activate (no messages yet)
    await apiFetch(`/api/chats/${currentChatId}/activate`, { method: 'POST' });
  }

  // Show user message in UI immediately
  appendMessageToUI({ role: 'user', content: message, attachments: sendAttachments });

  const msgId = 'streaming-' + Date.now();
  addLoadingMessage(msgId);

  setStreamingState(true);

  let tokens = '';
  let routingMode = '';
  let renderTimer = null;

  function scheduleRender() {
    if (renderTimer) return;
    renderTimer = setTimeout(() => {
      renderTimer = null;
      updateStreamingBody(msgId, tokens);
    }, 50);
  }

  try {
    const resp = await fetch(`/api/chats/${currentChatId}/query`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: actualMessage, mode: forcedMode, attachments: sendAttachments }),
    });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      throw new Error(err.detail || 'Server error');
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop();

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        let data;
        try { data = JSON.parse(line.slice(6)); } catch { continue; }

        if (data.type === 'routing') {
          routingMode = data.value;
          updateRoutingBadgeUI(msgId, routingMode);
        } else if (data.type === 'tool_used') {
          addToolBadge(msgId, data.value);
        } else if (data.type === 'file_written') {
          // Inline toast inside the chat thread: a small clickable card
          // telling the user a file landed in ~/.occ/state/<folder>/ and
          // offering a one-click Open button. Renders right under the
          // streaming message so it's seen in context, not buried in a
          // notification corner.
          const fname = data.value?.filename || '';
          const folder = data.value?.folder || 'workspace';
          if (fname) renderFileWrittenToast(msgId, fname, folder);
        } else if (data.type === 'peer_answers') {
          addSourcesButton(msgId, data.value);
        } else if (data.type === 'status') {
          updateStatusText(msgId, data.value);
          appendStatusLog(msgId, data.value);
        } else if (data.type === 'token') {
          _stopWordCycle();
          tokens += data.value;
          scheduleRender();
        } else if (data.type === 'done') {
          if (renderTimer) { clearTimeout(renderTimer); renderTimer = null; }
          finalizeMessage(msgId, tokens, data.routing || routingMode);
          updateCtxBar(data.ctx_used || 0, data.ctx_limit || 0);
          // Refresh chat list to update title
          await loadChats();
          document.querySelectorAll('.chat-item').forEach(el => {
            el.classList.toggle('active', el.dataset.id === currentChatId);
          });
          const updated = allChats.find(c => c.id === currentChatId);
          if (updated) document.getElementById('chat-title').textContent = updated.title;
        } else if (data.type === 'error') {
          const body = document.getElementById('body-' + msgId);
          if (body) body.innerHTML = `<span style="color:var(--red)">Error: ${escapeHtml(data.value)}</span>`;
        }
      }
    }
  } catch (err) {
    const body = document.getElementById('body-' + msgId);
    if (body) body.innerHTML = `<span style="color:var(--red)">Error: ${escapeHtml(err.message)}</span>`;
  } finally {
    setStreamingState(false);
    textarea.focus();
  }
}

// ── Command display ───────────────────────────────────────────────────────────

function appendCommandInput(cmd) {
  hideEmptyState();
  const container = document.getElementById('messages');
  const row = document.createElement('div');
  row.className = 'message-row command-input-row';
  row.innerHTML = `<span class="command-input-label">$</span><span class="command-input-text">${escapeHtml(cmd)}</span>`;
  container.appendChild(row);
  scrollToBottom();
}

function appendCommandResult(text) {
  const container = document.getElementById('messages');
  const row = document.createElement('div');
  row.className = 'message-row command-result-row';
  const pre = document.createElement('pre');
  pre.className = 'command-result';
  pre.textContent = text;
  row.appendChild(pre);
  container.appendChild(row);
  scrollToBottom();
}

// ── Tabs ─────────────────────────────────────────────────────────────────────

function switchTab(tab) {
  activeTab = tab;
  document.getElementById('panel-chat').classList.toggle('hidden', tab !== 'chat');
  document.getElementById('panel-logs').classList.toggle('hidden', tab !== 'logs');
  document.getElementById('tab-chat').classList.toggle('active', tab === 'chat');
  document.getElementById('tab-logs').classList.toggle('active', tab === 'logs');

  if (tab === 'logs' && !logsSource) {
    connectLogs();
  }
  if (tab === 'chat') {
    document.getElementById('message-input').focus();
  }
}

function connectLogs() {
  const body = document.getElementById('log-body');
  body.innerHTML = '';
  logsSource = new EventSource('/api/logs/stream');

  logsSource.onmessage = e => {
    const data = JSON.parse(e.data);
    appendLogLine(data.text);
  };
  logsSource.onerror = () => {
    appendLogLine('[GUI] Log stream disconnected.');
  };
}

function appendLogLine(text) {
  const body = document.getElementById('log-body');
  const line = document.createElement('span');
  line.className = 'log-line ' + classifyLogLine(text);
  line.textContent = text;
  body.appendChild(line);
  body.appendChild(document.createTextNode('\n'));

  logLineCount++;
  document.getElementById('log-counter').textContent = logLineCount + ' lines';

  // Auto-scroll if near bottom
  const nearBottom = body.scrollHeight - body.scrollTop - body.clientHeight < 80;
  if (nearBottom) body.scrollTop = body.scrollHeight;
}

function classifyLogLine(text) {
  if (text.includes('[OCC Node]'))  return 'node';
  if (text.includes('Error') || text.includes('error')) return 'error';
  if (text.includes('OK') || text.includes('ready') || text.includes('✓')) return 'ok';
  if (text.includes('Warning') || text.includes('warning')) return 'warn';
  return 'system';
}

// ── Settings modal ────────────────────────────────────────────────────────────

async function openSettings() {
  const cfg = await apiFetch('/api/config') || config;
  config = cfg;

  // Node Info — model, hardware, context only
  const info = document.getElementById('settings-info');
  info.innerHTML = `
    <div class="settings-info-row"><span class="settings-info-key">Model</span><span class="settings-info-val">${cfg.model || '—'}</span></div>
    <div class="settings-info-row"><span class="settings-info-key">Hardware</span><span class="settings-info-val">${cfg.hardware_profile || '—'} · ${cfg.detected_vram_gb > 0 ? cfg.detected_vram_gb + 'GB VRAM' : 'CPU'}</span></div>
    <div class="settings-info-row" style="border:none"><span class="settings-info-key">Context</span><span class="settings-info-val">${cfg.num_ctx_answer?.toLocaleString() || '—'} tokens</span></div>
  `;

  // Knowledge Source
  const localOn = !!cfg.local_mode;
  const localToggle = document.getElementById('local-mode-toggle');
  if (localToggle) localToggle.checked = localOn;
  _updateSourceSides(localOn);
  _renderPacksList(cfg);

  // OpenRouter — form always visible; toggle = Node inference only
  const orActive = !!cfg.openrouter_configured;
  const orToggle = document.getElementById('or-active-toggle');
  if (orToggle) orToggle.checked = orActive;
  document.getElementById('or-model').value = cfg.openrouter_model || 'qwen/qwen3.5-9b';
  const hint = document.getElementById('or-key-hint');
  if (hint) hint.style.display = cfg.openrouter_key_saved ? 'block' : 'none';

  document.getElementById('settings-modal').classList.remove('hidden');
}

async function clearAllChats() {
  const status = document.getElementById('clear-chats-status');
  if (!confirm('Cancellare tutte le chat? Questa operazione non può essere annullata.')) return;
  if (!confirm('Sei sicuro? Tutte le chat e i file caricati verranno eliminati definitivamente.')) return;
  status.textContent = 'Cancellazione…';
  try {
    await apiFetch('/api/chats', { method: 'DELETE' });
    status.textContent = 'Fatto.';
    setTimeout(() => { status.textContent = ''; }, 3000);
    closeModal('settings-modal');
    await loadChats();
    await newChat();
  } catch (e) {
    status.textContent = 'Errore: ' + e.message;
  }
}

function _updateSourceSides(localOn) {
  document.getElementById('source-server-side')?.classList.toggle('active', !localOn);
  document.getElementById('source-local-side')?.classList.toggle('active',  localOn);
}

function _renderPacksList(cfg) {
  const list = document.getElementById('settings-packs-list');
  if (!list) return;
  // pack_paths is the recursive on-disk truth; cfg.packs is the legacy flat
  // list (kept for the domain count chip).
  const packPaths = cfg.pack_paths || [];
  const disabled = new Set(cfg.disabled_packs || []);
  const domainsByName = {};
  for (const p of (cfg.packs || [])) {
    domainsByName[p.name] = p.domains || [];
  }
  const localOn = !!cfg.local_mode;

  if (!packPaths.length) {
    list.innerHTML = `<span class="settings-packs-note">No local packs — create one with Forge.</span>`;
    return;
  }

  const prefix = localOn
    ? ''
    : `<span class="settings-packs-note" style="width:100%;margin-bottom:0.25rem;">Available locally (active when Local only is ON):</span>`;

  const chips = packPaths.map(path => {
    const leaf = path.includes('/') ? path.slice(path.lastIndexOf('/') + 1) : path;
    const dc = domainsByName[leaf]?.length || 0;
    const isDisabled = disabled.has(path);
    const cls = isDisabled ? 'settings-pack-chip disabled' : 'settings-pack-chip';
    const tip = isDisabled ? 'Click to enable for retrieval' : 'Click to disable for retrieval';
    const safePath = escapeHtml(path);
    return `<span class="${cls}" data-pack-path="${safePath}" title="${tip}" onclick="togglePack('${safePath.replace(/'/g, '&#39;')}')">${escapeHtml(path)}${dc ? `<span class="settings-pack-chip-count">${dc}d</span>` : ''}</span>`;
  }).join('');

  list.innerHTML = prefix + chips;
}

async function togglePack(packPath) {
  if (!config) return;
  const current = new Set(config.disabled_packs || []);
  if (current.has(packPath)) {
    current.delete(packPath);
  } else {
    current.add(packPath);
  }
  const next = Array.from(current).sort();
  const r = await apiFetch('/api/local/pack-state', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ disabled: next }),
  });
  if (r?.ok) {
    config.disabled_packs = r.disabled;
    _renderPacksList(config);
  }
}

async function setAllPacksEnabled(enable) {
  if (!config) return;
  const all = config.pack_paths || [];
  const disabled = enable ? [] : Array.from(all);
  const r = await apiFetch('/api/local/pack-state', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ disabled }),
  });
  if (r?.ok) {
    config.disabled_packs = r.disabled;
    _renderPacksList(config);
  }
}

async function setLocalMode(enabled) {
  const r = await apiFetch('/api/config/local_mode', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ enabled }),
  });
  if (r?.ok) {
    _updateSourceSides(enabled);
    if (config) { config.local_mode = enabled; _renderPacksList(config); }
  }
}

async function localReindex() {
  const btn = document.getElementById('local-reindex-btn');
  const status = document.getElementById('local-reindex-status');
  if (!btn || !status) return;
  btn.disabled = true;
  status.className = 'settings-reindex-status';
  status.textContent = 'Reindexing…';
  try {
    const r = await apiFetch('/api/local/reindex', { method: 'POST' });
    if (r?.ok) {
      status.className = 'settings-reindex-status ok';
      status.textContent = `Done — ${r.packs_indexed} pack(s), ${r.pages_indexed} page(s)`;
    } else {
      status.className = 'settings-reindex-status err';
      status.textContent = 'Reindex failed';
    }
  } catch (e) {
    status.className = 'settings-reindex-status err';
    status.textContent = 'Reindex failed: ' + (e?.message || e);
  } finally {
    btn.disabled = false;
    setTimeout(() => {
      if (status.textContent.startsWith('Done')) {
        status.textContent = '';
        status.className = 'settings-reindex-status';
      }
    }, 4000);
  }
}

async function openServiceFolder(which) {
  // Opens ~/.occ/state/{workspace,upload} in the OS file manager. Backend
  // enforces an allowlist on `which`, so a hostile caller can't redirect
  // this to ~/.occ/keys etc.
  try {
    const r = await apiFetch(`/api/open-folder/${encodeURIComponent(which)}`, {
      method: 'POST',
    });
    if (!r?.ok) {
      alert(`Could not open ${which} folder.`);
    }
  } catch (e) {
    alert(`Could not open ${which} folder: ${e?.message || e}`);
  }
}

async function setOrActive(enabled) {
  const r = await apiFetch('/api/config/openrouter/active', {
    method: 'POST', body: JSON.stringify({ active: enabled }),
  });
  if (!r?.ok) return;
  if (enabled && r.active) {
    updateProviderBadge(true, r.model || config?.openrouter_model);
    if (config) config.openrouter_configured = true;
  } else if (!enabled) {
    updateProviderBadge(false);
    if (config) config.openrouter_configured = false;
  }
}

async function saveOpenRouter() {
  const keyInput = document.getElementById('or-key').value.trim();
  const model    = document.getElementById('or-model').value;
  const alreadyConfigured = config?.openrouter_configured;

  const key = keyInput || (alreadyConfigured ? '__keep__' : '');
  if (!key) { alert('Enter an API key.'); return; }

  const payload = key === '__keep__'
    ? { api_key: null, model }
    : { api_key: key, model };

  const r = await apiFetch('/api/config/openrouter', {
    method: 'POST', body: JSON.stringify(payload),
  });
  if (r?.ok) {
    document.getElementById('or-key').value = '';
    if (config) { config.openrouter_configured = true; config.openrouter_model = model; }
    const orToggle = document.getElementById('or-active-toggle');
    if (orToggle) orToggle.checked = true;
    const hint = document.getElementById('or-key-hint');
    if (hint) hint.style.display = 'block';
    updateProviderBadge(true, model);
  }
}

function closeModal(id) {
  document.getElementById(id).classList.add('hidden');
}

// ── Update ────────────────────────────────────────────────────────────────────

async function runUpdate() {
  const btn = document.getElementById('btn-update');
  const status = document.getElementById('update-status');
  btn.disabled = true;
  status.style.color = 'var(--text-faint)';
  status.textContent = 'Checking for updates…';

  let data;
  try {
    const r = await fetch('/api/update', { method: 'POST' });
    data = await r.json();
  } catch {
    status.style.color = 'var(--text-faint)';
    status.textContent = 'Network error.';
    btn.disabled = false;
    return;
  }

  if (!data.updated) {
    status.textContent = data.message || 'Already up to date.';
    btn.disabled = false;
    return;
  }

  status.style.color = 'var(--accent)';
  status.textContent = 'Updated — restarting…';

  // Poll until server is back, then reload
  await new Promise(r => setTimeout(r, 2500));
  for (let i = 0; i < 30; i++) {
    try {
      const r = await fetch('/api/config', { signal: AbortSignal.timeout(2000) });
      if (r.ok) { location.reload(); return; }
    } catch {}
    await new Promise(r => setTimeout(r, 1000));
  }
  status.textContent = 'Restart timed out — click the OCC Node icon to restart manually.';
  btn.disabled = false;
}

// ── Context bar ──────────────────────────────────────────────────────────────

function updateCtxBar(used, limit) {
  const bar  = document.getElementById('ctx-bar');
  const fill = document.getElementById('ctx-bar-fill');
  const text = document.getElementById('ctx-bar-text');
  if (!bar || !fill || !text || !limit) return;
  const pct = Math.min(used / limit * 100, 100);
  fill.style.width = pct + '%';
  fill.className = 'ctx-bar-fill' + (pct >= 85 ? ' crit' : pct >= 60 ? ' warn' : '');
  text.textContent = `${used.toLocaleString()} / ${limit.toLocaleString()}`;
  bar.classList.remove('hidden');
}

function resetCtxBar() {
  const bar = document.getElementById('ctx-bar');
  if (bar) bar.classList.add('hidden');
}

function updateProviderBadge(isCloud, model) {
  const badge = document.getElementById('provider-badge');
  if (!badge) return;
  if (isCloud) {
    badge.className = 'provider-badge cloud';
    badge.innerHTML = `<span>●</span> ${escapeHtml(model || 'openrouter')}`;
  } else {
    badge.className = 'provider-badge local';
    badge.innerHTML = `<span>●</span> local`;
  }
}

// ── Utilities ─────────────────────────────────────────────────────────────────

async function apiFetch(url, opts = {}) {
  const defaults = { headers: { 'Content-Type': 'application/json' } };
  const options = { ...defaults, ...opts };
  if (opts.body) options.headers = { ...defaults.headers, ...opts.headers };
  try {
    const r = await fetch(url, options);
    if (!r.ok) return null;
    const ct = r.headers.get('content-type') || '';
    return ct.includes('application/json') ? r.json() : r.text();
  } catch {
    return null;
  }
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function icon(emoji) {
  const s = document.createElement('span');
  s.textContent = emoji;
  return s;
}

// ── Scout ─────────────────────────────────────────────────────────────────────

const SCOUT_TOPTIER_MODELS = [
  { value: 'openai/gpt-5-mini',         label: 'GPT-5 Mini — fast & cheap (default)' },
  { value: 'openai/gpt-5',              label: 'GPT-5 — best quality' },
  { value: 'anthropic/claude-sonnet-4.6', label: 'Claude Sonnet 4.6' },
];

let scoutMode = 'wikipedia_first';
let scoutScope = 'overview';
let scoutResults = [];          // array of SourceResult dicts
let scoutSelected = new Set();  // dedup keys (source|url)
let scoutFullText = new Set();  // dedup keys of arXiv cards toggled to "Full PDF"
let scoutInited = false;
let scoutEvtSource = null;

// Track whether the current brief content was AI-generated. If the user has
// typed a brief manually, we never silently overwrite it on chip click.
let scoutBriefIsAuto = false;
let scoutSuggestInFlight = false;

// Books — heavy, excluded from "Select all", selection triggers confirm dialog.
function isBookResult(r) {
  return r.kind === 'book' || r.source === 'gutendex' || r.source === 'archive_org';
}
// Sources that support an opt-in "full text" download (independent of selection).
// arXiv: PDF download. PubMed: PubMed Central open-access XML (only when pmc_id present).
function supportsFullText(r) {
  if (r.source === 'arxiv') return true;
  if (r.source === 'pubmed' && r.extra && r.extra.pmc_id) return true;
  return false;
}
function fullTextLabel(r) {
  if (r.source === 'arxiv') return '📑 Download full PDF';
  if (r.source === 'pubmed') return '📄 Download full text (PMC)';
  return '📑 Download full text';
}

function scoutDedupKey(r) {
  const doi = (r.extra && r.extra.doi) ? String(r.extra.doi).toLowerCase().trim() : '';
  if (doi) return 'doi:' + doi;
  let u = (r.url || '').toLowerCase().trim();
  u = u.replace(/^https?:\/\//, '').replace(/^www\./, '').replace(/\/$/, '');
  return 'url:' + u;
}

function setupScoutListeners() {
  if (!document.getElementById('panel-scout')) return;

  // Mode buttons
  document.querySelectorAll('[data-scout-mode]').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('[data-scout-mode]').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      scoutMode = btn.dataset.scoutMode;
      scoutUpdateModeOptions();
    });
  });

  // Scope chips — clicking one also auto-fills brief + sources unless the user
  // has typed a brief manually (we don't clobber custom briefs silently).
  document.querySelectorAll('[data-scope]').forEach(chip => {
    chip.addEventListener('click', () => {
      document.querySelectorAll('[data-scope]').forEach(c => c.classList.remove('active'));
      chip.classList.add('active');
      scoutScope = chip.dataset.scope;
      maybeAutoFillFromScope();
    });
  });

  // Manual edit of the brief textarea: mark as "user-owned" so subsequent
  // chip clicks won't silently overwrite.
  document.getElementById('scout-brief')?.addEventListener('input', () => {
    scoutBriefIsAuto = false;
  });

  // Explicit regenerate button.
  document.getElementById('scout-suggest-btn')?.addEventListener('click', () => {
    runScoutSuggest({ force: true });
  });

  // Tabs (results / log)
  document.querySelectorAll('[data-scout-tab]').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('[data-scout-tab]').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const tab = btn.dataset.scoutTab;
      document.getElementById('scout-pane-results').classList.toggle('hidden', tab !== 'results');
      document.getElementById('scout-pane-log').classList.toggle('hidden', tab !== 'log');
    });
  });

  // LLM provider switch
  document.getElementById('scout-llm-provider')?.addEventListener('change', scoutLoadModels);

  // Filter dropdowns
  document.getElementById('scout-filter-source')?.addEventListener('change', renderScoutResults);
  document.getElementById('scout-filter-lang')?.addEventListener('change', renderScoutResults);

  // Select all — explicitly EXCLUDES books. Books must be picked manually
  // (each one triggers a confirm dialog). Already-selected books are left as-is
  // on toggle off.
  document.getElementById('scout-select-all')?.addEventListener('change', e => {
    const checked = e.target.checked;
    const visibleNonBook = scoutResults.filter(r => {
      const fs = document.getElementById('scout-filter-source').value;
      const fl = document.getElementById('scout-filter-lang').value;
      if (fs && r.source !== fs) return false;
      if (fl && (r.lang || '') !== fl) return false;
      return !isBookResult(r);
    });
    const keys = visibleNonBook.map(scoutDedupKey);
    if (checked) keys.forEach(k => scoutSelected.add(k));
    else         keys.forEach(k => scoutSelected.delete(k));
    renderScoutResults();
  });

  // Action buttons
  document.getElementById('scout-run-btn')?.addEventListener('click', runScout);
  document.getElementById('scout-reset-btn')?.addEventListener('click', resetScout);
  document.getElementById('scout-fetch-btn')?.addEventListener('click', fetchSelectedScout);
  document.getElementById('scout-runforge-btn')?.addEventListener('click', () => runForgeOnFetched());
  document.getElementById('scout-open-folder-btn')?.addEventListener('click', openScoutFolder);
  document.getElementById('scout-discard-btn')?.addEventListener('click', discardScoutFetch);
  document.getElementById('scout-forge-extract-model')?.addEventListener('change', updateScoutCostHint);
  document.getElementById('scout-forge-write-model')?.addEventListener('change', updateScoutCostHint);
  document.getElementById('scout-log-clear')?.addEventListener('click', () => {
    document.getElementById('scout-log-body').innerHTML = '';
  });
}

// Current fetched batch: {token, folder, file_count, url_count} or null
let scoutBatch = null;

function scoutInit() {
  if (scoutInited) return;
  scoutInited = true;
  scoutUpdateModeOptions();
  scoutLoadModels();
  initScoutResizer();
}

function initScoutResizer() {
  const resizer = document.getElementById('scout-resizer');
  const formArea = document.querySelector('.scout-form-area');
  const layout = document.querySelector('.scout-layout');
  if (!resizer || !formArea || !layout) return;
  if (resizer.dataset.bound === '1') return;
  resizer.dataset.bound = '1';

  const STORAGE_KEY = 'occ_scout_form_height_px';
  const MIN_FORM = 120;
  const MIN_OUTPUT = 150;

  const saved = localStorage.getItem(STORAGE_KEY);
  if (saved && !isNaN(parseFloat(saved))) {
    formArea.style.height = `${parseFloat(saved)}px`;
    formArea.style.maxHeight = 'none';
  }

  let dragging = false;
  let startY = 0;
  let startH = 0;

  const onDown = (e) => {
    dragging = true;
    startY = e.clientY;
    startH = formArea.getBoundingClientRect().height;
    resizer.classList.add('dragging');
    document.body.style.cursor = 'row-resize';
    document.body.style.userSelect = 'none';
    e.preventDefault();
  };
  const onMove = (e) => {
    if (!dragging) return;
    const layoutH = layout.getBoundingClientRect().height;
    const delta = e.clientY - startY;
    let newH = startH + delta;
    newH = Math.max(MIN_FORM, Math.min(newH, layoutH - MIN_OUTPUT));
    formArea.style.height = `${newH}px`;
    formArea.style.maxHeight = 'none';
  };
  const onUp = () => {
    if (!dragging) return;
    dragging = false;
    resizer.classList.remove('dragging');
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
    const h = parseFloat(formArea.style.height);
    if (!isNaN(h)) localStorage.setItem(STORAGE_KEY, String(h));
  };
  const onDouble = () => {
    formArea.style.height = '';
    formArea.style.maxHeight = '';
    localStorage.removeItem(STORAGE_KEY);
  };

  resizer.addEventListener('mousedown', onDown);
  window.addEventListener('mousemove', onMove);
  window.addEventListener('mouseup', onUp);
  resizer.addEventListener('dblclick', onDouble);
}

function scoutUpdateModeOptions() {
  const wikiOpts = document.getElementById('scout-opts-wikipedia');
  const multiOpts = document.getElementById('scout-opts-multi');
  const llmRow = document.getElementById('scout-llm-row');
  wikiOpts.classList.toggle('hidden', scoutMode !== 'wikipedia_first');
  multiOpts.classList.toggle('hidden', scoutMode === 'wikipedia_first');
  llmRow.classList.toggle('hidden', scoutMode === 'wikipedia_first');
}

async function scoutLoadModels() {
  const provider = document.getElementById('scout-llm-provider').value;
  const sel = document.getElementById('scout-llm-model');
  sel.innerHTML = '';
  if (provider === 'openrouter') {
    for (const m of SCOUT_TOPTIER_MODELS) {
      const o = document.createElement('option');
      o.value = m.value; o.textContent = m.label;
      sel.appendChild(o);
    }
  } else {
    const o = document.createElement('option');
    o.textContent = 'loading...'; o.disabled = true;
    sel.appendChild(o);
    try {
      const r = await apiFetch('/api/scout/installed_models');
      sel.innerHTML = '';
      if (!r || !r.models || !r.models.length) {
        const e = document.createElement('option');
        e.textContent = 'No local models found'; e.disabled = true;
        sel.appendChild(e);
        return;
      }
      for (const m of r.models) {
        const o2 = document.createElement('option');
        o2.value = m.name;
        o2.textContent = m.size_gb ? `${m.name} — ${m.size_gb} GB` : m.name;
        sel.appendChild(o2);
      }
    } catch (e) {
      sel.innerHTML = '';
      const o3 = document.createElement('option');
      o3.textContent = 'Error loading models'; o3.disabled = true;
      sel.appendChild(o3);
    }
  }
}

function scoutGetLangs() {
  const v = document.getElementById('scout-lang')?.value || 'en';
  return [v];
}

function scoutGetEnabledSources() {
  return Array.from(document.querySelectorAll('#scout-sources-grid input:checked'))
    .map(i => i.value);
}

function resetScout() {
  if (scoutEvtSource) { scoutEvtSource.close(); scoutEvtSource = null; }
  scoutResults = [];
  scoutSelected.clear();
  scoutFullText.clear();
  document.getElementById('scout-results-list').innerHTML =
    '<div class="scout-empty">Run Find Sources to start. Candidates from each source will appear here.</div>';
  document.getElementById('scout-log-body').innerHTML =
    '<span class="log-line system">Waiting for Scout run...</span>';
  document.getElementById('scout-progress-hint').textContent = '';
  document.getElementById('scout-log-spinner').classList.add('hidden');
  document.getElementById('scout-results-count').textContent = '0';
  hideFetchedBar();
  scoutBatch = null;
  updateScoutSelectedCount();
  updateScoutFilterDropdowns();
}

function showFetchedBar() {
  document.getElementById('scout-fetched-bar').classList.remove('hidden');
  updateScoutCostHint();
}
function hideFetchedBar() {
  document.getElementById('scout-fetched-bar').classList.add('hidden');
  document.getElementById('scout-fetched-summary').textContent = '';
}

// Real-cost estimates per WRITE CALL (one concept = one write call).
// Numbers in EUR cents, based on OpenRouter list pricing for typical input/output sizes.
// Forge produces ~5-10 concepts per source on average; we use 7 as the multiplier.
const SCOUT_AVG_CONCEPTS_PER_SOURCE = 7;
const SCOUT_COST_PER_CONCEPT_CENTS = {
  'openai/gpt-5-mini':           0.7,   // ~€0.007 / write call (~3k in, ~2k out)
  'openai/gpt-5':                3.5,   // ~€0.035 / write call (5× Mini on output)
  'anthropic/claude-sonnet-4.6': 1.8,   // ~€0.018 / write call (between Mini and GPT-5)
};
// Extract-pass cost per source (just one call per source, regardless of concept count).
const SCOUT_EXTRACT_COST_PER_SOURCE_CENTS = {
  'openai/gpt-5-mini':           0.3,
  'openai/gpt-5':                1.5,
  'anthropic/claude-sonnet-4.6': 0.8,
};

function updateScoutCostHint() {
  const hint = document.getElementById('scout-cost-hint');
  if (!hint) return;
  const ex = document.getElementById('scout-forge-extract-model')?.value || '';
  const wr = document.getElementById('scout-forge-write-model')?.value || '';
  const sources = scoutBatch ? scoutBatch.file_count : 0;

  const exPerSrc = SCOUT_EXTRACT_COST_PER_SOURCE_CENTS[ex] ?? 0.3;
  const wrPerConcept = SCOUT_COST_PER_CONCEPT_CENTS[wr] ?? 0.7;
  const perSrc = exPerSrc + wrPerConcept * SCOUT_AVG_CONCEPTS_PER_SOURCE;
  const totalCents = Math.max(1, Math.round(perSrc * sources));
  const totalEur = (totalCents / 100).toFixed(2);

  const label = (m) => m.includes('gpt-5-mini') ? 'Mini'
                    : m.includes('gpt-5')      ? 'GPT-5'
                    : m.includes('claude')     ? 'Claude'
                    : m;
  if (sources > 0) {
    hint.textContent =
      `~€${totalEur} · ${sources}src × ~${SCOUT_AVG_CONCEPTS_PER_SOURCE} concepts · ${label(ex)}+${label(wr)}`;
  } else {
    hint.textContent =
      `~€${(perSrc/100).toFixed(2)} / source · ${label(ex)}+${label(wr)} · assumes ~${SCOUT_AVG_CONCEPTS_PER_SOURCE} concepts/src`;
  }
  hint.classList.toggle('warn', totalCents >= 500);
}

// Fired on scope chip click: auto-fill the form only when it's safe
// (topic provided AND brief is empty or previously auto-generated).
// The Custom chip is explicitly user-driven — no auto-fill, just a hint.
function maybeAutoFillFromScope() {
  if (scoutScope === 'custom') {
    flashSuggestNote(
      "✏️ Custom scope — no template applied. Write your own brief below " +
      "(this is the 'do whatever you want' mode). To get an AI starting draft, " +
      "either pick a different scope or click ✨ Suggest from topic.",
      false
    );
    return;
  }
  const topic = document.getElementById('scout-topic').value.trim();
  if (!topic) return;
  const brief = document.getElementById('scout-brief').value;
  if (brief.trim() && !scoutBriefIsAuto) return;  // don't clobber user-owned briefs
  runScoutSuggest({ force: false });
}

// Calls /api/scout/suggest and applies the returned JSON to the form fields.
// Used by both the chip auto-trigger and the explicit ✨ Suggest button.
async function runScoutSuggest({ force = false } = {}) {
  if (scoutSuggestInFlight) return;
  const topic = document.getElementById('scout-topic').value.trim();
  if (!topic) {
    flashSuggestNote('Type a topic first, then click Suggest.', /*error*/ true);
    return;
  }
  // If user has typed a brief and this isn't a forced regenerate, ask first.
  const briefEl = document.getElementById('scout-brief');
  const hasManualBrief = briefEl.value.trim() && !scoutBriefIsAuto;
  if (hasManualBrief && force) {
    if (!confirm('Replace your current brief with an AI-suggested one?')) return;
  }

  const language = document.getElementById('scout-lang')?.value || 'en';
  const provider = document.getElementById('scout-llm-provider')?.value || 'openrouter';
  const model    = document.getElementById('scout-llm-model')?.value || 'openai/gpt-5-mini';

  scoutSuggestInFlight = true;
  const btn = document.getElementById('scout-suggest-btn');
  const spinner = document.getElementById('scout-suggest-spinner');
  if (btn) btn.disabled = true;
  if (spinner) spinner.classList.remove('hidden');

  let data = null;
  try {
    const r = await fetch('/api/scout/suggest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        topic,
        scope: scoutScope,
        language,
        llm_provider: provider,
        llm_model: model,
      }),
    });
    if (!r.ok) {
      const txt = await r.text();
      flashSuggestNote(`Suggest failed (${r.status}): ${txt.slice(0, 200)}`, true);
      return;
    }
    data = await r.json();
  } catch (e) {
    flashSuggestNote(`Network error: ${e.message}`, true);
    return;
  } finally {
    scoutSuggestInFlight = false;
    if (btn) btn.disabled = false;
    if (spinner) spinner.classList.add('hidden');
  }

  if (!data) return;
  applyScoutSuggestion(data);
}

// Apply the suggestion JSON to the form fields.
function applyScoutSuggestion(data) {
  // 0. The suggestion populates multi-source-specific fields (source list,
  //    per-source limit, top-K). Force the Mode selector to Multi-source so
  //    the user sees the populated fields and the chosen mode lines up with
  //    what will actually run.
  setScoutMode('multi_source');

  // 1. Brief
  if (typeof data.brief === 'string' && data.brief.trim()) {
    const briefEl = document.getElementById('scout-brief');
    briefEl.value = data.brief.trim();
    scoutBriefIsAuto = true;
  }
  // 1b. Pack name slug — only if the user hasn't typed one yet (we don't
  //     clobber a manually-typed name).
  if (typeof data.pack_name === 'string' && data.pack_name.trim()) {
    const packEl = document.getElementById('scout-pack-name');
    if (packEl && !packEl.value.trim()) {
      packEl.value = data.pack_name.trim();
    }
  }
  // 2. Source toggles
  if (Array.isArray(data.sources)) {
    const want = new Set(data.sources);
    document.querySelectorAll('#scout-sources-grid input').forEach(cb => {
      cb.checked = want.has(cb.value);
    });
  }
  // 3. Per-source limit + top-K — snap to nearest available option
  setDropdownNearest('scout-per-source', data.per_source_limit);
  setDropdownNearest('scout-top-k', data.top_k);
  // 4. Show the rationale as a soft note
  const note = (data.explanation || '').trim();
  if (note) flashSuggestNote(`✨ ${note}`, false);
}

// Switch the Mode buttons + scoutMode state in lockstep. Used by the auto-fill
// flow and could be called elsewhere if we add other mode-switching triggers.
function setScoutMode(mode) {
  if (mode !== scoutMode) {
    scoutMode = mode;
  }
  document.querySelectorAll('[data-scout-mode]').forEach(b => {
    b.classList.toggle('active', b.dataset.scoutMode === mode);
  });
  scoutUpdateModeOptions();
}

function setDropdownNearest(selectId, target) {
  if (target == null || isNaN(target)) return;
  const sel = document.getElementById(selectId);
  if (!sel) return;
  const options = Array.from(sel.options).map(o => parseInt(o.value, 10)).filter(n => !isNaN(n));
  if (!options.length) return;
  let best = options[0];
  let bestDist = Math.abs(best - target);
  for (const o of options) {
    const d = Math.abs(o - target);
    if (d < bestDist) { best = o; bestDist = d; }
  }
  sel.value = String(best);
}

function flashSuggestNote(text, isError) {
  const el = document.getElementById('scout-suggest-note');
  if (!el) return;
  // Inject text + a small × dismiss button. Stays visible until the user
  // dismisses it OR a new suggestion replaces the content. (Was auto-hiding
  // after 8s before — too fast for the user to actually read the rationale.)
  el.innerHTML = '';
  const textEl = document.createElement('span');
  textEl.className = 'scout-suggest-note-text';
  textEl.textContent = text;
  el.appendChild(textEl);
  const dismiss = document.createElement('button');
  dismiss.type = 'button';
  dismiss.className = 'scout-suggest-dismiss';
  dismiss.title = 'Dismiss';
  dismiss.textContent = '×';
  dismiss.addEventListener('click', () => el.classList.add('hidden'));
  el.appendChild(dismiss);
  el.classList.remove('hidden');
  el.style.color = isError ? '#fca5a5' : '';
}

async function runScout() {
  const topic = document.getElementById('scout-topic').value.trim();
  if (!topic) {
    appendScoutLog('❌ Enter a topic first.', 'error');
    switchScoutTab('log');
    return;
  }
  const langs = scoutGetLangs();

  // Reset state but keep terminal open
  scoutResults = [];
  scoutSelected.clear();
  scoutFullText.clear();
  document.getElementById('scout-results-list').innerHTML = '';
  document.getElementById('scout-log-body').innerHTML = '';
  document.getElementById('scout-results-count').textContent = '0';
  updateScoutSelectedCount();
  document.getElementById('scout-log-spinner').classList.remove('hidden');
  document.getElementById('scout-progress-hint').textContent = 'searching...';
  document.getElementById('scout-run-btn').disabled = true;

  // Build payload
  const isFullAuto = scoutMode === 'full_auto';
  const apiMode = isFullAuto ? 'multi_source' : scoutMode;
  const brief = document.getElementById('scout-brief').value.trim();
  const payload = {
    topic,
    mode: apiMode,
    langs,
    scope: scoutScope,
    brief,
    depth: parseInt(document.getElementById('scout-wiki-depth').value, 10) || 2,
    max_pages: parseInt(document.getElementById('scout-wiki-max').value, 10) || 30,
    include_internal_links: document.getElementById('scout-wiki-links').value === 'inline',
    use_wikidata: document.getElementById('scout-wiki-wikidata').checked,
    sources: scoutGetEnabledSources(),
    expand: document.getElementById('scout-expand').checked,
    auto_detect_domain: document.getElementById('scout-detect-domain').checked,
    per_source_limit: parseInt(document.getElementById('scout-per-source').value, 10) || 6,
    top_k: parseInt(document.getElementById('scout-top-k').value, 10) || 40,
    llm_provider: document.getElementById('scout-llm-provider').value,
    llm_model:    document.getElementById('scout-llm-model').value,
  };

  // For wikipedia_first, send empty source list (irrelevant) and skip LLM provider check
  appendScoutLog(`▶ Starting Scout (${scoutMode}) — topic: "${topic}"`, 'system');

  let body;
  try {
    const r = await fetch('/api/scout/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!r.ok) {
      const txt = await r.text();
      appendScoutLog(`❌ ${r.status}: ${txt}`, 'error');
      finishScoutRun();
      return;
    }
    body = r.body;
  } catch (e) {
    appendScoutLog(`❌ Network error: ${e.message}`, 'error');
    finishScoutRun();
    return;
  }

  await consumeSse(body, ev => {
    if (ev.type === 'log')      appendScoutLog(ev.text);
    else if (ev.type === 'domain') appendScoutLog(`  domain → ${ev.domain}`, 'ok');
    else if (ev.type === 'expanded') {
      // already logged item-by-item in scout.py
    }
    else if (ev.type === 'result') addScoutResult(ev.result);
    else if (ev.type === 'done') {
      appendScoutLog(`✅ Done — ${ev.total} candidate(s) found.`, 'ok');
      finishScoutRun(isFullAuto);
    }
  });
}

async function consumeSse(stream, onEvent) {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue;
      const payload = line.slice(6).trim();
      if (!payload) continue;
      try {
        onEvent(JSON.parse(payload));
      } catch (e) {
        // ignore malformed events
      }
    }
  }
}

function finishScoutRun(autoForge = false) {
  document.getElementById('scout-log-spinner').classList.add('hidden');
  document.getElementById('scout-progress-hint').textContent = `${scoutResults.length} candidate(s)`;
  document.getElementById('scout-run-btn').disabled = false;
  if (autoForge && scoutResults.length) {
    // Full-auto: select top half (capped at 15), then fetch + forge + lint sequentially
    const ranked = [...scoutResults].sort((a, b) => (b.score || 0) - (a.score || 0));
    const pickN = Math.min(15, Math.max(5, Math.ceil(ranked.length / 2)));
    scoutSelected = new Set(ranked.slice(0, pickN).map(r => scoutDedupKey(r)));
    renderScoutResults();
    appendScoutLog(`▶ Full-auto: auto-selected top ${pickN} candidates — fetching...`, 'system');
    fetchSelectedScout({ chainForge: true, autoLint: true });
  }
}

function addScoutResult(r) {
  scoutResults.push(r);
  document.getElementById('scout-results-count').textContent = String(scoutResults.length);
  // Streaming-render: append a single card rather than re-render the whole list
  const listEl = document.getElementById('scout-results-list');
  if (scoutResults.length === 1) listEl.innerHTML = '';   // clear empty state on first hit
  listEl.appendChild(scoutCardElement(r));
  updateScoutFilterDropdowns();
}

function scoutCardElement(r) {
  const key = scoutDedupKey(r);
  const book = isBookResult(r);
  const card = document.createElement('div');
  card.className = 'scout-card' + (book ? ' is-book' : '');
  card.dataset.key = key;
  card.dataset.source = r.source || '';
  card.dataset.lang = r.lang || '';

  if (scoutSelected.has(key)) card.classList.add('selected');

  const cb = document.createElement('input');
  cb.type = 'checkbox';
  cb.className = 'scout-card-check';
  cb.checked = scoutSelected.has(key);
  cb.addEventListener('change', () => {
    if (cb.checked && book) {
      // Confirm before adding a full-book download to the selection
      const ok = confirmBookSelection(r);
      if (!ok) {
        cb.checked = false;
        return;
      }
    }
    if (cb.checked) scoutSelected.add(key);
    else scoutSelected.delete(key);
    card.classList.toggle('selected', cb.checked);
    updateScoutSelectedCount();
  });

  const body = document.createElement('div');
  body.className = 'scout-card-body';

  const title = document.createElement('div');
  title.className = 'scout-card-title';
  const a = document.createElement('a');
  a.href = r.url || '#';
  a.target = '_blank';
  a.rel = 'noopener';
  a.textContent = r.title || '(untitled)';
  title.appendChild(a);

  const meta = document.createElement('div');
  meta.className = 'scout-card-meta';
  const src = document.createElement('span');
  src.className = 'src-tag kind-' + (r.kind || 'general');
  src.textContent = (r.source || '?') + (r.kind ? ' · ' + r.kind : '');
  meta.appendChild(src);
  if (r.lang) {
    const lg = document.createElement('span'); lg.textContent = r.lang; meta.appendChild(lg);
  }
  if (r.size_hint) {
    const sz = document.createElement('span');
    sz.textContent = (r.size_hint >= 1000 ? Math.round(r.size_hint / 1000) + 'k' : r.size_hint) + ' chars';
    meta.appendChild(sz);
  }
  if (r.score) {
    const sc = document.createElement('span');
    sc.className = 'score-tag';
    sc.textContent = '★ ' + (r.score).toFixed(2);
    meta.appendChild(sc);
  }

  const snip = document.createElement('div');
  snip.className = 'scout-card-snippet';
  snip.textContent = r.snippet || '';

  body.appendChild(title);
  body.appendChild(meta);
  if (r.snippet) body.appendChild(snip);

  // Books: extra inline warning banner
  if (book) {
    const warn = document.createElement('div');
    warn.className = 'scout-card-book-warn';
    warn.textContent = '⚠️ Full book — selecting downloads the entire text. Heavy. Not included in "Select all".';
    body.appendChild(warn);
  }

  // arXiv: optional "Download full PDF" toggle. Default OFF = abstract only.
  // ON = downloads PDF and extracts text via pymupdf (heavier, more cost).
  if (supportsFullText(r)) {
    const ftRow = document.createElement('label');
    ftRow.className = 'scout-card-fulltext';
    const ftCb = document.createElement('input');
    ftCb.type = 'checkbox';
    ftCb.checked = scoutFullText.has(key);
    ftCb.addEventListener('change', (e) => {
      e.stopPropagation();
      if (ftCb.checked) scoutFullText.add(key);
      else              scoutFullText.delete(key);
    });
    ftRow.appendChild(ftCb);
    const ftLabel = document.createElement('span');
    ftLabel.textContent = fullTextLabel(r);
    ftLabel.title = r.source === 'pubmed'
      ? 'OFF: only abstract + metadata. ON: Scout downloads the full open-access article body from PubMed Central. Costs more in Forge processing — but the abstract alone is often enough for concept extraction.'
      : 'OFF: only the paper abstract is fetched (cheap, often enough). ON: Scout downloads the full PDF and extracts text via pymupdf. Costs ~5-10× more in Forge processing.';
    ftRow.appendChild(ftLabel);
    body.appendChild(ftRow);
  }

  card.appendChild(cb);
  card.appendChild(body);
  return card;
}

// Confirm modal (native) for book selection — explains cost.
function confirmBookSelection(r) {
  // Roughly: a typical book ~500k chars → ~12 Forge chunks × ~7 concepts ≈ 80 concepts.
  // With Mini that's ~€0.60 on writes; with GPT-5 ~€3. Show a range.
  const sizeWords = (r.size_hint && r.size_hint > 0) ? Math.round(r.size_hint / 6) : 0;
  const sizeHint = sizeWords > 0 ? ` (~${sizeWords.toLocaleString()} words)` : '';
  const msg =
    `Heads up — this is a full book${sizeHint}.\n\n` +
    `If selected, Scout will download the entire text and Forge will process it. ` +
    `One book typically produces 50-150 wiki pages on its own, which will dominate ` +
    `the rest of the pack.\n\n` +
    `Estimated extra cost: ~€0.50–€1 with GPT-5 Mini, ~€2–€5 with GPT-5.\n\n` +
    `Source: ${r.title}\n\n` +
    `Include in the selection?`;
  return confirm(msg);
}

function renderScoutResults() {
  const listEl = document.getElementById('scout-results-list');
  listEl.innerHTML = '';
  const filterSource = document.getElementById('scout-filter-source').value;
  const filterLang   = document.getElementById('scout-filter-lang').value;
  const visible = scoutResults.filter(r =>
    (!filterSource || r.source === filterSource) &&
    (!filterLang   || (r.lang || '') === filterLang)
  );
  if (!visible.length) {
    listEl.innerHTML = '<div class="scout-empty">No candidates match the current filters.</div>';
  } else {
    for (const r of visible) listEl.appendChild(scoutCardElement(r));
  }
  updateScoutSelectedCount();
}

function currentVisibleScoutKeys() {
  const filterSource = document.getElementById('scout-filter-source').value;
  const filterLang   = document.getElementById('scout-filter-lang').value;
  return scoutResults
    .filter(r => (!filterSource || r.source === filterSource) && (!filterLang || (r.lang || '') === filterLang))
    .map(scoutDedupKey);
}

function updateScoutSelectedCount() {
  document.getElementById('scout-selected-count').textContent =
    `${scoutSelected.size} selected`;
  document.getElementById('scout-fetch-btn').disabled = scoutSelected.size === 0;
}

function updateScoutFilterDropdowns() {
  const srcSel = document.getElementById('scout-filter-source');
  const langSel = document.getElementById('scout-filter-lang');
  const prevSrc = srcSel.value;
  const prevLang = langSel.value;
  const sources = Array.from(new Set(scoutResults.map(r => r.source))).filter(Boolean).sort();
  const langs   = Array.from(new Set(scoutResults.map(r => r.lang)))  .filter(Boolean).sort();
  srcSel.innerHTML = '<option value="">All sources</option>';
  for (const s of sources) {
    const o = document.createElement('option');
    o.value = s; o.textContent = s; srcSel.appendChild(o);
  }
  if (sources.includes(prevSrc)) srcSel.value = prevSrc;

  langSel.innerHTML = '<option value="">All langs</option>';
  for (const l of langs) {
    const o = document.createElement('option');
    o.value = l; o.textContent = l; langSel.appendChild(o);
  }
  if (langs.includes(prevLang)) langSel.value = prevLang;
}

function appendScoutLog(text, kind = '') {
  const body = document.getElementById('scout-log-body');
  const line = document.createElement('span');
  let cls = 'log-line system';
  if (kind === 'error' || text.includes('❌'))      cls = 'log-line error';
  else if (kind === 'ok' || text.includes('✅') || text.includes('🎉')) cls = 'log-line ok';
  else if (text.includes('⚠')) cls = 'log-line warn';
  line.className = cls;
  line.textContent = text;
  body.appendChild(line);
  body.appendChild(document.createTextNode('\n'));
  const nearBottom = body.scrollHeight - body.scrollTop - body.clientHeight < 80;
  if (nearBottom) body.scrollTop = body.scrollHeight;
}

function switchScoutTab(tab) {
  document.querySelectorAll('[data-scout-tab]').forEach(b => {
    b.classList.toggle('active', b.dataset.scoutTab === tab);
  });
  document.getElementById('scout-pane-results').classList.toggle('hidden', tab !== 'results');
  document.getElementById('scout-pane-log').classList.toggle('hidden', tab !== 'log');
}

// Stage 1 — Fetch only. Writes selected sources straight into the target
// pack's raw/articles/ folder using Forge's raw format. Does NOT run Forge.
async function fetchSelectedScout(opts = {}) {
  const selected = scoutResults.filter(r => scoutSelected.has(scoutDedupKey(r)));
  if (!selected.length) {
    appendScoutLog('❌ No sources selected.', 'error');
    switchScoutTab('log');
    return;
  }
  const packName = document.getElementById('scout-pack-name').value.trim();
  if (!packName) {
    appendScoutLog('❌ Enter a target pack name first.', 'error');
    switchScoutTab('log');
    return;
  }

  // Lock UI during fetch
  const fetchBtn = document.getElementById('scout-fetch-btn');
  fetchBtn.disabled = true;
  document.getElementById('scout-log-spinner').classList.remove('hidden');
  appendScoutLog(`▶ Fetching ${selected.length} selected source(s) into "${packName}"...`, 'system');
  switchScoutTab('log');

  let stream;
  try {
    const fullTextKeys = selected
      .map(s => scoutDedupKey(s))
      .filter(k => scoutFullText.has(k));
    // Propagate the user's intent (scope chip + brief textarea) into the pack
    // manifest, so Forge can apply the same scope filter at extraction time.
    const briefForManifest = document.getElementById('scout-brief').value.trim();
    const r = await fetch('/api/scout/fetch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        pack_name: packName,
        selected,
        full_text_keys: fullTextKeys,
        scope: scoutScope,
        brief: briefForManifest,
      }),
    });
    if (!r.ok) {
      const txt = await r.text();
      appendScoutLog(`❌ ${r.status}: ${txt}`, 'error');
      fetchBtn.disabled = false;
      document.getElementById('scout-log-spinner').classList.add('hidden');
      return;
    }
    stream = r.body;
  } catch (e) {
    appendScoutLog(`❌ Network: ${e.message}`, 'error');
    fetchBtn.disabled = false;
    document.getElementById('scout-log-spinner').classList.add('hidden');
    return;
  }

  let finalEvent = null;
  await consumeSse(stream, ev => {
    if (ev.type === 'log') appendScoutLog(ev.text);
    else if (ev.type === 'done') finalEvent = ev;
  });
  document.getElementById('scout-log-spinner').classList.add('hidden');
  fetchBtn.disabled = scoutSelected.size === 0;

  if (!finalEvent || !finalEvent.token) {
    appendScoutLog('❌ Fetch did not complete (no batch produced).', 'error');
    return;
  }

  scoutBatch = {
    token:        finalEvent.token,
    pack_name:    finalEvent.pack_name,
    pack_dir:     finalEvent.pack_dir,
    pack_existed: finalEvent.pack_existed,
    file_count:   finalEvent.file_count,
    url_count:    finalEvent.url_count,
  };
  const inWord = scoutBatch.pack_existed ? 'added to' : 'created in';
  document.getElementById('scout-fetched-summary').textContent =
    `✅ ${scoutBatch.file_count} raw file(s) ${inWord} ${scoutBatch.pack_dir}`;
  showFetchedBar();
  appendScoutLog(`✅ Ready to forge. Inspect the pack folder or click "Run Forge →".`, 'ok');
  switchScoutTab('results');

  if (opts.chainForge) {
    runForgeOnFetched({ autoLint: !!opts.autoLint });
  }
}

// Stage 2 — Forge the pack Scout already populated.
async function runForgeOnFetched(opts = {}) {
  if (!scoutBatch || !scoutBatch.token) {
    appendScoutLog('❌ No fetched batch — run "Fetch sources" first.', 'error');
    return;
  }

  const extractModel = document.getElementById('scout-forge-extract-model')?.value || 'openai/gpt-5-mini';
  const writeModel   = document.getElementById('scout-forge-write-model')?.value   || 'openai/gpt-5-mini';
  const hintEl = document.getElementById('scout-cost-hint');

  // Confirm if the projected total triggers the warn state (≥ €5).
  if (!opts.autoLint && !opts.skipConfirm && hintEl && hintEl.classList.contains('warn')) {
    const ok = confirm(
      `Heads up — Forge with these models on ${scoutBatch.file_count + scoutBatch.url_count} source(s) ` +
      `will likely cost more than €5 (${hintEl.textContent}).\n\nProceed?`
    );
    if (!ok) return;
  }

  const payload = {
    token: scoutBatch.token,
    extract_model: extractModel,
    model: writeModel,
    fetch_images: false,
    fetch_math: false,
  };

  // Pop to Forge view so user sees the familiar Forge output stream
  switchView('forge');
  const out = document.getElementById('forge-output-body');
  out.innerHTML = '';
  appendForgeOutput(`▶ Forge from Scout — pack "${scoutBatch.pack_name}"`);

  let stream;
  try {
    const r = await fetch('/api/scout/forge_batch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!r.ok) {
      const txt = await r.text();
      appendForgeOutput(`❌ ${r.status}: ${txt}`);
      return;
    }
    stream = r.body;
  } catch (e) {
    appendForgeOutput(`❌ Network: ${e.message}`);
    return;
  }

  let completedPack = '';
  await consumeSse(stream, ev => {
    if (ev.type === 'run_started')        onRunStarted(ev);
    else if (ev.type === 'run_ended')     onRunEnded(ev.status);
    else if (ev.text)                     appendForgeOutput(ev.text);
    if (ev.type === 'forge_complete') completedPack = ev.pack_name;
  });
  if (completedPack) {
    showForgeActions(completedPack);
    if (opts.autoLint) {
      appendForgeOutput('\n▶ Full-auto: chaining Lint...');
      runLint(completedPack);
    }
  }
}

async function openScoutFolder() {
  if (!scoutBatch || !scoutBatch.token) return;
  await apiFetch(`/api/scout/open-folder/${scoutBatch.token}`, { method: 'POST' });
}

async function discardScoutFetch() {
  if (!scoutBatch || !scoutBatch.token) return;
  const token = scoutBatch.token;
  try {
    await fetch(`/api/scout/batch/${token}`, { method: 'DELETE' });
  } catch (e) { /* ignore */ }
  scoutBatch = null;
  hideFetchedBar();
  appendScoutLog('↺ Fetched batch discarded.', 'system');
}


// ── Persistent run banner + reconnect ─────────────────────────────────────────
//
// State machine: while a Forge run is alive, we keep `activeRun` = {id, kind,
// pack_name, status, started_at} in memory AND in localStorage. The banner
// shows whenever activeRun exists. On page load we try to reconnect to the
// stored run_id — if the server says it's still running, we tail it again.

const RUN_BANNER_STORAGE_KEY = 'occ_active_forge_run';
let activeRun = null;             // {id, kind, pack_name, status, started_at}
let activeRunStream = null;       // AbortController for the SSE fetch
let activeRunTicker = null;       // setInterval handle for elapsed updater

function saveActiveRunToStorage() {
  if (activeRun) {
    try { localStorage.setItem(RUN_BANNER_STORAGE_KEY, JSON.stringify(activeRun)); }
    catch (e) {}
  } else {
    localStorage.removeItem(RUN_BANNER_STORAGE_KEY);
  }
}

function loadActiveRunFromStorage() {
  try {
    const raw = localStorage.getItem(RUN_BANNER_STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch (e) {
    return null;
  }
}

function fmtElapsed(seconds) {
  const s = Math.max(0, Math.floor(seconds));
  const m = Math.floor(s / 60), r = s % 60;
  return `${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}`;
}

function renderRunBanner() {
  const el = document.getElementById('run-banner');
  if (!el) return;
  if (!activeRun) {
    el.classList.add('hidden');
    document.body.classList.remove('has-run-banner');
    return;
  }
  el.classList.remove('hidden');
  document.body.classList.add('has-run-banner');
  el.classList.remove('status-stopping','status-completed','status-failed','status-stopped');
  if (activeRun.status && activeRun.status !== 'running') {
    el.classList.add(`status-${activeRun.status}`);
  }
  const kindLabel = activeRun.kind === 'lint' ? 'Lint' : 'Forge';
  const verb = activeRun.status === 'running' ? 'running on'
             : activeRun.status === 'stopping' ? 'stopping on'
             : activeRun.status === 'completed' ? 'completed —'
             : activeRun.status === 'failed' ? 'failed on'
             : activeRun.status === 'stopped' ? 'stopped on'
             : 'on';
  document.getElementById('run-banner-text').innerHTML =
    `${kindLabel} ${verb} <strong>${activeRun.pack_name || '(?)'}</strong>`;
  const elapsed = (Date.now() / 1000) - (activeRun.started_at || Date.now() / 1000);
  document.getElementById('run-banner-elapsed').textContent = fmtElapsed(elapsed);
  // Stop button only when actively running
  const stopBtn = document.getElementById('run-banner-stop');
  stopBtn.style.display = (activeRun.status === 'running') ? '' : 'none';
}

function startRunTicker() {
  if (activeRunTicker) return;
  activeRunTicker = setInterval(renderRunBanner, 1000);
}
function stopRunTicker() {
  if (activeRunTicker) { clearInterval(activeRunTicker); activeRunTicker = null; }
}

function setActiveRun(run) {
  activeRun = run;
  saveActiveRunToStorage();
  renderRunBanner();
  if (run && run.status === 'running') startRunTicker();
  else                                   stopRunTicker();
}

// Mark the current activeRun as terminal and schedule a hide after a few seconds
function finalizeActiveRun(status) {
  if (!activeRun) return;
  activeRun.status = status;
  saveActiveRunToStorage();
  renderRunBanner();
  stopRunTicker();
  // Auto-hide after 8s on terminal status
  setTimeout(() => {
    if (activeRun && activeRun.status !== 'running') setActiveRun(null);
  }, 8000);
}

async function stopActiveRun() {
  if (!activeRun || !activeRun.id) return;
  if (!confirm('Stop the running Forge?\n\nForge will exit cleanly after the current source finishes (up to ~60s). LLM calls already in flight will complete and be charged; future sources are saved.')) return;
  try {
    await fetch(`/api/forge/runs/${activeRun.id}/stop`, { method: 'POST' });
    activeRun.status = 'stopping';
    saveActiveRunToStorage();
    renderRunBanner();
  } catch (e) {
    alert('Stop request failed: ' + e.message);
  }
}

function viewActiveRun() {
  if (!activeRun) return;
  // Forge and scout_forge both render into the Forge output panel.
  switchView('forge');
}

// Called by the SSE consumers in forgeRun / runForgeOnFetched / runLint when
// they receive a `run_started` event. Wires the banner to the new run.
function onRunStarted(ev) {
  setActiveRun({
    id:         ev.run_id,
    kind:       ev.kind || 'forge',
    pack_name:  ev.pack_name || '',
    status:     'running',
    started_at: ev.started_at || (Date.now() / 1000),
  });
}

function onRunEnded(status) {
  finalizeActiveRun(status || 'completed');
}

// On page load, if we have a stored run_id, try to reconnect to its stream.
async function tryReconnectActiveRun() {
  const stored = loadActiveRunFromStorage();
  if (!stored || !stored.id) return;
  let info;
  try {
    const r = await fetch(`/api/forge/runs/${stored.id}/status`);
    if (!r.ok) {
      // Run no longer exists on server — clear localStorage
      setActiveRun(null);
      return;
    }
    info = await r.json();
  } catch (e) {
    setActiveRun(null);
    return;
  }
  setActiveRun({
    id:         info.id,
    kind:       info.kind,
    pack_name:  info.pack_name,
    status:     info.status,
    started_at: info.started_at,
  });
  if (info.status !== 'running') {
    // Don't bother reconnecting — final status visible, banner auto-hides
    finalizeActiveRun(info.status);
    return;
  }
  // Reconnect to its SSE stream and pipe events into the Forge output panel.
  await streamExistingRun(info.id);
}

async function streamExistingRun(runId) {
  // Show Forge view so the user sees the log streaming back
  switchView('forge');
  const out = document.getElementById('forge-output-body');
  out.innerHTML = '';
  appendForgeOutput(`▶ Reconnected to in-progress run ${runId}`);

  if (activeRunStream) { try { activeRunStream.abort(); } catch(e){} }
  activeRunStream = new AbortController();
  let stream;
  try {
    const r = await fetch(`/api/forge/runs/${runId}/stream`, { signal: activeRunStream.signal });
    if (!r.ok) {
      appendForgeOutput(`❌ Could not reconnect: ${r.status}`);
      return;
    }
    stream = r.body;
  } catch (e) {
    appendForgeOutput(`❌ Reconnect failed: ${e.message}`);
    return;
  }
  let completedPack = '';
  await consumeSse(stream, ev => {
    if (ev.type === 'run_started') onRunStarted(ev);
    else if (ev.type === 'run_ended') onRunEnded(ev.status);
    else if (ev.text) appendForgeOutput(ev.text);
    if (ev.type === 'forge_complete' || ev.type === 'lint_complete') completedPack = ev.pack_name;
  });
  if (completedPack) showForgeActions(completedPack);
}


// ── Start ─────────────────────────────────────────────────────────────────────

function initBanner() {
  document.getElementById('run-banner-view')?.addEventListener('click', viewActiveRun);
  document.getElementById('run-banner-stop')?.addEventListener('click', stopActiveRun);
  tryReconnectActiveRun();
}

document.addEventListener('DOMContentLoaded', () => { init(); initBanner(); });
