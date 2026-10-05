import { useEffect, useState } from "react";
import { api } from "../api";

interface FileBrowserProps {
  onPick: (path: string) => void;
  onClose: () => void;
}

/** Navegador de arquivos local para escolher o vídeo. */
export default function FileBrowser({ onPick, onClose }: FileBrowserProps) {
  const [dir, setDir] = useState<string>("");
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .listFiles(dir)
      .then(setData)
      .catch((e) => setError(String(e)));
  }, [dir]);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <strong>Escolher vídeo</strong>
          <div className="modal-nav">
            {data?.drives?.length > 0 &&
              data.drives.map((d: string) => (
                <button key={d} onClick={() => setDir(d)}>{d}</button>
              ))}
            {data?.parent && (
              <button onClick={() => setDir(data.parent)}>↑ Subir</button>
            )}
          </div>
        </div>
        <div className="modal-path">{data?.current ?? "…"}</div>
        {error && <p className="error">{error}</p>}
        <div className="modal-list">
          {data?.dirs.map((d: string) => (
            <button
              key={d}
              className="row dir"
              onDoubleClick={() => setDir(joinPath(data.current, d))}
              onClick={() => setDir(joinPath(data.current, d))}
            >
              📁 {d}
            </button>
          ))}
          {data?.videos.map((v: string) => (
            <button
              key={v}
              className="row video"
              onClick={() => onPick(joinPath(data.current, v))}
            >
              🎞 {v}
            </button>
          ))}
          {data && data.dirs.length === 0 && data.videos.length === 0 && (
            <p className="hint">Pasta vazia.</p>
          )}
        </div>
      </div>
    </div>
  );
}

function joinPath(base: string, name: string): string {
  const sep = base.includes("\\") && !base.includes("/") ? "\\" : "/";
  return base.endsWith(sep) ? `${base}${name}` : `${base}${sep}${name}`;
}
