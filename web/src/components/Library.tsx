import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { Library, LibraryItem } from "../types";

interface LibraryProps {
  library: Library | null;
  onPickMusic: (item: LibraryItem) => void;
  onPickSfx: (item: LibraryItem) => void;
  onPickTransition: (t: string) => void;
  transitionType: string;
  transitionTypes: string[];
  onLibraryChanged: () => void;
}

type Tab = "music" | "sfx" | "transition";

export default function LibraryPanel({
  library,
  onPickMusic,
  onPickSfx,
  onPickTransition,
  transitionType,
  transitionTypes,
  onLibraryChanged,
}: LibraryProps) {
  const [tab, setTab] = useState<Tab>("music");
  const [query, setQuery] = useState("");
  const [importing, setImporting] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  async function importMusic(file: File) {
    setImporting(true);
    try {
      await api.uploadMusic(file);
      onLibraryChanged();
    } catch {
      // importação falhou; usuário pode tentar de novo
    } finally {
      setImporting(false);
    }
  }

  useEffect(() => {
    if (library && library.music.length > 0 && tab === "sfx" && library.sfx.length === 0)
      setTab("music");
  }, [library, tab]);

  const filter = (items: LibraryItem[]) =>
    items.filter((i) => i.label.toLowerCase().includes(query.toLowerCase()));

  return (
    <aside className="library">
      <div className="lib-tabs">
        <button className={tab === "music" ? "on" : ""} onClick={() => setTab("music")}>
          Música
        </button>
        <button className={tab === "sfx" ? "on" : ""} onClick={() => setTab("sfx")}>
          SFX
        </button>
        <button
          className={tab === "transition" ? "on" : ""}
          onClick={() => setTab("transition")}
        >
          Transições
        </button>
      </div>
      {tab !== "transition" && (
        <input
          className="lib-search"
          placeholder="Buscar…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      )}
      {tab === "music" && (
        <button
          className="lib-import"
          disabled={importing}
          onClick={() => fileRef.current?.click()}
        >
          {importing ? "Importando…" : "📲 Importar música do celular"}
        </button>
      )}
      <input
        ref={fileRef}
        type="file"
        accept="audio/*"
        style={{ display: "none" }}
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) importMusic(f);
          e.currentTarget.value = "";
        }}
      />
      <div className="lib-list">
        {tab === "music" &&
          (library ? (
            filter(library.music).map((m) => (
              <button
                key={m.path}
                className="lib-item"
                title={m.path}
                onClick={() => onPickMusic(m)}
              >
                <span className="lib-icon">{m.origin === "pack" ? "📁" : m.origin === "do celular" ? "📲" : "🎵"}</span>
                <span className="lib-name">{m.label}</span>
                <span className="lib-origin">{m.origin}</span>
              </button>
            ))
          ) : (
            <p className="lib-empty">Carregando…</p>
          ))}
        {tab === "sfx" &&
          (library && library.sfx.length > 0 ? (
            filter(library.sfx).map((s) => (
              <button
                key={s.path || s.label}
                className="lib-item"
                title={s.path || "Efeito gerado pelo programa"}
                onClick={() => onPickSfx(s)}
              >
                <span className="lib-icon">⚡</span>
                <span className="lib-name">{s.display || s.label}</span>
                {s.origin && <span className="lib-origin">{s.origin}</span>}
              </button>
            ))
          ) : (
            <p className="lib-empty">
              Nenhum SFX disponível — configure a pasta de SFX nas Configurações.
            </p>
          ))}
        {tab === "transition" && (
          <>
            {transitionTypes.map((t) => (
              <button
                key={t}
                className={`lib-item ${t === transitionType ? "selected" : ""}`}
                onClick={() => onPickTransition(t)}
              >
                <span className="lib-icon">🎬</span>
                <span className="lib-name">{transitionLabel(t)}</span>
                {t === transitionType && <span className="lib-origin">ativa</span>}
              </button>
            ))}
          </>
        )}
      </div>
    </aside>
  );
}

function transitionLabel(t: string): string {
  const labels: Record<string, string> = {
    corte: "Corte seco",
    fade: "Fade",
    slideleft: "Deslizar ←",
    slideup: "Deslizar ↑",
    circleopen: "Círculo",
    dissolve: "Dissolver",
    pixelize: "Pixelizar",
    wipeleft: "Varredura ←",
  };
  return labels[t] ?? t;
}
