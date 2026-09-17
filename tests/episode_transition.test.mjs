import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const component=readFileSync(new URL('../src/app/EpisodeTransition.tsx',import.meta.url),'utf8');
const main=readFileSync(new URL('../src/main.tsx',import.meta.url),'utf8');
const css=readFileSync(new URL('../src/app/episodeTransition.css',import.meta.url),'utf8');

test('episode transition owns one guarded request and always releases its veil',()=>{
  assert.match(component,/if \(active\.current\) return/);
  assert.match(component,/try \{\s*await open\(\);\s*\} finally/);
  assert.doesNotMatch(component,/finally[\s\S]{0,180}if \(!mounted\.current\) return/);
  assert.match(component,/clearTimeout\(timer\.current\)/);
  assert.match(component,/prefers-reduced-motion: reduce/);
  assert.match(component,/returnFocus\.current\.focus\(\{ preventScroll: true \}\)/);
  assert.match(component,/createPortal\([\s\S]*document\.body/);
  assert.match(component,/role="status" aria-live="polite" aria-atomic="true"/);
});

test('top episode selector preserves openProject guards under an inert workspace',()=>{
  const selector=main.slice(main.indexOf('episodeControl={<EpisodeSelector'),main.indexOf('/>}',main.indexOf('episodeControl={<EpisodeSelector'))+3);
  assert.match(main,/inert=\{episodeTransition \? true : undefined\}/);
  assert.match(main,/aria-busy=\{Boolean\(episodeTransition\)\}/);
  assert.match(main,/<EpisodeTransition transition=\{episodeTransition\} \/>/);
  assert.match(selector,/if \(projectId === project\.id\) return/);
  assert.match(selector,/currentEpisodes\.find\(\(item\) => item\.id === projectId\)/);
  assert.match(selector,/switchEpisode\(episodeLabel\(target\), \(\) => openProject\(projectId\)\)/);
  assert.doesNotMatch(selector,/setProject|setDoc|dirty\.current\s*=/);
});

test('episode veil is viewport-wide, visibly dark, animated, and motion-safe',()=>{
  assert.match(css,/position:\s*fixed/);
  assert.match(css,/inset:\s*0/);
  assert.match(css,/z-index:\s*10000/);
  assert.match(css,/background:\s*rgb\(0 0 0 \/ 68%\)/);
  assert.match(css,/is-loading[^}]*episode-veil-in/);
  assert.match(css,/is-revealing[^}]*episode-veil-out/);
  assert.match(css,/@media \(prefers-reduced-motion: reduce\)/);
});
