const path = require('node:path');
const { test, expect } = require(path.join(process.env.ERP_POOL_SOURCE_ROOT, 'frontend/node_modules/@playwright/test'));
const profile = require(process.env.ERP_POOL_PROFILE);
const frontend = `http://127.0.0.1:${profile.frontendPort}`;
const backend = `http://127.0.0.1:${profile.backendPort}`;

async function login(browser, username, role) {
  const context = await browser.newContext({ baseURL: frontend, storageState: { cookies: [], origins: [] } });
  try {
    const response = await context.request.post('/api/auth/login', { data: { username } });
    expect(response.status()).toBe(200);
    const result = await response.json();
    expect(result.user?.username).toBe(username);
    expect(result.user?.role).toBe(role);
    const access = await context.request.get('/api/system/access');
    expect(access.status()).toBe(200);
    expect((await access.json()).current_roles).toContain(role);
    return context;
  } catch (error) {
    await context.close();
    throw error;
  }
}

async function snapshot(context) {
  const response = await context.request.get('/api/__e2e_isolation');
  expect(response.status()).toBe(200); // Preserve the original isolation gate.
  const result = await response.json();
  expect(result.chain).toBe('CRM-READY-001-H04-E2E');
  expect(result.synthetic_only).toBe(true);
  expect(result.background_workers).toBe(false);
  expect(result.email_enabled).toBe(false);
  expect(result.egress_guard).toBe(true);
  const s = result.pool_diag;
  expect(Object.keys(s ?? {}).sort()).toEqual(['schema', 'sqlalchemy', 'aiosqlite', 'poolClass', 'size', 'maxOverflow', 'active', 'out', 'in', 'anomalies', 'owners', 'subscribers'].sort());
  expect(s?.schema).toBe(1);
  expect(s?.sqlalchemy).toMatch(/^\d+\.\d+\.\d+(?:[a-z0-9.+-]*)$/i);
  expect(s?.aiosqlite).toMatch(/^\d+\.\d+\.\d+(?:[a-z0-9.+-]*)$/i);
  for (const field of ['poolClass', 'size', 'maxOverflow', 'active', 'out', 'in', 'anomalies']) {
    expect(Number.isSafeInteger(s[field])).toBe(true);
  }
  expect(s.poolClass).toBe(1);
  expect(s.size).toBe(5);
  expect(s.maxOverflow).toBe(10);
  expect(s.anomalies).toBe(0);
  expect(s.owners).toHaveLength(5);
  expect(s.subscribers).toHaveLength(2);
  for (const [stage, count] of s.owners) {
    expect(Number.isSafeInteger(stage) && stage >= 0 && stage <= 4).toBe(true);
    expect(Number.isSafeInteger(count) && count >= 0).toBe(true);
  }
  expect(s.owners.map(row => row[0])).toEqual([0, 1, 2, 3, 4]);
  for (const count of s.subscribers) expect(Number.isSafeInteger(count) && count >= 0).toBe(true);
  expect(s.owners.reduce((sum, row) => sum + row[1], 0)).toBe(s.active);
  expect(s.out - s.in).toBe(s.active);
  return s;
}

async function record(info, stage, s) {
  // Only fixed stage IDs, counters and package versions; never tokens/cookies/bodies.
  await info.attach(`pool-stage-${stage}`, { contentType: 'application/json', body: Buffer.from(JSON.stringify({ stage, ...s })) });
}

async function closeContexts(...contexts) {
  const closed = await Promise.allSettled(contexts.filter(Boolean).map(context => Promise.resolve().then(() => context.close())));
  if (closed.some(result => result.status === 'rejected')) throw new Error('Diagnostic context cleanup failed');
}

async function firstFrame(reader) {
  const decoder = new TextDecoder();
  let frame = '';
  let bytes = 0;
  while (!frame.includes('\n\n')) {
    const chunk = await reader.read();
    if (chunk.done) throw new Error('SSE ended before its first complete frame');
    bytes += chunk.value.byteLength;
    if (bytes > 4096) throw new Error('SSE first frame exceeds diagnostic byte limit');
    frame += decoder.decode(chunk.value, { stream: true });
  }
  return frame.slice(0, frame.indexOf('\n\n') + 2);
}

async function settled(context, baseline) {
  await expect.poll(async () => {
    const s = await snapshot(context);
    return { active: s.active, subscribers: s.subscribers };
  }, { timeout: 12000 }).toEqual({ active: baseline.active, subscribers: baseline.subscribers });
  return snapshot(context);
}

test('KV_POOL_01_fresh_director_marker_and_db_counts', async ({ browser }, info) => {
  const director = await login(browser, 'kharkovich_d', 'director');
  try {
    const before = await snapshot(director);
    expect(before.active).toBe(0);
    expect(before.subscribers).toEqual([0, 0]);
    await record(info, 1, before);
    const access = await director.request.get('/api/system/access');
    expect(access.status()).toBe(200);
    const after = await settled(director, before);
    expect(after.out).toBeGreaterThan(before.out);
    expect(after.in).toBeGreaterThan(before.in);
    expect(after.active).toBe(0);
    expect(after.anomalies).toBe(0);
    await record(info, 2, after);
  } finally { await director.close(); }
});

test('KV_POOL_02_HTTP_sales_SSE_abort_cleanup', async ({ browser }, info) => {
  let observer;
  let owner;
  const abort = new AbortController();
  let reader;
  let timer;
  try {
    observer = await login(browser, 'kharkovich_d', 'director');
    owner = await login(browser, 'e2e_owner', 'sales');
    const owners = await owner.request.get('/api/sales/clients/owners');
    expect(owners.status()).toBe(200);
    expect((await owners.json()).map(row => row.id)).toEqual([2901]);
    const before = await snapshot(observer);
    expect(before.active).toBe(0);
    expect(before.subscribers).toEqual([0, 0]);
    timer = setTimeout(() => abort.abort(), 12000);
    const response = await fetch(`${backend}/sales/calls/stream`, {
      headers: { 'X-User': 'e2e_owner', 'X-User-Roles': 'sales' }, signal: abort.signal,
    });
    expect(response.status).toBe(200);
    expect(response.headers.get('content-type')).toContain('text/event-stream');
    reader = response.body.getReader();
    expect(await firstFrame(reader)).toBe(': connected\n\n');
    clearTimeout(timer);
    const open = await snapshot(observer);
    expect(open.subscribers).toEqual([1, 0]);
    await record(info, 3, open);
    abort.abort();
    await reader.cancel().catch(() => undefined);
    await record(info, 4, await settled(observer, before));
    const access = await owner.request.get('/api/system/access');
    expect(access.status()).toBe(200);
  } finally {
    clearTimeout(timer);
    abort.abort();
    if (reader) await reader.cancel().catch(() => undefined);
    await closeContexts(owner, observer);
  }
});

test('KV_POOL_03_Next_proxy_SSE_context_teardown_cleanup', async ({ browser }, info) => {
  let observer;
  let owner;
  try {
    observer = await login(browser, 'kharkovich_d', 'director');
    owner = await login(browser, 'e2e_owner', 'sales');
    const owners = await owner.request.get('/api/sales/clients/owners');
    expect(owners.status()).toBe(200);
    expect((await owners.json()).map(row => row.id)).toEqual([2901]);
    const before = await snapshot(observer);
    expect(before.active).toBe(0);
    expect(before.subscribers).toEqual([0, 0]);
    const page = await owner.newPage();
    // A JSON document avoids AppShell and its unrelated automatic subscriptions.
    await page.goto('/api/__e2e_isolation');
    const opened = await page.evaluate(async () => {
      const abort = new AbortController();
      const timer = setTimeout(() => abort.abort(), 12000);
      try {
        const response = await fetch('/api/sales/calls/stream', { signal: abort.signal });
        if (response.status !== 200) { clearTimeout(timer); abort.abort(); return { status: response.status, connected: false }; }
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let frame = '';
        let bytes = 0;
        while (!frame.includes('\n\n')) {
          const chunk = await reader.read();
          if (chunk.done) throw new Error('SSE ended before its first complete frame');
          bytes += chunk.value.byteLength;
          if (bytes > 4096) throw new Error('SSE first frame exceeds diagnostic byte limit');
          frame += decoder.decode(chunk.value, { stream: true });
        }
        const connected = frame.slice(0, frame.indexOf('\n\n') + 2) === ': connected\n\n';
        if (!connected) throw new Error('Unexpected SSE first frame');
        clearTimeout(timer);
        window.__erpPoolObservation = { reader, abort };
        return { status: response.status, connected };
      } catch {
        clearTimeout(timer);
        abort.abort();
        throw new Error('SSE first-frame diagnostic failed');
      }
    });
    expect(opened).toEqual({ status: 200, connected: true });
    const open = await snapshot(observer);
    expect(open.subscribers).toEqual([1, 0]);
    await record(info, 5, open);
    await owner.close(); // Browser disconnect must propagate through the real Next proxy.
    await record(info, 6, await settled(observer, before));
    const access = await observer.request.get('/api/system/access');
    expect(access.status()).toBe(200);
  } finally {
    await closeContexts(owner, observer);
  }
});
