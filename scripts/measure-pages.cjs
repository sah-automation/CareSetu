const { spawnSync, spawn } = require('node:child_process');
const net = require('node:net');

const CHANNELS = ['/patient', '/partner', '/operator'];
const WORKSPACE = '@caresetu/frontend';
const BUDGET_BYTES = 1.5 * 1024 * 1024;
const BUDGET_LABEL = `1.5 MB (${BUDGET_BYTES} bytes)`;
const READY_TIMEOUT_MS = 60_000;
const READY_POLL_MS = 250;
const HOST = '127.0.0.1';

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

async function fetchBuffer(url) {
  const response = await fetch(url, {
    headers: {
      'Accept-Encoding': 'identity',
      'Cookie': 'caresetu_session=ci-dummy-token',
    },
  });
  if (!response.ok) {
    throw new Error(`GET ${url} -> ${response.status} ${response.statusText}`);
  }
  return Buffer.from(await response.arrayBuffer());
}

function assetUrls(html) {
  const urls = [];
  const tagRe = /<(script|link)\b[^>]*>/gi;
  for (const match of html.matchAll(tagRe)) {
    const tag = match[0];
    const kind = match[1].toLowerCase();
    if (kind === 'script') {
      const src = tag.match(/\bsrc=["']([^"']+)["']/i);
      if (src) urls.push(src[1]);
    } else {
      const rel = tag.match(/\brel=["']stylesheet["']/i);
      const href = tag.match(/\bhref=["']([^"']+)["']/i);
      if (rel && href) urls.push(href[1]);
    }
  }
  return [...new Set(urls)];
}

function assetTotalBytes(assets) {
  return assets.reduce((sum, asset) => sum + asset.bytes, 0);
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

async function measureChannel(baseUrl, route) {
  const html = await fetchBuffer(`${baseUrl}${route}`);
  const assets = [];
  for (const url of assetUrls(html.toString('utf-8'))) {
    assets.push({ url, bytes: (await fetchBuffer(new URL(url, `${baseUrl}${route}`))).length });
  }
  if (assets.length === 0) {
    throw new Error(`no JS/CSS assets found on ${route} - the asset parser may be missing a tag type`);
  }
  const total = html.length + assetTotalBytes(assets);
  return { htmlBytes: html.length, assets, total };
}

function printReport(results) {
  console.log('');
  console.log('channel'.padEnd(12), 'html'.padEnd(10), 'js+css'.padEnd(10), 'total'.padEnd(10), 'budget');
  console.log('-'.repeat(52));
  for (const result of results) {
    const assetBytes = assetTotalBytes(result.assets);
    console.log(
      result.route.padEnd(12),
      formatBytes(result.htmlBytes).padEnd(10),
      formatBytes(assetBytes).padEnd(10),
      formatBytes(result.total).padEnd(10),
      result.total <= BUDGET_BYTES ? 'OK' : 'OVER BUDGET'
    );
  }
  console.log('-'.repeat(52));
  return results.every((result) => result.total <= BUDGET_BYTES);
}

async function main() {
  console.log('Page-budget gate (NFR-003): initial-route payload (HTML + JS + CSS) <=', BUDGET_LABEL, 'per channel');
  console.log('Building frontend...');
  runOrExit(['run', 'build']);

  const port = await freePort();
  const baseUrl = `http://${HOST}:${port}`;
  server = startServer(port);
  try {
    await waitUntilReady(baseUrl, server);
    const results = [];
    for (const route of CHANNELS) {
      results.push({ route, ...(await measureChannel(baseUrl, route)) });
    }
    return printReport(results);
  } finally {
    killTree(server);
  }
}

function formatBytes(bytes) {
  return `${(bytes / 1024).toFixed(1)} KB`;
}

main()
  .then((passed) => {
    if (passed) {
      console.log(`Page-budget gate PASSED: all ${CHANNELS.length} channels within ${BUDGET_LABEL}`);
      process.exit(0);
    }
    console.error(`Page-budget gate FAILED: at least one channel exceeds ${BUDGET_LABEL}`);
    process.exit(1);
  })
  .catch((error) => {
    console.error(error.stack || String(error));
    process.exit(1);
  });
