const { app, BrowserWindow, ipcMain, dialog } = require('electron');
const { spawn } = require('node:child_process');
const { randomBytes } = require('node:crypto');
const fs = require('node:fs/promises');
const path = require('node:path');
let backend, win, base, quitting = false;
const token = randomBytes(32).toString('hex');
async function request(method, endpoint, data) {
  const r = await fetch(base + endpoint, {
    method, headers: { 'X-City-Token': token, 'Content-Type': 'application/json' },
    body: data === undefined ? undefined : JSON.stringify(data), signal: AbortSignal.timeout(10000)
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}
function trusted(event) {
  if (!win || event.sender !== win.webContents || event.senderFrame !== win.webContents.mainFrame) throw new Error('Neznámý klient');
}
async function boot() {
  const root = app.isPackaged ? process.resourcesPath : path.join(__dirname, '..');
  let log = '', output = '', exit = false;
  backend = spawn(process.env.CITY_FORGE_PYTHON || '/usr/bin/python3', ['-u', '-m', 'backend.api'], {
    cwd: root, env: { ...process.env, CITY_TOKEN: token, CITY_DATA: path.join(app.getPath('userData'), 'runs') },
    stdio: ['ignore', 'pipe', 'pipe']
  });
  backend.stdout.on('data', chunk => {
    output = (output + chunk).slice(-4000);
    const match = output.match(/CITY_PORT=(\d+)/);
    if (match) base = `http://127.0.0.1:${match[1]}`;
  });
  backend.stderr.on('data', chunk => { log = (log + chunk).slice(-8000); });
  backend.on('error', err => { log += err.message; exit = true; });
  backend.on('exit', () => {
    exit = true;
    if (win && !quitting) { dialog.showErrorBox('Backend skončil', log || 'Proces byl ukončen.'); app.quit(); }
  });
  let ready = false;
  for (let n = 0; n < 100 && !exit; n++) {
    try { if (base) { await request('GET', '/health'); ready = true; break; } } catch {}
    await new Promise(r => setTimeout(r, 150));
  }
  if (!ready) throw new Error('Backend není dostupný. Ověřte Python a závislosti.\n' + log);
  ipcMain.handle('api', async (event, method, endpoint, data) => {
    trusted(event);
    const allowed = (method === 'GET' && /^\/(dataset|health|jobs\/[a-f0-9]{32})$/.test(endpoint)) ||
      (method === 'POST' && (endpoint === '/jobs' || /^\/jobs\/[a-f0-9]{32}\/cancel$/.test(endpoint)));
    if (!allowed) throw new Error('Nepovolený požadavek');
    return request(method, endpoint, data);
  });
  ipcMain.handle('import', async event => {
    trusted(event);
    const selected = await dialog.showOpenDialog(win, { properties: ['openFile'], filters: [{ name: 'Síť CITY FORGE', extensions: ['json'] }] });
    if (selected.canceled) return null;
    const filename = selected.filePaths[0];
    if ((await fs.stat(filename)).size > 262144) throw new Error('Import překračuje 256 KiB');
    return request('PUT', '/dataset', JSON.parse(await fs.readFile(filename, 'utf8')));
  });
  ipcMain.handle('export', async (event, id, format) => {
    trusted(event);
    if (!/^[a-f0-9]{32}$/.test(id) || !['html', 'csv'].includes(format)) throw new Error('Neplatný export');
    const r = await fetch(`${base}/jobs/${id}/export/${format}`, { headers: { 'X-City-Token': token }, signal: AbortSignal.timeout(10000) });
    if (!r.ok) throw new Error(await r.text());
    const text = await r.text();
    const selected = await dialog.showSaveDialog(win, { defaultPath: `city-forge-${id}.${format}` });
    if (!selected.canceled) await fs.writeFile(selected.filePath, text, 'utf8');
  });
  win = new BrowserWindow({ width: 1360, height: 920, webPreferences: {
    preload: path.join(__dirname, 'preload.cjs'), contextIsolation: true, nodeIntegration: false, sandbox: true
  } });
  win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  win.webContents.on('will-navigate', event => event.preventDefault());
  await win.loadFile(path.join(__dirname, '../dist/index.html'));
}
if (!app.requestSingleInstanceLock()) app.quit();
else {
  app.whenReady().then(boot).catch(err => { dialog.showErrorBox('CITY FORGE', String(err)); app.quit(); });
  app.on('second-instance', () => { if (win) { if (win.isMinimized()) win.restore(); win.focus(); } });
}
app.on('before-quit', () => { quitting = true; backend?.kill('SIGTERM'); });
app.on('window-all-closed', () => app.quit());
