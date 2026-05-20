const { app, BrowserWindow, shell } = require('electron');
const path = require('path');
const { spawn } = require('child_process');
const http = require('http');
const fs = require('fs');

let backendProc = null;
let mainWindow = null;

function backendExePath() {
  // In packaged app, the exe lives in resources/bin; in dev, project-local bin/
  if (app.isPackaged) {
    return path.join(process.resourcesPath, 'bin', 'casemind-backend.exe');
  }
  return path.join(__dirname, 'bin', 'casemind-backend.exe');
}

function webDir() {
  if (app.isPackaged) {
    return path.join(__dirname, 'web');
  }
  return path.join(__dirname, 'web');
}

function waitForBackend(retries = 60) {
  return new Promise((resolve, reject) => {
    const tryOnce = (n) => {
      const req = http.get('http://127.0.0.1:8888/api/health', (res) => {
        if (res.statusCode === 200) return resolve();
        if (n <= 0) return reject(new Error('backend timeout'));
        setTimeout(() => tryOnce(n - 1), 500);
      });
      req.on('error', () => {
        if (n <= 0) return reject(new Error('backend not reachable'));
        setTimeout(() => tryOnce(n - 1), 500);
      });
    };
    tryOnce(retries);
  });
}

function startBackend() {
  const exe = backendExePath();
  if (!fs.existsSync(exe)) {
    console.error('Backend exe not found:', exe);
    return;
  }
  backendProc = spawn(exe, [], {
    cwd: path.dirname(exe),
    windowsHide: true,
    env: { ...process.env, PYTHONUNBUFFERED: '1' },
  });
  backendProc.stdout?.on('data', d => console.log('[backend]', d.toString()));
  backendProc.stderr?.on('data', d => console.log('[backend]', d.toString()));
  backendProc.on('exit', code => console.log('[backend] exited', code));
}

async function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1280,
    height: 820,
    title: 'CaseMind',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });
  const index = path.join(webDir(), 'index.html');
  try {
    await waitForBackend();
  } catch (e) {
    console.warn('backend not ready, loading UI anyway:', e.message);
  }
  await mainWindow.loadFile(index);
}

app.whenReady().then(() => {
  startBackend();
  createWindow();
  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('window-all-closed', () => {
  if (backendProc) {
    try { backendProc.kill(); } catch (_) { /* ignore */ }
  }
  if (process.platform !== 'darwin') app.quit();
});
