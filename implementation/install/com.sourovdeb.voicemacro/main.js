'use strict';

const { app, dialog } = require('electron');
const { spawn } = require('child_process');
const { existsSync } = require('fs');
const { join, dirname } = require('path');

function fail(message) {
  dialog.showErrorBox('VoiceMacro', message);
  app.exit(1);
}

app.whenReady().then(() => {
  const local = process.env.LOCALAPPDATA;
  if (process.platform !== 'win32' || !local) {
    fail('This VoiceMacro launcher requires Windows.');
    return;
  }
  const exe = join(local, 'VoiceMacro', 'App', 'VoiceMacro.exe');
  if (!existsSync(exe)) {
    fail('Run Install-VoiceMacro.cmd for this Windows account.');
    return;
  }
  const child = spawn(exe, [], { cwd: dirname(exe), detached: true, stdio: 'ignore' });
  child.once('error', error => fail(error.message));
  child.once('spawn', () => {
    child.unref();
    app.quit();
  });
}).catch(error => fail(error.message));
