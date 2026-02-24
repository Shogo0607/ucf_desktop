const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('agent', {
  // Renderer -> Python (via main process)
  sendMessage: (content) => {
    ipcRenderer.send('send-to-python', { type: 'user_message', content });
  },
  sendMessageWithFolders: (content, folders) => {
    ipcRenderer.send('send-to-python', { type: 'user_message', content, rag_folders: folders });
  },
  sendConfirm: (id, approved) => {
    ipcRenderer.send('send-to-python', { type: 'confirm_response', id, approved });
  },
  sendCommand: (name, args) => {
    ipcRenderer.send('send-to-python', { type: 'command', name, args: args || '' });
  },

  // Folder selection dialog
  selectFolder: () => ipcRenderer.invoke('select-folder'),

  // Python -> Renderer
  onMessage: (callback) => {
    ipcRenderer.on('python-message', (_event, msg) => callback(msg));
  },
  removeAllListeners: () => {
    ipcRenderer.removeAllListeners('python-message');
  },
});
