#!/usr/bin/env node
/**
 * oauth_callback_server.js
 * ========================
 * Minimal OAuth 2.0 callback helper for the Uber MCP integration.
 *
 * PURPOSE:
 *   When Uber redirects the user back after authorization, this server
 *   receives the authorization code at /callback, exchanges it for an
 *   access token, and displays the token on screen.
 *
 *   You then copy the access token and provide it to Jarvis by saying:
 *     "Set my Uber access token to <token> for user jarvis"
 *   Jarvis will call the uber_set_access_token MCP tool.
 *
 * USAGE:
 *   1. Ensure UBER_CLIENT_ID, UBER_CLIENT_SECRET, UBER_REDIRECT_URI are
 *      set in your environment or in a .env file in this directory.
 *   2. Run:  node oauth_callback_server.js
 *   3. Keep this terminal open during the OAuth flow.
 *   4. After authorization, copy the token displayed here into Jarvis.
 *   5. Press Ctrl+C to stop this server when done.
 *
 * SECURITY:
 *   - This server only runs locally on port 3000.
 *   - It never stores or logs the client secret.
 *   - The displayed access token is yours — treat it as a password.
 *
 * REQUIRED PACKAGES:
 *   npm install express axios dotenv
 *   (or: npx --yes -- node -e "require('express')" 2>/dev/null)
 */

// Load .env if present (optional — env vars from shell also work)
try {
  require('dotenv').config();
} catch (e) {
  // dotenv not installed — rely on shell environment variables
}

const http = require('http');
const https = require('https');
const url = require('url');
const querystring = require('querystring');

const PORT = parseInt(process.env.OAUTH_CALLBACK_PORT || '3000', 10);

const CLIENT_ID     = process.env.UBER_CLIENT_ID;
const CLIENT_SECRET = process.env.UBER_CLIENT_SECRET;
const REDIRECT_URI  = process.env.UBER_REDIRECT_URI || `http://localhost:${PORT}/callback`;

if (!CLIENT_ID || !CLIENT_SECRET) {
  console.error('[ERROR] UBER_CLIENT_ID and UBER_CLIENT_SECRET must be set.');
  console.error('        Create a .env file (see .env.example) or export them in your shell.');
  process.exit(1);
}

// Exchange authorization code for access token using core https module
// (no axios dependency required — works with Node.js built-ins only)
function exchangeCode(code) {
  return new Promise((resolve, reject) => {
    const body = querystring.stringify({
      client_id:     CLIENT_ID,
      client_secret: CLIENT_SECRET,
      grant_type:    'authorization_code',
      redirect_uri:  REDIRECT_URI,
      code,
    });

    const options = {
      hostname: 'auth.uber.com',
      path:     '/oauth/v2/token',
      method:   'POST',
      headers: {
        'Content-Type':   'application/x-www-form-urlencoded',
        'Content-Length': Buffer.byteLength(body),
      },
    };

    const req = https.request(options, (res) => {
      let data = '';
      res.on('data', (chunk) => { data += chunk; });
      res.on('end', () => {
        try {
          const parsed = JSON.parse(data);
          if (res.statusCode === 200) {
            resolve(parsed);
          } else {
            reject(new Error(`Uber token endpoint returned ${res.statusCode}: ${data}`));
          }
        } catch (e) {
          reject(new Error(`Failed to parse token response: ${data}`));
        }
      });
    });

    req.on('error', reject);
    req.write(body);
    req.end();
  });
}

const server = http.createServer(async (req, res) => {
  const parsed = url.parse(req.url, true);

  if (parsed.pathname !== '/callback') {
    res.writeHead(404);
    res.end('Not found');
    return;
  }

  const { code, state, error, error_description } = parsed.query;

  if (error) {
    const msg = `Uber authorization failed: ${error} — ${error_description || ''}`;
    console.error(`[ERROR] ${msg}`);
    res.writeHead(400, { 'Content-Type': 'text/html' });
    res.end(`<html><body><h1>Authorization Failed</h1><p>${msg}</p></body></html>`);
    return;
  }

  if (!code) {
    res.writeHead(400, { 'Content-Type': 'text/html' });
    res.end('<html><body><h1>Bad Request</h1><p>Missing authorization code.</p></body></html>');
    return;
  }

  console.log(`\n[OAuth] Received authorization code. Exchanging for token...`);

  try {
    const tokenData = await exchangeCode(code);
    const accessToken = tokenData.access_token;
    const expiresIn   = tokenData.expires_in;
    const scope       = tokenData.scope;

    // Log non-sensitive metadata only
    console.log(`[OAuth] Token exchange successful.`);
    console.log(`        Scope    : ${scope}`);
    console.log(`        Expires  : ${expiresIn}s`);
    console.log(`        User ID (state): ${state || '(none)'}`);
    console.log(`\n[OAuth] ACCESS TOKEN (copy this into Jarvis):`);
    console.log(`        ${accessToken}`);
    console.log(`\n        In Jarvis, say:`);
    console.log(`        "Set my Uber access token to <token> for user jarvis"`);

    res.writeHead(200, { 'Content-Type': 'text/html' });
    res.end(`
      <html>
        <head><title>Uber Authorization Successful</title></head>
        <body style="font-family:sans-serif;max-width:700px;margin:40px auto;padding:0 20px">
          <h1 style="color:#1a1a1a">&#10003; Authorization Successful</h1>
          <p><strong>Scope:</strong> ${scope}</p>
          <p><strong>Expires in:</strong> ${expiresIn} seconds</p>
          <hr/>
          <h2>Your Access Token</h2>
          <p style="background:#f4f4f4;padding:12px;border-radius:6px;word-break:break-all;font-family:monospace">
            ${accessToken}
          </p>
          <p>Copy the token above and give it to Jarvis:</p>
          <blockquote style="background:#eef;padding:10px;border-left:4px solid #88a">
            "Set my Uber access token to &lt;token&gt; for user jarvis"
          </blockquote>
          <p><em>You can now close this tab and stop the callback server (Ctrl+C).</em></p>
        </body>
      </html>
    `);

  } catch (err) {
    console.error(`[ERROR] Token exchange failed: ${err.message}`);
    res.writeHead(500, { 'Content-Type': 'text/html' });
    res.end(`
      <html>
        <body>
          <h1>Token Exchange Failed</h1>
          <p>${err.message}</p>
          <p>Check the terminal for details.</p>
        </body>
      </html>
    `);
  }
});

server.listen(PORT, () => {
  console.log('='.repeat(60));
  console.log('  Uber OAuth Callback Server');
  console.log('='.repeat(60));
  console.log(`  Listening on : http://localhost:${PORT}`);
  console.log(`  Callback URL : ${REDIRECT_URI}`);
  console.log(`  Client ID    : ${CLIENT_ID.slice(0, 6)}...`);
  console.log('');
  console.log('  Make sure this redirect URI is added to your Uber');
  console.log('  Developer Dashboard → App → Auth tab.');
  console.log('');
  console.log('  Waiting for OAuth callback... (Ctrl+C to stop)');
  console.log('='.repeat(60));
});
