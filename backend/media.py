import json
import re
import shutil
import subprocess
from pathlib import Path
from .store import get_setting

def ffmpeg_executable():
    configured=get_setting('ffmpeg','ffmpeg')
    if shutil.which(configured) or Path(configured).is_file(): return configured
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError: raise ValueError('未找到 FFmpeg，请在 Worker 主机安装或在设置中指定可执行程序路径')

def probe(path):
    executable=ffmpeg_executable()
    ffprobe=Path(executable).with_name('ffprobe.exe' if str(executable).endswith('.exe') else 'ffprobe')
    if ffprobe.is_file() or shutil.which('ffprobe'):
        command=str(ffprobe) if ffprobe.is_file() else 'ffprobe'
        result=subprocess.run([command,'-v','error','-show_streams','-show_format','-of','json',str(path)],capture_output=True,text=True,timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if result.returncode==0:
            data=json.loads(result.stdout);video=next((x for x in data.get('streams',[]) if x.get('codec_type')=='video'),{})
            parts=video.get('avg_frame_rate','0/1').split('/')
            fps=float(parts[0])/float(parts[1]) if len(parts)==2 and float(parts[1]) else 0
            return {'duration':float(data.get('format',{}).get('duration',0)),'width':video.get('width'),'height':video.get('height'),'fps':fps,'has_audio':any(x.get('codec_type')=='audio' for x in data.get('streams',[]))}
    result=subprocess.run([executable,'-hide_banner','-i',str(path)],capture_output=True,timeout=30,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    text=result.stderr.decode('utf-8',errors='replace')
    duration=re.search(r'Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)',text)
    video=next((line for line in text.splitlines() if 'Video:' in line),'')
    size=re.search(r'\b(\d{2,5})x(\d{2,5})\b',video);fps=re.search(r'([\d.]+) fps',video)
    if not duration: raise ValueError('无法读取素材时长，请检查媒体文件是否完整')
    return {'duration':int(duration[1])*3600+int(duration[2])*60+float(duration[3]),'width':int(size[1]) if size else None,'height':int(size[2]) if size else None,'fps':float(fps[1]) if fps else None,'has_audio':'Audio:' in text}
