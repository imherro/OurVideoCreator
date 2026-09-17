import test from 'node:test';
import assert from 'node:assert/strict';
import {motionAssetChoices,referencePreviewKey,referenceMedia,promptParts,uploadMotionAsset} from '../src/referencePresentation.ts';
const assets=[{id:'motion',kind:'video',category:'motion_reference'},
 {id:'old',kind:'video',category:'video'},{id:'derived',kind:'video',category:'motion_reference',metadata:{motionDerivedFrom:'old'}},
 {id:'image',kind:'image',category:'motion_reference'}];
test('motion chooser lists originals only, preserves historical and missing bindings without changing catalog',()=>{
 assert.deepEqual(motionAssetChoices(assets).map(a=>a.id),['motion']);
 assert.deepEqual(motionAssetChoices(assets,'old').map(a=>a.id),['old','motion']);
 assert.equal(motionAssetChoices(assets,'old')[0].historical,true);
 assert.equal(motionAssetChoices(assets,'gone')[0].missing,true);
 assert.equal(motionAssetChoices(assets,'derived')[0].historical,true);
 assert.equal(assets[1].historical,undefined);assert.equal(assets.length,4);
});
test('inline references resolve exact kind and manifest id through authenticated media route only',()=>{
 const catalog=[{id:'a/b',kind:'image',name:'visible',url:'https://untrusted.example/image'},...assets];
 const manifest=[{kind:'image',index:12,assetId:'a/b',name:'compiled'}, {kind:'video',index:1,assetId:'gone'},
  {kind:'audio',index:1,assetIds:['old']},{kind:'image',index:2,source:{jobId:'pending'}},
  {kind:'video',index:2,assetId:'image'}];
 assert.deepEqual(referenceMedia('@图片12',manifest,catalog),{kind:'image',id:'a/b',name:'compiled',url:'/api/assets/a%2Fb/file'});
 for(const label of ['@视频1','@视频2','@音频1','@图片2','@图片1','@图片12x'])assert.equal(referenceMedia(label,manifest,catalog),undefined,label);
 assert.equal(referenceMedia('@图片12',manifest,assets),undefined,'removed assets cannot remain playable');
 const prompt='动作@视频1，外观@图片12；声音@音频2 <script>文字</script>';
 assert.equal(promptParts(prompt).join(''),prompt);assert.ok(promptParts(prompt).includes('@图片12'));
});
test('preview identity changes for shared voice, model, defaults, graph and asset dependencies',()=>{
 const doc={filmBible:{voices:{version:1}},nodes:[{id:'v',data:{prompt:'old'}}],edges:[]};
 const shot={id:'s',dialogues:[{text:'old'}]},node={id:'v',data:{model_id:'m'}},models=[{id:'m',capabilities:{multimodal_reference:true}}];
 const base=()=>['project',structuredClone(doc),structuredClone(shot),structuredClone(node),structuredClone(assets),structuredClone(models)];
 const original=referencePreviewKey(...base());
 for(const mutate of [a=>a[0]='other',a=>a[1].filmBible.voices.version++,a=>a[1].videoDuration=8,
  a=>a[1].nodes[0].data.prompt='new',a=>a[1].edges.push({source:'x',target:'v'}),
  a=>a[2].dialogues[0].text='new',a=>a[3].data.model_id='other',a=>a[4].pop(),
  a=>a[4][0].name='new',a=>a[5][0].capabilities.multimodal_reference=false]){
  const args=base();mutate(args);assert.notEqual(referencePreviewKey(...args),original);
 }
 assert.equal(referencePreviewKey(...base()),original);
});
test('upload classifies explicitly and binds only a successful still-current target',async()=>{
 const calls=[];const file=new File(['fixture'],'motion.mp4',{type:'video/mp4'});
 await uploadMotionAsset(file,'p','current',()=>'current',async(path,init)=>{
  assert.equal(path,'/projects/p/assets?category=motion_reference');assert.equal(init.method,'POST');
  assert.equal(init.body.get('file').name,'motion.mp4');return {id:'uploaded',kind:'video'};
 },asset=>calls.push(asset.id),id=>calls.push(id));
 assert.deepEqual(calls,['uploaded','uploaded']);
 await assert.rejects(uploadMotionAsset(file,'p','old',()=>'new',async()=>({id:'retained',kind:'video'}),()=>calls.push('wrong'),()=>calls.push('wrong')),/未覆盖当前绑定/);
 await assert.rejects(uploadMotionAsset(file,'p','same',()=>'same',async()=>({id:'audio',kind:'audio'}),()=>calls.push('wrong'),()=>calls.push('wrong')),/必须为视频/);
 assert.equal(calls.length,2);
});
test('late upload cannot bind after navigation or rebinding during the request',async()=>{
 let current='original',finish;const mutations=[];
 const result=uploadMotionAsset(new File(['fixture'],'motion.mp4'),'p','original',()=>current,
  ()=>new Promise(resolve=>{finish=resolve}),asset=>mutations.push(asset),id=>mutations.push(id));
 current='different shot or binding';finish({id:'stored-original-project',kind:'video'});
 await assert.rejects(result,/上传素材保留在原作品/);assert.deepEqual(mutations,[]);
});
