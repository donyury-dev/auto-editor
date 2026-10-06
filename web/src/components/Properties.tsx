import { useEffect, useState } from "react";
import type {
  CaptionStylePreset,
  Library,
  Selection,
  Timeline,
} from "../types";

interface PropertiesProps {
  timeline: Timeline;
  selection: Selection;
  onChange: (t: Timeline) => void;
  onDelete: () => void;
  captionStyles: CaptionStylePreset[];
  library: Library | null;
}

/** Painel de propriedades do item selecionado (corte/legenda/call-out/zoom/sfx/música). */
export default function Properties({
  timeline,
  selection,
  onChange,
  onDelete,
  captionStyles,
  library,
}: PropertiesProps) {
  if (!selection) {
    return (
      <aside className="properties">
        <h3>Propriedades</h3>
        <p className="hint">
          Selecione um corte, legenda ou call-out na timeline para editar.
        </p>
        <TransicaoPicker timeline={timeline} onChange={onChange} />
        <CaptionStylePicker
          timeline={timeline}
          onChange={onChange}
          captionStyles={captionStyles}
        />
        <MusicPicker timeline={timeline} onChange={onChange} library={library} />
      </aside>
    );
  }

  if (selection.kind === "cut") {
    const cut = timeline.cuts.find((c) => c.id === selection.id);
    if (!cut) return null;
    return (
      <aside className="properties">
        <h3>Corte</h3>
        <Num label="Início (s)" value={cut.start} min={0} max={timeline.video.duration}
          onChange={(v) => onChange(patchCut(timeline, cut.id, { start: v }))} />
        <Num label="Fim (s)" value={cut.end} min={0} max={timeline.video.duration}
          onChange={(v) => onChange(patchCut(timeline, cut.id, { end: v }))} />
        {cut.reason && <p className="hint">Motivo: {cut.reason}</p>}
        <CutTransitionPicker
          timeline={timeline}
          cutId={cut.id}
          onChange={onChange}
        />
        <button className="danger" onClick={onDelete}>Remover corte</button>
      </aside>
    );
  }

  if (selection.kind === "caption") {
    const cap = timeline.captions.find((c) => c.id === selection.id);
    if (!cap) return null;
    return (
      <aside className="properties">
        <h3>Legenda</h3>
        <textarea
          value={cap.text}
          rows={3}
          onChange={(e) =>
            onChange(patchCaption(timeline, cap.id, e.target.value))
          }
        />
        <p className="hint">
          Corrige erros de transcrição — vale para a prévia e para o render.
        </p>
        <CaptionStylePicker
          timeline={timeline}
          onChange={onChange}
          captionStyles={captionStyles}
        />
      </aside>
    );
  }

  if (selection.kind === "callout") {
    const co = timeline.callouts.find((c) => c.id === selection.id);
    if (!co) return null;
    return (
      <aside className="properties">
        <h3>Call-out</h3>
        <textarea
          value={co.text}
          rows={2}
          maxLength={40}
          onChange={(e) =>
            onChange(patchCallout(timeline, co.id, e.target.value))
          }
        />
        <Num label="Início (s)" value={co.start} min={0} max={timeline.video.duration}
          onChange={(v) => onChange(patchCalloutTime(timeline, co.id, { start: v }))} />
        <Num label="Fim (s)" value={co.end} min={0} max={timeline.video.duration}
          onChange={(v) => onChange(patchCalloutTime(timeline, co.id, { end: v }))} />
        <button className="danger" onClick={onDelete}>Remover call-out</button>
      </aside>
    );
  }

  if (selection.kind === "keyword") {
    const kw = timeline.keywords.find((k) => k.id === selection.id);
    if (!kw) return null;
    return (
      <aside className="properties">
        <h3>Palavra-chave</h3>
        <p className="hint">
          Pop gigante estilo anúncio: estoura na tela com profundidade 3D.
        </p>
        <input
          value={kw.text}
          maxLength={24}
          onChange={(e) =>
            onChange(patchKeyword(timeline, kw.id, e.target.value))
          }
        />
        <h3>Efeito</h3>
        <select
          value={kw.style || ""}
          onChange={(e) =>
            onChange(patchKeywordStyle(timeline, kw.id, e.target.value))
          }
        >
          <option value="">Automático (varia como no anúncio)</option>
          <option value="travessia">Travessia 3D (atravessa a cena)</option>
          <option value="quebra">Letras quebrando (cor letra a letra)</option>
          <option value="grifo">Grifo (marca-texto laranja)</option>
          <option value="tremor">Tremor</option>
          <option value="impacto">Impacto vermelho</option>
        </select>
        <Num label="Início (s)" value={kw.start} min={0} max={timeline.video.duration}
          onChange={(v) => onChange(patchKeywordTime(timeline, kw.id, { start: v }))} />
        <Num label="Fim (s)" value={kw.end} min={0} max={timeline.video.duration}
          onChange={(v) => onChange(patchKeywordTime(timeline, kw.id, { end: v }))} />
        <h3>Tamanho e posição</h3>
        <p className="hint">Arraste a palavra direto na prévia para posicionar.</p>
        <label>
          Tamanho: {Math.round((kw.scale ?? 1) * 100)}%
          <input
            type="range"
            min={40}
            max={160}
            value={Math.round((kw.scale ?? 1) * 100)}
            onChange={(e) =>
              onChange(patchKeywordProps(timeline, kw.id, { scale: Number(e.target.value) / 100 }))
            }
          />
        </label>
        <label>
          Posição horizontal: {Math.round((kw.x ?? 0.5) * 100)}%
          <input
            type="range"
            min={6}
            max={94}
            value={Math.round((kw.x ?? 0.5) * 100)}
            onChange={(e) =>
              onChange(patchKeywordProps(timeline, kw.id, { x: Number(e.target.value) / 100 }))
            }
          />
        </label>
        <label>
          Posição vertical: {Math.round(((kw.y !== undefined && kw.y >= 0 ? kw.y : 0.2)) * 100)}%
          <input
            type="range"
            min={4}
            max={92}
            value={Math.round((kw.y !== undefined && kw.y >= 0 ? kw.y : 0.2) * 100)}
            onChange={(e) =>
              onChange(patchKeywordProps(timeline, kw.id, { y: Number(e.target.value) / 100 }))
            }
          />
        </label>
        <button className="danger" onClick={onDelete}>Remover palavra-chave</button>
      </aside>
    );
  }

  if (selection.kind === "layout") {
    const l = (timeline.layouts || []).find((x) => x.id === selection.id);
    if (!l) return null;
    return (
      <aside className="properties">
        <h3>Cena (apresentador + painel)</h3>
        <Num label="Início (s)" value={l.start} min={0} max={timeline.video.duration}
          onChange={(v) => onChange(patchLayout(timeline, l.id, { start: v }))} />
        <Num label="Fim (s)" value={l.end} min={0} max={timeline.video.duration}
          onChange={(v) => onChange(patchLayout(timeline, l.id, { end: v }))} />
        <label>
          Lado do seu vídeo (card)
          <select
            value={l.side}
            onChange={(e) => onChange(patchLayout(timeline, l.id, { side: e.target.value }))}
          >
            <option value="left">Esquerda</option>
            <option value="right">Direita</option>
          </select>
        </label>
        <label>
          Título do painel
          <input
            value={l.title}
            maxLength={30}
            onChange={(e) => onChange(patchLayout(timeline, l.id, { title: e.target.value }))}
          />
        </label>
        <label>
          Cartões do painel (um por linha)
          <textarea
            rows={4}
            value={(l.steps || []).join("\n")}
            placeholder={"Deixe vazio para painel só com o título"}
            onChange={(e) =>
              onChange(
                patchLayout(timeline, l.id, {
                  steps: e.target.value.split("\n").filter((s) => s.trim()),
                })
              )
            }
          />
        </label>
        <button className="danger" onClick={onDelete}>Remover cena</button>
      </aside>
    );
  }

  if (selection.kind === "zoom") {
    const z = timeline.zooms.find((x) => x.id === selection.id);
    if (!z) return null;
    return (
      <aside className="properties">
        <h3>Zoom</h3>
        <Num label="Início (s)" value={z.start} min={0} max={timeline.video.duration}
          onChange={(v) => onChange(patchZoom(timeline, z.id, { start: v }))} />
        <Num label="Fim (s)" value={z.end} min={0} max={timeline.video.duration}
          onChange={(v) => onChange(patchZoom(timeline, z.id, { end: v }))} />
        <label>
          Intensidade: {Math.round(z.intensity * 100)}%
          <input
            type="range"
            min={5}
            max={30}
            value={Math.round(z.intensity * 100)}
            onChange={(e) =>
              onChange(patchZoom(timeline, z.id, { intensity: Number(e.target.value) / 100 }))
            }
          />
        </label>
        <button className="danger" onClick={onDelete}>Remover zoom</button>
      </aside>
    );
  }

  if (selection.kind === "sfx") {
    const s = timeline.sfx.find((x) => x.id === selection.id);
    if (!s) return null;
    return (
      <aside className="properties">
        <h3>Efeito sonoro</h3>
        <label>
          Tipo
          <select
            value={s.kind}
            onChange={(e) =>
              onChange({
                ...timeline,
                sfx: timeline.sfx.map((x) =>
                  x.id === s.id ? { ...x, kind: e.target.value } : x
                ),
              })
            }
          >
            {["whoosh", "ding", "impacto", "pop"].map((k) => (
              <option key={k} value={k}>{k}</option>
            ))}
          </select>
        </label>
        <Num label="Momento (s)" value={s.timestamp} min={0} max={timeline.video.duration}
          onChange={(v) =>
            onChange({
              ...timeline,
              sfx: timeline.sfx.map((x) =>
                x.id === s.id ? { ...x, timestamp: v } : x
              ),
            })
          }
        />
        <button className="danger" onClick={onDelete}>Remover efeito</button>
      </aside>
    );
  }

  if (selection.kind === "music") {
    const music = timeline.music;
    return (
      <aside className="properties">
        <h3>Música</h3>
        <MusicPicker timeline={timeline} onChange={onChange} library={library} />
        <p className="hint">{music.label || "Nenhuma trilha selecionada."}</p>
        {music.path && (
          <button
            className="danger"
            onClick={() => onChange({ ...timeline, music: { path: null, label: "", volume: 0.25 } })}
          >
            Remover música
          </button>
        )}
      </aside>
    );
  }

  const music = timeline.music;
  return (
    <aside className="properties">
      <h3>Música</h3>
      <p className="hint">{music.label || "Nenhuma trilha selecionada."}</p>
      <label>
        Volume: {Math.round(music.volume * 100)}%
        <input
          type="range"
          min={0}
          max={100}
          value={Math.round(music.volume * 100)}
          onChange={(e) =>
            onChange({
              ...timeline,
              music: { ...music, volume: Number(e.target.value) / 100 },
            })
          }
        />
      </label>
      {music.path && (
        <button className="danger" onClick={() => onChange({ ...timeline, music: { path: null, label: "", volume: 0.25 } })}>
          Remover música
        </button>
      )}
    </aside>
  );
}

function MusicPicker({
  timeline,
  onChange,
  library,
}: {
  timeline: Timeline;
  onChange: (t: Timeline) => void;
  library: Library | null;
}) {
  const tracks = library?.music ?? [];
  return (
    <>
      <h3>Música de fundo</h3>
      {tracks.length > 0 ? (
        <select
          value={timeline.music.path || ""}
          onChange={(e) => {
            const item = tracks.find((t) => t.path === e.target.value);
            if (!item) return;
            onChange({
              ...timeline,
              music: {
                path: item.path,
                label: item.label,
                volume: timeline.music.volume,
              },
            });
          }}
        >
          <option value="">Nenhuma</option>
          {tracks.map((t) => (
            <option key={t.path} value={t.path}>
              {t.label}
            </option>
          ))}
        </select>
      ) : (
        <p className="hint">
          Nenhuma trilha na biblioteca — conecte o HD do pack ou adicione
          arquivos em assets/music.
        </p>
      )}
      <label>
        Volume: {Math.round(timeline.music.volume * 100)}%
        <input
          type="range"
          min={0}
          max={100}
          value={Math.round(timeline.music.volume * 100)}
          onChange={(e) =>
            onChange({
              ...timeline,
              music: { ...timeline.music, volume: Number(e.target.value) / 100 },
            })
          }
        />
      </label>
    </>
  );
}

function CaptionStylePicker({
  timeline,
  onChange,
  captionStyles,
}: {
  timeline: Timeline;
  onChange: (t: Timeline) => void;
  captionStyles: CaptionStylePreset[];
}) {
  if (captionStyles.length === 0) return null;
  const current = timeline.captionStyle || captionStyles[0].id;
  const scale = timeline.captionScale || 1;
  return (
    <>
      <h3>Estilo da legenda</h3>
      <select
        value={current}
        onChange={(e) => onChange({ ...timeline, captionStyle: e.target.value })}
      >
        {captionStyles.map((s) => (
          <option key={s.id} value={s.id}>
            {s.id} ({s.font_family})
          </option>
        ))}
      </select>
      <label>
        Tamanho: {Math.round(scale * 100)}%
        <input
          type="range"
          min={50}
          max={150}
          value={Math.round(scale * 100)}
          onChange={(e) =>
            onChange({
              ...timeline,
              captionScale: Number(e.target.value) / 100,
            })
          }
        />
      </label>
      <p className="hint">Vale para a prévia e para o render final.</p>
    </>
  );
}

function TransicaoPicker({ timeline, onChange }: { timeline: Timeline; onChange: (t: Timeline) => void }) {
  const [types, setTypes] = useState<string[]>(["corte", "fade", "slideleft", "slideup", "circleopen", "dissolve"]);
  useEffect(() => {
    fetch("/api/transitions")
      .then((r) => r.json())
      .then((d) => setTypes(d.types))
      .catch(() => {});
  }, []);
  return (
    <>
      <h3>Transição</h3>
      <select
        value={timeline.transition.type}
        onChange={(e) =>
          onChange({ ...timeline, transition: { ...timeline.transition, type: e.target.value } })
        }
      >
        {types.map((t) => (
          <option key={t} value={t}>{t}</option>
        ))}
      </select>
      <label>
        Duração: {timeline.transition.duration.toFixed(2)}s
        <input
          type="range"
          min={10}
          max={80}
          value={Math.round(timeline.transition.duration * 100)}
          onChange={(e) =>
            onChange({
              ...timeline,
              transition: { ...timeline.transition, duration: Number(e.target.value) / 100 },
            })
          }
        />
      </label>
    </>
  );
}

function CutTransitionPicker({
  timeline,
  cutId,
  onChange,
}: {
  timeline: Timeline;
  cutId: string;
  onChange: (t: Timeline) => void;
}) {
  const [types, setTypes] = useState<string[]>([
    "corte",
    "fade",
    "slideleft",
    "slideup",
    "circleopen",
    "dissolve",
  ]);
  useEffect(() => {
    fetch("/api/transitions")
      .then((r) => r.json())
      .then((d) => setTypes(d.types))
      .catch(() => {});
  }, []);
  const cut = timeline.cuts.find((c) => c.id === cutId);
  if (!cut) return null;
  const override = cut.transition || null;
  const setOverride = (
    next: { type: string; duration: number } | null
  ) => {
    onChange({
      ...timeline,
      cuts: timeline.cuts.map((c) =>
        c.id === cutId ? { ...c, transition: next } : c
      ),
    });
  };
  return (
    <>
      <h3>Transição deste corte</h3>
      <select
        value={override?.type || ""}
        onChange={(e) => {
          const t = e.target.value;
          setOverride(
            t
              ? { type: t, duration: override?.duration || timeline.transition.duration }
              : null
          );
        }}
      >
        <option value="">Padrão do projeto ({timeline.transition.type})</option>
        {types.map((t) => (
          <option key={t} value={t}>{t}</option>
        ))}
      </select>
      {override && (
        <label>
          Duração: {override.duration.toFixed(2)}s
          <input
            type="range"
            min={10}
            max={80}
            value={Math.round(override.duration * 100)}
            onChange={(e) =>
              setOverride({
                ...override,
                duration: Number(e.target.value) / 100,
              })
            }
          />
        </label>
      )}
      <p className="hint">Vale só para a junção logo após este corte.</p>
    </>
  );
}

function Num({
  label,
  value,
  min,
  max,
  onChange,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  onChange: (v: number) => void;
}) {
  const [text, setText] = useState<string | null>(null);
  return (
    <label className="num-field">
      {label}
      <input
        type="number"
        min={min}
        max={max}
        step={0.05}
        value={text ?? value.toFixed(2)}
        onChange={(e) => {
          setText(e.target.value);
          const v = parseFloat(e.target.value.replace(",", "."));
          if (!Number.isNaN(v)) onChange(Math.min(max, Math.max(min, v)));
        }}
        onBlur={() => setText(null)}
      />
    </label>
  );
}

function patchCut(t: Timeline, id: string, patch: { start?: number; end?: number }): Timeline {
  return {
    ...t,
    cuts: t.cuts
      .map((c) => (c.id === id ? { ...c, ...patch } : c))
      .sort((a, b) => a.start - b.start),
  };
}

function patchCaption(t: Timeline, id: string, text: string): Timeline {
  return {
    ...t,
    captions: t.captions.map((c) => (c.id === id ? { ...c, text } : c)),
  };
}

function patchCallout(t: Timeline, id: string, text: string): Timeline {
  return {
    ...t,
    callouts: t.callouts.map((c) => (c.id === id ? { ...c, text } : c)),
  };
}

function patchCalloutTime(t: Timeline, id: string, patch: { start?: number; end?: number }): Timeline {
  return {
    ...t,
    callouts: t.callouts
      .map((c) => (c.id === id ? { ...c, ...patch } : c))
      .filter((c) => c.end > c.start),
  };
}

function patchKeyword(t: Timeline, id: string, text: string): Timeline {
  return {
    ...t,
    keywords: t.keywords.map((k) => (k.id === id ? { ...k, text } : k)),
  };
}

function patchKeywordStyle(t: Timeline, id: string, style: string): Timeline {
  return {
    ...t,
    keywords: t.keywords.map((k) => (k.id === id ? { ...k, style } : k)),
  };
}

function patchKeywordProps(
  t: Timeline,
  id: string,
  patch: { x?: number; y?: number; scale?: number }
): Timeline {
  return {
    ...t,
    keywords: t.keywords.map((k) => (k.id === id ? { ...k, ...patch } : k)),
  };
}

function patchLayout(
  t: Timeline,
  id: string,
  patch: Partial<{
    start: number;
    end: number;
    side: string;
    title: string;
    steps: string[];
  }>
): Timeline {
  return {
    ...t,
    layouts: (t.layouts || []).map((l) => (l.id === id ? { ...l, ...patch } : l)),
  };
}

function patchKeywordTime(t: Timeline, id: string, patch: { start?: number; end?: number }): Timeline {
  return {
    ...t,
    keywords: t.keywords
      .map((k) => (k.id === id ? { ...k, ...patch } : k))
      .filter((k) => k.end > k.start),
  };
}

function patchZoom(
  t: Timeline,
  id: string,
  patch: { start?: number; end?: number; intensity?: number }
): Timeline {
  return {
    ...t,
    zooms: t.zooms
      .map((z) => (z.id === id ? { ...z, ...patch } : z))
      .filter((z) => z.end > z.start),
  };
}
