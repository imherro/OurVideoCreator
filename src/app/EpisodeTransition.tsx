import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Hourglass } from "lucide-react";
import "./episodeTransition.css";

type EpisodeTransitionState = {
  label: string;
  phase: "loading" | "revealing";
};

export function useEpisodeTransition() {
  const [transition, setTransition] = useState<EpisodeTransitionState | null>(null);
  const active = useRef(false);
  const mounted = useRef(true);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const returnFocus = useRef<HTMLElement | null>(null);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      clearTimeout(timer.current);
    };
  }, []);
  useEffect(() => {
    if (!transition && returnFocus.current) {
      if (returnFocus.current.isConnected) returnFocus.current.focus({ preventScroll: true });
      returnFocus.current = null;
    }
  }, [transition]);

  async function switchEpisode(label: string, open: () => Promise<void>) {
    if (active.current) return;
    active.current = true;
    returnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setTransition({ label, phase: "loading" });
    try {
      await open();
    } finally {
      // Do not return from finally: a failed project load must still reject so
      // the existing host error reporting remains authoritative after unmount.
      if (mounted.current) {
        const finish = () => {
          active.current = false;
          setTransition(null);
        };
        if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) finish();
        else {
          setTransition({ label, phase: "revealing" });
          timer.current = setTimeout(finish, 160);
        }
      }
    }
  }

  return { transition, switchEpisode };
}

export function EpisodeTransition({ transition }: { transition: EpisodeTransitionState | null }) {
  if (!transition) return null;
  // The portal stays outside the temporarily inert studio workspace.
  return createPortal(
    <div className={`episode-transition is-${transition.phase}`}>
      <div className="episode-transition-label" role="status" aria-live="polite" aria-atomic="true">
        <Hourglass size={18} aria-hidden="true" />
        <span>正在切换到 <strong>{transition.label}</strong></span>
      </div>
    </div>,
    document.body,
  );
}
