import io,time
from PIL import Image
import pytest
from backend import store as s
from backend.contact_sheet import render_sheet

def test_sheet_uses_project_owned_images_and_paginates():
    s.init();pid=s.uid();aid=s.uid();now=time.time();path=s.ASSETS/(aid+'.png')
    Image.new('RGB',(64,64),'red').save(path)
    with s.db() as c:
        c.execute('INSERT INTO projects(id,name,revision,document,created,updated) VALUES(%s,%s,1,%s,%s,%s)',(pid,'分镜','{}',now,now))
        c.execute('INSERT INTO assets(id,project_id,name,kind,path,mime,metadata,created) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)',(aid,pid,'红色','image',path.name,'image/png','{}',now))
    project={'id':pid,'name':'测试','document':{'nodes':[{'id':'n','data':{'assetId':aid}}],'shots':[{'id':str(i),'imageNode':'n','duration':5,'action':'橘猫发现机器人'} for i in range(10)]}}
    image=Image.open(io.BytesIO(render_sheet(project,3,2)))
    assert image.size==(1536,518)
    assert image.getpixel((264,220))==(255,0,0)
    project['id']='other-project'
    other=Image.open(io.BytesIO(render_sheet(project,3,2)))
    assert other.getpixel((264,220))!=(255,0,0)
    with pytest.raises(ValueError):render_sheet(project,3,3)
