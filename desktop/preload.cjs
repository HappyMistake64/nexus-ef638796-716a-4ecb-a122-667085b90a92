const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('city', {
  api: (method, path, data) => ipcRenderer.invoke('api', method, path, data),
  importDataset: () => ipcRenderer.invoke('import'),
  export: (id, format) => ipcRenderer.invoke('export', id, format)
});
