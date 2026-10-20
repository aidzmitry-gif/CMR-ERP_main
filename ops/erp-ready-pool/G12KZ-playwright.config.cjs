const path = require('node:path');
const root = process.env.ERP_POOL_SOURCE_ROOT;
if (!root || !process.env.ERP_POOL_PROFILE) throw new Error('Private pool profile required');
const profile = require(process.env.ERP_POOL_PROFILE);
if (profile.kind !== 'ERP_READY_PRIVATE_POOL3_V1') throw new Error('Wrong profile');
process.env.E2E_BACKEND_PORT = String(profile.backendPort);
process.env.E2E_FRONTEND_PORT = String(profile.frontendPort);
const quote = value => "'" + value.replace(/'/g, "'\\''") + "'";
process.env.E2E_BACKEND_CMD = `python ${quote(path.join(__dirname, 'G12KZ-backend.py'))}`;
const base = require(path.join(root, 'frontend/playwright.config.ts')).default;
if (!Array.isArray(base.webServer) || base.webServer.length !== 2) throw new Error('Expected existing backend/frontend servers');
const servers = base.webServer.map((server, index) => ({ ...server, cwd: index === 0 ? root : path.join(root, 'frontend') }));
module.exports = {
  ...base,
  testDir: __dirname,
  testMatch: 'G12KZ-pool.spec.cjs',
  outputDir: path.join(__dirname, 'G12KZ-test-output'),
  workers: 1, retries: 0, maxFailures: 1,
  reporter: 'json',
  webServer: servers,
  metadata: { ...base.metadata, poolProjection: {
    backendCwd: servers[0].cwd, frontendCwd: servers[1].cwd, serverCount: servers.length,
    otherOptionsUnchanged: servers.every((server, index) => {
      const { cwd: _projectedCwd, ...projected } = server;
      const { cwd: _originalCwd, ...original } = base.webServer[index];
      return JSON.stringify(projected) === JSON.stringify(original);
    }),
  } },
  use: { ...base.use, baseURL: `http://127.0.0.1:${profile.frontendPort}`, trace: 'off', screenshot: 'off', video: 'off' },
  projects: [{ name: 'pool', use: { storageState: { cookies: [], origins: [] } } }],
};
