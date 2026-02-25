/**
 * web-agent.js - WebSocket 版 window.agent API
 *
 * Electron の preload.js が contextBridge で公開する window.agent と
 * 同一インターフェースを WebSocket 上で実装する。
 * ブラウザモード時のみ読み込まれる (index.html の条件分岐)。
 */
(function () {
  'use strict';

  var wsProto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  var wsUrl = wsProto + '//' + location.host + '/ws';

  var ws = null;
  var messageCallback = null;
  var reconnectTimer = null;

  function connect() {
    ws = new WebSocket(wsUrl);

    ws.onopen = function () {
      console.log('[web-agent] WebSocket connected');
    };

    ws.onmessage = function (event) {
      try {
        var msg = JSON.parse(event.data);
        if (messageCallback) {
          messageCallback(msg);
        }
      } catch (e) {
        console.error('[web-agent] Failed to parse message:', e);
      }
    };

    ws.onclose = function () {
      console.log('[web-agent] WebSocket closed, reconnecting in 2s...');
      reconnectTimer = setTimeout(connect, 2000);
    };

    ws.onerror = function (err) {
      console.error('[web-agent] WebSocket error:', err);
    };
  }

  function sendJSON(obj) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(obj));
    } else {
      console.warn('[web-agent] WebSocket not connected, message dropped');
    }
  }

  // preload.js と同一の window.agent API を公開
  window.agent = {
    sendMessage: function (content) {
      sendJSON({ type: 'user_message', content: content });
    },

    sendMessageWithFolders: function (content, folders) {
      sendJSON({ type: 'user_message', content: content, rag_folders: folders });
    },

    sendConfirm: function (id, approved) {
      sendJSON({ type: 'confirm_response', id: id, approved: approved });
    },

    sendCommand: function (name, args) {
      sendJSON({ type: 'command', name: name, args: args || '' });
    },

    selectFolder: function () {
      // Web モードではネイティブダイアログが使えないため prompt で代替
      return new Promise(function (resolve) {
        var path = prompt('フォルダの絶対パスを入力してください:');
        resolve(path && path.trim() ? path.trim() : null);
      });
    },

    onMessage: function (callback) {
      messageCallback = callback;
    },

    removeAllListeners: function () {
      messageCallback = null;
    }
  };

  // Web モード用 CSS クラスを付与
  document.body.classList.add('web-mode');

  connect();
})();
