// Component-only page, no API proxy, provider, credentials or user database.
import {createServer} from 'vite';
import react from '@vitejs/plugin-react';
import {fileURLToPath} from 'node:url';
const server=await createServer({root:fileURLToPath(new URL('..',import.meta.url)),configFile:false,
 plugins:[react()],server:{host:'127.0.0.1',port:0,open:false,proxy:{}}});
await server.listen();
console.log(server.resolvedUrls.local[0]+'tests/image_settings_browser.html');
process.stdin.resume();
process.stdin.on('data',async chunk=>{if(String(chunk).trim()==='stop'){await server.close();process.exit(0)}});
