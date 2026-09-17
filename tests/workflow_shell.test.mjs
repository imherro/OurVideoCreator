import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {
  WORKFLOW_STAGES,
  primaryWorkflowStages,
  defaultViewForStage,
  parseWorkflowStage,
  workflowStageScope,
  workflowStageUrl,
} from '../src/app/workflow.ts';
import {planGlobalPanelAction} from '../src/app/globalNavigation.ts';

test('workflow specifications are read-only in the shared header without duplicating the view toolbar', () => {
  const source = readFileSync(new URL('../src/main.tsx', import.meta.url), 'utf8');
  const header = source.slice(source.indexOf('<WorkflowStageNav'), source.indexOf('<GlobalNav'));
  assert.match(header, /className="workflow-header-meta"/);
  assert.match(header, /<span>\{doc.ratio\}<\/span>/);
  assert.match(header, /<span>\{doc.style\}<\/span>/);
  assert.match(header, /<span>\{doc.duration\} 秒<\/span>/);
  assert.doesNotMatch(source, /className="view-meta"/);
  assert.match(header, /对象协作/);
  assert.match(header, /saveCurrentView\(\)/);
});

test('current production header is compact without hiding collaboration controls', () => {
  const source = readFileSync(new URL('../src/main.tsx', import.meta.url), 'utf8');
  const start = source.indexOf('className={panel === "projectInfo" ? "project-menu active" : "project-menu"}');
  const end = source.indexOf('<WorkflowStageNav', start);
  const projectMenu = source.slice(start, end);
  const topbar = source.slice(source.indexOf('<header className="topbar">'), source.indexOf('<GlobalNav'));

  assert.match(projectMenu, /aria-label=\{`查看和修改项目：\$\{currentProduction\?\.name \|\| project\.name\}`\}/);
  assert.match(projectMenu, />\s*\{currentProduction\?\.name \|\| project\.name\}\s*<\/button>/);
  assert.match(projectMenu, /setProjectSettingsTab\("production"\)/);
  assert.doesNotMatch(projectMenu, /FolderOpen|ChevronDown|项目 ·/);
  assert.match(topbar, /className="team-switcher"/);
  assert.match(topbar, /className="project-settings-button"/);
  assert.match(topbar, /className=\{"save-status "/);
});

test('workflow shell exposes the production stages in order',()=>{
  assert.deepEqual(WORKFLOW_STAGES.map(stage=>stage.label),[
    '概览','原著','改编策划','剧本','分镜规划','塑角造景','分镜图','视频','剪辑','高级画布',
  ]);
});

test('direct creation keeps adaptation optional without deleting routes or bypassing review',()=>{
  assert.deepEqual(primaryWorkflowStages(true).map(stage=>stage.id),['overview','script','storyboard','art','images','video','editor','canvas']);
  assert.deepEqual(primaryWorkflowStages(false),WORKFLOW_STAGES);
  assert.equal(parseWorkflowStage('?stage=source'),'source');
  assert.equal(parseWorkflowStage('?stage=adaptation'),'adaptation');
  const nav=readFileSync(new URL('../src/app/WorkflowStageNav.tsx',import.meta.url),'utf8');
  assert.match(nav,/原著改编（可选）/);
  assert.match(nav,/<option value="source">原著资料/);
  assert.match(nav,/<option value="adaptation">改编策划/);
});

test('workflow stage URL survives refresh and rejects unknown stages',()=>{
  assert.equal(parseWorkflowStage('?stage=storyboard'),'storyboard');
  assert.equal(parseWorkflowStage('?stage=unknown'),'overview');
  assert.equal(parseWorkflowStage(''),'overview');
  assert.equal(
    workflowStageUrl('http://localhost:7868/?project=x#focus','editor'),
    '/?project=x&stage=editor#focus',
  );
});

test('workflow stages mount the existing workspace views',()=>{
  assert.equal(defaultViewForStage('overview'),'stage');
  assert.equal(defaultViewForStage('art'),'stage');
  assert.equal(defaultViewForStage('storyboard'),'shots');
  assert.equal(defaultViewForStage('images'),'grid');
  assert.equal(defaultViewForStage('editor'),'editor');
  assert.equal(defaultViewForStage('canvas'),'canvas');
});

test('workflow stages separate production planning from episode making',()=>{
  for (const stage of ['overview','source','adaptation','script']) assert.equal(workflowStageScope(stage),'production');
  for (const stage of ['storyboard','art','images','video','editor','canvas']) assert.equal(workflowStageScope(stage),'episode');
});

test('global trash navigation requests fresh server state before display',()=>{
  assert.deepEqual(planGlobalPanelAction(null,'trash'),{
    panel:'trash',
    loadTrash:true,
  });
  assert.deepEqual(planGlobalPanelAction('trash','trash'),{
    panel:null,
    loadTrash:false,
  });
  assert.deepEqual(planGlobalPanelAction(null,'assets'),{
    panel:'assets',
    loadTrash:false,
  });
});
