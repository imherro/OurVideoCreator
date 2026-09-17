import test from 'node:test';
import assert from 'node:assert/strict';
import {defaultProjectSetupDraft,projectSetupPayload,validateProjectSetupDraft} from '../src/projectSetup.ts';
import {deriveWorkflowGuide} from '../src/app/workflowGuide.ts';
test('new web projects explicitly select direct; adaptation remains an explicit option',()=>{
 const draft=defaultProjectSetupDraft([]);assert.equal(draft.creationMode,'direct');
 assert.equal(projectSetupPayload(draft).creation_mode,'direct');draft.creationMode='adaptation';
 assert.equal(projectSetupPayload(draft).creation_mode,'adaptation');draft.creationMode='bad';
 assert.ok(validateProjectSetupDraft(draft).some(text=>text.includes('创作起点')));
});
test('direct workflow skips optional planning, never script approval; other episodes do not approve this one',()=>{
 const input={currentProject:{id:'p',episode_no:2},document:{creationMode:'direct',nodes:[],shots:[]},
  scripts:[{projectId:'other',episodeNo:1,script:{status:'approved'}},{projectId:'p',episodeNo:2,script:{status:'draft',metadata:{adaptationLinked:false}}}]};
 let guide=deriveWorkflowGuide(input);assert.equal(guide.recommendedStage,'script');
 assert.equal(guide.stages.source.state,'skipped');assert.equal(guide.stages.storyboard.state,'blocked');
 input.scripts[1].script.status='review';assert.equal(deriveWorkflowGuide(input).stages.script.state,'review');
 input.scripts[1].script.status='approved';guide=deriveWorkflowGuide(input);
 assert.equal(guide.recommendedStage,'storyboard');assert.equal(guide.stages.storyboard.state,'ready');
 input.scripts[1].script.status='stale';assert.equal(deriveWorkflowGuide(input).stages.script.state,'stale');
 input.scripts[1].script.metadata.adaptationLinked=true;
 assert.notEqual(deriveWorkflowGuide(input).stages.adaptation.state,'skipped');
});
