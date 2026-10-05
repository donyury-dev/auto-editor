export interface CaptionWord {
  start: number;
  end: number;
  text: string;
}

export interface CaptionChunk {
  id: string;
  start: number;
  end: number;
  text: string;
  words: CaptionWord[];
}

export interface CutBlock {
  id: string;
  start: number;
  end: number;
  reason?: string;
}

export interface ZoomBlock {
  id: string;
  start: number;
  end: number;
  intensity: number;
}

export interface CalloutBlock {
  id: string;
  start: number;
  end: number;
  text: string;
}

export interface SfxBlock {
  id: string;
  kind: string;
  timestamp: number;
  path: string | null;
}

export interface Timeline {
  video: {
    path: string;
    duration: number;
    width: number;
    height: number;
  };
  cuts: CutBlock[];
  zooms: ZoomBlock[];
  transition: { type: string; duration: number };
  captions: CaptionChunk[];
  callouts: CalloutBlock[];
  music: { path: string | null; label: string; volume: number };
  sfx: SfxBlock[];
}

export interface LibraryItem {
  path: string;
  label: string;
  origin?: string;
}

export interface Library {
  music: LibraryItem[];
  sfx: LibraryItem[];
  pack: Record<string, { path: string; label: string }[]>;
}

export type Selection =
  | { kind: "cut"; id: string }
  | { kind: "caption"; id: string }
  | { kind: "callout"; id: string }
  | { kind: "music" }
  | null;
