'use strict';

// ── State ────────────────────────────────────────────────────────────────────

let currentChatId  = null;
let isStreaming    = false;
let allChats       = [];
let attachments    = [];   // [{name, type, data}]
let logsSource     = null; // EventSource for broker logs
let logLineCount   = 0;
let activeTab      = 'chat';
let config         = {};

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
  document.getElementById('btn-commands').addEventListener('click', openCommands);
  document.getElementById('close-settings').addEventListener('click', () => closeModal('settings-modal'));
  document.getElementById('close-commands').addEventListener('click', () => closeModal('commands-modal'));

  document.getElementById('tab-chat').addEventListener('click', () => switchTab('chat'));
  document.getElementById('tab-logs').addEventListener('click', () => switchTab('logs'));

  document.getElementById('attach-btn').addEventListener('click', () => document.getElementById('file-input').click());
  document.getElementById('file-input').addEventListener('change', e => handleFiles(e.target.files));

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

  document.getElementById('send-btn').addEventListener('click', sendMessage);

  document.getElementById('btn-save-or').addEventListener('click', saveOpenRouter);
  document.getElementById('btn-disable-or').addEventListener('click', disableOpenRouter);

  // Close modals on overlay click
  document.querySelectorAll('.modal-overlay').forEach(overlay => {
    overlay.addEventListener('click', e => {
      if (e.target === overlay) overlay.classList.add('hidden');
    });
  });
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
  btn.disabled = isStreaming || !hasContent;
}

function setStreamingState(active) {
  isStreaming = active;
  updateSendButton();
  const sidebar = document.querySelector('.sidebar');
  if (sidebar) sidebar.classList.toggle('is-streaming', active);
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
  const data = await apiFetch('/api/chats', { method: 'POST' });
  if (!data) return;
  await loadChats();
  await selectChat(data.id);
}

async function selectChat(id) {
  if (isStreaming) return;
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
  { cmd: '/clear',          desc: 'Clear conversation history' },
  { cmd: '/status',         desc: 'Show current config' },
  { cmd: '/packs',          desc: 'List all loaded packs' },
  { cmd: '/peers',          desc: 'Show peer nodes' },
  { cmd: '/load',           desc: 'Load model into VRAM' },
  { cmd: '/unload',         desc: 'Unload model from VRAM' },
  { cmd: '/model ',         desc: 'Switch model  (e.g. deepseek-r1:14b)' },
  { cmd: '/pack ',          desc: 'Load a specific pack  (e.g. docker)' },
  { cmd: '/openrouter on',  desc: 'Switch to OpenRouter' },
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
    if (msg.peer_answers) {
      addSourcesButton(msg.id || 'msg-' + Date.now(), msg.peer_answers);
    }
    container.appendChild(row);
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
    chat: 'chat', local: 'local',
    delegate: 'distributed', hybrid: 'hybrid',
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

  row.querySelector('.assistant-body').appendChild(statusLine);
  container.appendChild(row);
  scrollToBottom();
  _startWordCycle(msgId, 'Thinking');
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

  const blocks = [];
  if (data.local_answer) {
    blocks.push({ label: `Local — ${data.local_pack || 'local'}`, text: data.local_answer, role: 'local' });
  }
  if (data.expert_answer) {
    blocks.push({ label: 'Peer — expert', text: data.expert_answer, role: 'expert' });
  }
  if (data.contrarian_answer) {
    const label = data.mode === 'delegate' ? 'Peer — critical review' : 'Peer — expert 2';
    blocks.push({ label, text: data.contrarian_answer, role: 'contrarian' });
  }

  blocks.forEach(b => {
    const block = document.createElement('div');
    block.className = `source-block role-${b.role}`;
    const lbl = document.createElement('div');
    lbl.className = 'source-label';
    lbl.textContent = b.label;
    const body = document.createElement('div');
    body.className = 'source-body md-content';
    body.innerHTML = renderMarkdown(b.text);
    block.appendChild(lbl);
    block.appendChild(body);
    panel.appendChild(block);
  });

  return panel;
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

function updateStreamingBody(msgId, tokens) {
  const body = document.getElementById('body-' + msgId);
  if (!body) return;
  const status = document.getElementById('status-' + msgId);
  if (status) status.remove();
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
    if (message === '/openrouter on')  { const c = await apiFetch('/api/config'); if (c) updateProviderBadge(!!c.openrouter_configured, c.openrouter_model); }
    if (message === '/openrouter off') updateProviderBadge(false);
    return;
  }

  const sendAttachments = [...attachments];

  // ── Force-deliberate prefix (!) ────────────────────────────────────────────
  let forcedMode = 'auto';
  let actualMessage = message;
  if (message.startsWith('!')) {
    forcedMode = 'deliberate';
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
        } else if (data.type === 'peer_answers') {
          addSourcesButton(msgId, data.value);
        } else if (data.type === 'status') {
          updateStatusText(msgId, data.value);
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

  const info = document.getElementById('settings-info');
  info.innerHTML = `
    <div class="settings-info-row"><span class="settings-info-key">Model</span><span class="settings-info-val">${cfg.model || '—'}</span></div>
    <div class="settings-info-row"><span class="settings-info-key">Hardware</span><span class="settings-info-val">${cfg.hardware_profile || '—'} · ${cfg.detected_vram_gb > 0 ? cfg.detected_vram_gb + 'GB VRAM' : 'CPU'}</span></div>
    <div class="settings-info-row"><span class="settings-info-key">Context</span><span class="settings-info-val">${cfg.num_ctx_answer?.toLocaleString() || '—'} tokens</span></div>
    <div class="settings-info-row" style="border:none"><span class="settings-info-key">Packs</span><span class="settings-info-val">${cfg.packs?.map(p => p.name).join(', ') || 'none'}</span></div>
  `;

  const orStatus = document.getElementById('or-status-line');
  if (cfg.openrouter_configured) {
    orStatus.className = 'or-status ok';
    orStatus.textContent = `● Active — ${cfg.openrouter_model}`;
  } else {
    orStatus.className = 'or-status off';
    orStatus.textContent = '○ Not configured';
  }

  document.getElementById('or-model').value = cfg.openrouter_model || 'qwen/qwen3.5-9b';
  const hint = document.getElementById('or-key-hint');
  if (hint) hint.style.display = cfg.openrouter_configured ? 'block' : 'none';
  document.getElementById('settings-modal').classList.remove('hidden');
}

async function saveOpenRouter() {
  const keyInput = document.getElementById('or-key').value.trim();
  const model = document.getElementById('or-model').value;
  const alreadyConfigured = config?.openrouter_configured;

  // If no key entered and one is already saved, only update the model
  const key = keyInput || (alreadyConfigured ? '__keep__' : '');
  if (!key) { alert('Enter an API key.'); return; }

  const payload = key === '__keep__'
    ? { api_key: null, model }
    : { api_key: key, model };

  const r = await apiFetch('/api/config/openrouter', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  if (r?.ok) {
    document.getElementById('or-key').value = '';
    config.openrouter_configured = true;
    config.openrouter_model = model;
    const orStatus = document.getElementById('or-status-line');
    orStatus.className = 'or-status ok';
    orStatus.textContent = `● Active — ${model}`;
    updateProviderBadge(true, model);
  }
}

async function disableOpenRouter() {
  const r = await apiFetch('/api/config/openrouter', {
    method: 'POST',
    body: JSON.stringify({ api_key: '', model: 'qwen/qwen3.5-9b' }),
  });
  if (r?.ok) {
    config.openrouter_configured = false;
    const orStatus = document.getElementById('or-status-line');
    orStatus.className = 'or-status off';
    orStatus.textContent = '○ Not configured';
    updateProviderBadge(false);
  }
}

function openCommands() {
  document.getElementById('commands-modal').classList.remove('hidden');
}

function closeModal(id) {
  document.getElementById(id).classList.add('hidden');
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

// ── Start ─────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', init);
