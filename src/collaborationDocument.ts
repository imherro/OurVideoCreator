/** Bridge existing editor pure functions to independent persistence objects.
 * This returns commands' inputs, never a writable aggregate Project.document.
 */
import {deriveManagedGraph,isManagedVisualNode,isManagedVisualEdge} from './filmBible/managedGraph.ts';
import {defaultStage} from './directorScene.ts';
import {importLegacyTimeline,legacyTimelineProjection,timelineSettingsProjection} from './editor/legacyTimeline.ts';
import type {EditorAsset} from './editor/editorDocument.ts';
import {equalContent} from './objectDrafts.ts';

type Value = Record<string,any>;
export type DocumentPart = {key:string;kind:'shot'|'node'|'visual_card'|'graph'|'timeline'|'director';content:Value};
export type DocumentParts = {parts:Map<string,DocumentPart>;episodeMetadata:Value;productionMetadata:Value};
const copy = <T>(value:T):T => structuredClone(value);
const PRIVATE_KEYS = new Set(['selected','dragging','resizing','measured','width','height']);
const PRIVATE_DOCUMENT_KEYS = new Set(['viewport','selection','selected','playhead','panel','panoramaViewpoint','applied']);

function businessNode(node:Value) {
  const result=Object.fromEntries(Object.entries(node).filter(([key]) => key !== 'position' && !PRIVATE_KEYS.has(key)).map(([key,value])=>[key,copy(value)]));
  // GET-only fingerprint comparison is not authored node content.
  if(result.data){delete result.data.currentGenerationFingerprint;delete result.data.generationStatus;}
  return result;
}

/** Local invalidation traverses the graph for preview. A derived stale hint or
 * counter alone must never turn another assignee's object into a write target.
 * Fingerprints, result references and explicit state_reviewed remain business
 * content. When an actual edit happens, its own invalidation data is retained. */
export function samePartContent(kind:string,left:Value,right:Value){
  const comparable=(value:Value)=>{
    if(kind==='graph'&&value){
      const result=copy(value);
      result.positions={...result.positions};
      // A server-created node may omit its initial position. The read model
      // renders that exact default; materializing it is not a user move.
      for(const id of result.nodeOrder||[])result.positions[id]??={x:0,y:0};
      return result;
    }
    if(!value||!['shot','node'].includes(kind))return value;
    const result=copy(value);
    const nodes=kind==='shot'?result.nodes||[]:[result.node];
    // Children are identified by ID; their canvas ordering is graph-owned.
    // GET/graph projection can reorder them without any authored shot edit.
    if(kind==='shot')nodes.sort((a:Value,b:Value)=>String(a.id).localeCompare(String(b.id)));
    for(const node of nodes)if(node?.data)for(const key of ['stale','staleReason','generation_revision','generationStatus','currentGenerationFingerprint'])delete node.data[key];
    return result;
  };
  return equalContent(comparable(left),comparable(right));
}

export function splitCollaborationDocument(document:Value, assets:EditorAsset[]=[]):DocumentParts {
  const parts = new Map<string,DocumentPart>();
  const put=(kind:DocumentPart['kind'],key:string,content:Value)=>{
    const identity=`${kind}:${key}`;
    if(parts.has(identity))throw new Error('对象语义编号重复：'+identity);
    parts.set(identity,{key,kind,content});
  };
  const nodes:Value[]=document.nodes||[];
  const shots:Value[]=document.shots||[];
  const ownedNodes = new Set<string>();
  for(const shot of shots){
    const key=String(shot.uid||shot.id||'');
    if(!key)throw new Error('镜头缺少稳定编号');
    const childIds=new Set([shot.imageNode,shot.videoNode,shot.pipeline?.imageNodeId,shot.pipeline?.videoNodeId].filter(Boolean));
    const children=nodes.filter(node=>childIds.has(node.id));
    for(const node of children){
      if(ownedNodes.has(node.id))throw new Error('生成节点不能同时属于两个镜头');
      ownedNodes.add(node.id);
    }
    const content=copy(shot);
    delete content.order; // Structure owns ordering; text edits do not touch it.
    put('shot',key,{shot:content,nodes:children.map(businessNode)});
  }
  for(const node of nodes){
    if(ownedNodes.has(node.id)||isManagedVisualNode(node)||node.data?.canonicalScriptProjection)continue;
    put('node',String(node.id),{node:businessNode(node)});
  }
  const visual=document.filmBible?.visual||{cards:{},versions:{}};
  for(const [key,card] of Object.entries(visual.cards||{})){
    put('visual_card',key,{card:copy(card),versions:Object.fromEntries(
      Object.entries(visual.versions||{}).filter(([,version])=>(version as Value).cardId===key).map(([id,version])=>[id,copy(version)])),
      voice_profile:copy(document.filmBible?.voices?.profiles?.[key]||null)});
  }
  put('graph','graph',{
    edges:(document.edges||[]).filter((edge:Value)=>!isManagedVisualEdge(edge)).map((edge:Value)=>{
      const item=copy(edge);delete item.selected;return item;
    }),
    positions:Object.fromEntries(nodes.map(node=>[node.id,copy(node.position||{x:0,y:0})])),
    nodeOrder:nodes.map(node=>node.id),shotOrder:shots.map(shot=>String(shot.uid||shot.id)),
  });
  const timeline=document.editor?.timeline || importLegacyTimeline(document.timeline||[],assets,document.ratio,document.audio_id);
  put('timeline','timeline',{timeline:copy(timeline)});
  put('director','director',{stage:copy(document.director||defaultStage())});
  const filmBible=copy(document.filmBible||{});
  delete filmBible.visual;
  delete filmBible.voices;
  const productionMetadata={style:document.style,generationPolicy:copy(document.generationPolicy||{}),filmBible};
  const excluded=new Set(['nodes','edges','shots','timeline','editor','director','audio_id','music_volume','transition','export_resolution','filmBible','style','generationPolicy',...PRIVATE_DOCUMENT_KEYS]);
  const episodeMetadata=Object.fromEntries(Object.entries(document).filter(([key])=>!excluded.has(key)).map(([key,value])=>[key,copy(value)]));
  return {parts,episodeMetadata,productionMetadata};
}

export function composeCollaborationDocument(snapshot:DocumentParts, scriptNodes:Value[]=[]):Value {
  const values=[...snapshot.parts.values()];
  const singleton=(kind:DocumentPart['kind'])=>values.find(part=>part.kind===kind)?.content||{};
  const graph=singleton('graph');
  const shotParts=values.filter(part=>part.kind==='shot');
  const order:string[]=graph.shotOrder||[];
  shotParts.sort((a,b)=>{
    const ai=order.indexOf(a.key),bi=order.indexOf(b.key);
    return (ai<0?Number.MAX_SAFE_INTEGER:ai)-(bi<0?Number.MAX_SAFE_INTEGER:bi)||a.key.localeCompare(b.key);
  });
  const shots=shotParts.map((part,index)=>({...copy(part.content.shot),order:index+1}));
  const nodes=[...shotParts.flatMap(part=>copy(part.content.nodes||[])),
    ...values.filter(part=>part.kind==='node').map(part=>copy(part.content.node)),...copy(scriptNodes)];
  for(const node of nodes)node.position=copy(graph.positions?.[node.id]||{x:0,y:0});
  const nodeOrder:string[]=graph.nodeOrder||[];
  nodes.sort((a,b)=>{
    const ai=nodeOrder.indexOf(a.id),bi=nodeOrder.indexOf(b.id);
    return (ai<0?Number.MAX_SAFE_INTEGER:ai)-(bi<0?Number.MAX_SAFE_INTEGER:bi)||a.id.localeCompare(b.id);
  });
  const visual={cards:{} as Value,versions:{} as Value},profiles:Value={};
  for(const part of values.filter(part=>part.kind==='visual_card')){
    visual.cards[part.key]=copy(part.content.card);
    Object.assign(visual.versions,copy(part.content.versions));
    if(part.content.voice_profile)profiles[part.key]=copy(part.content.voice_profile);
  }
  const timeline=singleton('timeline').timeline;
  const result={...copy(snapshot.episodeMetadata),...copy(snapshot.productionMetadata),
    filmBible:{...copy(snapshot.productionMetadata.filmBible),visual,voices:{profiles}},
    shots,nodes,edges:copy(graph.edges||[]),director:copy(singleton('director').stage||defaultStage()),
    editor:{version:1,timeline:copy(timeline)},timeline:timeline?legacyTimelineProjection(timeline):[],
    ...(timeline?timelineSettingsProjection(timeline):{}),
  };
  const derived=deriveManagedGraph(result);
  return {...derived,nodes:derived.nodes.map(node=>({...node,
    position:copy(graph.positions?.[node.id]||node.position||{x:0,y:0})}))};
}

export function changedDocumentParts(before:DocumentParts,after:DocumentParts){
  const created:DocumentPart[]=[],updated:DocumentPart[]=[],removed:DocumentPart[]=[];
  for(const [key,part] of after.parts){
    const previous=before.parts.get(key);
    if(!previous)created.push(part);
    else if(!samePartContent(part.kind,previous.content,part.content))updated.push(part);
  }
  for(const [key,part] of before.parts)if(!after.parts.has(key))removed.push(part);
  return {created,updated,removed,
    episodeMetadata:!equalContent(before.episodeMetadata,after.episodeMetadata),
    productionMetadata:!equalContent(before.productionMetadata,after.productionMetadata)};
}
