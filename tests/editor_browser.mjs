// Isolated component smoke UI. No API proxy, database, provider, or user data.
// Run: node tests/editor_browser.mjs <existing-ffmpeg-executable>
import {mkdtempSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {resolve} from 'node:path';
import {fileURLToPath} from 'node:url';
import {execFileSync} from 'node:child_process';
import {createServer} from 'vite';
import react from '@vitejs/plugin-react';
const root = fileURLToPath(new URL('..', import.meta.url));
const publicDir = mkdtempSync(resolve(tmpdir(), 'ovc-editor-browser-'));
if (!process.argv[2]) throw new Error('Pass an existing FFmpeg executable path');
for (const color of ['red', 'blue']) execFileSync(process.argv[2], ['-v', 'error', '-f', 'lavfi', '-i',
  `color=c=${color}:s=320x180:r=24:d=4`, '-c:v', 'libx264', '-pix_fmt', 'yuv420p', resolve(publicDir, `${color}.mp4`)], {windowsHide: true});
const server = await createServer({root, configFile: false, publicDir, plugins: [react()],
  server: {host: '127.0.0.1', port: 0, open: false, proxy: {}}});
await server.listen();
console.log(JSON.stringify({url: `${server.resolvedUrls.local[0]}tests/editor_browser.html`, fixtureDirectory: publicDir}));
