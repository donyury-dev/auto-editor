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
  transition?: { type: string; duration: number } | null;
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

export interface KeywordBlock {
  id: string;
  start: number;
  end: number;
  text: string;
  style?: string; // travessia | quebra | grifo | tremor | impacto | ""
  x?: number; // posição horizontal (0..1, fração da largura)
  y?: number; // posição vertical (0..1; <0 = padrão acima da cabeça)
  scale?: number; // multiplicador de tamanho (1 = padrão)
}

export interface LayoutBlock {
  id: string;
  start: number;
  end: number;
  side: string; // "left" | "right" — lado do card do apresentador
  title: string; // título do painel
  steps: string[]; // cartões do painel
  stepImages?: string[]; // ícone (imagem do pack) por cartão
}

export interface SfxBlock {
  id: string;
  kind: string;
  timestamp: number;
  path: string | null;
  origin?: string; // "manual" (biblioteca) | auto (cortes/zooms)
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
  keywords: KeywordBlock[];
  layouts?: LayoutBlock[];
  music: { path: string | null; label: string; volume: number };
  sfx: SfxBlock[];
  captionStyle?: string;
  captionScale?: number;
}

export interface CaptionStylePreset {
  id: string;
  font_family: string;
  font_size_vertical: number;
  font_size_horizontal: number;
  primary_color: string;
  highlight_color: string;
  outline: number;
  uppercase: boolean;
}

export interface LibraryItem {
  path: string;
  label: string;
  origin?: string;
  display?: string; // nome amigável (SFX sintetizados)
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
  | { kind: "keyword"; id: string }
  | { kind: "layout"; id: string }
  | { kind: "zoom"; id: string }
  | { kind: "sfx"; id: string }
  | { kind: "music" }
  | null;
