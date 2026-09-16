"""Real FFmpeg export integration; not a mocked renderer."""
import io
import subprocess
from pathlib import Path
from PIL import Image
from backend import store as s
from backend.media import ffmpeg_executable
from backend.worker import Worker,register
import time

def test_real_export_two_stills_and_decode():
    s.init()
    import pytest
    try: ffmpeg=ffmpeg_executable()
    except ValueError: pytest.skip('FFmpeg not installed')
    s.set_setting('ffmpeg',ffmpeg)
    pid=s.uid();jid=s.uid();now=time.time()
    with s.db() as c:
        c.execute('INSERT INTO projects(id,name,revision,document,created,updated) VALUES(%s,%s,1,%s,%s,%s)',(pid,'Export integration','{}',now,now))
        c.execute('INSERT INTO jobs(id,submission_id,project_id,node_id,kind,status,input,created,updated) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)',(jid,jid,pid,'export','export','running','{}',now,now))
    job={'id':jid,'project_id':pid,'node_id':'export','kind':'export','input':{}}
    timeline=[]
    for color in ('red','blue'):
        image=s.DATA/(s.uid()+'.png');Image.new('RGB',(64,64),color).save(image)
        asset=register(job,image,'frame.png');image.unlink()
        timeline.append({'asset_id':asset['id'],'duration':.5,'start':0})
    job['input']={'timeline':timeline,'resolution':'128x128'}
    result=Worker().export(job)
    assert result['assets'][0]['kind']=='video'
    with s.db() as c:
        file=s.ASSETS/c.execute('SELECT path FROM assets WHERE id=%s',(result['assets'][0]['id'],)).fetchone()['path']
    assert file.stat().st_size>500
    frames=[]
    for offset in ('0.1','0.7'):
        response=subprocess.run([ffmpeg,'-v','error','-ss',offset,'-i',str(file),'-frames:v','1','-vf','scale=1:1','-f','rawvideo','-pix_fmt','rgb24','-'],capture_output=True,timeout=30)
        assert response.returncode==0,response.stderr
        assert len(response.stdout)==3
        frames.append(tuple(response.stdout))
    assert frames[0][0]>frames[0][2]+150,frames
    assert frames[1][2]>frames[1][0]+150,frames

def test_export_original_audio_music_subtitle_and_mute():
    import array,math
    from backend.media import ffmpeg_executable,probe
    s.init();ffmpeg=ffmpeg_executable()
    pid=s.uid();now=time.time()
    with s.db() as c:c.execute('INSERT INTO projects(id,name,revision,document,created,updated) VALUES(%s,%s,1,%s,%s,%s)',(pid,'Sound and subtitle','{}',now,now))
    def job():
        jid=s.uid()
        with s.db() as c:c.execute('INSERT INTO jobs(id,submission_id,project_id,node_id,kind,status,input,created,updated) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)',(jid,jid,pid,'export','export','running','{}',now,now))
        return {'id':jid,'project_id':pid,'node_id':'export','kind':'export','input':{}}
    source=s.DATA/(s.uid()+'.mp4');music=s.DATA/(s.uid()+'.wav');base=job()
    for args in (
        ['-f','lavfi','-i','color=c=blue:s=320x180:r=24:d=1','-f','lavfi','-i','sine=frequency=440:duration=1','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(source)],
        ['-f','lavfi','-i','sine=frequency=880:duration=0.3',str(music)],
    ):
        response=subprocess.run([ffmpeg,'-y','-v','error',*args],capture_output=True,timeout=30)
        assert response.returncode==0,response.stderr
    video=register(base,source);audio=register(base,music);source.unlink();music.unlink()
    sid=s.uid();subtitle=s.ASSETS/(sid+'.srt')
    subtitle.write_text('1\n00:00:00,000 --> 00:00:01,000\nTEST\n',encoding='utf-8')
    with s.db() as c:c.execute('INSERT INTO assets(id,project_id,name,kind,path,mime,metadata,created) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',(sid,pid,'test.srt','subtitle',subtitle.name,'application/x-subrip','{}',now))
    amplitudes=[]
    for volume in (1,0):
        current=job();current['input']={'timeline':[{'asset_id':video['id'],'duration':1,'volume':volume}], 'resolution':'320x180','audio_id':audio['id'],'music_volume':.5,'subtitle_id':sid,'transition':'fade'}
        result=Worker().export(current)
        with s.db() as c:path=s.ASSETS/c.execute('SELECT path FROM assets WHERE id=%s',(result['assets'][0]['id'],)).fetchone()['path']
        info=probe(path);assert info['has_audio'] and .95<info['duration']<1.2
        pcm=subprocess.run([ffmpeg,'-v','error','-ss','0.2','-i',str(path),'-t','0.6','-vn','-ac','1','-ar','8000','-f','f32le','-'],capture_output=True,timeout=30)
        assert pcm.returncode==0
        samples=array.array('f',pcm.stdout)
        def amplitude(hz):
            real=sum(x*math.cos(2*math.pi*hz*i/8000) for i,x in enumerate(samples))
            imag=sum(x*math.sin(2*math.pi*hz*i/8000) for i,x in enumerate(samples))
            return math.hypot(real,imag)*2/len(samples)
        amplitudes.append((amplitude(440),amplitude(880)))
        frame=subprocess.run([ffmpeg,'-v','error','-ss','0.5','-i',str(path),'-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','-'],capture_output=True,timeout=30)
        assert frame.returncode==0
        # A blue source has no white pixels; the burned subtitle must be visible.
        assert sum(min(frame.stdout[i:i+3])>180 for i in range(0,len(frame.stdout),3))>30
    assert amplitudes[0][0]>.02,amplitudes
    assert amplitudes[1][0]<amplitudes[0][0]/10,amplitudes
    assert all(a[1]>.01 for a in amplitudes),amplitudes

def test_editor_export_composites_tracks_text_and_audio():
    import array,math
    from backend.media import ffmpeg_executable,probe
    s.init();ffmpeg=ffmpeg_executable()
    pid=s.uid();jid=s.uid();now=time.time()
    with s.db() as c:
        c.execute('INSERT INTO projects(id,name,revision,document,created,updated) VALUES(%s,%s,1,%s,%s,%s)',(pid,'Editor export','{}',now,now))
        c.execute('INSERT INTO jobs(id,submission_id,project_id,node_id,kind,status,input,created,updated) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)',(jid,jid,pid,'export','export','running','{}',now,now))
    job={'id':jid,'project_id':pid,'node_id':'export','kind':'export','input':{}}
    source=s.DATA/(s.uid()+'.mp4');music=s.DATA/(s.uid()+'.wav');overlay=s.DATA/(s.uid()+'.png')
    commands=(
        ['-f','lavfi','-i','color=c=blue:s=160x90:r=24:d=1','-f','lavfi','-i','sine=frequency=440:duration=1','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(source)],
        ['-f','lavfi','-i','sine=frequency=880:duration=1',str(music)],
    )
    for args in commands:
        response=subprocess.run([ffmpeg,'-y','-v','error',*args],capture_output=True,timeout=30)
        assert response.returncode==0,response.stderr
    Image.new('RGB',(40,30),'red').save(overlay)
    video=register(job,source);audio=register(job,music);image=register(job,overlay)
    source.unlink();music.unlink();overlay.unlink()
    project={'version':2,'backgroundColor':'#000000','tracks':[
        {'id':'v1','name':'V1','type':'video','elements':[{
            'id':'video','type':'video','s':0,'e':1,'props':{'srcAssetId':video['id'],'time':0,'volume':.4,'playbackRate':1},
            'metadata':{'assetId':video['id']},'frame':{'x':0,'y':0,'size':[160,90]},'objectFit':'fill'
        }]},
        {'id':'v2','name':'V2','type':'video','elements':[{
            'id':'overlay','type':'image','s':.2,'e':.8,'props':{'srcAssetId':image['id'],'opacity':1},
            'metadata':{'assetId':image['id'],'mvc':{'fade':{'videoIn':.05,'videoOut':.05}}},
            'frame':{'x':0,'y':0,'size':[40,30]},'objectFit':'fill'
        }]},
        {'id':'a2','name':'A2','type':'audio','elements':[{
            'id':'music','type':'audio','s':0,'e':1,'props':{'srcAssetId':audio['id'],'time':0,'volume':.3,'playbackRate':1},
            'metadata':{'assetId':audio['id'],'mvc':{'fade':{'audioIn':.05,'audioOut':.05},'volumeKeyframes':[{'time':0,'value':.2},{'time':.5,'value':1},{'time':1,'value':.2}]}},'mediaDuration':1
        }]},
        {'id':'t1','name':'T1','type':'text','elements':[{
            'id':'title','type':'text','s':0,'e':1,'props':{'text':'TEST','x':55,'y':55,'fontSize':20,'fill':'#ffffff','stroke':'#000000','fontWeight':700}
        }]},
    ]}
    job['input']={'editor_timeline':project,'render_mode':'editor','resolution':'160x90'}
    result=Worker().export(job)
    assert result['render']=={'mode':'editor','duration':1.0,'visual_count':2,'audio_count':2,'text_count':1}
    with s.db() as c:path=s.ASSETS/c.execute('SELECT path FROM assets WHERE id=%s',(result['assets'][0]['id'],)).fetchone()['path']
    info=probe(path);assert info['has_audio'] and .95<info['duration']<1.2
    frame=subprocess.run([ffmpeg,'-v','error','-ss','0.5','-i',str(path),'-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','-'],capture_output=True,timeout=30)
    assert frame.returncode==0,frame.stderr
    def pixel(x,y):
        offset=(y*160+x)*3
        return tuple(frame.stdout[offset:offset+3])
    assert pixel(10,10)[0]>pixel(10,10)[2]+120
    assert pixel(145,75)[2]>pixel(145,75)[0]+120
    assert sum(min(frame.stdout[i:i+3])>180 for i in range(0,len(frame.stdout),3))>15
    automation=[]
    for offset in (.08,.5,.9):
        pcm=subprocess.run([ffmpeg,'-v','error','-ss',f'{offset:.2f}','-i',str(path),'-t','0.08','-vn','-ac','1','-ar','8000','-f','f32le','-'],capture_output=True,timeout=30)
        assert pcm.returncode==0,pcm.stderr
        samples=array.array('f',pcm.stdout)
        real=sum(x*math.cos(2*math.pi*880*i/8000) for i,x in enumerate(samples))
        imag=sum(x*math.sin(2*math.pi*880*i/8000) for i,x in enumerate(samples))
        automation.append(math.hypot(real,imag)*2/len(samples))
    assert automation[1]>automation[0]*2,automation
    assert automation[1]>automation[2]*2,automation

def test_editor_export_crossfades_adjacent_visuals():
    from backend.media import ffmpeg_executable
    s.init();ffmpeg=ffmpeg_executable()
    pid=s.uid();jid=s.uid();now=time.time()
    with s.db() as c:
        c.execute('INSERT INTO projects(id,name,revision,document,created,updated) VALUES(%s,%s,1,%s,%s,%s)',(pid,'Crossfade','{}',now,now))
        c.execute('INSERT INTO jobs(id,submission_id,project_id,node_id,kind,status,input,created,updated) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)',(jid,jid,pid,'export','export','running','{}',now,now))
    job={'id':jid,'project_id':pid,'node_id':'export','kind':'export','input':{}}
    assets=[]
    for color in ('red','blue'):
        source=s.DATA/(s.uid()+'.png');Image.new('RGB',(64,64),color).save(source)
        assets.append(register(job,source));source.unlink()
    project={'version':2,'tracks':[
        {'id':'v1','name':'V1','type':'video','elements':[{
            'id':'red','type':'image','name':'red','s':0,'e':1,
            'props':{'srcAssetId':assets[0]['id'],'transition':{'toElementId':'blue','kind':'crossfade','duration':.4}},
            'metadata':{'assetId':assets[0]['id']},'frame':{'x':0,'y':0,'size':[64,64]},'objectFit':'fill',
            'transition':{'toElementId':'blue','kind':'crossfade','duration':.4}
        }]},
        {'id':'v2','name':'V2','type':'video','elements':[{
            'id':'blue','type':'image','name':'blue','s':1,'e':2,'props':{'srcAssetId':assets[1]['id']},
            'metadata':{'assetId':assets[1]['id']},'frame':{'x':0,'y':0,'size':[64,64]},'objectFit':'fill'
        }]},
    ]}
    job['input']={'editor_timeline':project,'resolution':'64x64'}
    result=Worker().export(job)
    with s.db() as c:path=s.ASSETS/c.execute('SELECT path FROM assets WHERE id=%s',(result['assets'][0]['id'],)).fetchone()['path']
    colors=[]
    for offset in ('0.2','0.8','1.3'):
        frame=subprocess.run([ffmpeg,'-v','error','-ss',offset,'-i',str(path),'-frames:v','1','-vf','scale=1:1','-f','rawvideo','-pix_fmt','rgb24','-'],capture_output=True,timeout=30)
        assert frame.returncode==0,frame.stderr
        colors.append(tuple(frame.stdout))
    assert colors[0][0]>colors[0][2]+120,colors
    assert colors[1][0]>30 and colors[1][2]>30,colors
    assert colors[2][2]>colors[2][0]+120,colors


def test_editor_export_honors_source_trim_rate_filter_and_caption():
    from backend.media import ffmpeg_executable,probe
    s.init();ffmpeg=ffmpeg_executable()
    pid=s.uid();jid=s.uid();now=time.time()
    with s.db() as c:
        c.execute('INSERT INTO projects(id,name,revision,document,created,updated) VALUES(%s,%s,1,%s,%s,%s)',(pid,'Trim filter caption','{}',now,now))
        c.execute('INSERT INTO jobs(id,submission_id,project_id,node_id,kind,status,input,created,updated) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)',(jid,jid,pid,'export','export','running','{}',now,now))
    job={'id':jid,'project_id':pid,'node_id':'export','kind':'export','input':{}}
    source=s.DATA/(s.uid()+'.mp4')
    command=[ffmpeg,'-y','-v','error',
        '-f','lavfi','-i','color=c=red:s=128x128:r=24:d=1',
        '-f','lavfi','-i','color=c=blue:s=128x128:r=24:d=1',
        '-filter_complex','[0:v][1:v]concat=n=2:v=1:a=0[v]',
        '-map','[v]','-c:v','libx264','-pix_fmt','yuv420p',str(source)]
    response=subprocess.run(command,capture_output=True,timeout=30)
    assert response.returncode==0,response.stderr
    asset=register(job,source);source.unlink()
    project={'version':2,'tracks':[
        {'id':'v1','name':'V1','type':'video','elements':[{
            'id':'video','type':'video','s':0,'e':.5,
            'props':{'srcAssetId':asset['id'],'time':1,'playbackRate':2,'volume':0,'mediaFilter':'blackWhite'},
            'metadata':{'assetId':asset['id'],'mvc':{'fade':{'videoIn':.05,'videoOut':.05}}},
            'frame':{'x':0,'y':0,'size':[128,128]},'objectFit':'fill','mediaDuration':2,
        }]},
        {'id':'captions','name':'字幕','type':'caption','props':{
            'font':{'family':'Arial','size':24,'weight':700},
            'colors':{'text':'#ffffff','outlineColor':'#000000'},
        },'elements':[{'id':'caption','type':'caption','s':0,'e':.5,'t':'CAPTION','props':{}}]},
    ]}
    job['input']={'editor_timeline':project,'resolution':'128x128'}
    result=Worker().export(job)
    with s.db() as c:path=s.ASSETS/c.execute('SELECT path FROM assets WHERE id=%s',(result['assets'][0]['id'],)).fetchone()['path']
    info=probe(path);assert .45<info['duration']<.65
    frame=subprocess.run([ffmpeg,'-v','error','-ss','0.25','-i',str(path),'-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','-'],capture_output=True,timeout=30)
    assert frame.returncode==0,frame.stderr
    background=tuple(frame.stdout[(15*128+15)*3:(15*128+15)*3+3])
    assert max(background)-min(background)<12,background
    assert sum(min(frame.stdout[i:i+3])>190 for i in range(0,len(frame.stdout),3))>20
