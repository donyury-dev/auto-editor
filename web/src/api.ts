import type { CaptionStylePreset, Library, Timeline } from "./types";

async function j<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(text);
  }
  return res.json() as Promise<T>;
}

export const api = {
  listFiles: (dir: string) =>
    fetch(`/api/files?dir=${encodeURIComponent(dir)}`).then((r) => j<any>(r)),

  createProject: (path: string) =>
    fetch("/api/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    }).then((r) => j<{ id: string; name: string }>(r)),

  uploadVideo: (file: File, onProgress?: (pct: number) => void) =>
    new Promise<{ path: string; name: string; size: number }>((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", "/api/upload");
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total);
      };
      xhr.onload = () => {
        if (xhr.status >= 200 && xhr.status < 300) {
          try {
            resolve(JSON.parse(xhr.responseText));
          } catch {
            reject(new Error("Resposta inválida do servidor"));
          }
        } else {
          reject(new Error(xhr.responseText || "Falha no envio do vídeo"));
        }
      };
      xhr.onerror = () => reject(new Error("Falha no envio do vídeo"));
      const form = new FormData();
      form.append("file", file);
      xhr.send(form);
    }),

  analyze: (id: string) =>
    fetch(`/api/projects/${id}/analyze`, { method: "POST" }).then((r) =>
      j<{ ok: boolean }>(r)
    ),

  render: (id: string) =>
    fetch(`/api/projects/${id}/render`, { method: "POST" }).then((r) =>
      j<{ ok: boolean }>(r)
    ),

  timeline: (id: string) =>
    fetch(`/api/projects/${id}/timeline`).then((r) =>
      j<{ status: string; timeline: Timeline }>(r)
    ),

  saveTimeline: (id: string, timeline: Timeline) =>
    fetch(`/api/projects/${id}/timeline`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        cuts: timeline.cuts,
        zooms: timeline.zooms,
        transition: timeline.transition,
        captions: timeline.captions,
        callouts: timeline.callouts,
        keywords: timeline.keywords,
        music: timeline.music,
        sfx: timeline.sfx,
        caption_style: timeline.captionStyle || "",
        caption_scale: timeline.captionScale || 0,
      }),
    }).then((r) => j<{ ok: boolean }>(r)),

  captionStyles: () =>
    fetch("/api/caption-styles").then((r) => j<{ styles: CaptionStylePreset[] }>(r)),

  library: () => fetch("/api/library").then((r) => j<Library>(r)),

  transitions: () =>
    fetch("/api/transitions").then((r) => j<{ types: string[] }>(r)),
};

export function openSSE(
  id: string,
  handlers: Record<string, (data: any) => void>,
  onClose?: () => void
): () => void {
  const es = new EventSource(`/api/projects/${id}/events`);
  for (const [name, fn] of Object.entries(handlers)) {
    es.addEventListener(name, (ev) => {
      try {
        fn(JSON.parse((ev as MessageEvent).data));
      } catch {
        /* ignora pings inválidos */
      }
    });
  }
  es.onerror = () => {
    es.close();
    onClose?.();
  };
  return () => es.close();
}
