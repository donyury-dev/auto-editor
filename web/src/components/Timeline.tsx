import { useEffect, useRef, useState } from "react";
import type { Selection, Timeline } from "../types";

interface TimelineProps {
  timeline: Timeline;
  selection: Selection;
  onSelect: (s: Selection) => void;
  onCommit: (t: Timeline) => void;
  videoRef: React.RefObject<HTMLVideoElement>;
  zoom: number;
}

type DragState =
  | {
      kind: "cut" | "callout" | "zoom" | "sfx";
      id: string;
      edge: "left" | "right" | "move";
      startX: number;
      origStart: number;
      origEnd: number;
    }
  | null;

const TRACK_H = 40;

/** Timeline multi-track com cortes arrastáveis, playhead e régua. */
export default function Timeline({
  timeline,
  selection,
  onSelect,
  onCommit,
  videoRef,
  zoom,
}: TimelineProps) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const laneRef = useRef<HTMLDivElement>(null);
  const playheadRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(800);
  const drag = useRef<DragState>(null);
  // estado visual do arraste; o ref mantém o valor atual para o commit
  const [dragTL, setDragTL] = useState<{ id: string; start: number; end: number } | null>(
    null
  );
  const dragTLRef = useRef<{ id: string; start: number; end: number } | null>(null);
  // timeline/pxPerSec atuais para os handlers globais (estáveis durante o arraste)
  const stateRef = useRef({ timeline, pxPerSec: 0, duration: 0.1 });
  stateRef.current = { timeline, pxPerSec: 0, duration: 0.1 };

  const duration = Math.max(0.1, timeline.video.duration);
  const inner = Math.max(200, width - 24);
  const pxPerSec = (inner * zoom) / duration;
  const laneWidth = duration * pxPerSec;
  stateRef.current.pxPerSec = pxPerSec;
  stateRef.current.duration = duration;

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setWidth(el.clientWidth));
    ro.observe(el);
    setWidth(el.clientWidth);
    return () => ro.disconnect();
  }, []);

  // playhead via rAF (sem re-render do React)
  useEffect(() => {
    let raf = 0;
    const tick = () => {
      const v = videoRef.current;
      const ph = playheadRef.current;
      if (v && ph) ph.style.left = `${(v.currentTime * pxPerSec).toFixed(1)}px`;
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [pxPerSec, videoRef]);

  const xToTime = (clientX: number): number => {
    const el = laneRef.current;
    if (!el) return 0;
    const rect = el.getBoundingClientRect();
    return clamp((clientX - rect.left) / pxPerSec, 0, duration);
  };

  const startDrag = (
    e: React.PointerEvent,
    kind: "cut" | "callout" | "zoom" | "sfx",
    id: string,
    edge: "left" | "right" | "move"
  ) => {
    e.stopPropagation();
    e.preventDefault();
    const block =
      kind === "cut"
        ? timeline.cuts.find((c) => c.id === id)
        : kind === "callout"
          ? timeline.callouts.find((c) => c.id === id)
          : kind === "zoom"
            ? timeline.zooms.find((z) => z.id === id)
            : timeline.sfx.find((s) => s.id === id);
    if (!block) return;
    const orig = {
      start: "timestamp" in block ? block.timestamp : block.start,
      end: "end" in block ? block.end : ("timestamp" in block ? block.timestamp : 0),
    };
    drag.current = {
      kind,
      id,
      edge,
      startX: e.clientX,
      origStart: orig.start,
      origEnd: orig.end,
    };
    onSelect({ kind, id } as Selection);
    window.addEventListener("pointermove", onDragMove);
    window.addEventListener("pointerup", onDragUp);
  };

  const onDragMove = (e: PointerEvent) => {
    const d = drag.current;
    if (!d) return;
    const dt = (e.clientX - d.startX) / stateRef.current.pxPerSec;
    let s = d.origStart;
    let en = d.origEnd;
    const minLen = 0.15;
    const maxT = stateRef.current.duration;
    if (d.edge === "left") s = clamp(d.origStart + dt, 0, d.origEnd - minLen);
    else if (d.edge === "right")
      en = clamp(d.origEnd + dt, d.origStart + minLen, maxT);
    else {
      if (d.kind === "sfx") {
        s = clamp(d.origStart + dt, 0, maxT);
        en = s;
      } else {
        const span = d.origEnd - d.origStart;
        s = clamp(d.origStart + dt, 0, maxT - span);
        en = s + span;
      }
    }
    const val = { id: d.id, start: s, end: en };
    dragTLRef.current = val;
    setDragTL(val);
  };

  const onDragUp = () => {
    const d = drag.current;
    const cur = dragTLRef.current;
    window.removeEventListener("pointermove", onDragMove);
    window.removeEventListener("pointerup", onDragUp);
    drag.current = null;
    dragTLRef.current = null;
    if (d && cur) {
      const next: Timeline = { ...stateRef.current.timeline };
      if (d.kind === "cut") {
        next.cuts = next.cuts.map((c) =>
          c.id === cur.id ? { ...c, start: round(cur.start), end: round(cur.end) } : c
        );
      } else if (d.kind === "callout") {
        next.callouts = next.callouts.map((c) =>
          c.id === cur.id ? { ...c, start: round(cur.start), end: round(cur.end) } : c
        );
      } else if (d.kind === "zoom") {
        next.zooms = next.zooms.map((z) =>
          z.id === cur.id ? { ...z, start: round(cur.start), end: round(cur.end) } : z
        );
      } else {
        next.sfx = next.sfx.map((s) =>
          s.id === cur.id ? { ...s, timestamp: round(cur.start) } : s
        );
      }
      onCommit(next);
    }
    setDragTL(null);
  };

  const seekFromEvent = (e: React.PointerEvent) => {
    const t = xToTime(e.clientX);
    const v = videoRef.current;
    if (v) v.currentTime = t;
  };

  const tickStep = niceStep(pxPerSec);
  const ticks: number[] = [];
  for (let t = 0; t <= duration + 0.001; t += tickStep) ticks.push(t);

  const isSelected = (kind: string, id: string) =>
    selection?.kind === kind && "id" in selection && selection.id === id;

  const dragBlock = (id: string) =>
    dragTL && dragTL.id === id ? dragTL : null;

  return (
    <div className="timeline" ref={scrollRef}>
      <div className="lane" ref={laneRef} style={{ width: laneWidth }}>
        <div className="ruler">
          {ticks.map((t) => (
            <div key={t} className="tick" style={{ left: t * pxPerSec }}>
              <span>{fmt(t)}</span>
            </div>
          ))}
        </div>

        <div
          className="track video-track"
          style={{ height: TRACK_H }}
          onPointerDown={(e) => {
            if ((e.target as HTMLElement).dataset.block) return;
            seekFromEvent(e);
          }}
        >
          <div className="base-clip" style={{ width: laneWidth }} />
          {timeline.cuts.map((c) => {
            const d = dragBlock(c.id);
            const start = d ? d.start : c.start;
            const end = d ? d.end : c.end;
            return (
              <div
                key={c.id}
                data-block="1"
                className={`cut-block ${isSelected("cut", c.id) ? "selected" : ""}`}
                style={{
                  left: start * pxPerSec,
                  width: Math.max(4, (end - start) * pxPerSec),
                }}
                title={c.reason || "Corte"}
                onPointerDown={(e) => startDrag(e, "cut", c.id, "move")}
              >
                <div
                  className="handle left"
                  onPointerDown={(e) => startDrag(e, "cut", c.id, "left")}
                />
                <span className="cut-label">corte</span>
                <div
                  className="handle right"
                  onPointerDown={(e) => startDrag(e, "cut", c.id, "right")}
                />
              </div>
            );
          })}
        </div>

        <div
          className="track caption-track"
          style={{ height: 30 }}
          onPointerDown={(e) => {
            if ((e.target as HTMLElement).dataset.block) return;
            seekFromEvent(e);
          }}
        >
          {timeline.captions.map((k) => (
            <div
              key={k.id}
              data-block="1"
              className={`mini-block caption ${isSelected("caption", k.id) ? "selected" : ""}`}
              style={{
                left: k.start * pxPerSec,
                width: Math.max(3, (k.end - k.start) * pxPerSec),
              }}
              title={k.text}
              onPointerDown={(e) => {
                e.stopPropagation();
                onSelect({ kind: "caption", id: k.id });
              }}
            />
          ))}
        </div>

        <div
          className="track callout-track"
          style={{ height: 30 }}
          onPointerDown={(e) => {
            if ((e.target as HTMLElement).dataset.block) return;
            seekFromEvent(e);
          }}
        >
          {timeline.callouts.map((o) => {
            const d = dragBlock(o.id);
            const start = d ? d.start : o.start;
            const end = d ? d.end : o.end;
            return (
              <div
                key={o.id}
                data-block="1"
                className={`mini-block callout ${isSelected("callout", o.id) ? "selected" : ""}`}
                style={{
                  left: start * pxPerSec,
                  width: Math.max(6, (end - start) * pxPerSec),
                }}
                title={o.text}
                onPointerDown={(e) => startDrag(e, "callout", o.id, "move")}
              />
            );
          })}
        </div>

        <div
          className="track zoom-track"
          style={{ height: 26 }}
          onPointerDown={(e) => {
            if ((e.target as HTMLElement).dataset.block) return;
            seekFromEvent(e);
          }}
        >
          {timeline.zooms.map((z) => {
            const d = dragBlock(z.id);
            const start = d ? d.start : z.start;
            const end = d ? d.end : z.end;
            return (
              <div
                key={z.id}
                data-block="1"
                className={`mini-block zoomb ${isSelected("zoom", z.id) ? "selected" : ""}`}
                style={{
                  left: start * pxPerSec,
                  width: Math.max(8, (end - start) * pxPerSec),
                }}
                title={`Zoom ${Math.round(z.intensity * 100)}% @ ${fmt(z.start)}`}
                onPointerDown={(e) => startDrag(e, "zoom", z.id, "move")}
              >
                <div
                  className="handle left"
                  onPointerDown={(e) => startDrag(e, "zoom", z.id, "left")}
                />
                <span className="mini-label">zoom</span>
                <div
                  className="handle right"
                  onPointerDown={(e) => startDrag(e, "zoom", z.id, "right")}
                />
              </div>
            );
          })}
        </div>

        <div
          className="track music-track"
          style={{ height: 26 }}
          onPointerDown={(e) => {
            if ((e.target as HTMLElement).dataset.block) return;
            seekFromEvent(e);
          }}
        >
          {timeline.music.path ? (
            <div
              className="mini-block music"
              style={{ left: 0, width: laneWidth }}
              title={timeline.music.label}
              onPointerDown={(e) => {
                e.stopPropagation();
                onSelect({ kind: "music" });
              }}
            >
              <span className="mini-label">{timeline.music.label || "música"}</span>
            </div>
          ) : (
            <div
              className="mini-block music empty"
              style={{ left: 0, width: laneWidth }}
              onPointerDown={(e) => {
                e.stopPropagation();
                onSelect({ kind: "music" });
              }}
            >
              <span className="mini-label">+ música de fundo (escolha na biblioteca)</span>
            </div>
          )}
        </div>

        <div
          className="track sfx-track"
          style={{ height: 24 }}
          onPointerDown={(e) => {
            if ((e.target as HTMLElement).dataset.block) return;
            seekFromEvent(e);
          }}
        >
          {timeline.sfx.map((s) => {
            const d = dragBlock(s.id);
            const ts = d ? d.start : s.timestamp;
            return (
              <div
                key={s.id}
                data-block="1"
                className={`sfx-marker ${isSelected("sfx", s.id) ? "selected" : ""}`}
                style={{ left: ts * pxPerSec }}
                title={`SFX ${s.kind} @ ${fmt(s.timestamp)} — arraste para mover`}
                onPointerDown={(e) => startDrag(e, "sfx", s.id, "move")}
              />
            );
          })}
        </div>

        <div className="playhead" ref={playheadRef} />
      </div>
    </div>
  );
}

function clamp(v: number, a: number, b: number): number {
  return Math.max(a, Math.min(b, v));
}

function round(v: number): number {
  return Math.round(v * 1000) / 1000;
}

function fmt(t: number): string {
  const m = Math.floor(t / 60);
  const s = Math.floor(t % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function niceStep(pxPerSec: number): number {
  for (const s of [0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300])
    if (s * pxPerSec >= 60) return s;
  return 600;
}
