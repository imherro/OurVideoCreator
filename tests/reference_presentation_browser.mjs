// Component-only synthetic media. No API proxy, credentials, database or provider.
import {createServer} from 'vite';
import react from '@vitejs/plugin-react';
import {fileURLToPath} from 'node:url';
const wav=Buffer.alloc(44+16000);
wav.write('RIFF');wav.writeUInt32LE(wav.length-8,4);wav.write('WAVEfmt ',8);wav.writeUInt32LE(16,16);
wav.writeUInt16LE(1,20);wav.writeUInt16LE(1,22);wav.writeUInt32LE(8000,24);wav.writeUInt32LE(16000,28);
wav.writeUInt16LE(2,32);wav.writeUInt16LE(16,34);wav.write('data',36);wav.writeUInt32LE(16000,40);
const fixtures={name:'synthetic-reference-media',configureServer(server){server.middlewares.use((req,res,next)=>{
 if(req.url==='/api/assets/fixture-frame/file'){
  res.setHeader('Content-Type','image/svg+xml');res.end('<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360"><rect width="640" height="360" fill="#334d75"/><circle cx="320" cy="180" r="80" fill="#dca95b"/><text x="20" y="40" fill="white" font-size="24">SYNTHETIC REFERENCE - NO USER MEDIA</text></svg>');return;
 }
 if(req.url==='/api/assets/fixture-sample/file'){res.setHeader('Content-Type','audio/wav');res.end(wav);return;}
 if(req.url?.startsWith('/api/')){res.statusCode=404;res.end('Test fixture has no business API');return;}
 next();
})}};
const server=await createServer({root:fileURLToPath(new URL('..',import.meta.url)),configFile:false,
 plugins:[react(),fixtures],server:{host:'127.0.0.1',port:0,open:false,proxy:{}}});
await server.listen();console.log(server.resolvedUrls.local[0]+'tests/motion_reference_browser.html');
process.stdin.resume();process.stdin.on('data',async chunk=>{if(String(chunk).trim()==='stop'){await server.close();process.exit(0)}});
