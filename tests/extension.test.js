'use strict';
const assert = require('assert');
const Module = require('module');
const os = require('os');
const fs = require('fs');
const path = require('path');
const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'strata-extension-'));
const commands = {};
const registered = [];
let plugin;
const fake = {
  workspace: {isTrusted: true, workspaceFolders: [{uri: {fsPath: '/repo'}}],
    getConfiguration: () => ({get: (k, d) => d}), onDidGrantWorkspaceTrust: () => ({}), onDidChangeWorkspaceFolders: () => ({})},
  window: {createOutputChannel: () => ({appendLine: () => {}, dispose: () => {}}), showWarningMessage: () => {}},
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
setImmediate(async () => {
  try {
    assert.equal(registered.length, 1);
    assert.equal(registered[0].server.env.STRATA_API_KEY, 'test-key');
    assert.equal(JSON.parse(registered[0].server.env.STRATA_CODER_CONFIG).mode, 'ssh');
    assert(registered[0].server.args.includes('/repo'));
    assert(plugin.endsWith('cursor-plugin'));
    assert(commands['strataCoder.checkConnection']);
    fake.workspace.isTrusted = false;
    await commands['strataCoder.connect']();
    assert.equal(registered.length, 1);
    console.log('Extension registration, secret forwarding and workspace trust tests passed');
  } finally {fs.rmSync(dir, {recursive: true, force: true});}
});
