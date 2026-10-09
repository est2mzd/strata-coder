'use strict';
const vscode = require('vscode');
const path = require('path');
const fs = require('fs');
const crypto = require('crypto');
const cp = require('child_process');

function activate(context) {
  let registered = [];
  let pluginRegistered = false;
  const output = vscode.window.createOutputChannel('Strata-Coder');
  context.subscriptions.push(output);
  const config = () => vscode.workspace.getConfiguration('strataCoder');
  const unregister = () => {
    if (vscode.cursor && vscode.cursor.mcp) {
      for (const name of registered) vscode.cursor.mcp.unregisterServer(name);
    }
    registered = [];
  };
  function settings() {
    const c = config();
    return {mode: c.get('connectionMode', 'ssh'), ssh_host: c.get('sshHost', 'gdx-spark'),
      remote_port: c.get('remotePort', 8080), base_url: c.get('baseUrl', 'http://127.0.0.1:18080/v1'),
      model: c.get('model', ''), tests: c.get('testCommands', {}), request_timeout: 90,
      max_output_tokens: c.get('maxOutputTokens', 2048)};
  }
  async function connection(folder) {
    const key = await context.secrets.get('strataApiKey');
    const state = path.join(context.globalStorageUri.fsPath, 'tasks', crypto.createHash('sha256').update(folder.uri.fsPath).digest('hex').slice(0, 16));
    fs.mkdirSync(state, {recursive: true});
    return {command: config().get('pythonPath', process.platform === 'win32' ? 'python' : 'python3'),
      args: [path.join(context.extensionPath, 'tools', 'gateway.py'), '--repo', folder.uri.fsPath, '--state', state],
      env: {...process.env, STRATA_CODER_CONFIG: JSON.stringify(settings()), STRATA_API_KEY: key || ''}};
  }
  async function register() {
    unregister();
    if (!vscode.workspace.isTrusted) return;
    if (!(vscode.cursor && vscode.cursor.mcp && vscode.cursor.mcp.registerServer)) {
      vscode.window.showWarningMessage('This Cursor version lacks the MCP extension API. See Strata-Coder README for manual MCP setup.');
      return;
    }
    for (const folder of vscode.workspace.workspaceFolders || []) {
      const id = crypto.createHash('sha256').update(folder.uri.fsPath).digest('hex').slice(0, 8);
      const name = 'strata-coder-' + id;
      vscode.cursor.mcp.registerServer({name, server: await connection(folder)});
      registered.push(name);
    }
    const pluginPath = path.join(context.extensionPath, 'cursor-plugin');
    if (!pluginRegistered && vscode.cursor.plugins && vscode.cursor.plugins.registerPath) {
      vscode.cursor.plugins.registerPath(pluginPath);
      pluginRegistered = true;
    }
    output.appendLine('Registered ' + registered.length + ' workspace MCP server(s). Use Strata-Coder in Agent chat.');
  }
  context.subscriptions.push(vscode.commands.registerCommand('strataCoder.connect', register));
  context.subscriptions.push(vscode.commands.registerCommand('strataCoder.setApiKey', async () => {
    const value = await vscode.window.showInputBox({password: true, prompt: 'Strata API key (empty to remove)', ignoreFocusOut: true});
    if (value === undefined) return;
    if (value) await context.secrets.store('strataApiKey', value); else await context.secrets.delete('strataApiKey');
    await register();
  }));
  context.subscriptions.push(vscode.commands.registerCommand('strataCoder.checkConnection', async () => {
    if (!vscode.workspace.isTrusted) return;
    const folders = vscode.workspace.workspaceFolders || [];
    const folder = folders.length === 1 ? folders[0] : await vscode.window.showWorkspaceFolderPick();
    if (!folder) return;
    const c = await connection(folder);
    cp.execFile(c.command, [...c.args, '--health'], {env: c.env, timeout: 45000, maxBuffer: 16384}, (err, stdout) => {
      if (err) vscode.window.showErrorMessage('Strata-Coder connection failed. Verify Python, SSH key/agent and remote API.');
      else {output.appendLine(stdout.trim()); output.show(true); vscode.window.showInformationMessage('Strata-Coder connected.');}
    });
  }));
  context.subscriptions.push(vscode.workspace.onDidGrantWorkspaceTrust(() => register().catch(e => output.appendLine(e.message))));
  context.subscriptions.push(vscode.workspace.onDidChangeWorkspaceFolders(() => register().catch(e => output.appendLine(e.message))));
  context.subscriptions.push({dispose: () => {
    unregister();
    if (pluginRegistered) vscode.cursor.plugins.unregisterPath(path.join(context.extensionPath, 'cursor-plugin'));
  }});
  register().catch(e => output.appendLine('Registration failed: ' + e.message));
}
exports.activate = activate;
exports.deactivate = () => {};
