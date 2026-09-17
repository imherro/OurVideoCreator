import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Pause, Play, X } from "lucide-react";
import { clipSourceTime, timelineDuration, timelinePosition, type Clip } from "./timeline";
import "./timelinePreview.css";

type Asset = {
  id: string;
  url: string;
  kind: string;
  name: string;
  metadata: Record<string, any>;
};

type TimelinePreviewProps = {
  clips: Clip[];
  assets: Asset[];
  audioId?: string;
  musicVolume: number;
  transition: string;
  ratio: string;
  autoPlay?: boolean;
  onClose: () => void;
};

export function TimelinePreview({
  clips,
  assets,
  audioId,
  musicVolume,
  transition,
  ratio,
  autoPlay = false,
  onClose,
}: TimelinePreviewProps) {
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(autoPlay);
  const [buffering, setBuffering] = useState(false);
  const [error, setError] = useState("");
  const video = useRef<HTMLVideoElement>(null);
  const music = useRef<HTMLAudioElement>(null);
  const duration = timelineDuration(clips);
  const position = timelinePosition(clips, time);
  const asset = assets.find((item) => item.id === position?.clip.asset_id);
  const audio = assets.find((item) => item.id === audioId);

  function playbackFailed(message: string) {
    setPlaying(false);
    setBuffering(false);
    setError(message);
  }

  function playElement(element: HTMLMediaElement | null, message: string) {
    if (!element) return;
    element.play().catch(() => playbackFailed(message));
  }

  // This runs during the button-triggered render that opened the preview, so
  // browsers treat the first playback request as a user-initiated action.
  useLayoutEffect(() => {
    if (!autoPlay) return;
    playElement(video.current, "浏览器阻止了自动播放，请点击播放重试。");
    playElement(music.current, "配乐无法自动播放，请点击播放重试。");
  }, [autoPlay]);

  useEffect(() => {
    if (!playing || buffering) return;
    let last = performance.now();
    let frame = 0;
    const tick = (now: number) => {
      const elapsed = (now - last) / 1000;
      last = now;
      setTime((value) => Math.min(duration, value + elapsed));
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, buffering, duration]);

  useEffect(() => {
    if (time >= duration) setPlaying(false);
  }, [time, duration]);

  useEffect(() => {
    const stop = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", stop);
    return () => window.removeEventListener("keydown", stop);
  }, [onClose]);

  useEffect(() => {
    const element = video.current;
    if (!element || !position) return;
    element.volume = Math.max(0, Math.min(1, position.clip.volume ?? 1));
    element.playbackRate = Number(position.clip.playbackRate ?? 1);
    const target = clipSourceTime(position.clip, position.offset);
    if (element.readyState >= 1 && Math.abs(element.currentTime - target) > 0.25)
      element.currentTime = target;
    if (playing && element.paused)
      playElement(element, "无法播放当前视频，请检查素材或点击播放重试。");
    if (!playing) element.pause();
  }, [time, playing, position?.index, asset?.id]);

  useEffect(() => {
    const element = music.current;
    if (!element) return;
    element.volume = Math.max(0, Math.min(1, musicVolume));
    if (Number.isFinite(element.duration) && element.duration > 0) {
      const target = time % element.duration;
      if (Math.abs(element.currentTime - target) > 0.3) element.currentTime = target;
    }
    if (playing && element.paused)
      playElement(element, "配乐播放失败，请点击播放重试。");
    if (!playing) element.pause();
  }, [time, playing, audioId, musicVolume]);

  const fade = position ? Math.min(0.3, position.duration / 4) : 0.3;
  const opacity =
    transition === "fade" && position
      ? Math.max(
          0,
          Math.min(1, position.offset / fade, (position.duration - position.offset) / fade),
        )
      : 1;
  const togglePlayback = () => {
    if (playing) {
      setPlaying(false);
      return;
    }
    if (time >= duration) setTime(0);
    setError("");
    setBuffering(false);
    setPlaying(true);
    playElement(video.current, "无法播放当前视频，请检查素材或点击播放重试。");
    playElement(music.current, "配乐播放失败，请点击播放重试。");
  };

  return (
    <div
      className="preview-overlay"
      role="dialog"
      aria-modal="true"
      aria-label="时间线预览"
    >
      <div className="timeline-preview">
        <div className="panel-title">
          <h2>时间线预览</h2>
          <button className="icon-button" aria-label="关闭预览" onClick={onClose}>
            <X />
          </button>
        </div>
        <div className="timeline-screen" style={{ aspectRatio: ratio.replace(":", "/") }}>
          {asset?.kind === "video" ? (
            <video
              key={position?.clip.id}
              ref={video}
              src={asset.url}
              style={{ opacity }}
              playsInline
              preload="auto"
              onLoadedMetadata={(event) => {
                event.currentTarget.playbackRate = Number(position?.clip.playbackRate ?? 1);
                if (position) event.currentTarget.currentTime = clipSourceTime(position.clip, position.offset);
              }}
              onWaiting={() => {
                setBuffering(true);
                setError("素材缓冲中，加载完成后会自动继续播放。");
              }}
              onCanPlay={(event) => {
                setBuffering(false);
                setError("");
                if (playing)
                  playElement(
                    event.currentTarget,
                    "无法播放当前视频，请检查素材或点击播放重试。",
                  );
              }}
              onError={() => playbackFailed("视频素材无法读取。")}
            />
          ) : asset?.kind === "image" ? (
            <img src={asset.url} alt={asset.name} style={{ opacity }} />
          ) : (
            <p>当前镜头素材不可用</p>
          )}
        </div>
        {audio && <audio ref={music} src={audio.url} loop preload="auto" />}
        <div className="preview-controls">
          <button className="primary" disabled={!position} onClick={togglePlayback}>
            {playing ? <Pause size={16} /> : <Play size={16} />}
            {playing ? "暂停" : "播放"}
          </button>
          <input
            aria-label="预览位置"
            type="range"
            min="0"
            max={duration}
            step="0.01"
            value={time}
            onChange={(event) => {
              setTime(Number(event.target.value));
              setError("");
            }}
          />
          <span>
            {time.toFixed(2)} / {duration.toFixed(2)} 秒
          </span>
        </div>
        <p className="muted">
          镜头 {(position?.index || 0) + 1} / {clips.length} · {asset?.name}。预览包含原声、配乐和淡入淡出，字幕请以导出成片为准。
        </p>
        {error && <p className="error">{error}</p>}
      </div>
    </div>
  );
}
