import { useCallback, useEffect, useRef, useState } from "react";
import { api, openSSE } from "./api";
import type {
  CaptionStylePreset,
  Library,
  LibraryItem,
  Selection,
  Timeline,
} from "./types";
import Player from "./components/Player";
import TimelineView from "./components/Timeline";
import LibraryPanel from "./components/Library";
import PropertiesPanel from "./components/Properties";
import FileBrowser from "./components/FileBrowser";
import ProviderModal from "./components/ProviderModal";

type Screen = "home" | "busy" | "editor";

export default function App() {
  const [screen, setScreen] = useState<Screen>("home");
  const [projectId, setProjectId] = useState<string | null>(null);
  const [progress, setProgress] = useState({ overall: 0, step: "", msg: "" });
  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const [selection, setSelection] = useState<Selection>(null);
  const [library, setLibrary] = useState<Library | null>(null);
  const [captionStyles, setCaptionStyles] = useState<CaptionStylePreset[]>([]);
  const [resultMode, setResultMode] = useState(true);
  const [muted, setMuted] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [zoom, setZoom] = useState(1);
  const [showBrowser, setShowBrowser] = useState(false);
  const [showProviders, setShowProviders] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [rendering, setRendering] = useState(false);
  const [renderDone, setRenderDone] = useState(false);
  const [error, setError] = useState("");
  const videoRef = useRef<HTMLVideoElement>(null);
  const closeSSE = useRef<(() => void) | null>(null);

  useEffect(() => {
    api.library().then(setLibrary).catch(() => {});
    api.captionStyles().then((d) => setCaptionStyles(d.styles)).catch(() => {});
  }, [projectId]);

  // Reabre um projeto existente via URL: /?p=<projectId>
  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("p");
    if (!id) return;
    setProjectId(id);
    api
      .timeline(id)
      .then((res) => {
        setTimeline(res.timeline);
        setScreen("editor");
      })
      .catch(() => {});
  }, []);

  useEffect(
    () => () => {
      closeSSE.current?.();
    },
    []
  );

  const startSSE = useCallback((id: string, mode: "analyze" | "render") => {
    closeSSE.current?.();
    closeSSE.current = openSSE(
      id,
      {
        progress: (d: any) =>
          setProgress({ overall: d.overall, step: d.step, msg: d.msg }),
        timeline: (d: any) => {
          setTimeline(d.timeline);
          setScreen("editor");
        },
        status: (d: any) => {
          if (d.status === "ready") setScreen("editor");
        },
        done: () => {
          setRendering(false);
          setRenderDone(true);
        },
        error: (d: any) => {
          setError(d.message);
          setRendering(false);
        },
      },
      () => {}
    );
  }, []);

  const startAnalysis = async (path: string) => {
    setError("");
    try {
      const p = await api.createProject(path);
      setProjectId(p.id);
      setScreen("busy");
      setProgress({ overall: 0, step: "", msg: "iniciando…" });
      startSSE(p.id, "analyze");
      await api.analyze(p.id);
    } catch (e: any) {
      setError(String(e.message || e));
      setScreen("home");
    }
  };

  const handleFile = async (file: File) => {
    setError("");
    setScreen("busy");
    setProgress({ overall: 0, step: "Enviando vídeo", msg: file.name });
    try {
      const res = await api.uploadVideo(file, (pct) =>
        setProgress({
          overall: pct * 0.5,
          step: "Enviando vídeo",
          msg: `${file.name} — ${Math.round(pct * 100)}%`,
        })
      );
      await startAnalysis(res.path);
    } catch (e: any) {
      setError(String(e.message || e));
      setScreen("home");
    }
  };

  const pickVideo = async (path: string) => {
    setShowBrowser(false);
    await startAnalysis(path);
  };

  const commit = async (next: Timeline) => {
    setTimeline(next);
    if (projectId) api.saveTimeline(projectId, next).catch(() => {});
  };

  const doRender = async () => {
    if (!projectId) return;
    setError("");
    setRenderDone(false);
    setRendering(true);
    setProgress({ overall: 0, step: "", msg: "preparando render…" });
    startSSE(projectId, "render");
    try {
      await api.render(projectId);
    } catch (e: any) {
      setError(String(e.message || e));
      setRendering(false);
    }
  };

  const togglePlay = () => {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused) {
      v.play();
      setPlaying(true);
    } else {
      v.pause();
      setPlaying(false);
    }
  };

  const addCutHere = () => {
    if (!timeline || !videoRef.current) return;
    const t = videoRef.current.currentTime;
    const end = Math.min(t + 2, timeline.video.duration);
    const id = `c${Date.now().toString(36)}`;
    commit({
      ...timeline,
      cuts: [...timeline.cuts, { id, start: t, end, reason: "corte manual" }].sort(
        (a, b) => a.start - b.start
      ),
    });
    setSelection({ kind: "cut", id });
  };

  const addCalloutHere = () => {
    if (!timeline || !videoRef.current) return;
    const t = videoRef.current.currentTime;
    const end = Math.min(t + 2.5, timeline.video.duration);
    const id = `o${Date.now().toString(36)}`;
    commit({
      ...timeline,
      callouts: [
        ...timeline.callouts,
        { id, start: t, end, text: "Destaque" },
      ],
    });
    setSelection({ kind: "callout", id });
  };

  const addKeywordHere = () => {
    if (!timeline || !videoRef.current) return;
    const t = videoRef.current.currentTime;
    const end = Math.min(t + 1.5, timeline.video.duration);
    const id = `w${Date.now().toString(36)}`;
    commit({
      ...timeline,
      keywords: [
        ...timeline.keywords,
        { id, start: t, end, text: "PALAVRA" },
      ],
    });
    setSelection({ kind: "keyword", id });
  };

  const moveKeyword = useCallback((id: string, x: number, y: number) => {
    setTimeline(
      (t) =>
        t && {
          ...t,
          keywords: t.keywords.map((k) => (k.id === id ? { ...k, x, y } : k)),
        }
    );
  }, []);

  const moveKeywordEnd = useCallback(() => {
    setTimeline((t) => {
      if (t && projectId) api.saveTimeline(projectId, t).catch(() => {});
      return t;
    });
  }, [projectId]);

  const selectKeyword = useCallback((id: string) => {
    setSelection({ kind: "keyword", id });
  }, []);

  const deleteSelection = () => {
    if (!timeline || !selection) return;
    if (selection.kind === "cut") {
      commit({ ...timeline, cuts: timeline.cuts.filter((c) => c.id !== selection.id) });
    } else if (selection.kind === "callout") {
      commit({
        ...timeline,
        callouts: timeline.callouts.filter((c) => c.id !== selection.id),
      });
    } else if (selection.kind === "keyword") {
      commit({
        ...timeline,
        keywords: timeline.keywords.filter((k) => k.id !== selection.id),
      });
    } else if (selection.kind === "zoom") {
      commit({
        ...timeline,
        zooms: timeline.zooms.filter((z) => z.id !== selection.id),
      });
    } else if (selection.kind === "sfx") {
      commit({
        ...timeline,
        sfx: timeline.sfx.filter((s) => s.id !== selection.id),
      });
    } else if (selection.kind === "layout") {
      commit({
        ...timeline,
        layouts: (timeline.layouts || []).filter((l) => l.id !== selection.id),
      });
    }
    setSelection(null);
  };

  const addLayoutHere = () => {
    if (!timeline || !videoRef.current) return;
    const t = videoRef.current.currentTime;
    const end = Math.min(t + 5, timeline.video.duration);
    const id = `l${Date.now().toString(36)}`;
    const n = (timeline.layouts || []).length;
    commit({
      ...timeline,
      layouts: [
        ...(timeline.layouts || []),
        {
          id,
          start: t,
          end,
          side: n % 2 === 0 ? "left" : "right",
          title: "EXPLICAÇÃO",
          steps: [],
        },
      ],
    });
    setSelection({ kind: "layout", id });
  };

  const pickMusic = (item: LibraryItem) => {
    if (!timeline) return;
    commit({
      ...timeline,
      music: { path: item.path, label: item.label, volume: timeline.music.volume },
    });
    setSelection({ kind: "music" });
  };

  const pickSfx = (item: LibraryItem) => {
    if (!timeline || !videoRef.current) return;
    const t = videoRef.current.currentTime;
    const id = `s${Date.now().toString(36)}`;
    commit({
      ...timeline,
      sfx: [
        ...timeline.sfx,
        {
          id,
          kind: item.label,
          timestamp: t,
          path: item.path || null,
          origin: "manual",
        },
      ].sort((a, b) => a.timestamp - b.timestamp),
    });
  };

  const pickTransition = (t: string) => {
    if (!timeline) return;
    commit({ ...timeline, transition: { ...timeline.transition, type: t } });
  };

  if (screen === "home") {
    return (
      <div
        className="home"
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          const file = e.dataTransfer.files?.[0];
          if (file) handleFile(file);
        }}
      >
        <div className="home-card">
          <h1>Auto Editor</h1>
          <p className="subtitle">Edição viral com IA — cortes, legendas, call-outs e trilha</p>
          <label className={`dropzone ${dragging ? "active" : ""}`}>
            <input
              type="file"
              accept="video/*"
              style={{ display: "none" }}
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) handleFile(file);
                e.currentTarget.value = "";
              }}
            />
            <span className="dropzone-icon">⬆</span>
            <strong>Arraste um vídeo aqui</strong>
            <span className="hint">ou clique para escolher do seu computador</span>
          </label>
          <button className="ghost" onClick={() => setShowBrowser(true)}>
            Escolher por pastas (sem copiar o arquivo)
          </button>
          <button className="ghost" onClick={() => setShowProviders(true)}>
            ⚙ Configurar IA (Claude, ChatGPT ou local)
          </button>
          <p className="hint">
            O vídeo é analisado localmente: transcrição, cortes, legendas e
            sugestões — tudo antes de você revisar na timeline.
          </p>
          {error && <p className="error">{error}</p>}
        </div>
        {showBrowser && (
          <FileBrowser onPick={pickVideo} onClose={() => setShowBrowser(false)} />
        )}
        {showProviders && (
          <ProviderModal onClose={() => setShowProviders(false)} />
        )}
      </div>
    );
  }

  if (screen === "busy") {
    return (
      <div className="home">
        <div className="home-card">
          <div className="ai-badge">
            <span className="dot" /> IA editando
          </div>
          <h2>{progress.step || "Analisando"}</h2>
          <p className="hint">{progress.msg}</p>
          <div className="progress">
            <div
              className="progress-fill"
              style={{ width: `${Math.round(progress.overall * 100)}%` }}
            />
          </div>
          <p className="pct">{Math.round(progress.overall * 100)}%</p>
          {error && <p className="error">{error}</p>}
        </div>
      </div>
    );
  }

  if (!timeline) {
    return (
      <div className="home">
        <div className="home-card">
          <p>Carregando timeline…</p>
          {error && <p className="error">{error}</p>}
        </div>
      </div>
    );
  }

  return (
    <div className="editor">
      <header className="topbar">
        <span className="logo">Auto Editor</span>
        <div className="spacer" />
        <button className="ghost" onClick={() => setShowProviders(true)}>
          ⚙ IA
        </button>
        <button className="accent" onClick={doRender} disabled={rendering}>
          {rendering ? "Renderizando…" : "Renderizar"}
        </button>
      </header>

      {rendering && (
        <div className="render-bar">
          <div className="ai-badge small">
            <span className="dot" /> IA editando
          </div>
          <div className="progress inline">
            <div
              className="progress-fill"
              style={{ width: `${Math.round(progress.overall * 100)}%` }}
            />
          </div>
          <span className="hint">
            {progress.step} — {Math.round(progress.overall * 100)}%
          </span>
        </div>
      )}
      {renderDone && (
        <div className="render-bar ok">
          Vídeo pronto!{" "}
          <a href={`/api/projects/${projectId}/output`} download>
            Baixar MP4
          </a>
        </div>
      )}
      {error && <div className="render-bar fail">{error}</div>}
      {showProviders && (
        <ProviderModal onClose={() => setShowProviders(false)} />
      )}

      <div className="main">
        <LibraryPanel
          library={library}
          onPickMusic={pickMusic}
          onPickSfx={pickSfx}
          onPickTransition={pickTransition}
          transitionType={timeline.transition.type}
          transitionTypes={[]}
        />
        <div className="center">
          <Player
            videoUrl={`/api/projects/${projectId}/video`}
            timeline={timeline}
            resultMode={resultMode}
            muted={muted}
            videoRef={videoRef}
            captionStyles={captionStyles}
            onKeywordMove={moveKeyword}
            onKeywordMoveEnd={moveKeywordEnd}
            onSelectKeyword={selectKeyword}
          />
          <div className="controls">
            <button onClick={togglePlay} className="primary">
              {playing ? "⏸ Pausar" : "▶ Play"}
            </button>
            <label className="toggle">
              <input
                type="checkbox"
                checked={resultMode}
                onChange={(e) => setResultMode(e.target.checked)}
              />
              Prévia do resultado
            </label>
            <label className="toggle">
              <input
                type="checkbox"
                checked={muted}
                onChange={(e) => setMuted(e.target.checked)}
              />
              Mudo
            </label>
            <button onClick={addCutHere}>+ Corte aqui</button>
            <button onClick={addCalloutHere}>+ Call-out aqui</button>
            <button onClick={addKeywordHere}>+ Palavra-chave aqui</button>
            <button onClick={addLayoutHere}>+ Cena aqui</button>
            {selection && (
              <button className="danger" onClick={deleteSelection}>
                Excluir seleção
              </button>
            )}
            <div className="spacer" />
            <label className="zoom">
              Zoom
              <input
                type="range"
                min={1}
                max={20}
                value={zoom}
                onChange={(e) => setZoom(Number(e.target.value))}
              />
            </label>
          </div>
        </div>
        <PropertiesPanel
          timeline={timeline}
          selection={selection}
          onChange={commit}
          onDelete={deleteSelection}
          captionStyles={captionStyles}
          library={library}
        />
      </div>

      <div className="timeline-area">
        <TimelineView
          timeline={timeline}
          selection={selection}
          onSelect={setSelection}
          onCommit={commit}
          videoRef={videoRef}
          zoom={zoom}
        />
      </div>
    </div>
  );
}
