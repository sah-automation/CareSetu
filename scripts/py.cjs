const { spawnSync } = require('node:child_process');
const path = require('node:path');

const venvName = process.env.CARESETU_BACKEND_ENV || 'backend-env';
const python = path.join('D:\\Dev', 'venvs', venvName, 'Scripts', 'python.exe');
const args = process.argv.slice(2);

const result = spawnSync(python, args, { stdio: 'inherit', cwd: process.cwd() });
process.exit(result.status === null ? 1 : result.status);
