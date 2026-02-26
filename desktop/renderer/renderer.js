// ── Per-conversation state ─────────────────────────────────────
const conversations = new Map(); // convId -> ConversationState

function createConversationState(id, title) {
  const el = document.createElement('div');
  el.className = 'conversation-messages';
  el.dataset.convId = id;
  return {
    id: id,
    el: el,
    title: title || '',
    currentAssistantEl: null,
    currentAssistantRaw: '',
    pendingToolCards: [],
  };
}

// ── Global state ──────────────────────────────────────────────
const globalState = {
  isConnected: false,
  isBusy: false,
  autoConfirm: false,
  disabledSkills: new Set(),
  ragFolders: [],
  backendConvId: null,    // Which conv the backend is processing
  activeConvId: null,     // Which conv is currently displayed
  pendingSwitchId: null,  // Queued switch when busy
};

function getBackendConv() {
  return conversations.get(globalState.backendConvId) || null;
}

function getActiveConv() {
  return conversations.get(globalState.activeConvId) || null;
}

// ── DOM refs ───────────────────────────────────────────────────
const messagesContainer = document.getElementById('messages-container');
const inputEl      = document.getElementById('user-input');
const sendBtn      = document.getElementById('send-btn');
const statusConn   = document.getElementById('status-conn');
const statusModel  = document.getElementById('status-model');
const statusCwd    = document.getElementById('status-cwd');
const btnAutoconf  = document.getElementById('btn-autoconfirm');
const skillsListEl = document.getElementById('skills-list');
const btnSkillsReload = document.getElementById('btn-skills-reload');
const ragFoldersEl = document.getElementById('rag-folders');
const btnAddFolder = document.getElementById('btn-add-folder');
const btnNewConv   = document.getElementById('btn-new-conv');
const convListEl   = document.getElementById('conv-list');

// ── Conversation management ────────────────────────────────────

function ensureConversation(convId, title) {
  if (!conversations.has(convId)) {
    const convState = createConversationState(convId, title);
    conversations.set(convId, convState);
    messagesContainer.appendChild(convState.el);
    convState.el.style.display = 'none';
  }
  return conversations.get(convId);
}

function showConversation(convId) {
  for (const [id, conv] of conversations) {
    conv.el.style.display = (id === convId) ? 'block' : 'none';
  }
  globalState.activeConvId = convId;
  updateConversationListHighlight();
}

function switchConversation(convId) {
  if (convId === globalState.activeConvId && convId === globalState.backendConvId) {
    return;
  }

  if (globalState.isBusy) {
    // Visual-only switch while agent is busy
    showConversation(convId);
    if (convId === globalState.backendConvId) {
      // Switching back to the conversation being processed
      globalState.pendingSwitchId = null;
      disableInputWithMessage('処理中...');
    } else {
      globalState.pendingSwitchId = convId;
      disableInputWithMessage('処理完了後に送信できます');
    }
    return;
  }

  // Full switch: visual + backend
  showConversation(convId);

  // Save current UI HTML before switching
  var currentConv = conversations.get(globalState.backendConvId);
  var currentHtml = currentConv ? currentConv.el.innerHTML : '';

  // Tell backend to switch
  window.agent.sendCommand('switch_conversation', {
    id: convId,
    ui_html: currentHtml,
  });

  globalState.backendConvId = convId;
}

// ── Message rendering ──────────────────────────────────────────

function appendUserMessage(content) {
  var conv = getBackendConv();
  if (!conv) return;
  var group = document.createElement('div');
  group.className = 'message-group message-user';
  var bubble = document.createElement('div');
  bubble.className = 'bubble';
  bubble.textContent = content;
  group.appendChild(bubble);
  conv.el.appendChild(group);
  scrollToBottomIfActive();
}

function startAssistantMessage() {
  var conv = getBackendConv();
  if (!conv) return null;
  var group = document.createElement('div');
  group.className = 'message-group message-assistant';
  var bubble = document.createElement('div');
  bubble.className = 'bubble streaming-cursor';
  group.appendChild(bubble);
  conv.el.appendChild(group);
  conv.currentAssistantEl = bubble;
  conv.currentAssistantRaw = '';
  scrollToBottomIfActive();
  return bubble;
}

function appendToken(content) {
  var conv = getBackendConv();
  if (!conv) return;
  if (!conv.currentAssistantEl) {
    startAssistantMessage();
  }
  conv.currentAssistantRaw += content;
  conv.currentAssistantEl.innerHTML = renderMarkdown(conv.currentAssistantRaw);
  scrollToBottomIfActive();
}

function finalizeAssistantMessage() {
  var conv = getBackendConv();
  if (!conv || !conv.currentAssistantEl) return;
  if (conv.currentAssistantRaw) {
    conv.currentAssistantEl.innerHTML = renderMarkdown(conv.currentAssistantRaw);
  }
  conv.currentAssistantEl.classList.remove('streaming-cursor');
  conv.currentAssistantEl = null;
  conv.currentAssistantRaw = '';
}

// Initialize marked (loaded via <script> tag as UMD global)
if (typeof marked !== 'undefined') {
  marked.setOptions({ breaks: true, gfm: true });
}

function renderMarkdown(text) {
  if (!text) return '';
  try {
    var html = marked.parse(text);
    html = html.replace(
      /<!--\s*sources\s*-->([\s\S]*?)<!--\s*\/sources\s*-->/g,
      function(_, inner) {
        return '<div class="source-card">' +
          '<div class="source-card-title"><span>&#128269;</span> 参照元</div>' +
          inner +
          '</div>';
      }
    );
    return html;
  } catch (e) {
    return escHtml(text).replace(/\n/g, '<br>');
  }
}

function appendToolCall(name, args) {
  finalizeAssistantMessage();

  var conv = getBackendConv();
  if (!conv) return null;

  var argsStr = JSON.stringify(args, null, 2);
  var card = document.createElement('div');
  card.className = 'tool-card running';
  card.dataset.toolName = name;

  var cmdPreview = (name === 'run_command' && args && args.command)
    ? args.command
    : '';
  var statusHtml = cmdPreview
    ? '<div class="tool-card-status">' +
        '<span class="tool-card-status-label">実行中:</span>' +
        '<span class="tool-card-status-cmd">' + escHtml(cmdPreview) + '</span>' +
      '</div>'
    : '<div class="tool-card-status">' +
        '<span class="tool-card-status-label">実行中...</span>' +
      '</div>';

  card.innerHTML =
    '<div class="tool-card-header">' +
      '<span class="icon">&#9889;</span>' +
      '<span>' + escHtml(name) + '</span>' +
      '<span class="tool-card-spinner"></span>' +
    '</div>' +
    statusHtml +
    '<div class="tool-card-args">' +
      escHtml(argsStr.length > 300 ? argsStr.slice(0, 300) + '...' : argsStr) +
    '</div>';

  conv.el.appendChild(card);
  conv.pendingToolCards.push(card);
  scrollToBottomIfActive();
  return card;
}

function appendToolResult(name, result, status) {
  var conv = getBackendConv();
  if (!conv) return;

  var idx = conv.pendingToolCards.findIndex(function(c) { return c.dataset.toolName === name; });
  var card = idx >= 0 ? conv.pendingToolCards.splice(idx, 1)[0] : null;

  if (card) {
    card.classList.remove('running');
    card.classList.add('result-' + status);
    var icon = status === 'ok' ? '\u2713' : status === 'error' ? '\u2717' : '\u2013';
    var headerEl = card.querySelector('.tool-card-header');
    headerEl.innerHTML =
      '<span class="icon">' + icon + '</span>' +
      '<span>' + escHtml(name) + '</span>' +
      '<span style="margin-left:auto;color:var(--text-dim);font-size:10px">' +
        escHtml(status) +
      '</span>';

    var argsEl = card.querySelector('.tool-card-args');
    var preview = result.length > 150 ? result.slice(0, 150) + '...' : result;
    if (argsEl) argsEl.textContent = preview;
  }
}

function appendConfirmCard(id, toolName, args, preview) {
  finalizeAssistantMessage();

  var conv = getBackendConv();
  if (!conv) return;

  var card = document.createElement('div');
  card.className = 'confirm-card';
  card.dataset.confirmId = id;

  var argsStr = JSON.stringify(args, null, 2);
  var argsDisplay = argsStr.length > 200 ? argsStr.slice(0, 200) + '...' : argsStr;

  var html =
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

  card.querySelector('.confirm-btn-approve').addEventListener('click', function() {
    resolveConfirm(card, id, true);
  });
  card.querySelector('.confirm-btn-cancel').addEventListener('click', function() {
    resolveConfirm(card, id, false);
  });

  conv.el.appendChild(card);
  scrollToBottomIfActive();
}

function resolveConfirm(card, id, approved) {
  card.querySelectorAll('.confirm-btn').forEach(function(b) { b.disabled = true; });
  var label = approved ? '承認済み' : 'キャンセル済み';
  var color = approved ? 'var(--accent-green)' : 'var(--text-dim)';
  card.querySelector('.confirm-buttons').innerHTML =
    '<span style="font-size:12px;color:' + color + '">' + label + '</span>';

  window.agent.sendConfirm(id, approved);
}

function renderDiffPreview(text) {
  if (!text) return '';
  return text.split('\n').map(function(line) {
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
  var conv = getBackendConv();
  if (!conv) return;
  removeEphemeralStatus();
  var el = document.createElement('div');
  el.className = 'status-message';
  el.textContent = text;
  if (ephemeral) el.dataset.ephemeral = '1';
  conv.el.appendChild(el);
  scrollToBottomIfActive();
}

function removeEphemeralStatus() {
  var conv = getBackendConv();
  if (!conv) return;
  conv.el.querySelectorAll('.status-message[data-ephemeral="1"]')
    .forEach(function(el) { el.remove(); });
}

function appendErrorMessage(text) {
  var conv = getBackendConv();
  if (!conv) return;
  var el = document.createElement('div');
  el.className = 'error-message';
  el.textContent = text;
  conv.el.appendChild(el);
  scrollToBottomIfActive();
}

// ── Conversation list UI ────────────────────────────────────────

function renderConversationList(convList) {
  convListEl.innerHTML = '';
  if (!convList || convList.length === 0) return;

  convList.forEach(function(conv) {
    var item = document.createElement('div');
    item.className = 'conv-item' +
      (conv.id === globalState.activeConvId ? ' conv-item-active' : '');
    item.dataset.convId = conv.id;

    var titleSpan = document.createElement('span');
    titleSpan.className = 'conv-item-title';
    titleSpan.textContent = conv.title || '新しい会話';
    titleSpan.title = conv.title || '';

    var deleteBtn = document.createElement('button');
    deleteBtn.className = 'conv-item-delete';
    deleteBtn.innerHTML = '&times;';
    deleteBtn.title = '削除';
    deleteBtn.addEventListener('click', function(e) {
      e.stopPropagation();
      if (conv.id === globalState.backendConvId) return;
      if (confirm('この会話を削除しますか？')) {
        window.agent.sendCommand('delete_conversation', conv.id);
      }
    });

    item.appendChild(titleSpan);
    item.appendChild(deleteBtn);

    item.addEventListener('click', function() {
      switchConversation(conv.id);
    });

    convListEl.appendChild(item);
  });
}

function updateConversationListHighlight() {
  var items = convListEl.querySelectorAll('.conv-item');
  items.forEach(function(item) {
    if (item.dataset.convId === globalState.activeConvId) {
      item.classList.add('conv-item-active');
    } else {
      item.classList.remove('conv-item-active');
    }
  });
}

// ── Incoming message handler ───────────────────────────────────

window.agent.onMessage(function(msg) {
  switch (msg.type) {

    case 'system_info':
      statusModel.textContent = 'model: ' + msg.model;
      statusCwd.textContent = 'cwd: ' + msg.cwd;
      statusConn.textContent = '接続済み';
      statusConn.className = 'status-ready';
      globalState.isConnected = true;
      if (msg.disabled_skills) {
        globalState.disabledSkills = new Set(msg.disabled_skills);
      }
      // Initialize first conversation
      if (msg.conversation_id) {
        ensureConversation(msg.conversation_id, '');
        showConversation(msg.conversation_id);
        globalState.backendConvId = msg.conversation_id;
        globalState.activeConvId = msg.conversation_id;
      }
      if (msg.conversations) {
        renderConversationList(msg.conversations);
      }
      enableInput();
      if (msg.permission_mode) {
        updatePermissionButton(msg.permission_mode);
      }
      if (msg.has_context) {
        appendStatusMessage('プロジェクトコンテキスト読み込み済み', true);
        setTimeout(removeEphemeralStatus, 3000);
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
        globalState.disabledSkills.delete(msg.name);
      } else {
        globalState.disabledSkills.add(msg.name);
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
      if (globalState.isBusy) {
        setStatus('ready');
        setBusy(false);
      }
      // Save current conversation HTML
      var finishedConv = getBackendConv();
      if (finishedConv) {
        window.agent.sendCommand('save_conversation_html', {
          ui_html: finishedConv.el.innerHTML,
        });
      }
      // Execute queued conversation switch
      if (globalState.pendingSwitchId) {
        var targetId = globalState.pendingSwitchId;
        globalState.pendingSwitchId = null;
        switchConversation(targetId);
      }
      // Request updated conversation list
      window.agent.sendCommand('list_conversations');
      break;

    case 'compacting':
      showCompactingSpinner();
      break;

    case 'compact_done':
      hideCompactingSpinner();
      appendStatusMessage(msg.message || '会話を自動圧縮しました');
      break;

    case 'pdf_progress':
      handlePdfProgress(msg);
      break;

    case 'todo_update':
      renderTodoList(msg.todos);
      break;

    case 'permission_mode':
      updatePermissionButton(msg.mode);
      break;

    case 'error':
      finalizeAssistantMessage();
      hideCompactingSpinner();
      appendErrorMessage(msg.message);
      setStatus('error');
      setBusy(false);
      break;

    // ── Conversation events ──
    case 'conversation_new':
      ensureConversation(msg.conversation_id, '');
      showConversation(msg.conversation_id);
      globalState.backendConvId = msg.conversation_id;
      globalState.pendingSwitchId = null;
      enableInput();
      break;

    case 'conversation_switched':
      var switchedConv = ensureConversation(msg.conversation_id, msg.title);
      if (msg.ui_html && switchedConv.el.children.length === 0) {
        switchedConv.el.innerHTML = msg.ui_html;
      }
      showConversation(msg.conversation_id);
      globalState.backendConvId = msg.conversation_id;
      globalState.pendingSwitchId = null;
      enableInput();
      scrollToBottom();
      break;

    case 'conversations_list':
      renderConversationList(msg.conversations);
      break;

    case 'conversation_deleted':
      var delConv = conversations.get(msg.conversation_id);
      if (delConv) {
        delConv.el.remove();
        conversations.delete(msg.conversation_id);
      }
      break;

    case 'conversation_renamed':
      var renConv = conversations.get(msg.conversation_id);
      if (renConv) renConv.title = msg.title;
      break;
  }
});

// ── Sending messages ───────────────────────────────────────────

function sendMessage() {
  var content = inputEl.value.trim();
  if (!content || globalState.isBusy || !globalState.isConnected) return;

  // Can only send if active conv matches backend conv
  if (globalState.activeConvId !== globalState.backendConvId) return;

  if (globalState.ragFolders.length > 0) {
    var folderNames = globalState.ragFolders.map(function(f) { return f.split('/').pop() || f; });
    appendUserMessage(content + '\n[RAG folders: ' + folderNames.join(', ') + ']');
  } else {
    appendUserMessage(content);
  }
  inputEl.value = '';
  autoResizeInput();

  setBusy(true);
  setStatus('busy');

  if (globalState.ragFolders.length > 0) {
    window.agent.sendMessageWithFolders(content, globalState.ragFolders);
  } else {
    window.agent.sendMessage(content);
  }
}

// ── Input handling ─────────────────────────────────────────────

inputEl.addEventListener('keydown', function(e) {
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

// ── RAG folder management ──────────────────────────────────────

btnAddFolder.addEventListener('click', async function() {
  var folderPath = await window.agent.selectFolder();
  if (!folderPath) return;
  if (globalState.ragFolders.includes(folderPath)) return;
  globalState.ragFolders.push(folderPath);
  renderRagFolders();
});

function renderRagFolders() {
  ragFoldersEl.innerHTML = '';
  if (globalState.ragFolders.length === 0) {
    ragFoldersEl.classList.add('hidden');
    return;
  }
  ragFoldersEl.classList.remove('hidden');
  globalState.ragFolders.forEach(function(folder, idx) {
    var chip = document.createElement('span');
    chip.className = 'rag-folder-chip';
    var name = folder.split('/').pop() || folder;
    chip.innerHTML =
      '<span class="rag-folder-icon">&#128193;</span>' +
      '<span class="rag-folder-name" title="' + escHtml(folder) + '">' + escHtml(name) + '</span>' +
      '<button class="rag-folder-remove" title="削除">&times;</button>';
    chip.querySelector('.rag-folder-remove').addEventListener('click', function() {
      globalState.ragFolders.splice(idx, 1);
      renderRagFolders();
    });
    ragFoldersEl.appendChild(chip);
  });
}

// ── Permission mode ──────────────────────────────────────────────

var permissionLabels = {ask: '常に確認', auto_read: '読取自動', auto_all: '全自動'};
var permissionColors = {ask: 'var(--accent-green)', auto_read: 'var(--accent-yellow)', auto_all: 'var(--accent-red)'};
var currentPermission = 'ask';

function updatePermissionButton(mode) {
  currentPermission = mode;
  btnAutoconf.textContent = '権限: ' + (permissionLabels[mode] || mode);
  btnAutoconf.style.color = permissionColors[mode] || 'var(--text-secondary)';
}

// ── Sidebar buttons ────────────────────────────────────────────

btnNewConv.addEventListener('click', function() {
  if (globalState.isBusy) return;
  var currentConv = getBackendConv();
  var currentHtml = currentConv ? currentConv.el.innerHTML : '';
  window.agent.sendCommand('new_conversation', { ui_html: currentHtml });
});

btnAutoconf.addEventListener('click', function() {
  window.agent.sendCommand('autoconfirm');
});

// ── Skills ──────────────────────────────────────────────────────

btnSkillsReload.addEventListener('click', function() {
  window.agent.sendCommand('skills_reload');
});

function renderSkillsList(skills) {
  skillsListEl.innerHTML = '';
  if (!skills || skills.length === 0) {
    skillsListEl.innerHTML = '<div class="skills-empty">スキルなし</div>';
    return;
  }
  skills.forEach(function(skill) {
    var isDisabled = globalState.disabledSkills.has(skill.name);

    var row = document.createElement('div');
    row.className = 'skill-row' + (isDisabled ? ' skill-disabled' : '');
    row.dataset.skillName = skill.name;

    var btn = document.createElement('button');
    btn.className = 'skill-btn';
    btn.title = skill.description;
    var badges = '';
    if (skill.has_scripts) badges += ' <span class="skill-badge">S</span>';
    if (skill.has_references) badges += ' <span class="skill-badge">R</span>';
    if (skill.has_assets) badges += ' <span class="skill-badge">A</span>';
    btn.innerHTML =
      '<span class="skill-name">' + escHtml(skill.name) + badges + '</span>';
    btn.addEventListener('click', function() {
      if (globalState.isBusy || isDisabled) return;
      setBusy(true);
      setStatus('busy');
      appendStatusMessage('スキル実行: ' + skill.name);
      window.agent.sendCommand('run_skill', skill.name);
    });

    var toggle = document.createElement('label');
    toggle.className = 'skill-toggle';
    toggle.title = isDisabled ? '有効にする' : '無効にする';
    toggle.innerHTML =
      '<input type="checkbox"' + (isDisabled ? '' : ' checked') + '>' +
      '<span class="skill-toggle-slider"></span>';
    toggle.querySelector('input').addEventListener('change', function(e) {
      e.stopPropagation();
      window.agent.sendCommand('toggle_skill', skill.name);
    });

    row.appendChild(btn);
    row.appendChild(toggle);
    skillsListEl.appendChild(row);
  });
}

function updateSkillToggleUI(skillName, enabled) {
  var row = skillsListEl.querySelector('.skill-row[data-skill-name="' + skillName + '"]');
  if (!row) return;
  if (enabled) {
    row.classList.remove('skill-disabled');
  } else {
    row.classList.add('skill-disabled');
  }
  var checkbox = row.querySelector('.skill-toggle input');
  if (checkbox) checkbox.checked = enabled;
  var toggleLabel = row.querySelector('.skill-toggle');
  if (toggleLabel) toggleLabel.title = enabled ? '無効にする' : '有効にする';
}

// ── Compacting spinner ──────────────────────────────────────────

function showCompactingSpinner() {
  if (document.getElementById('compacting-overlay')) return;
  var overlay = document.createElement('div');
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
  var overlay = document.getElementById('compacting-overlay');
  if (overlay) overlay.remove();
}

// ── PDF progress ────────────────────────────────────────────────

function handlePdfProgress(msg) {
  var container = document.getElementById('pdf-progress');
  var label = document.getElementById('pdf-progress-label');
  var detail = document.getElementById('pdf-progress-detail');
  var bar = document.getElementById('pdf-progress-bar');

  if (msg.status === 'done') {
    container.classList.add('hidden');
    return;
  }

  container.classList.remove('hidden');

  var fileInfo = msg.total_files > 1
    ? '[' + (msg.file_index + 1) + '/' + msg.total_files + '] '
    : '';
  label.textContent = fileInfo + (msg.file || 'PDF分析中...');
  detail.textContent = msg.detail || '';

  var pct = Math.min(Math.max(msg.percent || 0, 0), 100);
  bar.style.width = pct + '%';
}

// ── TodoWrite ────────────────────────────────────────────────────

function renderTodoList(todos) {
  var conv = getBackendConv();
  if (!conv) return;

  // 既存のカードがあれば更新、なければ新規作成
  var card = conv.el.querySelector('.todo-card');
  if (!card) {
    card = document.createElement('div');
    card.className = 'todo-card';
    conv.el.appendChild(card);
  }

  var completed = todos.filter(function(t) { return t.status === 'completed'; }).length;
  var total = todos.length;
  var pct = total > 0 ? Math.round(completed / total * 100) : 0;

  var html =
    '<div class="todo-card-header">' +
      '<span class="todo-card-title">&#9744; タスク</span>' +
      '<span class="todo-card-count">' + completed + '/' + total + '</span>' +
    '</div>' +
    '<div class="todo-progress-bar"><div class="todo-progress-fill" style="width:' + pct + '%"></div></div>';

  todos.forEach(function(t) {
    var statusClass = 'todo-status-' + t.status;
    var icon = t.status === 'completed' ? '\u2713'
      : t.status === 'in_progress' ? '\u25C9'
      : '\u25CB';
    html +=
      '<div class="todo-item ' + statusClass + '">' +
        '<span class="todo-icon">' + icon + '</span>' +
        '<span class="todo-text">' + escHtml(t.status === 'in_progress' ? t.activeForm : t.content) + '</span>' +
      '</div>';
  });

  card.innerHTML = html;
  scrollToBottomIfActive();
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
  var container = document.getElementById('chat-container');
  requestAnimationFrame(function() {
    container.scrollTop = container.scrollHeight;
  });
}

function scrollToBottomIfActive() {
  if (globalState.backendConvId === globalState.activeConvId) {
    scrollToBottom();
  }
}

function enableInput() {
  inputEl.disabled = false;
  sendBtn.disabled = false;
  inputEl.placeholder = 'メッセージを入力... (Enter で送信, Shift+Enter で改行)';
  inputEl.focus();
}

function disableInputWithMessage(msg) {
  inputEl.disabled = true;
  sendBtn.disabled = true;
  inputEl.placeholder = msg;
}

function setBusy(busy) {
  globalState.isBusy = busy;
  inputEl.disabled = busy;
  sendBtn.disabled = busy;
  if (!busy) {
    // Restore input if active conv matches backend
    if (globalState.activeConvId === globalState.backendConvId) {
      inputEl.placeholder = 'メッセージを入力... (Enter で送信, Shift+Enter で改行)';
    }
    inputEl.focus();
  }
}

function setStatus(s) {
  var labels = {
    connecting: '接続中...',
    ready: '準備完了',
    busy: '処理中...',
    error: 'エラー',
  };
  statusConn.textContent = labels[s] || s;
  statusConn.className = 'status-' + s;
}
