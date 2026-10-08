import { useEffect, useRef } from "react";
import type { CaptionStylePreset, CutBlock, Timeline } from "../types";

interface PlayerProps {
  videoUrl: string;
  timeline: Timeline;
  resultMode: boolean;
  muted: boolean;
  videoRef: React.RefObject<HTMLVideoElement>;
  captionStyles: CaptionStylePreset[];
  onKeywordMove?: (id: string, x: number, y: number) => void;
  onKeywordMoveEnd?: () => void;
  onSelectKeyword?: (id: string) => void;
}

/** Player com legendas e call-outs desenhados por cima, sincronizados. */
export default function Player({
  videoUrl,
  timeline,
  resultMode,
  muted,
  videoRef,
  captionStyles,
  onKeywordMove,
  onKeywordMoveEnd,
  onSelectKeyword,
}: PlayerProps) {
  const overlayRef = useRef<HTMLDivElement>(null);
  const captionRef = useRef<HTMLDivElement>(null);
  const calloutRef = useRef<HTMLDivElement>(null);
  const fxRef = useRef<HTMLDivElement>(null);
  const keywordRef = useRef<HTMLDivElement>(null);
  const kwShownRef = useRef<string | null>(null);
  const kwDragRef = useRef<{
    id: string;
    startX: number;
    startY: number;
    origX: number;
    origY: number;
  } | null>(null);
  const lastFxRef = useRef("");
  const layoutRef = useRef<HTMLDivElement>(null);
  const layoutVidRef = useRef<HTMLVideoElement>(null);
  const layoutTitleRef = useRef<HTMLDivElement>(null);
  const layoutStepsRef = useRef<HTMLDivElement>(null);
  const layoutShownRef = useRef<string | null>(null);

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
        // posição/tamanho customizados (arrastáveis na prévia)
        const fx = kw.x ?? 0.5;
        const fy = kw.y !== undefined && kw.y >= 0 ? kw.y : 0.2;
        const fscale = kw.scale ?? 1;
        kwShownRef.current = kw.id;
        kwEl.style.left = `${(fx * 100).toFixed(2)}%`;
        kwEl.style.top = `${(fy * 100).toFixed(2)}%`;
        kwEl.style.right = "auto";
        kwEl.style.transform = "translate(-50%, -50%)";
        kwEl.style.fontSize = `${(13 * fscale).toFixed(2)}cqh`;
        if (style === "travessia") {
          const scale =
            p < 0.22
              ? 0.2 + (p / 0.22) * 0.85
              : p < 0.3
                ? 1.05 - ((p - 0.22) / 0.08) * 0.05
                : 1.0 + Math.min(0.10, ((p - 0.3) / 0.58) * 0.10);
          const blur =
            p < 0.22 ? 8 * (1 - p / 0.22) : p < 0.3 ? 1.2 * (1 - (p - 0.22) / 0.08) : 0;
          // deriva sutil (±1.5%): parte do cenário sem sair do frame
          const tx = 1.5 - p * 3;
          const opacity = p < 0.15 ? p / 0.15 : p > 0.9 ? Math.max(0, (1 - p) / 0.1) : 1;
          kwEl.innerHTML = `<span style="transform:scale(${scale.toFixed(3)}) translateX(${tx.toFixed(2)}%);filter:blur(${blur.toFixed(1)}px);opacity:${opacity.toFixed(3)}">${text}</span>`;
        } else if (style === "impacto") {
          const scale =
            p < 0.09
              ? 1.9 - (p / 0.09) * 0.94
              : p < 0.16
                ? 0.96 + ((p - 0.09) / 0.07) * 0.08
                : p < 0.23
                  ? 1.04 - ((p - 0.16) / 0.07) * 0.04
                  : 1.0 + Math.min(0.04, Math.sin(((p - 0.23) / 0.6) * Math.PI) * 0.03);
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
        // corrige se estourar a largura, considerando o pico de escala
        // da animação de cada efeito
        const span = kwEl.firstElementChild as HTMLElement | null;
        if (span) {
          const peak: Record<string, number> = {
            travessia: 1.1,
            quebra: 1.08,
            grifo: 1.04,
            tremor: 1.12,
            impacto: 1.06,
          };
          const maxW = kwEl.clientWidth * 0.92;
          const w = span.offsetWidth;
          const need = w * (peak[style] ?? 1.1);
          if (w > 0 && need > maxW) {
            const fix = maxW / need;
            span.style.transform = `${span.style.transform || ""} scale(${fix.toFixed(3)})`;
          }
          // só a palavra é clicável/arrastável (o resto deixa o vídeo passar)
          span.style.pointerEvents = "auto";
          span.style.cursor = "grab";
        }
        kwEl.style.display = "block";
      } else {
        kwShownRef.current = null;
        kwEl.style.display = "none";
      }
    }
    // cena de layout "aula": fundo escuro + card do apresentador + painel
    const layEl = layoutRef.current;
    if (layEl) {
      const sc = (timeline.layouts || []).find(
        (l) => t >= l.start - 0.02 && t <= l.end + 0.02
      );
      if (sc) {
        if (layoutShownRef.current !== sc.id) {
          layoutShownRef.current = sc.id;
          layEl.className = `layout-overlay side-${sc.side}`;
          if (layoutTitleRef.current)
            layoutTitleRef.current.textContent = sc.title;
          if (layoutStepsRef.current)
            layoutStepsRef.current.innerHTML = (sc.steps || [])
              .map((s) => `<div class="layout-step">${escapeHtml(s)}</div>`)
              .join("");
          const lv = layoutVidRef.current;
          if (lv && lv.src !== videoUrl) lv.src = videoUrl;
        }
        // animação de entrada (0.5s): painel desliza + fade
        const p = Math.min(1, (t - sc.start) / 0.5);
        layEl.style.opacity = String(Math.min(1, p * 2));
        const panel = layEl.querySelector(
          ".layout-panel"
        ) as HTMLElement | null;
        if (panel) {
          const off = (1 - p) * (1 - p) * 12;
          panel.style.transform = `translateX(${sc.side === "right" ? "" : "-"}${off.toFixed(2)}%)`;
        }
        // card do apresentador desliza do centro para o lado (0.6s ease-out)
        const card = layEl.querySelector(
          ".layout-card"
        ) as HTMLElement | null;
        if (card) {
          const pc = Math.min(1, (t - sc.start) / 0.6);
          const ease = 1 - (1 - pc) * (1 - pc);
          const finalPct = 3;
          const centerPct = (100 - 44) / 2;
          const leftPct = finalPct + (centerPct - finalPct) * (1 - ease);
          if (sc.side === "right") {
            card.style.right = `${leftPct.toFixed(2)}%`;
            card.style.left = "auto";
          } else {
            card.style.left = `${leftPct.toFixed(2)}%`;
            card.style.right = "auto";
          }
        }
        // vídeo dentro do card sincronizado com o principal
        const lv = layoutVidRef.current;
        const v = videoRef.current;
        if (lv && v) {
          if (Math.abs(lv.currentTime - v.currentTime) > 0.25)
            lv.currentTime = v.currentTime;
          if (v.paused !== lv.paused) {
            if (v.paused) lv.pause();
            else lv.play().catch(() => {});
          }
        }
        // cartões aparecem progressivamente conforme a fala avança
        const frac =
          (t - sc.start) / Math.max(0.5, sc.end - sc.start);
        layEl
          .querySelectorAll<HTMLElement>(".layout-step")
          .forEach((el, i) => {
            const show =
              frac > (i + 0.5) / ((sc.steps?.length || 1) + 0.5);
            el.style.opacity = show ? "1" : "0.18";
          });
        layEl.style.display = "block";
      } else {
        layoutShownRef.current = null;
        layEl.style.display = "none";
        layoutVidRef.current?.pause();
      }
    }
  }

  function handleKwPointerDown(e: React.PointerEvent) {
    const id = kwShownRef.current;
    if (!id || !onKeywordMove) return;
    const kw = timeline.keywords.find((k) => k.id === id);
    if (!kw) return;
    e.preventDefault();
    onSelectKeyword?.(id);
    kwDragRef.current = {
      id,
      startX: e.clientX,
      startY: e.clientY,
      origX: kw.x ?? 0.5,
      origY: kw.y !== undefined && kw.y >= 0 ? kw.y : 0.2,
    };
    const onMove = (ev: PointerEvent) => {
      const drag = kwDragRef.current;
      const box = keywordRef.current?.parentElement;
      if (!drag || !box) return;
      const rect = box.getBoundingClientRect();
      const dx = (ev.clientX - drag.startX) / rect.width;
      const dy = (ev.clientY - drag.startY) / rect.height;
      const x = Math.min(0.94, Math.max(0.06, drag.origX + dx));
      const y = Math.min(0.92, Math.max(0.04, drag.origY + dy));
      onKeywordMove(drag.id, x, y);
    };
    const onUp = () => {
      kwDragRef.current = null;
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      onKeywordMoveEnd?.();
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
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
        <div className="layout-overlay" ref={layoutRef} style={{ display: "none" }}>
          <div className="layout-bg" />
          <div className="layout-card">
            <video ref={layoutVidRef} muted playsInline />
          </div>
          <div className="layout-panel">
            <div className="layout-panel-title" ref={layoutTitleRef}></div>
            <div className="layout-steps" ref={layoutStepsRef}></div>
          </div>
        </div>
        <div className="fx-overlay" ref={fxRef} />
        <div
          className="keyword-overlay"
          ref={keywordRef}
          onPointerDown={handleKwPointerDown}
        ></div>
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
