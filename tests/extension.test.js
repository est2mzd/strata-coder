'use strict';
const assert = require('assert');
const Module = require('module');
const os = require('os');
const fs = require('fs');
const path = require('path');
const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'strata-extension-'));
const commands = {};
const notices = [];
const statusBar = {show: () => {}, dispose: () => {}};
let monitorTick;
const originalInterval = global.setInterval;
global.setInterval = fn => {monitorTick = fn; return {unref: () => {}};};
const registered = [];
let plugin;
const fake = {
  workspace: {isTrusted: true, workspaceFolders: [{uri: {fsPath: '/repo'}}],
    getConfiguration: () => ({get: (k, d) => k === 'supervisionMode' ? 'legacy' : d}), onDidGrantWorkspaceTrust: () => ({}), onDidChangeWorkspaceFolders: () => ({})},
  window: {createStatusBarItem: () => statusBar, showInformationMessage: m => notices.push(m), createOutputChannel: () => ({appendLine: () => {}, dispose: () => {}}), showWarningMessage: () => {}},
  commands: {registerCommand: (id, fn) => {commands[id] = fn; return {}; }},
  cursor: {mcp: {registerServer: x => registered.push(x), unregisterServer: () => {}},
    plugins: {registerPath: x => {plugin = x;}, unregisterPath: () => {}}}
};
const load = Module._load;
Module._load = function(name, ...args) {return name === 'vscode' ? fake : load.call(this, name, ...args);};
const extension = require('../extension/extension');
const context = {subscriptions: [], extensionPath: path.resolve(__dirname, '..'),
  globalStorageUri: {fsPath: dir}, secrets: {get: async () => 'test-key'}};
extension.activate(context);
global.setInterval = originalInterval;
setImmediate(async () => {
  try {
    assert.equal(registered.length, 1);
    assert.equal(registered[0].server.env.STRATA_API_KEY, 'test-key');
    assert.equal(JSON.parse(registered[0].server.env.STRATA_CODER_CONFIG).mode, 'ssh');
    assert(registered[0].server.args.includes('/repo'));
    assert(plugin.endsWith('cursor-plugin'));
    assert(commands['strataCoder.checkConnection']);
    assert(commands['strataCoder.setCoordinatorToken']);
    const crypto = require('crypto');
    const state = path.join(dir, 'tasks', crypto.createHash('sha256').update('/repo').digest('hex').slice(0, 16), 'progress.json');
    fs.writeFileSync(state, JSON.stringify({cursor: 1, events: [{seq: 1, task_id: 'a', status: 'running'}]}));
    monitorTick();
    assert(statusBar.text.includes('1 running'));
    fs.writeFileSync(state, JSON.stringify({cursor: 2, events: [{seq: 2, task_id: 'a', status: 'review_ready'}]}));
    monitorTick(); monitorTick();
    assert.equal(notices.length, 1);
    assert(statusBar.text.includes('1 review'));

    fake.workspace.getConfiguration = () => ({get: (k, d) => d});
    await commands['strataCoder.connect']();
    assert.equal(registered.length, 1, 'decision mode must not register worker tools');
    assert(commands['strataCoder.prepareDecision']);
    assert(commands['strataCoder.copyDecision']);
    assert(commands['strataCoder.executeDecision']);
    fake.workspace.isTrusted = false;
    await commands['strataCoder.connect']();
    assert.equal(registered.length, 1);
    console.log('Extension registration, secret forwarding, workspace trust and deduplicated progress notification tests passed');
  } finally {fs.rmSync(dir, {recursive: true, force: true});}
});
