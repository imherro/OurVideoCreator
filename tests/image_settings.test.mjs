import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {patchNode} from '../src/graph.ts';
import {ensureShotNodes} from '../src/shotNodes.ts';

test('image setting edits stale dependent results and preserve existing assets',()=>{
 const graph={nodes:[{id:'i',data:{kind:'image',assetId:'old-image'}},{id:'v',data:{kind:'video',assetId:'old-video'}}],edges:[{source:'i',target:'v'}]};
 const next=patchNode(graph,'i',{imageSettings:{sizeMode:'custom',size:'1280x720',seed:7}});
 assert.equal(next.nodes[0].data.stale,true);assert.equal(next.nodes[1].data.stale,true);
 assert.equal(next.nodes[0].data.assetId,'old-image');assert.equal(next.nodes[1].data.assetId,'old-video');
 assert.ok(next.nodes[0].data.generation_revision>0);
 assert.equal(graph.nodes[0].data.imageSettings,undefined);
});

test('batch preparation does not replace explicitly saved image settings',()=>{
 const image={id:'i',data:{kind:'image',imageSettings:{sizeMode:'custom',size:'1280x720',seed:7},parameters:{resolution:'1280x720'}}};
 const video={id:'v',data:{kind:'video'}};
 const graph={nodes:[image,video],edges:[{id:'edge',source:'i',target:'v'}],shots:[{id:'s',imageNode:'i',videoNode:'v'}]};
 const next=ensureShotNodes(graph,[],[],()=>{throw new Error('unexpected new node')});
 assert.equal(next.nodes.find(n=>n.id==='i'),image);
});

test('table grid and canvas wire the shared settings component without a direct save shortcut',()=>{
 const main=readFileSync(new URL('../src/main.tsx',import.meta.url),'utf8');
 const workspace=readFileSync(new URL('../src/pages/StoryboardWorkspace.tsx',import.meta.url),'utf8');
 assert.equal((main.match(/<ImageGenerationSettings/g)||[]).length,2);
 assert.equal((workspace.match(/props.renderImageSettings\?\.\(node\)/g)||[]).length,2);
 const settings=readFileSync(new URL('../src/ImageGenerationSettings.tsx',import.meta.url),'utf8');
 assert.ok(settings.includes('/image-spec'));
 assert.ok(!settings.includes('/jobs')&&!settings.includes("method:'PUT'"));
});
