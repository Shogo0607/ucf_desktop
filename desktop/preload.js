const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('agent', {
  // Renderer -> Python (via main process)
  sendMessage: (content) => {
    ipcRenderer.send('send-to-python', { type: 'user_message', content });
  },
  sendConfirm: (id, approved) => {
    ipcRenderer.send('send-to-python', { type: 'confirm_response', id, approved });
  },
  sendCommand: (name, args) => {
    ipcRenderer.send('send-to-python', { type: 'command', name, args: args || '' });
  },

  // Python -> Renderer
  onMessage: (callback) => {
    ipcRenderer.on('python-message', (_event, msg) => callback(msg));
  },
  removeAllListeners: () => {
    ipcRenderer.removeAllListeners('python-message');
  },
});
