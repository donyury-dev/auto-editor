import { useEffect, useRef } from "react";
import type { Timeline } from "../types";

interface PlayerProps {
  videoUrl: string;
  timeline: Timeline;
  resultMode: boolean;
  muted: boolean;
  videoRef: React.RefObject<HTMLVideoElement>;
}

/** Player com legendas e call-outs desenhados por cima, sincronizados. */
export default function Player({
  videoUrl,
  timeline,
  resultMode,
  muted,
  videoRef,
}: PlayerProps) {
  const overlayRef = useRef<HTMLDivElement>(null);
  const captionRef = useRef<HTMLDivElement>(null);
  const calloutRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let raf = 0;
    const tick = () => {
      const video = videoRef.current;
      if (video) {
        const t = video.currentTime;
        if (resultMode) {
          const cut = timeline.cuts.find(
            (c) => t >= c.start - 0.02 && t < c.end
          );
          if (cut) {
            if (cut.end >= video.duration - 0.05) {
              video.pause();
              video.currentTime = video.duration - 0.05;
            } else {
              video.currentTime = cut.end + 0.01;
            }
          }
        }
        renderOverlays(t);
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [timeline, resultMode]);

  const isVertical = timeline.video.height >= timeline.video.width;

  function renderOverlays(t: number) {
    // legenda
    const cap = captionRef.current;
    if (cap) {
      const chunk = timeline.captions.find(
        (c) => t >= c.start - 0.05 && t <= c.end + 0.1
      );
      if (chunk) {
        const parts = chunk.words.map((w, i) => {
          const active = t >= w.start && t < w.end;
          return `<span class="cap-word ${active ? "active" : ""}" data-i="${i}">${escapeHtml(w.text)}</span>`;
        });
        cap.innerHTML = parts.join(" ");
        cap.style.display = "flex";
      } else {
        cap.style.display = "none";
      }
    }
    // call-out
    const call = calloutRef.current;
    if (call) {
      const co = timeline.callouts.find(
        (c) => t >= c.start - 0.05 && t <= c.end + 0.1
      );
      if (co) {
        const elapsed = t - co.start;
        // pop de entrada: 60% → 112% → 105% em ~400ms
        let scale = 1;
        if (elapsed < 0.4) {
          if (elapsed < 0.22) scale = 0.6 + (elapsed / 0.22) * 0.52;
          else scale = 1.12 - ((elapsed - 0.22) / 0.18) * 0.07;
        }
        call.innerHTML = `<span style="display:inline-block;transform:scale(${scale.toFixed(3)})">${escapeHtml(co.text.toUpperCase())}</span>`;
        call.style.display = "block";
      } else {
        call.style.display = "none";
      }
    }
  }

  return (
    <div className={`player ${isVertical ? "vertical" : "horizontal"}`}>
      <video
        ref={videoRef}
        src={videoUrl}
        muted={muted}
        onEnded={() => {}}
        playsInline
      />
      <div className="overlays" ref={overlayRef}>
        <div className="callout-overlay" ref={calloutRef}></div>
        <div className="caption-overlay" ref={captionRef}></div>
      </div>
    </div>
  );
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
