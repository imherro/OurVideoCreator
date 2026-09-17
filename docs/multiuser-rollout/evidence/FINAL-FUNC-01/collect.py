"""Export the bounded actual UI trace and necessary, synthetic final evidence.

Usage: python collect.py SESSION_JSONL LOCAL_EVIDENCE FIXTURE_FOLDER END_UTC
Does not operate on the application or database. Raw local records are retained.
"""
import json
from pathlib import Path
import re
import subprocess
import sys

session, local, fixture = map(Path, sys.argv[1:4])
end = sys.argv[4]
out = Path(__file__).resolve().parent
start = '2026-09-17T02:44:45'
sha = '7a54da479808b7f05d3fd78ff48d29b167fe20a3'


def redact(text):
    text = re.sub(r'P5-browser-[\w!-]+', '[REDACTED_TEST_PASSWORD]', text)
    text = re.sub(r'\+?861390000000[1-4]', '[REDACTED_TEST_LOGIN]', text)
    text = re.sub(r'(?<!\d)1390000000[1-4](?!\d)', '[REDACTED_TEST_LOGIN]', text)
    return text.replace('C:\\Users\\kunpeng', '<USER>').replace('C:\\\\Users\\\\kunpeng', '<USER>')


calls, rows = set(), []
with session.open(encoding='utf-8') as stream:
    for line in stream:
        item = json.loads(line)
        if item.get('type') != 'response_item' or not start <= item.get('timestamp', '') < end:
            continue
        payload = item['payload']
        if payload.get('type') == 'function_call':
            args = payload.get('arguments', '')
            if payload.get('name') != 'js' or not re.search(r'\bfinal(?:[ABM]|Fixed|DeleteDialog)\b', args):
                continue
            if 'handoffTab' in args:
                continue
            calls.add(payload['call_id'])
        elif payload.get('type') != 'function_call_output' or payload.get('call_id') not in calls:
            continue
        rows.append({'utc': item['timestamp'], 'payload': payload})
trace = {'source': 'Actual browser tool calls and returned AX/DOM, not reconstructed assertions',
         'runtime_sha': sha, 'utc_start': start, 'utc_end_exclusive': end,
         'suffix_runtime_sha': '018a6049bde4e47226ff41ff3b289d3496f75446',
         'suffix_scope': 'finalFixed is an additional Web on port 5459, same isolated data; no new Worker/provider jobs',
         'redaction': 'Synthetic login inputs and local home prefix only; no cookies/HAR exported',
         'calls': len(calls), 'entries': rows}
(out/'browser-tools.json').write_text(redact(json.dumps(trace, ensure_ascii=False, indent=2))+'\n', encoding='utf-8')
database = json.loads((local/'browser-db.json').read_text(encoding='utf-8'))
database['fake_get_requests'] = [json.loads(path.read_text(encoding='utf-8')) for path in sorted(fixture.glob('fake-get-*.json'))]
(out/'browser-db.json').write_text(redact(json.dumps(database, ensure_ascii=False, indent=2))+'\n', encoding='utf-8')
mp4 = fixture/'data/assets/asset-55170aa2b376478b9836d8570c431118.mp4'
commands = [
    ['ffprobe', '-v', 'error', '-show_entries', 'stream=codec_name,codec_type,width,height,r_frame_rate,nb_frames:format=duration,size', '-of', 'json', str(mp4)],
    ['ffmpeg', '-v', 'error', '-i', str(mp4), '-f', 'null', '-'],
]
media = []
for command in commands:
    result = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', timeout=60)
    media.append({'command': command, 'exit_code': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr})
(out/'media-check.json').write_text(redact(json.dumps(media, ensure_ascii=False, indent=2))+'\n', encoding='utf-8')
for name in ('targeted.txt', 'targeted-018a604.txt'):
    text = (local/name).read_text(encoding='utf-8-sig')
    (out/name).write_text(redact(text).replace('\r\n', '\n').rstrip()+'\n', encoding='utf-8')
print(json.dumps({'browser_calls': len(calls), 'media_exit_codes': [item['exit_code'] for item in media]}))
