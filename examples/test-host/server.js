/**
 * Xdocs test host + mock IdP (design §17).
 *
 * Serves the static demo page that embeds <xdocs-viewer>, and emulates the
 * host's identity provider:
 *   - GET /.well-known/jwks.json  -> public signing keys (backend trusts these)
 *   - GET /auth/token?role=...    -> a short-lived demo JWT for the chosen role
 *
 * FOR LOCAL TESTING/DEMO ONLY — never use this in production.
 */
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { extname, join, normalize } from 'node:path';
import { fileURLToPath } from 'node:url';
import { dirname } from 'node:path';
import { generateKeyPair, exportJWK, SignJWT } from 'jose';

const __dirname = dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.TEST_HOST_PORT || 8080);
const ISSUER = process.env.MOCK_IDP_ISSUER || 'https://mock-idp.local';
const AUDIENCE = process.env.MOCK_IDP_AUDIENCE || 'xdocs';
const KID = 'mock-1';
const PUBLIC_DIR = join(__dirname, 'public');

// One ephemeral signing key per process.
const { publicKey, privateKey } = await generateKeyPair('RS256');
const jwk = { ...(await exportJWK(publicKey)), kid: KID, use: 'sig', alg: 'RS256' };

// Demo claim sets per role (API Spec §3). reader/editor are scoped to the
// sql-server space only (so platform stays hidden, demonstrating ACL isolation);
// admin holds a global role and sees every space.
const ROLES = {
  reader: { roles: [], scopes: ['space:sql-server:read'] },
  editor: { roles: [], scopes: ['space:sql-server:write'] },
  admin: { roles: ['admin'], scopes: [] },
};

async function issueToken(role) {
  const claims = ROLES[role] || ROLES.reader;
  return new SignJWT({ email: `${role}@example.com`, locale: 'en', ...claims })
    .setProtectedHeader({ alg: 'RS256', kid: KID })
    .setSubject(`demo-${role}`)
    .setIssuedAt()
    .setIssuer(ISSUER)
    .setAudience(AUDIENCE)
    .setExpirationTime('1h')
    .sign(privateKey);
}

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.map': 'application/json',
  '.svg': 'image/svg+xml',
};

function json(res, status, body) {
  const data = JSON.stringify(body);
  res.writeHead(status, {
    'content-type': 'application/json',
    'access-control-allow-origin': '*',
  });
  res.end(data);
}

async function serveStatic(res, urlPath) {
  const rel = normalize(urlPath === '/' ? '/index.html' : urlPath).replace(/^(\.\.[/\\])+/, '');
  const filePath = join(PUBLIC_DIR, rel);
  try {
    const data = await readFile(filePath);
    res.writeHead(200, { 'content-type': MIME[extname(filePath)] || 'application/octet-stream' });
    res.end(data);
  } catch {
    json(res, 404, { error: { code: 'not_found', message: rel } });
  }
}

const server = createServer(async (req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`);
  if (url.pathname === '/.well-known/jwks.json') {
    return json(res, 200, { keys: [jwk] });
  }
  if (url.pathname === '/auth/token') {
    const role = url.searchParams.get('role') || 'reader';
    return json(res, 200, { token: await issueToken(role), role });
  }
  if (url.pathname === '/healthz') {
    return json(res, 200, { status: 'ok' });
  }
  return serveStatic(res, url.pathname);
});

server.listen(PORT, () => {
  console.log(`[test-host] http://localhost:${PORT}  (mock-IdP issuer=${ISSUER})`);
});
