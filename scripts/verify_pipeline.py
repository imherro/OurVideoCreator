"""Verify completed native pipeline outputs without running any models."""
import argparse,json,os,subprocess,sys
from pathlib import Path
parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('directory',type=Path);args=parser.parse_args()
root=args.directory.resolve()
if not (root/'pipeline-result.json').is_file():raise SystemExit('Pipeline result is not available yet')
os.environ['MVC_DATA_DIR']=str(root)
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend.media import probe,ffmpeg_executable
from backend import store
from PIL import Image
result=json.loads((root/'pipeline-result.json').read_text(encoding='utf-8'))
report={}
multi=result.get('acceptance',{}).get('shots',0)>1
stages=[]
if multi:
    for index in range(1,result['acceptance']['shots']+1):stages.extend([('image-'+str(index),'image'),('video-'+str(index),'video')])
else:stages=[('image','image'),('video','video')]
stages.append(('export','export'))
store.init()
with store.db() as db:
    video_assets=[]
    for stage_name,kind in stages:
        if stage_name not in result:raise SystemExit(f'Incomplete pipeline: {stage_name} is missing')
        stage=result[stage_name]
        job=db.execute('SELECT status,input FROM jobs WHERE id=%s',(stage['job_id'],)).fetchone()
        assert job and job['status']=='succeeded',f'{kind}: job is not successful'
        asset=stage['result']['assets'][0]
        row=db.execute('SELECT path,kind FROM assets WHERE id=%s',(asset['id'],)).fetchone()
        assert row and row['kind']==('video' if kind=='export' else kind)
        path=(root/'assets'/row['path']).resolve()
        assert path.is_relative_to(root/'assets') and path.is_file()
        if kind=='image':
            with Image.open(path) as image:
                image.load();assert image.size==(864,480);report[stage_name]={'width':image.width,'height':image.height}
        else:
            info=probe(path);assert info['fps']==24,info
            expected=(1280,720) if kind=='export' else (864,480)
            assert (info['width'],info['height'])==expected,info
            expected_duration=(result['acceptance']['planned_duration'] if multi else 5) if kind=='export' else 124/24
            assert abs(info['duration']-expected_duration)<.15,info
            decoded=subprocess.run([ffmpeg_executable(),'-v','error','-i',str(path),'-f','null','-'],capture_output=True,timeout=120,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            assert decoded.returncode==0,decoded.stderr.decode(errors='replace')
            report[stage_name]={**info,'full_decode':True}
        if kind=='video':
            image_name='image'+stage_name.removeprefix('video')
            assert result[image_name]['result']['assets'][0]['id'] in json.loads(job['input'])['asset_ids']
            video_assets.append(asset['id'])
        if kind=='export':assert [clip['asset_id'] for clip in json.loads(job['input'])['timeline']]==video_assets
(root/'verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))
