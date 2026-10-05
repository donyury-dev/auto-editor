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
    // palavra-chave em pop gigante (estilo anúncio) com efeitos variados
    const kwEl = keywordRef.current;
    if (kwEl) {
      const kw = timeline.keywords.find(
        (k) => t >= k.start - 0.02 && t <= k.end && k.text.trim()
      );
      if (kw) {
        const dur = Math.max(0.4, kw.end - kw.start);
        const p = Math.min(1, Math.max(0, (t - kw.start) / dur));
        const style = kw.style || "travessia";
        kwEl.className = `keyword-overlay kwfx-${style}`;
        const text = escapeHtml(kw.text.toUpperCase());
        if (style === "travessia") {
          const scale =
            p < 0.22
              ? 0.2 + (p / 0.22) * 0.85
              : p < 0.3
                ? 1.05 - ((p - 0.22) / 0.08) * 0.05
                : 1.0 + Math.min(0.18, ((p - 0.3) / 0.58) * 0.18);
          const blur =
            p < 0.22 ? 8 * (1 - p / 0.22) : p < 0.3 ? 1.2 * (1 - (p - 0.22) / 0.08) : 0;
          const tx =
            p < 0.22
              ? 6 - (p / 0.22) * 4
              : p < 0.3
                ? 2 - ((p - 0.22) / 0.08) * 2
                : 2 - Math.min(1, (p - 0.3) / 0.58) * 8;
          const opacity = p < 0.15 ? p / 0.15 : p > 0.9 ? Math.max(0, (1 - p) / 0.1) : 1;
          kwEl.innerHTML = `<span style="transform:scale(${scale.toFixed(3)}) translateX(${tx.toFixed(2)}%);filter:blur(${blur.toFixed(1)}px);opacity:${opacity.toFixed(3)}">${text}</span>`;
        } else if (style === "impacto") {
          const scale =
            p < 0.09
              ? 3.1 - (p / 0.09) * 2.14
              : p < 0.16
                ? 0.96 + ((p - 0.09) / 0.07) * 0.08
                : p < 0.23
                  ? 1.04 - ((p - 0.16) / 0.07) * 0.04
                  : 1.0 + Math.min(0.06, ((p - 0.23) / 0.6) * 0.06);
          const blur = p < 0.09 ? 6 * (1 - p / 0.09) : 0;
          kwEl.innerHTML = `<span style="transform:scale(${scale.toFixed(3)});filter:blur(${blur.toFixed(1)}px)">${text}</span>`;
        } else if (style === "quebra") {
          // letras "quebrando": cor varre a palavra letra a letra
          const letters = kw.text.toUpperCase().split("");
          const sweep = Math.min(0.55, 1.1 / letters.length);
          const n = Math.min(letters.length, Math.max(1, Math.floor(p / sweep)));
          const sweepPct = Math.round((n / letters.length) * 100);
          kwEl.innerHTML = `<span style="background:linear-gradient(90deg,#ff6b2b ${sweepPct}%,#ffffff ${sweepPct}%);-webkit-background-clip:text;background-clip:text;color:transparent;-webkit-text-stroke:0.5cqh #1a1a1a">${text}</span>`;
        } else if (style === "grifo") {
          const barW = Math.min(106, (p / 0.28) * 106);
          kwEl.innerHTML = `<span style="background:linear-gradient(90deg,rgba(255,107,43,0.85) ${barW.toFixed(0)}%,rgba(255,107,43,0) ${barW.toFixed(0)}%);background-size:100% 36%;background-position:50% 88%;background-repeat:no-repeat;color:#ffffff;-webkit-text-stroke:0.5cqh #1a1a1a">${text}</span>`;
        } else {
          // tremor
          const scale = p < 0.14 ? 0.2 + (p / 0.14) * 0.92 : p < 0.2 ? 1.12 - ((p - 0.14) / 0.06) * 0.12 : 1;
          const rot = p >= 0.2 ? Math.sin(p * 60) * 2.5 : 0;
          kwEl.innerHTML = `<span style="transform:scale(${scale.toFixed(3)}) rotate(${rot.toFixed(2)}deg)">${text}</span>`;
        }
        // auto-ajuste exato: mede o span real (fonte já carregada) e
        // corrige se estourar a largura
        const span = kwEl.firstElementChild as HTMLElement | null;
        if (span) {
          const maxW = kwEl.clientWidth * 0.94;
          const w = span.offsetWidth;
          if (w > 0 && w > maxW) {
            const fix = maxW / w;
            span.style.transform = `${span.style.transform || ""} scale(${fix.toFixed(3)})`;
          }
        }
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
