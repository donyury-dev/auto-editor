import { useEffect, useRef } from "react";
import type { CaptionStylePreset, CutBlock, Timeline } from "../types";

interface PlayerProps {
  videoUrl: string;
  timeline: Timeline;
  resultMode: boolean;
  muted: boolean;
  videoRef: React.RefObject<HTMLVideoElement>;
  captionStyles: CaptionStylePreset[];
}

/** Player com legendas e call-outs desenhados por cima, sincronizados. */
export default function Player({
  videoUrl,
  timeline,
  resultMode,
  muted,
  videoRef,
  captionStyles,
}: PlayerProps) {
  const overlayRef = useRef<HTMLDivElement>(null);
  const captionRef = useRef<HTMLDivElement>(null);
  const calloutRef = useRef<HTMLDivElement>(null);
  const fxRef = useRef<HTMLDivElement>(null);
  const keywordRef = useRef<HTMLDivElement>(null);
  const lastFxRef = useRef("");

  const preset =
    captionStyles.find((s) => s.id === (timeline.captionStyle || "")) ||
    captionStyles[0];
  const scale = timeline.captionScale || 1;
  const vertical = timeline.video.height >= timeline.video.width;
  const baseFs = preset
    ? vertical
      ? preset.font_size_vertical
      : preset.font_size_horizontal
    : 74;
  // referência: 1920px de altura no vídeo vertical, 1080 no horizontal
  const refH = vertical ? 1920 : 1080;
  const captionStyleCss: React.CSSProperties = preset
    ? {
        fontFamily: `"${preset.font_family}", "Arial Black", Impact, sans-serif`,
        fontSize: `${((baseFs * scale) / refH) * 100}cqh`,
        textTransform: preset.uppercase ? "uppercase" : "none",
      }
    : {};

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
            if (lastFxRef.current !== cut.id) {
              lastFxRef.current = cut.id;
              if (cut.end >= video.duration - 0.05) {
                video.pause();
                video.currentTime = video.duration - 0.05;
              } else {
                triggerFx(cut);
                video.currentTime = cut.end + 0.01;
              }
            }
          } else {
            lastFxRef.current = "";
          }
        }
        // zoom simulado: CSS scale durante o bloco de zoom
        const zoom = timeline.zooms.find((z) => t >= z.start && t < z.end);
        video.style.transform = zoom
          ? `scale(${(1 + zoom.intensity).toFixed(3)})`
          : "scale(1)";
        renderOverlays(t);
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [timeline, resultMode]);

  const isVertical = timeline.video.height >= timeline.video.width;

  function triggerFx(cut: CutBlock) {
    const fx = fxRef.current;
    if (!fx) return;
    const type = cut.transition?.type || timeline.transition.type || "";
    const dur =
      cut.transition?.duration || timeline.transition.duration || 0.25;
    if (!type || type === "corte") return;
    const anim =
      type === "circleopen"
        ? "fxCircle"
        : type === "slideleft"
          ? "fxSlideLeft"
          : type === "slideup"
            ? "fxSlideUp"
            : "fxFade";
    fx.style.animation = "none";
    void fx.offsetWidth; // força restart da animação
    fx.style.animation = `${anim} ${dur}s ease-out forwards`;
  }

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
    // palavra-chave em pop gigante (estilo anúncio)
    const kwEl = keywordRef.current;
    if (kwEl) {
      const kw = timeline.keywords.find(
        (k) => t >= k.start - 0.02 && t <= k.end && k.text.trim()
      );
      if (kw) {
        const elapsed = t - kw.start;
        // pop 3D: estoura com overshoot e segue crescendo até o fim
        let scale = 1;
        if (elapsed < 0.2) scale = 0.22 + (elapsed / 0.2) * 0.94;
        else if (elapsed < 0.34) scale = 1.16 - ((elapsed - 0.2) / 0.14) * 0.16;
        else scale = 1.0 + Math.min(0.14, (elapsed - 0.34) * 0.1);
        const fadeOut = Math.max(0, Math.min(1, (kw.end - t) / 0.22));
        kwEl.innerHTML = `<span style="display:inline-block;transform:scale(${scale.toFixed(3)});opacity:${fadeOut.toFixed(3)}">${escapeHtml(kw.text.toUpperCase())}</span>`;
        kwEl.style.display = "block";
      } else {
        kwEl.style.display = "none";
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
        <div className="fx-overlay" ref={fxRef} />
        <div className="keyword-overlay" ref={keywordRef}></div>
        <div className="callout-overlay" ref={calloutRef}></div>
        <div
          className="caption-overlay"
          ref={captionRef}
          style={{
            ...captionStyleCss,
            color: preset?.primary_color,
            ["--cap-highlight" as any]: preset?.highlight_color,
          }}
        ></div>
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
