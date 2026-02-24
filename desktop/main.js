const { app, BrowserWindow, ipcMain, dialog } = require('electron');
const { spawn, execSync } = require('child_process');
const path = require('path');
const readline = require('readline');
const fs = require('fs');
const os = require('os');

let mainWindow;
let pythonProcess;

// ── Python 実行コマンドの解決 ────────────────────────────────

function resolveCommand() {
  const plat = os.platform();

  // Strategy 1: uv (preferred)
  try {
    execSync('uv --version', { stdio: 'ignore' });
    return {
      cmd: plat === 'win32' ? 'uv.exe' : 'uv',
      buildArgs: (agentPath) => ['run', 'python', agentPath, '--gui'],
    };
  } catch (_) { /* uv not found */ }

  // Strategy 2: .venv の python
  const venvPython = plat === 'win32'
    ? path.join(__dirname, '..', '.venv', 'Scripts', 'python.exe')
    : path.join(__dirname, '..', '.venv', 'bin', 'python3');

  if (fs.existsSync(venvPython)) {
    return {
      cmd: venvPython,
      buildArgs: (agentPath) => [agentPath, '--gui'],
    };
  }

  // Strategy 3: システム python
  const candidates = plat === 'win32'
    ? ['python', 'python3']
    : ['python3', 'python'];

  for (const c of candidates) {
    try {
      execSync(`${c} --version`, { stdio: 'ignore' });
      return {
        cmd: c,
        buildArgs: (agentPath) => [agentPath, '--gui'],
      };
    } catch (_) { /* not found */ }
  }

  throw new Error(
    'Python が見つかりません。Python 3.9+ または uv をインストールしてください。'
  );
}

function getAgentPath() {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, 'agent.py');
  }
  return path.join(__dirname, '..', 'agent.py');
}

// ── Python プロセスの起動と IPC ブリッジ ──────────────────────

function setupPythonBridge(win) {
  // ウィンドウ破棄済みかチェックしてから送信するヘルパー
  function safeSend(channel, data) {
    if (!win.isDestroyed()) {
      win.webContents.send(channel, data);
    }
  }

  const agentPath = getAgentPath();
  const workingDir = path.dirname(agentPath);

  let resolved;
  try {
    resolved = resolveCommand();
  } catch (err) {
    safeSend('python-message', {
      type: 'error',
      message: err.message,
    });
    return;
  }

  const cmd = resolved.cmd;
  const args = resolved.buildArgs(agentPath);

  console.log(`Spawning: ${cmd} ${args.join(' ')}`);
  console.log(`CWD: ${workingDir}`);

  const env = Object.assign({}, process.env, {
    PYTHONIOENCODING: 'utf-8',
    PYTHONUNBUFFERED: '1',
  });

  pythonProcess = spawn(cmd, args, {
    cwd: workingDir,
    env,
    stdio: ['pipe', 'pipe', 'pipe'],
    shell: false,
    windowsHide: true,
  });

  // stdout / stderr を UTF-8 で読む
  pythonProcess.stdout.setEncoding('utf-8');
  pythonProcess.stderr.setEncoding('utf-8');

  // stdout を行ごとに読んで JSON パース → renderer に転送
  const rl = readline.createInterface({ input: pythonProcess.stdout });
  rl.on('line', (line) => {
    line = line.trim();
    if (!line) return;
    try {
      const msg = JSON.parse(line);
      safeSend('python-message', msg);
    } catch (e) {
      console.error('Failed to parse Python output:', line);
    }
  });

  // stderr をログ出力（PDF 分析等のログは UI に表示しない）
  pythonProcess.stderr.on('data', (data) => {
    const text = data.toString().trim();
    if (text) {
      console.error('[Python stderr]', text);
      // PDF 分析のログや tqdm 出力は UI に表示しない
      const isPdfLog = /^(Checking for|Found \d+|Processing |  Converting|  Starting batch|  Saved |  Finished |  Created output|  Moving |  Failed to|No new PDFs|Error (processing|summarizing) page)/i.test(text);
      const isTqdmOutput = /\d+%\||\|.*\d+\/\d+/.test(text);
      if (!isPdfLog && !isTqdmOutput) {
        safeSend('python-message', {
          type: 'error',
          message: text,
        });
      }
    }
  });

  pythonProcess.on('close', (code) => {
    console.log('Python process exited with code', code);
    safeSend('python-message', {
      type: 'error',
      message: `Python プロセスが終了しました (code ${code})`,
    });
  });

  pythonProcess.on('error', (err) => {
    console.error('Failed to spawn Python:', err);
    safeSend('python-message', {
      type: 'error',
      message: `Python の起動に失敗しました: ${err.message}`,
    });
  });

  // renderer → Python stdin
  ipcMain.on('send-to-python', (_event, msg) => {
    if (pythonProcess && pythonProcess.stdin.writable) {
      pythonProcess.stdin.write(JSON.stringify(msg) + '\n', 'utf-8');
    }
  });
}

// ── フォルダ選択ダイアログ ─────────────────────────────────────

ipcMain.handle('select-folder', async () => {
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openDirectory'],
    title: 'RAG 対象フォルダを選択',
  });
  if (result.canceled || result.filePaths.length === 0) {
    return null;
  }
  return result.filePaths[0];
});

// ── ウィンドウ作成 ───────────────────────────────────────────

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1100,
    height: 800,
    minWidth: 600,
    minHeight: 400,
    backgroundColor: '#1a1a1a',
    titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'default',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.loadFile(path.join(__dirname, 'renderer', 'index.html'));
  setupPythonBridge(mainWindow);
}

app.whenReady().then(createWindow);

app.on('window-all-closed', () => {
  if (pythonProcess) {
    pythonProcess.kill();
    pythonProcess = null;
  }
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createWindow();
  }
});

app.on('before-quit', () => {
  if (pythonProcess) {
    pythonProcess.kill();
    pythonProcess = null;
  }
});
