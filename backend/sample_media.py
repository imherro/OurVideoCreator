"""Frame-addressable review copies: retain CFR rates, normalize VFR explicitly."""
import json
from pathlib import Path
import shutil
import subprocess
from fractions import Fraction

from .media import ffmpeg_executable

FPS=25
FLAGS=getattr(subprocess,'CREATE_NO_WINDOW',0)


def inspect(path):
    executable=ffmpeg_executable()
    sibling=Path(executable).with_name('ffprobe.exe' if str(executable).endswith('.exe') else 'ffprobe')
    command=str(sibling) if sibling.is_file() else shutil.which('ffprobe')
    if not command:raise ValueError('样片审阅需要安装 FFprobe；未保存新版本')
    result=subprocess.run([command,'-v','error','-protocol_whitelist','file,pipe',
        '-show_streams','-show_format','-of','json',str(path)],capture_output=True,text=True,timeout=30,creationflags=FLAGS)
    if result.returncode:raise ValueError('无法读取样片，请上传完整的 MP4、MOV 或 WebM 视频')
    value=json.loads(result.stdout)
    video=next((s for s in value.get('streams',[]) if s.get('codec_type')=='video'),None)
    if not video:raise ValueError('样片中没有视频轨道')
    duration=float(value.get('format',{}).get('duration') or 0)
    width=int(video.get('width') or 0);height=int(video.get('height') or 0)
    if not 0<duration<=3600 or not 0<width<=8192 or not 0<height<=8192:
        raise ValueError('样片需要有效视频尺寸，时长不超过 60 分钟、边长不超过 8192 像素')
    return {'duration':duration,'width':width,'height':height,'codec':video.get('codec_name'),
        'fps':video.get('avg_frame_rate'),'nominal_fps':video.get('r_frame_rate'),'time_base':video.get('time_base'),
        'start_time':float(video.get('start_time') or 0),'frames':int(video.get('nb_frames') or 0),
        'has_audio':any(s.get('codec_type')=='audio' for s in value.get('streams',[]))}


def normalize(original,review):
    source=inspect(original)
    rate=Fraction(FPS)
    try:
        average=Fraction(source['fps']);nominal=Fraction(source['nominal_fps'])
        if average==nominal and 1<=average<=120:rate=average
    except (ValueError,ZeroDivisionError,TypeError):pass
    rate_text=f'{rate.numerator}/{rate.denominator}'
    # Preserve a declared constant rate, including fractional broadcast rates.
    # Do not independently shift the audio track: FFmpeg preserves A/V offsets.
    result=subprocess.run([ffmpeg_executable(),'-nostdin','-v','error','-protocol_whitelist','file,pipe',
        '-i',str(original),'-map','0:v:0','-map','0:a:0?',
        '-vf',f'fps={rate_text},pad=ceil(iw/2)*2:ceil(ih/2)*2','-c:v','libx264',
        '-preset','fast','-crf','20','-pix_fmt','yuv420p','-fps_mode','cfr',
        '-c:a','aac','-movflags','+faststart',str(review)],
        capture_output=True,timeout=900,creationflags=FLAGS)
    if result.returncode:raise ValueError('审片副本转换失败；未发布新版本，请检查视频编码或重新导出 MP4')
    checked=inspect(review)
    if checked['codec']!='h264' or Fraction(checked['fps'])!=rate or checked['frames']<1 or abs(checked['start_time'])>0.001:
        raise ValueError('审片副本帧率或起点校验失败；未发布新版本')
    if source['fps']==source['nominal_fps'] and source['frames'] and checked['frames']!=source['frames']:
        raise ValueError('审片副本帧数与固定帧率原片不一致；未发布新版本')
    return {'source':source,'review':checked,'review_fps':float(rate),
        'fps_num':rate.numerator,'fps_den':rate.denominator,'frame_count':checked['frames'],
        'timeline_note':f'批注按本审片副本 {rate_text} fps 从零开始定位；原文件完整保留。'}
