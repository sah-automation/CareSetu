const { spawnSync } = require('node:child_process');
const path = require('node:path');
const fs = require('node:fs');

const venvName = process.env.CARESETU_BACKEND_ENV || 'backend-env';
const python = path.join('D:\\Dev', 'venvs', venvName, 'Scripts', 'python.exe');
const alembicIni = path.join('apps', 'backend', 'alembic.ini');

if (!fs.existsSync(alembicIni)) {
  console.error(`migration-check: missing ${alembicIni}`);
  process.exit(1);
}

const result = spawnSync(python, ['-m', 'alembic', '-c', 'apps/backend/alembic.ini', 'heads'], {
  encoding: 'utf-8',
  cwd: process.cwd(),
});

if (result.status !== 0) {
  console.error('migration-check: alembic heads failed');
  console.error(result.stderr || result.stdout);
  process.exit(1);
}

const heads = (result.stdout || '')
  .split(/\r?\n/)
  .map((line) => line.trim())
  .filter(Boolean);

if (heads.length === 0) {
  console.log('migration-check: no migrations yet (expected before PHASE-1). OK');
  process.exit(0);
}

if (heads.length > 1) {
  console.error(`migration-check: multiple heads (${heads.length}) — linear history required`);
  process.exit(1);
}

console.log(`migration-check: single head ${heads[0].split(' ')[0]}. OK`);
process.exit(0);
