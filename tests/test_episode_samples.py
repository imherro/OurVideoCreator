"""Actual FFmpeg media and real PostgreSQL; no external/provider traffic."""
import subprocess
import json
import uuid

import pytest

from backend import store as s
from tests.test_business_roles import change_roles
from tests.test_episode_deliveries import prepared,confirm
from tests.test_p5_object_transactions import team,admin,clients,clear_auth_rate_limits


@pytest.fixture
def clip(tmp_path):
    path=tmp_path/'editor-original.mp4'
    subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','color=c=red:s=160x120:r=30:d=1',
        '-f','lavfi','-i','sine=frequency=440:duration=1','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(path)],check=True)
    return path


def setup(team):
    path,_,_=prepared(team)
    delivery=team['a'].post(path,json=confirm(team,path)).json()
    return '/api/projects/'+team['pid']+'/samples',delivery['id']


def upload(team,path,delivery,clip,*,client=None,values=None):
    who=client or team['b'];state=who.get(path).json()
    data={'delivery_id':delivery,'upload_id':str(uuid.uuid4()),'previous_id':state['latest_id'],
        'staffing_revision':str(state['staffing_revision'])}
    data.update(values or {})
    with clip.open('rb') as file:return who.post(path,data=data,files={'file':(clip.name,file,'video/mp4')})


def test_editor_upload_real_clip_retains_original_and_range_playable_review(team,clip):
    path,delivery=setup(team)
    assert team['b'].get(path).json()['can_upload']
    assert not team['a'].get(path).json()['can_upload']
    assert upload(team,path,delivery,clip,client=team['a']).status_code==403
    assert upload(team,path,delivery,clip,client=team['admin']).status_code==403
    response=upload(team,path,delivery,clip);assert response.status_code==201,response.text
    sample=response.json();assert sample['version']==1
    metadata=sample['metadata'];assert metadata['source']['fps']=='30/1'
    assert metadata['review_fps']==30 and metadata['frame_count']==30
    assert metadata['review']['has_audio']
    assert team['admin'].get(path+'/'+sample['id']+'/original').content==clip.read_bytes()
    media=team['admin'].get(path+'/'+sample['id']+'/review')
    assert media.status_code==200 and media.headers['content-type']=='video/mp4'
    partial=team['admin'].get(path+'/'+sample['id']+'/review',headers={'Range':'bytes=0-31'})
    assert partial.status_code==206 and partial.content==media.content[:32]
    assert 'original_path' not in sample and 'review_path' not in sample


def test_new_versions_never_replace_old_and_retry_does_not_duplicate(team,clip):
    path,delivery=setup(team);request_id=str(uuid.uuid4())
    one=upload(team,path,delivery,clip,values={'upload_id':request_id})
    assert one.status_code==201,one.text
    one=one.json();original=team['b'].get(path+'/'+one['id']+'/original').content
    repeated=upload(team,path,delivery,clip,values={'upload_id':request_id,'previous_id':''})
    assert repeated.status_code==201 and repeated.json()['id']==one['id']
    assert upload(team,path,delivery,clip,values={'previous_id':''}).status_code==409
    two=upload(team,path,delivery,clip);assert two.status_code==201,two.text
    assert two.json()['version']==2
    assert team['b'].get(path+'/'+one['id']+'/original').content==original
    assert [row['version'] for row in team['admin'].get(path).json()['items']]==[2,1]


def test_revocation_during_conversion_cannot_publish_sample(team,clip,monkeypatch):
    from backend import episode_samples as samples
    path,delivery=setup(team);original=samples.normalize
    def revoke(source,target):
        result=original(source,target)
        change_roles(team,team['bid'],[])
        return result
    monkeypatch.setattr(samples,'normalize',revoke)
    response=upload(team,path,delivery,clip)
    assert response.status_code==403,response.text
    assert team['admin'].get(path).json()['items']==[]


def test_wrong_delivery_cross_project_and_invalid_video_fail_closed(team,clip,tmp_path):
    path,delivery=setup(team)
    assert upload(team,path,'not-this-episode',clip).status_code==422
    invalid=tmp_path/'invalid.mp4';invalid.write_bytes(b'not a video')
    assert upload(team,path,delivery,invalid).status_code==400
    sample=upload(team,path,delivery,clip).json()
    other=team['admin'].post('/api/projects',json={'name':'other samples','five_role_workflow':True}).json()
    assert team['admin'].get('/api/projects/'+other['id']+'/samples/'+sample['id']+'/review').status_code==404
    assert team['admin'].get(path+'/'+sample['id']+'/unknown').status_code==404
    with s.db() as c:
        c.execute('DELETE FROM production_members WHERE production_id=%s AND user_id=%s',(team['production'],team['bid']))
    assert team['b'].get(path+'/'+sample['id']+'/original').status_code in (403,404)


def test_variable_frame_rate_gets_fixed_review_timeline(tmp_path):
    from backend.sample_media import normalize
    source=tmp_path/'vfr.mp4';dest=tmp_path/'review.mp4'
    subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i','testsrc2=size=160x120:rate=30:duration=1',
        '-vf',r'select=not(mod(n\,3))+not(mod(n\,7))','-fps_mode','vfr','-c:v','libx264',str(source)],check=True)
    result=normalize(source,dest)
    assert result['source']['fps']!='25/1'
    assert result['review']['fps']=='25/1' and result['frame_count']>1
    assert result['review']['start_time']==0
    frames=json.loads(subprocess.run(['ffprobe','-v','error','-select_streams','v:0','-show_frames',
        '-show_entries','frame=best_effort_timestamp_time','-of','json',str(dest)],capture_output=True,text=True,check=True).stdout)['frames']
    timestamps=[float(frame['best_effort_timestamp_time']) for frame in frames]
    assert len(timestamps)==result['frame_count']
    assert all(abs((b-a)-0.04)<0.00001 for a,b in zip(timestamps,timestamps[1:]))


@pytest.mark.parametrize('rate,count', [('30000/1001',30),('24000/1001',24)])
def test_fractional_frame_rates_preserve_exact_frame_clock(tmp_path,rate,count):
    from backend.sample_media import normalize
    from fractions import Fraction
    source=tmp_path/'fractional.mp4';dest=tmp_path/'fractional-review.mp4'
    subprocess.run(['ffmpeg','-nostdin','-v','error','-f','lavfi','-i',
        f'testsrc2=size=160x120:rate={rate}','-frames:v',str(count),'-c:v','libx264',str(source)],check=True)
    result=normalize(source,dest);fps=Fraction(rate)
    assert (result['fps_num'],result['fps_den'])==(fps.numerator,fps.denominator)
    assert result['frame_count']==count and result['review']['start_time']==0
    frames=json.loads(subprocess.run(['ffprobe','-v','error','-select_streams','v:0','-show_frames',
        '-show_entries','frame=best_effort_timestamp_time','-of','json',str(dest)],capture_output=True,text=True,check=True).stdout)['frames']
    assert len(frames)==count
    for index,frame in enumerate(frames):
        assert abs(float(frame['best_effort_timestamp_time'])-float(index/fps))<0.000002
