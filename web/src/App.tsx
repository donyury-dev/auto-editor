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
import CaptionEditor from "./components/CaptionEditor";
import InstagramPublishModal from "./components/InstagramPublishModal";

type Screen = "home" | "busy" | "editor";
type MobileTab = "preview" | "edit" | "tools";

function EditorApp() {
  const [screen, setScreen] = useState<Screen>("home");
  const [projectId, setProjectId] = useState<string | null>(null);
  const [progress, setProgress] = useState({ overall: 0, step: "", msg: "" });
  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const [selection, setSelection] = useState<Selection>(null);
  const [library, setLibrary] = useState<Library | null>(null);
  const [transitionTypes, setTransitionTypes] = useState<string[]>([]);
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
  const [publishCaption, setPublishCaption] = useState("");
  const [publishHashtags, setPublishHashtags] = useState("");
  const [showPublish, setShowPublish] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [mTab, setMTab] = useState<MobileTab>("preview");
  const [isMobile, setIsMobile] = useState(
    typeof window !== "undefined" && window.matchMedia("(max-width: 768px)").matches
  );

  useEffect(() => {
    const mq = window.matchMedia("(max-width: 768px)");
    const fn = () => setIsMobile(mq.matches);
    mq.addEventListener("change", fn);
    return () => mq.removeEventListener("change", fn);
  }, []);
  const videoRef = useRef<HTMLVideoElement>(null);
  const closeSSE = useRef<(() => void) | null>(null);
  const screenRef = useRef<Screen>("home");
  const renderingRef = useRef(false);
  const gotErrorRef = useRef(false);
  const wakeRef = useRef<any>(null);
  const lastFileRef = useRef<File | null>(null);

  useEffect(() => {
    screenRef.current = screen;
  }, [screen]);
  useEffect(() => {
    renderingRef.current = rendering;
  }, [rendering]);

  // Mantém a tela do celular acesa durante upload/análise/renderização
  const requestWake = useCallback(async () => {
    try {
      if ("wakeLock" in navigator && !wakeRef.current) {
        wakeRef.current = await (navigator as any).wakeLock.request("screen");
        wakeRef.current.addEventListener("release", () => {
          wakeRef.current = null;
        });
      }
    } catch {
      // Wake Lock indisponível — segue o fluxo normal
    }
  }, []);
  const releaseWake = useCallback(() => {
    try {
      wakeRef.current?.release();
    } catch {
      // nada a liberar
    }
    wakeRef.current = null;
  }, []);

  useEffect(() => {
    if (screen === "busy" || rendering) requestWake();
    else releaseWake();
    return () => releaseWake();
  }, [screen, rendering, requestWake, releaseWake]);

  // Readquire o lock se o usuário voltar para a aba
  useEffect(() => {
    const onVis = () => {
      if (document.visibilityState === "visible" && (screenRef.current === "busy" || renderingRef.current))
        requestWake();
    };
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, [requestWake]);

  const reloadLibrary = useCallback(() => {
    api.library().then(setLibrary).catch(() => {});
  }, []);

  useEffect(() => {
    reloadLibrary();
    api.transitions().then((d) => setTransitionTypes(d.types)).catch(() => {});
    api.captionStyles().then((d) => setCaptionStyles(d.styles)).catch(() => {});
  }, [projectId, reloadLibrary]);

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
    gotErrorRef.current = false;
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
          gotErrorRef.current = true;
          setError(d.message);
          setRendering(false);
        },
      },
      () => {
        // Conexão caiu sem evento de erro/done — o worker provavelmente
        // morreu (ex.: servidor sem memória). Avisa em vez de travar.
        if (gotErrorRef.current) return;
        if (screenRef.current === "busy") {
          setError(
            "A análise foi interrompida (o servidor pode ter ficado sem memória). Tente novamente — foi escolhido automaticamente um modelo de transcrição mais leve."
          );
          setScreen("home");
        } else if (renderingRef.current) {
          setError(
            "A renderização foi interrompida (o servidor pode ter ficado sem memória). Tente novamente."
          );
          setRendering(false);
        }
      }
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
    lastFileRef.current = file;
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
      setError(
        String(e.message || e).includes("Falha no envio")
          ? "O envio do vídeo foi interrompido (a tela do celular pode ter apagado ou a internet caiu). O sistema já tenta manter a tela acesa — toque em Tentar novamente."
          : String(e.message || e)
      );
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
          {error && lastFileRef.current && (
            <button className="accent" onClick={() => handleFile(lastFileRef.current!)}>
              Tentar novamente
            </button>
          )}
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
          {error && (
            <>
              <p className="error">{error}</p>
              <button className="ghost" onClick={() => setScreen("home")}>
                Voltar
              </button>
              {lastFileRef.current && (
                <button className="accent" onClick={() => handleFile(lastFileRef.current!)}>
                  Tentar novamente
                </button>
              )}
            </>
          )}
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
        <div>
          <span className="logo">Auto Editor</span>
          <span className="editor-subtitle">Revisão do seu vídeo</span>
        </div>
        <div className="spacer" />
        <button className="ghost desktop-only" onClick={() => setShowAdvanced((v) => !v)}>
          {showAdvanced ? "Ocultar ferramentas" : "Mais ferramentas"}
        </button>
        <button className="accent" onClick={doRender} disabled={rendering}>
          {rendering ? "Preparando vídeo…" : "Gerar vídeo final"}
        </button>
      </header>

      <div className="editor-guide">
        <div className="guide-step active"><b>1</b><span>Confira a prévia</span></div>
        <div className="guide-line" />
        <div className="guide-step"><b>2</b><span>Ajuste se quiser</span></div>
        <div className="guide-line" />
        <div className="guide-step"><b>3</b><span>Gere e publique</span></div>
      </div>

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
          <div className="render-done-row">
            <span>Vídeo pronto!</span>
            <a className="download-button" href={`/api/projects/${projectId}/output`} download>
              Baixar vídeo
            </a>
            <button
              className="accent"
              onClick={() => setShowPublish(true)}
            >
              Publicar nas redes
            </button>
          </div>
          <CaptionEditor
            projectId={projectId!}
            onCaptionChange={(c, h) => {
              setPublishCaption(c);
              setPublishHashtags(h);
            }}
          />
        </div>
      )}
      {showPublish && projectId && (
        <InstagramPublishModal
          projectId={projectId}
          initialCaption={`${publishCaption}\n\n${publishHashtags}`.trim()}
          onClose={() => setShowPublish(false)}
        />
      )}
      {error && <div className="render-bar fail">{error}</div>}
      {timeline?.warning && (
        <div className="render-bar warn">{timeline.warning}</div>
      )}
      {showProviders && (
        <ProviderModal onClose={() => setShowProviders(false)} />
      )}

      <div className={`main ${isMobile ? `m-${mTab}` : "desktop"}`}>
        {!isMobile && showAdvanced && (
          <LibraryPanel
            library={library}
            onPickMusic={pickMusic}
            onPickSfx={pickSfx}
            onPickTransition={pickTransition}
            transitionType={timeline.transition.type}
            transitionTypes={transitionTypes}
            onLibraryChanged={reloadLibrary}
          />
        )}
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
              {playing ? "⏸ Pausar prévia" : "▶ Reproduzir prévia"}
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
            {!isMobile && showAdvanced && <><button onClick={addCutHere}>+ Adicionar corte</button>
            <button onClick={addCalloutHere}>+ Adicionar texto</button>
            <button onClick={addKeywordHere}>+ Palavra em destaque</button>
            <button onClick={addLayoutHere}>+ Adicionar cena</button></>}
            {selection && !isMobile && (
              <button className="danger" onClick={deleteSelection}>
                Excluir seleção
              </button>
            )}
            <div className="spacer" />
            {isMobile ? (
              <div className="zoom-btns">
                <button aria-label="Menos zoom" onClick={() => setZoom((z) => Math.max(1, z / 1.4))}>
                  ➖
                </button>
                <button aria-label="Mais zoom" onClick={() => setZoom((z) => Math.min(30, z * 1.4))}>
                  🔍➕
                </button>
              </div>
            ) : (
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
            )}
          </div>
        </div>
        {!isMobile &&
          (showAdvanced ? (
            <PropertiesPanel
              timeline={timeline}
              selection={selection}
              onChange={commit}
              onDelete={deleteSelection}
              captionStyles={captionStyles}
              library={library}
            />
          ) : (
            <aside className="properties simple-help">
              <h3>Como editar</h3>
              <p>1. Aperte <b>Reproduzir prévia</b> para assistir.</p>
              <p>2. Arraste a linha azul para navegar.</p>
              <p>3. Abra <b>Mais ferramentas</b> apenas quando precisar ajustar cortes, textos, música ou transições.</p>
              <button className="ghost" onClick={() => setShowAdvanced(true)}>Abrir ferramentas de edição</button>
            </aside>
          ))}
      </div>

      <div className={`timeline-area ${isMobile && mTab !== "preview" ? "m-short" : ""}`}>
        <TimelineView
          timeline={timeline}
          selection={selection}
          onSelect={setSelection}
          onCommit={commit}
          videoRef={videoRef}
          zoom={zoom}
          onZoom={setZoom}
        />
      </div>

      {isMobile && mTab !== "preview" && (
        <div className="bottom-sheet">
          {mTab === "edit" ? (
            <PropertiesPanel
              timeline={timeline}
              selection={selection}
              onChange={commit}
              onDelete={deleteSelection}
              captionStyles={captionStyles}
              library={library}
            />
          ) : (
            <>
              <LibraryPanel
                library={library}
                onPickMusic={pickMusic}
                onPickSfx={pickSfx}
                onPickTransition={pickTransition}
                transitionType={timeline.transition.type}
                transitionTypes={transitionTypes}
                onLibraryChanged={reloadLibrary}
              />
              <div className="m-actions">
                <p className="m-actions-title">Adicionar no ponto atual do vídeo</p>
                <button onClick={addCutHere}>✂️ Corte aqui</button>
                <button onClick={addCalloutHere}>📝 Texto explicativo</button>
                <button onClick={addKeywordHere}>🔥 Palavra em destaque</button>
                <button onClick={addLayoutHere}>🎬 Cena explicativa</button>
                {selection && (
                  <button className="danger" onClick={deleteSelection}>
                    🗑️ Excluir seleção
                  </button>
                )}
              </div>
            </>
          )}
        </div>
      )}

      {isMobile && (
        <nav className="mobile-nav">
          <button className={mTab === "preview" ? "on" : ""} onClick={() => setMTab("preview")}>
            ▶ Prévia
          </button>
          <button className={mTab === "edit" ? "on" : ""} onClick={() => setMTab(mTab === "edit" ? "preview" : "edit")}>
            ⚙ Ajustes
          </button>
          <button className={mTab === "tools" ? "on" : ""} onClick={() => setMTab(mTab === "tools" ? "preview" : "tools")}>
            🎵 Ferramentas
          </button>
        </nav>
      )}
    </div>
  );
}

export default function App() {
  const [accessState, setAccessState] = useState<"checking" | "allowed" | "denied">("checking");
  const [accessMessage, setAccessMessage] = useState("");

  useEffect(() => {
    const token = new URLSearchParams(window.location.search).get("access_token") ?? "";
    fetch(`/api/access${token ? `?access_token=${encodeURIComponent(token)}` : ""}`)
      .then(async (res) => {
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          throw new Error(body.error || "Acesso não liberado.");
        }
        setAccessState("allowed");
      })
      .catch((err) => {
        setAccessMessage(err instanceof Error ? err.message : "Acesso não liberado.");
        setAccessState("denied");
      });
  }, []);

  if (accessState === "checking") {
    return <div className="home"><div className="home-card"><p>Verificando acesso…</p></div></div>;
  }
  if (accessState === "denied") {
    return (
      <div className="home">
        <div className="home-card">
          <h1>Acesso ao editor bloqueado</h1>
          <p className="subtitle">{accessMessage}</p>
          <p className="hint">
            Peça ao administrador da plataforma para liberar o Editor de Vídeo no painel central
            (Gestão da Plataforma → Clientes → Editor → +30 dias / Permanente).
          </p>
          <button
            className="btn-primary"
            onClick={() => window.location.reload()}
            style={{ marginTop: 16 }}
          >
            Tentar novamente
          </button>
        </div>
      </div>
    );
  }
  return <EditorApp />;
}
