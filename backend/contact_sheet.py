"""Storyboard review sheets rendered from saved project assets."""
import io,math,os
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont,ImageOps
from . import store as s

def render_sheet(project,columns=3,page=1):
    if columns not in (2,3):raise ValueError('宫格列数只能为 2 或 3')
    shots=project['document'].get('shots',[])
    pages=max(1,math.ceil(len(shots)/9))
    if not shots:raise ValueError('请先创建分镜')
    if not 1<=page<=pages:raise ValueError('分镜页码无效')
    selected=shots[(page-1)*9:page*9];nodes={n['id']:n for n in project['document'].get('nodes',[])}
    cell_w,cell_h,gap=480,370,24
    width=columns*cell_w+(columns+1)*gap;height=100+math.ceil(len(selected)/columns)*(cell_h+gap)+gap
    canvas=Image.new('RGB',(width,height),'#15191d');draw=ImageDraw.Draw(canvas)
    font_path=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/'msyh.ttc'
    font=ImageFont.truetype(str(font_path),20) if font_path.exists() else ImageFont.load_default()
    draw.text((gap,25),f'{project["name"]} · 分镜 {page}/{pages}',font=font,fill='white')
    def wrapped(text,max_width):
        lines=['']
        for char in str(text).replace('\n',' '):
            if draw.textlength(lines[-1]+char,font=font)>max_width:lines.append('')
            lines[-1]+=char
        return lines[:3]
    for i,shot in enumerate(selected):
        x=gap+(i%columns)*(cell_w+gap);y=100+(i//columns)*(cell_h+gap)
        draw.rounded_rectangle((x,y,x+cell_w,y+cell_h),radius=8,fill='#252c32')
        node=nodes.get(shot.get('imageNode'),{});aid=node.get('data',{}).get('assetId');asset=None
        if aid:
            with s.db() as c:asset=c.execute("SELECT * FROM assets WHERE id=%s AND project_id=%s AND kind='image'",(aid,project['id'])).fetchone()
        if asset:
            path=(s.ASSETS/asset['path']).resolve()
            if path.is_relative_to(s.ASSETS) and path.is_file():
                with Image.open(path) as image:
                    frame=ImageOps.contain(image.convert('RGB'),(cell_w,240))
                    canvas.paste(frame,(x+(cell_w-frame.width)//2,y+(240-frame.height)//2))
        else:draw.text((x+20,y+100),'等待分镜图',font=font,fill='#9ea7ad')
        label=f'{(page-1)*9+i+1:02d} · {shot.get("duration",0)} 秒'
        if node.get('data',{}).get('stale'):label+=' · 输入已更改'
        draw.text((x+12,y+246),label,font=font,fill='#e4bf79')
        for line_no,line in enumerate(wrapped(shot.get('action') or shot.get('scene',''),cell_w-24)):
            draw.text((x+12,y+276+line_no*27),line,font=font,fill='white')
    buffer=io.BytesIO();canvas.save(buffer,format='PNG');return buffer.getvalue()
