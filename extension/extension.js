'use strict';
const vscode = require('vscode');
const path = require('path');
const fs = require('fs');
const crypto = require('crypto');
const cp = require('child_process');

function activate(context) {
  let registered = [];
  const decisionProcesses = new Set();
  let pluginRegistered = false;
  const progressFiles = new Set();
  const cursors = new Map();
  const taskStates = new Map();
  const taskDepths = new Map();
  const statusBar = vscode.window.createStatusBarItem ? vscode.window.createStatusBarItem() : null;
  if (statusBar) {
    statusBar.command = 'strataCoder.showTasks';
    statusBar.text = 'Strata: idle';
    statusBar.show();
    context.subscriptions.push(statusBar);
  }
  const output = vscode.window.createOutputChannel('Strata-Coder');
  context.subscriptions.push(output);
  const config = () => vscode.workspace.getConfiguration('strataCoder');
  const unregister = () => {
    if (vscode.cursor && vscode.cursor.mcp) {
      for (const name of registered) vscode.cursor.mcp.unregisterServer(name);
    }
    registered = [];
    progressFiles.clear();
  };
  function settings() {
    const c = config();
    return {depth: c.get('depth', 'auto'), execution_mode: c.get('supervisionMode', 'decision') === 'decision' ? 'queued' : c.get('executionMode', 'single'), worker_concurrency: c.get('workerConcurrency', 2),
      test_concurrency: c.get('testConcurrency', 1), coordinator_port: c.get('coordinatorPort', 8091),
      coordinator_url: c.get('coordinatorUrl', 'http://127.0.0.1:18091/v1'), mode: c.get('connectionMode', 'ssh'), ssh_host: c.get('sshHost', 'gdx-spark'),
      remote_port: c.get('remotePort', 8080), base_url: c.get('baseUrl', 'http://127.0.0.1:18080/v1'),
      model: c.get('model', ''), tests: c.get('testCommands', {}), request_timeout: 90,
      max_output_tokens: c.get('maxOutputTokens', 2048)};
  }
  async function connection(folder) {
    const key = await context.secrets.get('strataApiKey');
    const coordinatorToken = await context.secrets.get('coordinatorToken');
    const state = path.join(context.globalStorageUri.fsPath, 'tasks', crypto.createHash('sha256').update(folder.uri.fsPath).digest('hex').slice(0, 16));
    fs.mkdirSync(state, {recursive: true});
    progressFiles.add(path.join(state, 'progress.json'));
    return {command: config().get('pythonPath', process.platform === 'win32' ? 'python' : 'python3'),
      args: [path.join(context.extensionPath, 'tools', 'gateway.py'), '--repo', folder.uri.fsPath, '--state', state],
      env: {...process.env, STRATA_CODER_CONFIG: JSON.stringify(settings()), STRATA_API_KEY: key || '', STRATA_COORDINATOR_TOKEN: coordinatorToken || ''}};
  }
  async function register() {
    unregister();
    if (!vscode.workspace.isTrusted) return;
    if (config().get('supervisionMode', 'decision') === 'decision') {
      if (pluginRegistered) { vscode.cursor.plugins.unregisterPath(path.join(context.extensionPath, 'cursor-plugin')); pluginRegistered = false; }
      output.appendLine('Decision mode: use Prepare Decision Batch, Copy Decision Brief, then Execute Decision. No worker MCP tools are registered.');
      return;
    }
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
  // Poll local status files, never a language model. Completion does not auto-resume Cursor Agent.
  const monitor = setInterval(() => {
    let completed = 0;
    for (const file of progressFiles) {
      try {
        const data = JSON.parse(fs.readFileSync(file, 'utf8'));
        const previous = cursors.get(file);
        if (previous === data.cursor) continue;
        cursors.set(file, data.cursor);
        for (const event of data.events || []) {
          taskStates.set(event.task_id, event.status);
          if (event.depth_selection) taskDepths.set(event.task_id, event.depth_selection);
          if (previous !== undefined && event.seq > previous && ['review_ready','needs_supervisor','failed','interrupted','applied'].includes(event.status)) completed++;
        }
      } catch (_) { /* No gateway/status file yet. */ }
    }
    if (taskStates.size > 500) {
      for (const id of Array.from(taskStates.keys()).slice(0, taskStates.size - 500)) { taskStates.delete(id); taskDepths.delete(id); }
    }
    if (statusBar && taskStates.size) {
      const counts = {};
      for (const state of taskStates.values()) counts[state] = (counts[state] || 0) + 1;
      statusBar.text = `Strata: ${counts.running || 0} running / ${counts.queued || 0} queued / ${counts.review_ready || 0} review`;
      statusBar.tooltip = 'Recent task states. Click to view IDs; no Cursor model tokens used for monitoring.';
    }
    if (completed) vscode.window.showInformationMessage(`Strata-Coder: ${completed} task update(s) ready. Open task status, then ask the originating Agent to retrieve its result.`);
  }, 1500);
  if (monitor.unref) monitor.unref();
  context.subscriptions.push({dispose: () => clearInterval(monitor)});
  async function decisionContext() {
    if (!vscode.workspace.isTrusted) throw new Error('Trust this workspace before running workers.');
    const folders = vscode.workspace.workspaceFolders || [];
    const folder = folders.length === 1 ? folders[0] : await vscode.window.showWorkspaceFolderPick();
    if (!folder) return null;
    const c = await connection(folder);
    return {folder, c, parent: c.args[c.args.indexOf('--state') + 1]};
  }
  function runDecision(ctx, state, action, extra) {
    output.appendLine('Strata-Coder: ' + action + ' running locally; no Cursor polling required.'); output.show(true);
    return new Promise((resolve, reject) => {
      const child = cp.execFile(ctx.c.command, [path.join(context.extensionPath, 'tools', 'decision.py'), action,
        '--repo', ctx.folder.uri.fsPath, '--state', state, ...extra],
        {env: ctx.c.env, timeout: 7200000, maxBuffer: 1048576}, (err, stdout, stderr) => {
          decisionProcesses.delete(child);
          if (err) { output.appendLine(stderr || err.message); reject(err); }
          else { output.appendLine(stdout); resolve(stdout); }
        });
      decisionProcesses.add(child);
    });
  }
  const decisionCommand = (name, fn) => context.subscriptions.push(vscode.commands.registerCommand(name, async () => {
    try { const ctx = await decisionContext(); if (ctx) await fn(ctx); }
    catch (e) { vscode.window.showErrorMessage('Strata-Coder: ' + e.message); }
  }));
  decisionCommand('strataCoder.prepareDecision', async ctx => {
    const files = await vscode.window.showOpenDialog({canSelectMany: false, filters: {JSON: ['json']}, title: 'Select mission contracts (outside the working repo)'});
    if (!files || !files.length) return;
    const state = path.join(ctx.parent, 'decisions', crypto.randomBytes(8).toString('hex'));
    fs.mkdirSync(state, {recursive: true});
    fs.writeFileSync(path.join(ctx.parent, 'last-decision.json'), JSON.stringify({state}));
    await runDecision(ctx, state, 'prepare', ['--missions', files[0].fsPath]);
    vscode.window.showInformationMessage('Brief prepared. Use Copy Decision Brief and paste into a fresh Cursor Chat.');
  });
  decisionCommand('strataCoder.copyDecision', async ctx => {
    const {state} = JSON.parse(fs.readFileSync(path.join(ctx.parent, 'last-decision.json'), 'utf8'));
    const prompt = await runDecision(ctx, state, 'prompt', []);
    await vscode.env.clipboard.writeText(prompt);
    vscode.window.showInformationMessage('Copied bounded decision brief. Paste into a fresh Chat without adding code context.');
  });
  decisionCommand('strataCoder.executeDecision', async ctx => {
    const {state} = JSON.parse(fs.readFileSync(path.join(ctx.parent, 'last-decision.json'), 'utf8'));
    const value = await vscode.window.showInputBox({prompt: 'Paste the JSON decision object from Cursor (no explanation)', ignoreFocusOut: true});
    if (value === undefined) return;
    const parsed = JSON.parse(value); if (!parsed || typeof parsed !== 'object') throw new Error('Expected decision JSON');
    const file = path.join(state, 'user-decisions.json');fs.writeFileSync(file, JSON.stringify(parsed));
    await runDecision(ctx, state, 'execute', ['--decisions', file]);
    vscode.window.showInformationMessage('Decision processing finished. See local status; no Cursor completion call is needed.');
  });
  context.subscriptions.push(vscode.commands.registerCommand('strataCoder.showTasks', () => {
    for (const [id, state] of taskStates) {
      const d = taskDepths.get(id);
      output.appendLine(`${id}: ${state}${d && d.depth ? ` | ${d.depth} -> ${d.reasoning_effort}: ${d.depth_reason}` : ''}`);
    }
    output.show(true);
  }));
  context.subscriptions.push(vscode.commands.registerCommand('strataCoder.setCoordinatorToken', async () => {
    const value = await vscode.window.showInputBox({password: true, prompt: 'Shared coordinator token (not SSH password)', ignoreFocusOut: true});
    if (value === undefined) return;
    if (value) await context.secrets.store('coordinatorToken', value); else await context.secrets.delete('coordinatorToken');
    await register();
  }));
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
    for (const child of decisionProcesses) child.kill();
    unregister();
    if (pluginRegistered) vscode.cursor.plugins.unregisterPath(path.join(context.extensionPath, 'cursor-plugin'));
  }});
  register().catch(e => output.appendLine('Registration failed: ' + e.message));
}
exports.activate = activate;
exports.deactivate = () => {};
