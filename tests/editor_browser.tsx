import React, {useState} from 'react';
import {createRoot} from 'react-dom/client';
import {EditorWorkspace} from '../src/editor/EditorWorkspace';
import {planInitialTimeline} from '../src/editor/initialTimeline';
const assets = ['red', 'blue'].map(id => ({id, project_id: 'isolated-editor', origin_episode_no: 1, name: id, kind: 'video', url: `/${id}.mp4`, metadata: {duration: 4, node_id: id}}));
const shots = assets.map((asset, index) => ({id: asset.id, videoNode: asset.id, duration: index + 2}));
const nodes = assets.map(asset => ({id: asset.id, data: {assetId: asset.id}}));
const sharedAssets = [...assets, {...assets[1], id: 'other-ep-blue', project_id: 'other-episode', origin_episode_no: 2,
  name: '第二集蓝色参考.mp4', metadata: {duration: 4, node_id: 'blue'}}];
const episodes = ['isolated-editor', 'other-episode'].map((id, index) => ({id, name: id,
  revision: 1, created: 0, updated: 0, production_id: 'isolated-production', episode_no: index + 1,
  episode_title: index ? '第二集' : '当前集'}));
let serial = 0;
const initial = planInitialTimeline({assets, shots, nodes, resolution: {width: 1280, height: 720}}, () => String(++serial)).timeline;
function App() {
  const empty = new URLSearchParams(location.search).has('empty');
  const [editor, setEditor] = useState({version: 1 as const, timeline: empty ? {...initial, tracks: []} : initial});
  const [writes, setWrites] = useState(0);
  return <><output>隔离组件测试 · 红色 0–4 秒 / 蓝色 4–8 秒 · 本地修改次数 {writes}</output>
    <EditorWorkspace projectId="isolated-editor" productionName="纯本地合成视频" episodeLabel="多片段回归"
      episodes={episodes}
      ratio="16:9" duration={empty ? 4 : 8} assets={sharedAssets} shots={shots} nodes={nodes} editor={editor}
      onChange={value => {setEditor(value); setWrites(count => count + 1);}} onExport={() => {}} /></>;
}
createRoot(document.getElementById('root')!).render(<App />);
