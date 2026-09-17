// Compatibility fixes for the locked Twick build. Fail closed on upgrades:
// preflight every artifact before changing any, including already-patched ones.
import {readFileSync, writeFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import {resolve, dirname} from 'node:path';

export function patchedTwick(source, kind) {
  const once = (before, after) => {
    if (source.includes(after)) return;
    if (source.split(before).length !== 2) throw new Error(`Unsupported Twick ${kind} build: ${before}`);
    source = source.replace(before, after);
  };
  if (kind === 'timeline') {
    once('await element.updateVideoMeta();',
      'if (!(Number(element.getMediaDuration()) > 0)) await element.updateVideoMeta();');
  } else {
    const context = kind === 'index.js' ? 'timeline.useTimelineContext' : 'useTimelineContext';
    once(`const { changeLog } = ${context}();`, `const { changeLog, totalDuration } = ${context}();`);
    once('if (durationRef.current && time2 >= durationRef.current) {',
      'const playbackDuration = totalDuration || durationRef.current;\n    if (playbackDuration && time2 >= playbackDuration) {');
    once('transform: "translateX(-50%)",\n                      color: "rgba(255,255,255,0.7)",',
      'transform: t2 >= duration - epsilon ? "translateX(-100%)" : "translateX(-50%)",\n                      color: "rgba(255,255,255,0.7)",');
  }
  return source;
}

export function patchTwick(root = resolve(dirname(fileURLToPath(import.meta.url)), '..')) {
  const changes = ['video-editor', 'timeline'].flatMap(pkg => ['index.mjs', 'index.js'].map(file => {
    const path = resolve(root, 'node_modules', '@twick', pkg, 'dist', file);
    const before = readFileSync(path, 'utf8');
    return {path, before, after: patchedTwick(before, pkg === 'timeline' ? 'timeline' : file)};
  }));
  for (const {path, before, after} of changes) if (before !== after) {
    writeFileSync(path, after);
    console.log(`Patched ${path}`);
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) patchTwick();
