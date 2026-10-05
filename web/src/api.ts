import type { Library, Timeline } from "./types";

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
        music: timeline.music,
        sfx: timeline.sfx,
      }),
    }).then((r) => j<{ ok: boolean }>(r)),

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
