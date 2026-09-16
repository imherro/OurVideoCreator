"""Extract selected real CUA calls/results; never export the whole session.

Evidence-only utility. It removes synthetic secrets and generic tool docs, keeps
UTC/call IDs/actions/AX/CDP results and errors. No page requests are replayed.
"""
import argparse
import ast
import hashlib
import json
import re
from pathlib import Path

parser=argparse.ArgumentParser()
parser.add_argument('session',type=Path)
parser.add_argument('--since',required=True)
parser.add_argument('--until',required=True)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
selected={}; records=[]
for line in args.session.open(encoding='utf-8'):
    entry=json.loads(line)
    if not args.since<=entry.get('timestamp','')<=args.until or entry.get('type')!='response_item': continue
    p=entry['payload']; kind=p.get('type'); call_id=p.get('call_id')
    if kind=='function_call' and p.get('name')=='js':
        arguments=json.loads(p['arguments'])
        code=arguments.get('code','')
        if not re.search(r'\bp4(?:tab|raw|cdp|collect|final)',code): continue
        if 'p4review' in code: continue
        selected[call_id]=True
        records.append({'utc':entry['timestamp'],'call_id':call_id,'type':'tool_call','tool':'mcp__cua_repl.js',
                        'title':arguments.get('title'),'code':code})
    elif kind=='function_call_output' and call_id in selected:
        output=p.get('output',[])
        text='\n'.join(item.get('text','') for item in output if item.get('type') in ('text','input_text')) if isinstance(output,list) else str(output)
        # Documentation is not browser evidence. Keep the actual tab state.
        if text.startswith('# Other Browser APIs') and 'Browser tab: 2' in text:
            text=text[text.index('Browser tab: 2'):]
        records.append({'utc':entry['timestamp'],'call_id':call_id,'type':'tool_result','text':text})
raw=json.dumps(records,ensure_ascii=False,indent=2)
repo=Path(__file__).resolve().parents[4]
for filename, constant in [('p4_browser_harness.py','CANARY'),('auth_helpers.py','ADMIN_PASSWORD')]:
    tree=ast.parse((repo/'tests'/filename).read_text(encoding='utf-8'))
    value=next(ast.literal_eval(node.value) for node in tree.body
               if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id==constant for t in node.targets))
    raw=raw.replace(value,'[SYNTHETIC_SECRET_REDACTED]')
assert 'chatgpt.com/c/' not in raw, 'Reviewer conversation must not enter app evidence'
args.output.write_text(raw+'\n',encoding='utf-8')
print(json.dumps({'records':len(records),'calls':len(selected),'output':args.output.name,
    'sha256':hashlib.sha256(args.output.read_bytes()).hexdigest(),
    'redaction':'Exact synthetic key/password literals; generic docs omitted where noted; no auth headers or cookie values were printed'}))
