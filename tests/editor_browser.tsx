import React, {useState} from 'react';
import {createRoot} from 'react-dom/client';
import {EditorWorkspace} from '../src/editor/EditorWorkspace';
import {planInitialTimeline} from '../src/editor/initialTimeline';
const assets = ['red', 'blue'].map(id => ({id, name: id, kind: 'video', url: `/${id}.mp4`, metadata: {duration: 4}}));
const shots = assets.map((asset, index) => ({id: asset.id, videoNode: asset.id, duration: index + 2}));
const nodes = assets.map(asset => ({id: asset.id, data: {assetId: asset.id}}));
let serial = 0;
const initial = planInitialTimeline({assets, shots, nodes, resolution: {width: 1280, height: 720}}, () => String(++serial)).timeline;
function App() {
  const empty = new URLSearchParams(location.search).has('empty');
  const [editor, setEditor] = useState({version: 1 as const, timeline: empty ? {...initial, tracks: []} : initial});
  const [writes, setWrites] = useState(0);
  return <><output>隔离组件测试 · 红色 0–4 秒 / 蓝色 4–8 秒 · 本地修改次数 {writes}</output>
    <EditorWorkspace projectId="isolated-editor" productionName="纯本地合成视频" episodeLabel="多片段回归"
      ratio="16:9" duration={empty ? 4 : 8} assets={assets} shots={shots} nodes={nodes} editor={editor}
      onChange={value => {setEditor(value); setWrites(count => count + 1);}} onExport={() => {}} /></>;
}
createRoot(document.getElementById('root')!).render(<App />);
