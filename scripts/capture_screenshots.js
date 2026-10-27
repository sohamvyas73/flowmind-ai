#!/usr/bin/env node
/**
 * Regenerates every screenshot in docs/images/gallery from a running FlowMind stack.
 *
 *   1. Start the backend (admin seeded) and the frontend dev server:
 *        ADMIN_EMAIL=admin@flowmind.com ADMIN_PASSWORD=ChangeMe-Demo-1 ALLOW_PRIVATE_URLS=true uvicorn app.main:app
 *        (cd frontend && npm run dev)
 *   2. Optional demo database for the Connections screens (any PostgreSQL with a couple of tables):
 *        SHOP_DB=postgresql://user:pass@127.0.0.1:5432/shop   (host/port/db/user/password are taken from it)
 *   3. Run:   NODE_PATH=$(npm root -g) node scripts/capture_screenshots.js [outputDir]
 *      (needs `playwright` installed: npm i -g playwright && npx playwright install chromium)
 *
 * The script seeds demo users, files, workflows, runs and schedules through the public API, then drives the real UI.
 * Every section is independent: a failure is reported at the end but does not stop the others.
 */
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');

const API = process.env.API_URL || 'http://localhost:8000/api/v1';
const UI = process.env.UI_URL || 'http://localhost:5173';
const ADMIN = { email: process.env.ADMIN_EMAIL || 'admin@flowmind.com', password: process.env.ADMIN_PASSWORD || 'ChangeMe-Demo-1' };
const OUT = path.resolve(process.argv[2] || 'docs/images/gallery');
const SHOP = process.env.SHOP_DB ? new URL(process.env.SHOP_DB) : null;

const failures = [];
const taken = [];
const sleep = ms => new Promise(r => setTimeout(r, ms));

async function api(pathname, { method = 'GET', token, body, form } = {}) {
  const headers = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  if (body) headers['Content-Type'] = 'application/json';
  const res = await fetch(API + pathname, { method, headers, body: form || (body ? JSON.stringify(body) : undefined) });
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = text; }
  if (!res.ok) throw new Error(`${method} ${pathname} -> ${res.status} ${text.slice(0, 200)}`);
  return data;
}

async function login(email, password) {
  return (await api('/auth/login', { method: 'POST', body: { email, password } })).access_token;
}

async function shot(page, area, name, opts = {}) {
  const dir = path.join(OUT, area);
  fs.mkdirSync(dir, { recursive: true });
  const file = path.join(dir, `${name}.png`);
  if (opts.locator) await opts.locator.screenshot({ path: file });
  else await page.screenshot({ path: file, clip: opts.clip, fullPage: !!opts.fullPage });
  taken.push(`${area}/${name}.png`);
}

async function section(name, fn) {
  try { await fn(); console.log(`ok    ${name}`); }
  catch (e) { failures.push(`${name}: ${e.message.split('\n')[0]}`); console.log(`FAIL  ${name}: ${e.message.split('\n')[0]}`); }
}

const node = (id, type, x, y, data) => ({ id, type, position: { x, y }, data: { label: data.label || id, ...data } });
const chain = (nodes, pairs) => ({ nodes, edges: pairs.map(([a, b], i) => ({ id: `e${i}`, source: a, target: b })) });

// A workflow containing one node of every kind, so each node's settings panel can be captured.
function kitchenSink() {
  const t = [
    ['inputNode', { label: 'Customer input', fields: [{ id: 'f1', name: 'customer_id', type: 'text' }, { id: 'f2', name: 'amount', type: 'number' }] }],
    ['aiNode', { label: 'AI Agent', aiTask: 'extraction', outputFormat: 'json', temperature: 0.2, prompt: 'Extract the customer name and the requested amount.' }],
    ['verificationNode', { label: 'Verification', verificationType: 'consistency' }],
    ['decisionNode', { label: 'Decision', conditionType: 'threshold', threshold: 0.8, prompt: 'Approve if the applicant is eligible.' }],
    ['outputNode', { label: 'Output', outputType: 'api' }],
    ['httpNode', { label: 'HTTP Request', method: 'GET', url: 'https://api.example.com/customers/{{customer_id}}', headers: [{ key: 'Accept', value: 'application/json' }], authType: 'bearer', authValue: '', authHeader: 'X-API-Key', bodyTemplate: '', timeout: 30 }],
    ['transformNode', { label: 'Transform', transformMode: 'field_map', fieldMappings: [{ from: 'customer_id', to: 'id' }], template: '{}', filterKeys: '' }],
    ['humanReviewNode', { label: 'Human Review', reviewPrompt: 'Please review the data from the previous step and approve or reject.' }],
    ['ruleNode', { label: 'Rule Engine', combineMode: 'AND', rules: [{ field: 'amount', operator: 'gte', value: '1000' }] }],
    ['validatorNode', { label: 'Validator', validationRules: [{ field: 'customer_id', required: true, fieldType: 'string' }] }],
    ['switchNode', { label: 'Switch Router', switchField: 'tier', cases: [{ value: 'gold', label: 'Gold' }, { value: 'silver|bronze', label: 'Other' }] }],
    ['formatterNode', { label: 'Formatter', template: 'Hello {{full_name}}, your request {{customer_id}} is {{decision}}.', outputFormat: 'text', subjectTemplate: '' }],
    ['aggregatorNode', { label: 'Aggregator', sourceField: 'items', operation: 'sum', valueField: 'amount', groupBy: '', separator: ', ' }],
    ['indianKycNode', { label: 'Indian KYC', documentType: 'pan', provider: 'surepass', apiKey: '', documentField: 'document_number', customEndpoint: '' }],
    ['loadDataNode', { label: 'Load Data', source: 'file', fileName: 'orders.csv', connectionId: '', schema: 'public', table: '', maxRows: '' }],
    ['cleanDataNode', { label: 'Clean', trimAll: true, removeDuplicates: true, dropMissing: ['customer_id'], fillMissing: [], rename: [], keepColumns: [] }],
    ['combineDataNode', { label: 'Combine', joinType: 'inner', keys: [{ left: 'customer_id', right: 'customer_id' }], swap: false }],
    ['summariseDataNode', { label: 'Summarise', groupBy: ['status'], aggregations: [{ column: '*', fn: 'count', as: 'orders' }] }],
    ['sqlNode', { label: 'SQL', query: 'SELECT status, count(*) AS n\nFROM input\nGROUP BY status' }],
    ['qualityGateNode', { label: 'Quality Check', onFail: 'stop', rules: [{ type: 'unique', columns: ['order_id'] }, { type: 'range', column: 'quantity', min: 1, max: 100 }] }],
  ];
  return { nodes: t.map(([type, d], i) => node(`k${i}`, type, 60 + (i % 5) * 260, 60 + Math.floor(i / 5) * 150, d)), edges: [] };
}

async function main() {
  fs.mkdirSync(OUT, { recursive: true });

  // ── seed through the API ───────────────────────────────────────────────────
  const admin = await login(ADMIN.email, ADMIN.password);
  const ensureUser = async (email, name, active, credits) => {
    try { await api('/auth/signup', { method: 'POST', body: { email, password: 'DemoPass-123', full_name: name } }); } catch { /* exists */ }
    const users = await api('/admin/users', { token: admin });
    const u = users.find(x => x.email === email);
    await api(`/admin/users/${u.id}`, { method: 'PATCH', token: admin, body: { is_active: active, credits_total: credits } });
    return u;
  };
  await ensureUser('pending.user@example.com', 'Priya Nair', false, 100);
  await ensureUser('demo.user@example.com', 'Demo Analyst', true, 400);
  const demo = await login('demo.user@example.com', 'DemoPass-123');
  for (const tok of [admin, demo]) await api('/data/examples', { method: 'POST', token: tok });

  const mk = (tok, name, graph) => api('/workflows/workflows', { method: 'POST', token: tok, body: { name, graph_data: graph } });
  const exec = (tok, wf, input = {}) => api(`/workflows/workflows/${wf.id}/execute`, { method: 'POST', token: tok, body: { workflow_id: wf.id, input_data: input } });

  const sink = await mk(admin, 'All node types (reference)', kitchenSink());
  const precheck = await mk(admin, 'Loan pre-check (no AI)', chain([
    node('in', 'inputNode', 60, 140, { label: 'Applicant', fields: [{ id: 'a', name: 'full_name', type: 'text' }, { id: 'b', name: 'income', type: 'number' }, { id: 'c', name: 'loan_amount', type: 'number' }] }),
    node('val', 'validatorNode', 300, 140, { label: 'Check fields', validationRules: [{ field: 'income', required: true, fieldType: 'number', min: 0 }, { field: 'loan_amount', required: true, fieldType: 'number', min: 1 }] }),
    node('rule', 'ruleNode', 540, 140, { label: 'Affordability', combineMode: 'AND', rules: [{ field: 'income', operator: 'gte', value: '30000' }, { field: 'loan_amount', operator: 'lte', value: '500000' }] }),
    node('fmt', 'formatterNode', 780, 140, { label: 'Message', outputFormat: 'text', template: 'Hello {{full_name}}: pre-check result is {{result}} (matched {{matched}} rule(s)).' }),
    node('out', 'outputNode', 1020, 140, { label: 'Result', outputType: 'api' }),
  ], [['in', 'val'], ['val', 'rule'], ['rule', 'fmt'], ['fmt', 'out']]));

  const dataWf = await mk(admin, 'Sales by region', chain([
    node('l', 'loadDataNode', 60, 140, { label: 'Daily sales', source: 'file', fileName: 'sales.csv' }),
    node('s', 'summariseDataNode', 320, 140, { label: 'Revenue by region', groupBy: ['region'], aggregations: [{ column: 'revenue', fn: 'sum', as: 'total_revenue' }, { column: 'units', fn: 'sum', as: 'total_units' }] }),
  ], [['l', 's']]));
  const gateWf = await mk(admin, 'Quality gate on dirty orders', chain([
    node('l', 'loadDataNode', 60, 140, { label: 'Dirty orders', source: 'file', fileName: 'orders_dirty.csv' }),
    node('g', 'qualityGateNode', 320, 140, { label: 'Order checks', onFail: 'stop', rules: [
      { type: 'unique', columns: ['order_id'] }, { type: 'not_null', columns: ['customer_id', 'unit_price'] },
      { type: 'range', column: 'quantity', min: 1, max: 100 }, { type: 'allowed_values', column: 'status', values: ['delivered', 'shipped', 'cancelled'] } ] }),
    node('s', 'summariseDataNode', 580, 140, { label: 'Orders by status', groupBy: ['status'], aggregations: [{ column: '*', fn: 'count', as: 'orders' }] }),
  ], [['l', 'g'], ['g', 's']]));

  // some history: successful runs (different users), a failed gate, a background run, a schedule
  await exec(admin, precheck, { node_inputs: { in: { full_name: { content: 'Asha Patel' }, income: { content: '64000' }, loan_amount: { content: '250000' } } } }).catch(() => {});
  await exec(admin, dataWf); await exec(admin, gateWf);
  const demoWf = await mk(demo, 'Sales by region', chain([
    node('l', 'loadDataNode', 60, 140, { label: 'Daily sales', source: 'file', fileName: 'sales.csv' }),
    node('s', 'summariseDataNode', 320, 140, { label: 'Revenue by region', groupBy: ['region'], aggregations: [{ column: 'revenue', fn: 'sum', as: 'total_revenue' }] }),
  ], [['l', 's']]));
  await exec(demo, demoWf); await exec(demo, demoWf);
  await api('/runs', { method: 'POST', token: admin, body: { workflow_id: dataWf.id } });
  await api('/schedules', { method: 'POST', token: admin, body: { workflow_id: dataWf.id, name: 'Weekday morning report', cron: '0 9 * * 1-5', timezone: 'Asia/Kolkata' } }).catch(() => {});
  await api('/schedules', { method: 'POST', token: admin, body: { workflow_id: gateWf.id, name: 'Hourly order check', cron: '0 * * * *', timezone: 'UTC' } }).catch(() => {});
  if (SHOP) {
    try {
      const c = await api('/connections', { method: 'POST', token: admin, body: {
        name: 'Shop database', type: 'postgres', access_mode: 'read_only', host_allowlist: ['127.0.0.1', 'localhost'],
        config: { host: SHOP.hostname, port: Number(SHOP.port || 5432), database: SHOP.pathname.slice(1), user: decodeURIComponent(SHOP.username), password: decodeURIComponent(SHOP.password || ''), sslmode: 'disable' } } });
      await api(`/connections/${c.id}/test`, { method: 'POST', token: admin });
    } catch (e) { console.log('connection seed skipped:', e.message.split('\n')[0]); }
  }
  await sleep(4000); // let the background run and scheduler settle

  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, acceptDownloads: true });
  const page = await ctx.newPage();
  page.on('dialog', d => d.accept());
  const signIn = async (pg, email, password) => {
    await pg.goto(UI + '/');
    await pg.fill('input[type=email]', email);
    await pg.fill('input[type=password]', password);
    await pg.click('button[type=submit]');
  };
  const back = async () => { await page.getByText('Back to Canvas').click(); await page.waitForSelector('.react-flow'); };
  const closeModal = async () => { await page.keyboard.press('Escape'); const x = page.locator('div.fixed button:has(svg.lucide-x)'); if (await x.count()) await x.first().click(); };
  const loadSaved = async name => {
    await page.click('button[title="Load Workflow"]');
    await page.waitForSelector(`text=${name}`);
    await page.locator('div.fixed').getByText(name, { exact: true }).first().click();
    await page.waitForSelector('.react-flow__node');
    await sleep(500);
  };
  const loadSample = async name => {
    await page.locator('p.font-semibold', { hasText: name }).locator('xpath=..').getByRole('button', { name: 'Load' }).click();
    await page.waitForSelector('.react-flow__node');
    await sleep(500);
  };

  // ── 01 getting started: login, signup, pending approval ───────────────────
  await section('auth screens', async () => {
    await page.goto(UI + '/');
    await page.waitForSelector('input[type=email]');
    await shot(page, '01-getting-started', '01-login');
    await page.getByRole('button', { name: /sign up/i }).first().click();
    await sleep(300);
    await shot(page, '01-getting-started', '02-signup');
    const ctx2 = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const p2 = await ctx2.newPage();
    await signIn(p2, 'pending.user@example.com', 'DemoPass-123');
    await p2.waitForSelector('text=Account Pending Approval');
    await shot(p2, '01-getting-started', '03-pending-approval');
    await ctx2.close();
  });

  await signIn(page, ADMIN.email, ADMIN.password);
  await page.waitForSelector('button[title="Load Workflow"]', { timeout: 20000 });

  // ── 02 canvas ──────────────────────────────────────────────────────────────
  await section('canvas empty + palette', async () => {
    await page.waitForSelector('text=Sample Workflows');
    await shot(page, '02-canvas', '01-empty-canvas');
    await shot(page, '02-canvas', '02-node-palette', { clip: { x: 0, y: 0, width: 300, height: 900 } });
  });

  await section('sample workflows', async () => {
    const names = ['KYC Verification', 'Fraud Detection', 'Document Processing', 'API Enrichment + Review', 'Loan Eligibility',
      'Data: Tidy up messy contacts', 'Data: Sales by region', 'Data: Orders + customers (join)', 'Data: Top products (SQL)',
      'Data: Quality gate on dirty orders', 'Data: Protect personal data'];
    let i = 3;
    for (const n of names) {
      try {
        await page.locator('p.font-semibold', { hasText: n }).first().scrollIntoViewIfNeeded();
        await loadSample(n);
        await shot(page, '03-sample-workflows', `${String(i++).padStart(2, '0')}-${n.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')}`);
      } catch (e) { failures.push(`sample ${n}: ${e.message.split('\n')[0]}`); }
    }
  });

  // ── 04 every node's settings ───────────────────────────────────────────────
  await section('node settings panels', async () => {
    await loadSaved('All node types (reference)');
    const labels = [
      ['Customer input', 'input'], ['AI Agent', 'ai-agent'], ['Verification', 'verification'], ['Decision', 'decision'], ['Output', 'output'],
      ['HTTP Request', 'http-request'], ['Transform', 'transform'], ['Human Review', 'human-review'], ['Rule Engine', 'rule-engine'],
      ['Validator', 'validator'], ['Switch Router', 'switch-router'], ['Formatter', 'formatter'], ['Aggregator', 'aggregator'],
      ['Indian KYC', 'indian-kyc'], ['Load Data', 'load-data'], ['Clean', 'clean'], ['Combine', 'combine'], ['Summarise', 'summarise'],
      ['SQL', 'sql'], ['Quality Check', 'quality-check'],
    ];
    const fit = page.locator('button.react-flow__controls-fitview');
    if (await fit.count()) { await fit.click(); await sleep(400); await page.locator('button.react-flow__controls-zoomout').click(); await sleep(400); await page.mouse.move(600, 760); await page.mouse.down(); await page.mouse.move(840, 800, { steps: 8 }); await page.mouse.up(); await sleep(500); }
    await shot(page, '04-node-settings', '00-all-nodes-canvas');
    let i = 1;
    for (const [label, slug] of labels) {
      try {
        await page.keyboard.press('Escape');
        await page.locator('.react-flow__node', { hasText: label }).first().dispatchEvent('click');
        const panel = page.locator('div.absolute.right-4.top-4');
        await panel.waitFor({ timeout: 5000 });
        await sleep(250);
        await shot(page, '04-node-settings', `${String(i++).padStart(2, '0')}-${slug}`, { locator: panel });
      } catch (e) { failures.push(`node ${label}: ${e.message.split('\n')[0]}`); }
    }
  });

  // ── 05 running workflows ───────────────────────────────────────────────────
  await section('execute + results', async () => {
    await page.reload();
    await page.waitForSelector('button[title="Load Workflow"]');
    await loadSaved('Loan pre-check (no AI)');
    await shot(page, '05-running', '01-workflow-ready');
    await page.getByRole('button', { name: 'Execute' }).click();
    await page.waitForSelector('text=Execute Workflow');
    const inputs = page.locator('div.fixed input[type=text], div.fixed input[type=number], div.fixed textarea');
    const n = await inputs.count();
    const vals = ['Asha Patel', '64000', '250000'];
    for (let i = 0; i < Math.min(n, 3); i++) await inputs.nth(i).fill(vals[i]);
    await shot(page, '05-running', '02-execute-modal');
    await page.getByRole('button', { name: 'Run Workflow' }).click();
    await page.waitForSelector('text=Execution Results', { timeout: 30000 });
    await sleep(400);
    await shot(page, '05-running', '03-execution-results');
    await page.getByRole('button', { name: 'Close' }).click();
    await page.getByRole('button', { name: 'Live API' }).click();
    await sleep(500);
    await shot(page, '05-running', '04-live-api-panel');
    await page.getByRole('button', { name: 'Live API' }).click();
  });

  // ── 06 data pipelines ──────────────────────────────────────────────────────
  await section('data page', async () => {
    await page.click('button[title="Upload files and browse pipeline outputs"]');
    await page.waitForSelector('text=Your files');
    await shot(page, '06-data', '01-data-page');
    await page.locator('div.divide-y > div', { hasText: 'orders_dirty.csv' }).getByRole('button', { name: 'Preview' }).click();
    await page.waitForSelector('table');
    await shot(page, '06-data', '02-file-preview');
    await closeModal();
    await page.locator('div.divide-y > div', { hasText: 'orders_dirty.csv' }).getByRole('button', { name: 'Profile' }).click();
    await page.waitForSelector('text=Different values');
    await shot(page, '06-data', '03-file-profile');
    await closeModal();
    await page.locator('div.divide-y > div', { hasText: 'People per city' }).first().waitFor({ timeout: 1000 }).catch(() => {});
    await shot(page, '06-data', '04-outputs', { fullPage: true });
    await back();
  });

  await section('preview + quality', async () => {
    await loadSample('Data: Orders + customers (join)').catch(async () => { await page.reload(); await page.waitForSelector('text=Sample Workflows'); await loadSample('Data: Orders + customers (join)'); });
    await page.getByRole('button', { name: 'Preview data', exact: true }).click();
    await page.waitForSelector('text=SQL this step ran', { timeout: 40000 });
    await shot(page, '06-data', '05-preview-join-sql');
    await closeModal();
    await loadSample('Data: Quality gate on dirty orders');
    await page.getByRole('button', { name: 'Preview data', exact: true }).click();
    await page.waitForSelector('text=checks failed', { timeout: 40000 });
    await page.locator('button', { hasText: 'quantity must be between' }).first().click();
    await sleep(300);
    await shot(page, '06-data', '06-quality-report');
    await closeModal();
    await page.locator('.react-flow__node', { hasText: 'Order checks' }).click();
    await page.waitForSelector('text=When a check fails');
    await shot(page, '06-data', '07-quality-editor', { locator: page.locator('div.absolute.right-4.top-4') });
    await loadSample('Data: Protect personal data');
    await page.locator('.react-flow__node', { hasText: 'Protect' }).first().click();
    await page.waitForSelector('text=Protect personal data');
    await shot(page, '06-data', '08-protect-personal-data', { locator: page.locator('div.absolute.right-4.top-4') });
  });

  // ── 07 connections, runs, schedules ────────────────────────────────────────
  await section('connections', async () => {
    await page.click('button[title="Data connections"]');
    await page.waitForSelector('text=Data Connections');
    await sleep(500);
    await shot(page, '07-connections-runs', '01-connections');
    await page.getByText('New connection').click();
    await page.waitForSelector('text=PostgreSQL');
    await shot(page, '07-connections-runs', '02-new-connection');
    await closeModal();
    if (await page.getByRole('button', { name: 'Browse' }).count()) {
      await page.getByRole('button', { name: 'Browse' }).first().click();
      await page.waitForSelector('text=Select a table');
      const first = page.locator('div.fixed button.text-left').first();
      if (await first.count()) { await first.click(); await sleep(900); }
      await shot(page, '07-connections-runs', '03-browse-tables');
      await closeModal();
    }
    await back();
  });

  await section('runs + schedules', async () => {
    await page.click('button[title="Background runs & schedules"]');
    await page.waitForSelector('text=Run history');
    await sleep(800);
    await shot(page, '07-connections-runs', '04-runs');
    const rows = page.locator('div.divide-y > div');
    const failed = rows.filter({ hasText: 'Failed' }).first();
    if (await failed.count()) { await failed.locator('button').first().click(); await page.waitForSelector('text=Data lineage', { timeout: 15000 }).catch(() => {}); await sleep(400); }
    await shot(page, '07-connections-runs', '05-run-detail-lineage', (await failed.count()) ? { locator: failed } : {});
    await page.getByRole('button', { name: 'schedules' }).click();
    await page.waitForSelector('text=New schedule');
    await sleep(400);
    await shot(page, '07-connections-runs', '06-schedules');
    await back();
  });

  // ── 08 settings ────────────────────────────────────────────────────────────
  await section('model settings', async () => {
    await page.click('button[title="Model & API Settings"]');
    await page.waitForSelector('text=Model & API Settings');
    await sleep(600);
    await shot(page, '08-settings', '01-model-and-api-settings', { fullPage: true });
    await back();
  });

  // ── 09 admin ───────────────────────────────────────────────────────────────
  await section('admin panel', async () => {
    await page.click('button[title="Admin Panel"]');
    await page.waitForSelector('text=Overview');
    await sleep(900);
    await shot(page, '09-admin', '01-overview');
    for (const [label, file] of [['Users', '02-users-and-approvals'], ['Credit Usage', '03-credit-usage'], ['Connectors', '04-connectors'], ['Workflows', '05-all-workflows'], ['Platform Settings', '06-platform-settings']]) {
      await page.locator('nav button, aside button, button').filter({ hasText: new RegExp(`^\\s*${label}\\s*$`) }).first().click();
      await sleep(900);
      await shot(page, '09-admin', file, { fullPage: true });
    }
    await page.locator('button').filter({ hasText: /^\s*Credit Usage\s*$/ }).first().click();
    await sleep(500);
    for (const [label, file] of [['Transactions', '07-credit-transactions'], ['Pricing Guide', '08-pricing-guide']]) {
      await page.getByRole('button', { name: label }).first().click();
      await sleep(700);
      await shot(page, '09-admin', file, { fullPage: true });
    }
  });

  await browser.close();
  console.log(`\n${taken.length} screenshots written to ${OUT}`);
  if (failures.length) { console.log('\nFAILURES:\n- ' + failures.join('\n- ')); process.exitCode = 1; }
}

main().catch(e => { console.error('FATAL', e); process.exit(1); });
