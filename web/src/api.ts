import type { CaptionStylePreset, Library, Timeline } from "./types";

export interface ProviderInfo {
  id: string;
  label: string;
  model: string;
  base_url: string;
  requires_api_key: boolean;
  supports_base_url: boolean;
  has_key: boolean;
}

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
        layouts: timeline.layouts || [],
        hook: timeline.hook,
        music: timeline.music,
        sfx: timeline.sfx,
        caption_style: timeline.captionStyle || "",
        caption_scale: timeline.captionScale || 0,
      }),
    }).then((r) => j<{ ok: boolean }>(r)),

  caption: (id: string) =>
    fetch(`/api/projects/${id}/caption`).then((r) =>
      j<{ caption: string; hashtags: string[]; full_text: string }>(r)
    ),

  instagramConnect: (accessToken: string) =>
    fetch("/api/instagram/connect", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ access_token: accessToken }),
    }).then((r) =>
      j<{ connected: boolean; ig_user_id: string; username: string }>(r)
    ),

  instagramOAuthStart: () =>
    fetch("/api/instagram/oauth/start").then((r) =>
      j<{ url: string; redirect_uri: string }>(r)
    ),

  instagramPublish: (
    id: string,
    body: {
      access_token: string;
      ig_user_id: string;
      media_type: string;
      caption: string;
      token_kind: string;
    }
  ) =>
    fetch(`/api/projects/${id}/instagram/publish`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then((r) =>
      j<{ ok: boolean; media_id: string; permalink: string }>(r)
    ),

  captionStyles: () =>
    fetch("/api/caption-styles").then((r) => j<{ styles: CaptionStylePreset[] }>(r)),

  library: () => fetch("/api/library").then((r) => j<Library>(r)),

  transitions: () =>
    fetch("/api/transitions").then((r) => j<{ types: string[] }>(r)),

  providers: () =>
    fetch("/api/providers").then(
      (r) => j<{ providers: ProviderInfo[]; active: string }>(r)
    ),

  saveProvider: (p: {
    provider_id: string;
    api_key?: string;
    model?: string;
    base_url?: string;
    active?: boolean;
  }) =>
    fetch("/api/providers", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(p),
    }).then((r) => j<{ ok: boolean; providers: ProviderInfo[]; active: string }>(r)),
};

export function openSSE(
  id: string,
  handlers: Record<string, (data: any) => void>,
  onClose?: () => void
): () => void {
  const es = new EventSource(`/api/projects/${id}/events`);
  let lastEventTs = Date.now();
  let failCount = 0;
  for (const [name, fn] of Object.entries(handlers)) {
    es.addEventListener(name, (ev) => {
      lastEventTs = Date.now();
      failCount = 0;
      try {
        fn(JSON.parse((ev as MessageEvent).data));
      } catch {
        /* ignora pings inválidos */
      }
    });
  }
  // Reconexões transitórias são normais no SSE — só tratamos como queda
  // quando o navegador desiste (CLOSED) ou as falhas se repetem sem
  // evento nenhum por mais de 15s (servidor provavelmente morreu).
  es.onopen = () => {
    failCount = 0;
  };
  es.onerror = () => {
    failCount++;
    const dead =
      es.readyState === EventSource.CLOSED ||
      (failCount >= 3 && Date.now() - lastEventTs > 15000);
    if (dead) {
      es.close();
      onClose?.();
    }
  };
  return () => es.close();
}
