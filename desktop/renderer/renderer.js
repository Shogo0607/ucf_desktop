// ── State ──────────────────────────────────────────────────────
const state = {
  isConnected: false,
  isBusy: false,
  autoConfirm: false,
  currentAssistantEl: null,
  disabledSkills: new Set(),
};

// ── DOM refs ───────────────────────────────────────────────────
const messagesEl   = document.getElementById('messages');
const inputEl      = document.getElementById('user-input');
const sendBtn      = document.getElementById('send-btn');
const statusConn   = document.getElementById('status-conn');
const statusModel  = document.getElementById('status-model');
const statusCwd    = document.getElementById('status-cwd');
const btnClear     = document.getElementById('btn-clear');
const btnAutoconf  = document.getElementById('btn-autoconfirm');
const skillsListEl = document.getElementById('skills-list');
const btnSkillsReload = document.getElementById('btn-skills-reload');

// ── Tool card queue (FIFO for matching tool_call -> tool_result) ──
const pendingToolCards = [];

// ── Message rendering ──────────────────────────────────────────

function appendUserMessage(content) {
  const group = document.createElement('div');
  group.className = 'message-group message-user';
  const bubble = document.createElement('div');
  bubble.className = 'bubble';
  bubble.textContent = content;
  group.appendChild(bubble);
  messagesEl.appendChild(group);
  scrollToBottom();
}

function startAssistantMessage() {
  const group = document.createElement('div');
  group.className = 'message-group message-assistant';
  const bubble = document.createElement('div');
  bubble.className = 'bubble streaming-cursor';
  group.appendChild(bubble);
  messagesEl.appendChild(group);
  state.currentAssistantEl = bubble;
  scrollToBottom();
  return bubble;
}

function appendToken(content) {
  if (!state.currentAssistantEl) {
    startAssistantMessage();
  }
  state.currentAssistantEl.textContent += content;
  scrollToBottom();
}

function finalizeAssistantMessage() {
  if (state.currentAssistantEl) {
    state.currentAssistantEl.classList.remove('streaming-cursor');
    state.currentAssistantEl = null;
  }
}

function appendToolCall(name, args) {
  // Finalize any in-progress assistant text before showing tool card
  finalizeAssistantMessage();

  const argsStr = JSON.stringify(args, null, 2);
  const card = document.createElement('div');
  card.className = 'tool-card';
  card.dataset.toolName = name;

  card.innerHTML =
    '<div class="tool-card-header">' +
      '<span class="icon">&#9889;</span>' +
      '<span>' + escHtml(name) + '</span>' +
    '</div>' +
    '<div class="tool-card-args">' +
      escHtml(argsStr.length > 300 ? argsStr.slice(0, 300) + '...' : argsStr) +
    '</div>';

  messagesEl.appendChild(card);
  pendingToolCards.push(card);
  scrollToBottom();
  return card;
}

function appendToolResult(name, result, status) {
  const idx = pendingToolCards.findIndex(c => c.dataset.toolName === name);
  const card = idx >= 0 ? pendingToolCards.splice(idx, 1)[0] : null;

  if (card) {
    card.classList.add('result-' + status);
    const icon = status === 'ok' ? '\u2713' : status === 'error' ? '\u2717' : '\u2013';
    const headerEl = card.querySelector('.tool-card-header');
    headerEl.innerHTML =
      '<span class="icon">' + icon + '</span>' +
      '<span>' + escHtml(name) + '</span>' +
      '<span style="margin-left:auto;color:var(--text-dim);font-size:10px">' +
        escHtml(status) +
      '</span>';

    const argsEl = card.querySelector('.tool-card-args');
    const preview = result.length > 150 ? result.slice(0, 150) + '...' : result;
    if (argsEl) argsEl.textContent = preview;
  }
}

function appendConfirmCard(id, toolName, args, preview) {
  // Finalize any in-progress assistant text
  finalizeAssistantMessage();

  const card = document.createElement('div');
  card.className = 'confirm-card';
  card.dataset.confirmId = id;

  const argsStr = JSON.stringify(args, null, 2);
  const argsDisplay = argsStr.length > 200 ? argsStr.slice(0, 200) + '...' : argsStr;

  let html =
    '<div class="confirm-card-title">&#9888; 確認が必要な操作</div>' +
    '<div class="confirm-card-tool">' + escHtml(toolName) + '</div>' +
    '<div class="confirm-card-detail">' + escHtml(argsDisplay) + '</div>';

  if (preview) {
    html += '<div class="confirm-card-preview">' + renderDiffPreview(preview) + '</div>';
  }

  html +=
    '<div class="confirm-buttons">' +
      '<button class="confirm-btn confirm-btn-approve">承認</button>' +
      '<button class="confirm-btn confirm-btn-cancel">キャンセル</button>' +
    '</div>';

  card.innerHTML = html;

  // Wire up buttons
  card.querySelector('.confirm-btn-approve').addEventListener('click', () => {
    resolveConfirm(card, id, true);
  });
  card.querySelector('.confirm-btn-cancel').addEventListener('click', () => {
    resolveConfirm(card, id, false);
  });

  messagesEl.appendChild(card);
  scrollToBottom();
}

function resolveConfirm(card, id, approved) {
  card.querySelectorAll('.confirm-btn').forEach(b => { b.disabled = true; });
  const label = approved ? '承認済み' : 'キャンセル済み';
  const color = approved ? 'var(--accent-green)' : 'var(--text-dim)';
  card.querySelector('.confirm-buttons').innerHTML =
    '<span style="font-size:12px;color:' + color + '">' + label + '</span>';

  window.agent.sendConfirm(id, approved);
}

function renderDiffPreview(text) {
  if (!text) return '';
  return text.split('\n').map(line => {
    if (line.startsWith('+') && !line.startsWith('+++'))
      return '<span class="diff-add">' + escHtml(line) + '</span>';
    if (line.startsWith('-') && !line.startsWith('---'))
      return '<span class="diff-del">' + escHtml(line) + '</span>';
    if (line.startsWith('@@'))
      return '<span class="diff-hunk">' + escHtml(line) + '</span>';
    return escHtml(line);
  }).join('\n');
}

function appendStatusMessage(text, ephemeral) {
  removeEphemeralStatus();
  const el = document.createElement('div');
  el.className = 'status-message';
  el.textContent = text;
  if (ephemeral) el.dataset.ephemeral = '1';
  messagesEl.appendChild(el);
  scrollToBottom();
}

function removeEphemeralStatus() {
  messagesEl.querySelectorAll('.status-message[data-ephemeral="1"]')
    .forEach(el => el.remove());
}

function appendErrorMessage(text) {
  const el = document.createElement('div');
  el.className = 'error-message';
  el.textContent = text;
  messagesEl.appendChild(el);
  scrollToBottom();
}

// ── Incoming message handler ───────────────────────────────────

window.agent.onMessage((msg) => {
  switch (msg.type) {

    case 'system_info':
      statusModel.textContent = 'model: ' + msg.model;
      statusCwd.textContent = 'cwd: ' + msg.cwd;
      statusConn.textContent = '接続済み';
      statusConn.className = 'status-ready';
      state.isConnected = true;
      if (msg.disabled_skills) {
        state.disabledSkills = new Set(msg.disabled_skills);
      }
      enableInput();
      if (msg.has_context) {
        appendStatusMessage('プロジェクトコンテキスト読み込み済み');
      }
      if (msg.skills && msg.skills.length > 0) {
        renderSkillsList(msg.skills);
      }
      break;

    case 'skills_list':
      renderSkillsList(msg.skills);
      break;

    case 'skill_toggled':
      if (msg.enabled) {
        state.disabledSkills.delete(msg.name);
      } else {
        state.disabledSkills.add(msg.name);
      }
      updateSkillToggleUI(msg.name, msg.enabled);
      break;

    case 'status':
      appendStatusMessage(msg.message, msg.ephemeral);
      break;

    case 'token':
      removeEphemeralStatus();
      appendToken(msg.content);
      setStatus('busy');
      break;

    case 'tool_call':
      removeEphemeralStatus();
      appendToolCall(msg.name, msg.args);
      setStatus('busy');
      break;

    case 'confirm_request':
      appendConfirmCard(msg.id, msg.tool, msg.args, msg.preview);
      break;

    case 'tool_result':
      appendToolResult(msg.name, msg.result, msg.status);
      break;

    case 'assistant_done':
      removeEphemeralStatus();
      finalizeAssistantMessage();
      setStatus('ready');
      setBusy(false);
      break;

    case 'chat_finished':
      removeEphemeralStatus();
      finalizeAssistantMessage();
      if (state.isBusy) {
        setStatus('ready');
        setBusy(false);
      }
      break;

    case 'compacting':
      showCompactingSpinner();
      break;

    case 'compact_done':
      hideCompactingSpinner();
      appendStatusMessage(msg.message || '会話を自動圧縮しました');
      break;

    case 'error':
      finalizeAssistantMessage();
      hideCompactingSpinner();
      appendErrorMessage(msg.message);
      setStatus('error');
      setBusy(false);
      break;
  }
});

// ── Sending messages ───────────────────────────────────────────

function sendMessage() {
  const content = inputEl.value.trim();
  if (!content || state.isBusy || !state.isConnected) return;

  appendUserMessage(content);
  inputEl.value = '';
  autoResizeInput();

  setBusy(true);
  setStatus('busy');

  window.agent.sendMessage(content);
}

// ── Input handling ─────────────────────────────────────────────

inputEl.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendMessage();
  }
});

inputEl.addEventListener('input', autoResizeInput);
sendBtn.addEventListener('click', sendMessage);

function autoResizeInput() {
  inputEl.style.height = 'auto';
  inputEl.style.height = Math.min(inputEl.scrollHeight, 160) + 'px';
}

// ── Sidebar buttons ────────────────────────────────────────────

btnClear.addEventListener('click', () => {
  messagesEl.innerHTML = '';
  pendingToolCards.length = 0;
  state.currentAssistantEl = null;
  window.agent.sendCommand('clear');
});

btnAutoconf.addEventListener('click', () => {
  state.autoConfirm = !state.autoConfirm;
  btnAutoconf.textContent = '自動確認: ' + (state.autoConfirm ? 'ON' : 'OFF');
  btnAutoconf.style.color = state.autoConfirm
    ? 'var(--accent-red)' : 'var(--text-secondary)';
  window.agent.sendCommand('autoconfirm');
});

// ── Skills ──────────────────────────────────────────────────────

btnSkillsReload.addEventListener('click', () => {
  window.agent.sendCommand('skills_reload');
});

function renderSkillsList(skills) {
  skillsListEl.innerHTML = '';
  if (!skills || skills.length === 0) {
    skillsListEl.innerHTML = '<div class="skills-empty">スキルなし</div>';
    return;
  }
  skills.forEach(skill => {
    const isDisabled = state.disabledSkills.has(skill.name);

    const row = document.createElement('div');
    row.className = 'skill-row' + (isDisabled ? ' skill-disabled' : '');
    row.dataset.skillName = skill.name;

    // スキル実行ボタン
    const btn = document.createElement('button');
    btn.className = 'skill-btn';
    btn.title = skill.description;
    let badges = '';
    if (skill.has_scripts) badges += ' <span class="skill-badge">S</span>';
    if (skill.has_references) badges += ' <span class="skill-badge">R</span>';
    if (skill.has_assets) badges += ' <span class="skill-badge">A</span>';
    btn.innerHTML =
      '<span class="skill-name">' + escHtml(skill.name) + badges + '</span>';
    btn.addEventListener('click', () => {
      if (state.isBusy || isDisabled) return;
      setBusy(true);
      setStatus('busy');
      appendStatusMessage('スキル実行: ' + skill.name);
      window.agent.sendCommand('run_skill', skill.name);
    });

    // トグルスイッチ
    const toggle = document.createElement('label');
    toggle.className = 'skill-toggle';
    toggle.title = isDisabled ? '有効にする' : '無効にする';
    toggle.innerHTML =
      '<input type="checkbox"' + (isDisabled ? '' : ' checked') + '>' +
      '<span class="skill-toggle-slider"></span>';
    toggle.querySelector('input').addEventListener('change', (e) => {
      e.stopPropagation();
      window.agent.sendCommand('toggle_skill', skill.name);
    });

    row.appendChild(btn);
    row.appendChild(toggle);
    skillsListEl.appendChild(row);
  });
}

function updateSkillToggleUI(skillName, enabled) {
  const row = skillsListEl.querySelector('.skill-row[data-skill-name="' + skillName + '"]');
  if (!row) return;
  if (enabled) {
    row.classList.remove('skill-disabled');
  } else {
    row.classList.add('skill-disabled');
  }
  const checkbox = row.querySelector('.skill-toggle input');
  if (checkbox) checkbox.checked = enabled;
  const toggleLabel = row.querySelector('.skill-toggle');
  if (toggleLabel) toggleLabel.title = enabled ? '無効にする' : '有効にする';
}

// ── Compacting spinner ──────────────────────────────────────────

function showCompactingSpinner() {
  if (document.getElementById('compacting-overlay')) return;
  const overlay = document.createElement('div');
  overlay.id = 'compacting-overlay';
  overlay.innerHTML =
    '<div class="compacting-spinner-box">' +
      '<div class="compacting-spinner"></div>' +
      '<div class="compacting-label">会話を圧縮中...</div>' +
    '</div>';
  document.getElementById('chat-container').appendChild(overlay);
  scrollToBottom();
}

function hideCompactingSpinner() {
  const overlay = document.getElementById('compacting-overlay');
  if (overlay) overlay.remove();
}

// ── Utilities ──────────────────────────────────────────────────

function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function scrollToBottom() {
  const container = document.getElementById('chat-container');
  requestAnimationFrame(() => {
    container.scrollTop = container.scrollHeight;
  });
}

function enableInput() {
  inputEl.disabled = false;
  sendBtn.disabled = false;
  inputEl.focus();
}

function setBusy(busy) {
  state.isBusy = busy;
  inputEl.disabled = busy;
  sendBtn.disabled = busy;
  if (!busy) {
    inputEl.focus();
  }
}

function setStatus(s) {
  const labels = {
    connecting: '接続中...',
    ready: '準備完了',
    busy: '処理中...',
    error: 'エラー',
  };
  statusConn.textContent = labels[s] || s;
  statusConn.className = 'status-' + s;
}

