const { spawnSync, spawn } = require('node:child_process');
const net = require('node:net');
const fs = require('node:fs');

const WORKSPACE = '@caresetu/frontend';
const TARGET_ROUTE = '/';
const HOST = '127.0.0.1';
const READY_TIMEOUT_MS = 60_000;
const READY_POLL_MS = 250;
const LIGHTHOUSE_VERSION = '13.4.1';
const REPORT_STEM = 'lighthouse-report';

// Scores are 0-1 in the Lighthouse report. PWA is deliberately NOT gated: the
// frontend has no manifest/service-worker/icons and Lighthouse 13 has no PWA
// category (plan §3.C1). The --only-categories run below never requests it.
const THRESHOLDS = {
  performance: 0.85,
  accessibility: 0.90,
  'best-practices': 0.90,
  seo: 0.90,
};

let server;

process.on('exit', () => killTree(server));

const npm = process.platform === 'win32' ? 'npm.cmd' : 'npm';
const cmd = process.env.ComSpec || 'cmd.exe';

function npmCommandLine(args) {
  return `npm ${args.join(' ')}`;
}

function runOrExit(args) {
  const result =
    process.platform === 'win32'
      ? spawnSync(cmd, ['/d', '/s', '/c', npmCommandLine(args)], { encoding: 'utf-8', stdio: 'pipe' })
      : spawnSync(npm, args, { encoding: 'utf-8', stdio: 'pipe' });
  if (result.status !== 0) {
    console.error(result.stderr || result.stdout);
    process.exit(result.status || 1);
  }
  return result.stdout;
}

function freePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.on('error', reject);
    server.listen(0, HOST, () => {
      const { port } = server.address();
      server.close(() => resolve(port));
    });
  });
}

function startServer(port) {
  const args = ['run', 'start', '-w', WORKSPACE, '--', '-p', String(port), '-H', HOST];
  const opts = { detached: process.platform !== 'win32', stdio: 'ignore' };
  if (process.platform === 'win32') {
    return spawn(cmd, ['/d', '/s', '/c', npmCommandLine(args)], opts);
  }
  return spawn(npm, args, opts);
}

function killTree(child) {
  if (!child || child.pid === undefined) return;
  if (process.platform === 'win32') {
    spawnSync('taskkill', ['/pid', String(child.pid), '/T', '/F'], { stdio: 'ignore' });
  } else {
    try {
      process.kill(-child.pid, 'SIGTERM');
    } catch {
      child.kill('SIGTERM');
    }
  }
}

async function waitUntilReady(baseUrl, child) {
  const deadline = Date.now() + READY_TIMEOUT_MS;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) {
      throw new Error('next start exited before becoming ready');
    }
    try {
      const response = await fetch(`${baseUrl}/_not-found`, { headers: { 'Accept-Encoding': 'identity' } });
      if (response.status === 404) return;
    } catch {
      // not up yet
    }
    await new Promise((resolve) => setTimeout(resolve, READY_POLL_MS));
  }
  throw new Error(`next start did not become ready within ${READY_TIMEOUT_MS}ms`);
}

function chromePath() {
  if (process.env.CHROME_PATH) return process.env.CHROME_PATH;
  try {
    // Local fallback: the Playwright-bundled Chromium, the same browser the
    // CI job points CHROME_PATH at.
    const { chromium } = require('@playwright/test');
    return chromium.executablePath();
  } catch {
    return undefined;
  }
}

function lighthouseCliPath() {
  try {
    return require.resolve('lighthouse/cli/index.js');
  } catch {
    console.error(
      `lighthouse@${LIGHTHOUSE_VERSION} is not installed. Install it once with: ` +
        `npm install --no-save lighthouse@${LIGHTHOUSE_VERSION}`
    );
    process.exit(1);
  }
}

function lighthouseArgs(baseUrl) {
  return [
    `${baseUrl}${TARGET_ROUTE}`,
    // Mobile emulation with simulated throttled 4G (NFR-PERF-001 / AMB-001).
    '--only-categories=performance,accessibility,best-practices,seo',
    '--form-factor=mobile',
    '--throttling-method=simulate',
    '--throttling.rttMs=150',
    '--throttling.throughputKbps=1638.4',
    '--throttling.cpuSlowdownMultiplier=4',
    '--screenEmulation.mobile=true',
    '--screenEmulation.width=412',
    '--screenEmulation.height=915',
    '--screenEmulation.deviceScaleFactor=2',
    '--chrome-flags=--headless --no-sandbox --disable-gpu',
    '--output=json,html',
    `--output-path=${REPORT_STEM}`,
    '--quiet',
  ];
}

function runLighthouse(baseUrl) {
  const chrome = chromePath();
  if (!chrome) {
    console.error('No Chrome binary found. Set CHROME_PATH to the Playwright Chromium executable.');
    process.exit(1);
  }
  const cliPath = lighthouseCliPath();
  const jsonPath = `${REPORT_STEM}.report.json`;
  const htmlPath = `${REPORT_STEM}.report.html`;
  // Drop any stale report so a failed run cannot parse leftovers from an
  // earlier attempt.
  for (const file of [jsonPath, htmlPath, `${REPORT_STEM}.json`, `${REPORT_STEM}.html`]) {
    fs.rmSync(file, { force: true });
  }
  const result = spawnSync(process.execPath, [cliPath, ...lighthouseArgs(baseUrl)], {
    env: { ...process.env, CHROME_PATH: chrome },
    encoding: 'utf-8',
    maxBuffer: 20 * 1024 * 1024,
  });
  if (!fs.existsSync(jsonPath)) {
    console.error(result.stdout || result.stderr || 'no output');
    console.error(`lighthouse did not write ${jsonPath}`);
    process.exit(1);
  }
  if (result.status !== 0) {
    if (process.platform !== 'win32') {
      // Strict posture (plan §5): on CI a non-zero lighthouse exit fails the
      // gate even if a report was written.
      console.error(result.stdout || result.stderr || 'no output');
      console.error(`lighthouse exited ${result.status}`);
      process.exit(1);
    }
    // Windows-only: chrome-launcher teardown can exit non-zero after the
    // report is already written (taskkill + rmSync race). The report is the
    // gate, so continue parsing it.
    console.warn(
      `WARNING: lighthouse exited ${result.status} after writing the report; parsing it anyway`
    );
  }
  fs.renameSync(jsonPath, `${REPORT_STEM}.json`);
  fs.renameSync(htmlPath, `${REPORT_STEM}.html`);
  return JSON.parse(fs.readFileSync(`${REPORT_STEM}.json`, 'utf8'));
}

function printReport(report) {
  console.log('');
  console.log('category'.padEnd(16), 'score'.padEnd(8), 'required'.padEnd(10), 'result');
  console.log('-'.repeat(50));
  const rows = [];
  let passed = true;
  for (const [id, required] of Object.entries(THRESHOLDS)) {
    const category = report.categories[id];
    const score = category && typeof category.score === 'number' ? category.score : null;
    const ok = score !== null && score >= required;
    rows.push({ id, score, required, ok });
    if (!ok) passed = false;
  }
  for (const row of rows) {
    console.log(
      row.id.padEnd(16),
      (row.score === null ? 'n/a' : row.score.toFixed(2)).padEnd(8),
      row.required.toFixed(2).padEnd(10),
      row.ok ? 'OK' : 'FAIL'
    );
  }
  console.log('-'.repeat(50));
  console.log('PWA category deliberately not gated (no manifest/service-worker/icons, plan §3.C1).');
  return passed;
}

async function main() {
  console.log('Lighthouse gate (NFR-PERF-001): mobile emulation + simulated throttled 4G on the local build');
  console.log('Building frontend...');
  runOrExit(['run', 'build']);

  const port = await freePort();
  const baseUrl = `http://${HOST}:${port}`;
  server = startServer(port);
  try {
    await waitUntilReady(baseUrl, server);
    const warm = await fetch(`${baseUrl}${TARGET_ROUTE}`, {
      headers: { 'Cookie': 'caresetu_session=ci-dummy-token' },
    });
    if (!warm.ok) {
      throw new Error(`GET ${TARGET_ROUTE} -> ${warm.status} ${warm.statusText}; not scanning`);
    }
    const report = runLighthouse(baseUrl);
    return printReport(report);
  } finally {
    killTree(server);
  }
}

main()
  .then((passed) => {
    if (passed) {
      console.log(`Lighthouse gate PASSED: all ${Object.keys(THRESHOLDS).length} categories above threshold`);
      process.exit(0);
    }
    console.error('Lighthouse gate FAILED: at least one category below its threshold (see reports above)');
    process.exit(1);
  })
  .catch((error) => {
    console.error(error.stack || String(error));
    process.exit(1);
  });
