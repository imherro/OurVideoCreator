import test from 'node:test';
import assert from 'node:assert/strict';
import {shotParameters} from '../src/generationParameters.ts';

test('image size and quality tier are independent published controls', () => {
  const model={rules:{resolution:{type:'string',enum:['2k']},size:{type:'string',enum:['1024x1024','1152x2048']}}};
  assert.deepEqual(shotParameters('image',model,{resolution:'2k',size:'1024x1024'},{},'9:16'),
    {resolution:'2k',size:'1152x2048'});
  model.rules.resolution = {type:'string'};
  assert.deepEqual(shotParameters('image',model,{resolution:'2k',size:'1024x1024'},{},'9:16'),
    {resolution:'2k',size:'1152x2048'});
});

test('incompatible platform image sizes fail instead of silently using square output', () => {
  assert.throws(()=>shotParameters('image',{rules:{size:{type:'string',enum:['1024x1024']}}},
    {size:'1024x1024'},{},'9:16'),/画幅/);
  assert.deepEqual(shotParameters('image',{rules:{size:{type:'string',enum:['1280x720']}}},
    {size:'1280x720'},{},'16:9'),{size:'1280x720'});
});

test('published aspect aliases agree with the project without inventing unlisted parameters', () => {
  assert.deepEqual(shotParameters('image',{rules:{ratio:{type:'string',enum:['1:1','9:16']}}},
    {ratio:'1:1'},{},'9:16'),{ratio:'9:16'});
  assert.deepEqual(shotParameters('image',{rules:{}},{},{},'9:16'),{});
  assert.throws(()=>shotParameters('image',{rules:{ratio:{type:'string',enum:['1:1']}}},
    {ratio:'1:1'},{},'9:16'),/画幅/);
});

test('explicit panorama construction keeps the existing 2:1 approved size', () => {
  assert.deepEqual(shotParameters('image',{rules:{size:{type:'string',enum:['1024x512']}}},
    {size:'1024x512'},{},'2:1'),{size:'1024x512'});
});
