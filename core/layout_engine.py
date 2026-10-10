"""Cenas de layout "aula": apresentador em card + painel de conceito.

Detecta momentos de explicação/definição na transcrição (heurística,
revisável pelo usuário) e renderiza o layout no vídeo final via FFmpeg:
o apresentador encolhe para um card de um lado e um painel com o título
e os cartões do conceito ocupa o outro, sobre fundo escuro com grade.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from core.edit_plan import LayoutScene

logger = logging.getLogger(__name__)

# gatilhos de fala que costumam introduzir uma explicação/definição
_TRIGGERS = [
    "explicação",
    "explicando",
    "significa",
    "quer dizer",
    "por exemplo",
    "na prática",
    "resumindo",
    "basicamente",
    "ou seja",
    "importante",
    "entenda",
    "conceito",
    "passo",
    "primeiro",
    "como funciona",
    "é isso que",
    "funciona assim",
]

MIN_LAYOUT_S = 4.0  # cena curta demais não dá tempo de ler o painel
GAP_S = 8.0  # distância mínima entre cenas
MAX_LAYOUTS = 3  # teto por vídeo (não virar template)

# ---------------------------------------------------------------- design
BG = "0x12151d"  # fundo escuro
GRID = "0x232837"  # linhas da grade
ACCENT = "0xff6b2b"  # laranja da marca
PANEL_BG = "0x1a1f2b"  # painel
WHITE = "0xFFFFFF"


@dataclass
class _Candidate:
    start: float
    end: float
    score: int
    trigger_idx: int


def _sentence_bounds(words: list, idx: int, duration: float) -> tuple[float, float]:
    """Limites da frase ao redor da palavra idx (pausa > 0.6s = fronteira)."""
    start = words[idx].start
    end = words[idx].end
    j = idx - 1
    while j >= 0 and words[j + 1].start - words[j].end < 0.6:
        start = words[j].start
        j -= 1
    j = idx + 1
    while j < len(words) and words[j].start - words[j - 1].end < 0.6:
        end = words[j].end
        j += 1
    return max(0.0, start), min(duration, end)


def _normalize(text: str) -> str:
    return re.sub(r"[^\wÀ-ÿ ]", " ", text.lower())


def pick_layouts(words: list, duration: float) -> list[LayoutScene]:
    """Escolhe até MAX_LAYOUTS momentos de explicação p/ cena de layout."""
    if not words or duration < MIN_LAYOUT_S + 2:
        return []
    norm = [_normalize(w.text) for w in words]
    candidates: list[_Candidate] = []
    for i, wtext in enumerate(norm):
        hit = next((t for t in _TRIGGERS if t in wtext or t in " ".join(norm[max(0, i - 2): i + 1])), None)
        if hit is None:
            continue
        start, end = _sentence_bounds(words, i, duration)
        # cena precisa ter folga: estende até cobrir MIN_LAYOUT_S
        if end - start < MIN_LAYOUT_S:
            end = min(duration, start + MIN_LAYOUT_S + 1.0)
        if end - start < MIN_LAYOUT_S:
            continue
        candidates.append(_Candidate(start, end, score=len(hit) + len(words) and i, trigger_idx=i))

    # Sem gatilhos na fala → nenhuma cena de layout é criada.
    # (o fallback antigo forçava cenas em todo vídeo e ficava fora de contexto;
    # o usuário pode adicionar a cena manualmente pela timeline)
    candidates.sort(key=lambda c: (-(c.end - c.start)))
    chosen: list[_Candidate] = []
    for c in candidates:
        if len(chosen) >= MAX_LAYOUTS:
            break
        if any(c.start < o.end + GAP_S and o.start < c.end + GAP_S for o in chosen):
            continue
        chosen.append(c)
    chosen.sort(key=lambda c: c.start)

    layouts: list[LayoutScene] = []
    for n, c in enumerate(chosen):
        side = "left" if n % 2 == 0 else "right"
        title, steps = _title_and_steps(words, c.start, c.end)
        layouts.append(
            LayoutScene(
                start=c.start,
                end=c.end,
                side=side,
                title=title,
                steps=steps,
                reason="trecho explicativo detectado na fala",
            )
        )
    return layouts


def _title_and_steps(words: list, start: float, end: float) -> tuple[str, list[str]]:
    """Título e cartões do painel derivados da FALA do trecho.

    O título é a palavra mais forte do trecho (não-genérica) — nada de
    "EXPLICAÇÃO" solto sem contexto. Os cartões recebem a própria frase
    explicativa dividida em blocos curtos (até 3), revelados em progresso.
    """
    ws = [w for w in words if w.start < end and w.end > start]
    tokens = [re.sub(r"[^\wÀ-ÿ-]", "", w.text).strip() for w in ws]
    tokens = [t for t in tokens if t]
    if not tokens:
        return "EXPLICAÇÃO", []

    from core.keyword_engine import MIN_WORD_LEN, STOPWORDS_PT

    strong = [
        t for t in tokens
        if len(t) >= MIN_WORD_LEN + 2 and t.lower() not in STOPWORDS_PT
        and t.lower() not in GENERIC_TITLES
    ]
    pool = strong or [t for t in tokens if len(t) >= MIN_WORD_LEN] or tokens
    title = max(pool, key=len)[:20].upper()

    # cartões: a frase falada dividida em até 3 blocos de ~6 palavras
    texts = [w.text.strip() for w in ws if w.text.strip()]
    n_chunks = min(3, max(1, round(len(texts) / 6)))
    size = max(1, -(-len(texts) // n_chunks))
    steps = []
    for i in range(0, len(texts), size):
        chunk = " ".join(texts[i:i + size]).strip()
        if chunk:
            steps.append(chunk)
    return title, steps[:3]


# palavras genéricas/abstratas que não servem de título de painel
GENERIC_TITLES = {
    "explicação", "explicando", "coisa", "coisas", "gente", "pessoal",
    "vídeo", "palavra", "palavras", "forma", "jeito", "questão", "assunto",
    "ideia", "ponto", "hoje", "agora", "melhor", "tudo", "nada", "verdade",
}


# ----------------------------------------------------------------------
# Render via FFmpeg + PIL
# ----------------------------------------------------------------------

def _render_scene_pngs(
    sc: LayoutScene,
    play_w: int,
    play_h: int,
    fonts_dir,
    out_base: str,
) -> dict:
    """Desenha a cena (fundo, grade, painel, textos) em PNGs via PIL.

    Devolve um dict com as posições do card e os caminhos das camadas:
    `_bg.png` (opaco, com buraco transparente no card), `_panel.png`
    (painel + título, animado separadamente), `_frame.png` (borda do
    card) e um `_step{j}.png` por cartão.
    """
    from PIL import Image, ImageDraw, ImageFont

    gap = int(play_w * 0.03)
    # Card ~9:16 na metade de baixo (como no vídeo modelo): altura ≈ largura
    # * 16/9 garante que o vídeo entre sem zoom — cabeça e ombros visíveis.
    card_w = int(play_w * 0.46)
    card_h = int(card_w * 16 / 9)
    card_y = play_h - card_h - int(play_h * 0.05)
    card_x = (play_w - card_w - gap) if sc.side == "right" else gap
    panel_x = gap if sc.side == "right" else card_w + gap * 2
    panel_w = play_w - card_w - gap * 3

    bg_rgb = (18, 21, 29)
    grid_rgb = (35, 40, 55)
    accent = (255, 107, 43)
    panel_rgb = (26, 31, 43)

    base = Image.new("RGBA", (play_w, play_h), bg_rgb + (255,))
    d = ImageDraw.Draw(base)
    step = max(40, play_w // 12)
    for x in range(0, play_w, step):
        d.line([(x, 0), (x, play_h)], fill=grid_rgb, width=2)
    for y in range(0, play_h, step):
        d.line([(0, y), (play_w, y)], fill=grid_rgb, width=2)

    # painel é uma camada própria para poder deslizar com fade no render
    panel_y = int(play_h * 0.05)
    panel_h = int(play_h * 0.40)
    panel = Image.new("RGBA", (play_w, play_h), (0, 0, 0, 0))
    dp = ImageDraw.Draw(panel)
    dp.rounded_rectangle(
        [panel_x, panel_y, panel_x + panel_w, panel_y + panel_h],
        radius=int(play_w * 0.02),
        fill=panel_rgb + (240,),
        outline=accent,
        width=max(3, play_w // 300),
    )
    # título
    title_size = int(play_w * 0.045)
    f_title = ImageFont.truetype(str(fonts_dir / "Anton-Regular.ttf"), title_size)
    dp.text(
        (panel_x + gap, panel_y + int(play_h * 0.025)),
        sc.title.upper(),
        font=f_title,
        fill=(255, 255, 255),
    )
    dp.line(
        [(panel_x + gap, panel_y + int(play_h * 0.09)),
         (panel_x + panel_w - gap, panel_y + int(play_h * 0.09))],
        fill=accent, width=max(2, play_w // 400),
    )
    # Cartões dos passos (até 3). Cada um vira uma camada própria para que
    # o render revele a explicação progressivamente.
    step_size = int(play_w * 0.030)
    try:
        f_step = ImageFont.truetype(
            str(fonts_dir / "Poppins-ExtraBold.ttf"), step_size
        )
    except OSError:
        f_step = ImageFont.truetype(str(fonts_dir / "Anton-Regular.ttf"), step_size)
    step_paths: list[str] = []
    for j, s in enumerate(sc.steps[:3]):
        cy = panel_y + int(play_h * 0.10) + j * int(play_h * 0.085)
        step = Image.new("RGBA", (play_w, play_h), (0, 0, 0, 0))
        ds = ImageDraw.Draw(step)
        ds.rounded_rectangle(
            [panel_x + gap // 2, cy, panel_x + panel_w - gap // 2,
             cy + int(play_h * 0.070)],
            radius=int(play_w * 0.015),
            fill=accent + (40,),
            outline=accent,
            width=max(2, play_w // 450),
        )
        # ícone do pack (se houver): quadrado à direita do cartão
        img_path = sc.step_images[j] if j < len(sc.step_images) else ""
        text_x = panel_x + gap
        max_text_w = panel_w - gap * 2
        if img_path and Path(img_path).exists():
            side_px = int(play_h * 0.055)
            try:
                icon = Image.open(img_path).convert("RGBA")
                icon.thumbnail((side_px, side_px))
                ix = panel_x + panel_w - gap // 2 - side_px - int(gap * 0.4)
                iy = cy + (int(play_h * 0.070) - icon.height) // 2
                step.alpha_composite(icon, (max(0, ix), max(0, iy)))
                # texto não invade o ícone: reduz a largura disponível
                max_text_w = ix - (panel_x + gap) - int(gap * 0.4)
            except OSError:
                pass  # arquivo corrompido: cartão fica só com texto
        # quebra o texto em até 2 linhas se não couber numa
        if ds.textlength(s, font=f_step) > max_text_w and " " in s:
            words = s.split()
            line1 = ""
            for w_ in words:
                cand = (line1 + " " + w_).strip()
                if ds.textlength(cand, font=f_step) > max_text_w and line1:
                    break
                line1 = cand
            line2 = s[len(line1):].strip()
            ty = cy + int(play_h * 0.006)
            ds.text((text_x, ty), line1, font=f_step, fill=(255, 255, 255))
            ds.text((text_x, ty + int(play_h * 0.028)), line2,
                    font=f_step, fill=(255, 255, 255))
        else:
            ds.text(
                (text_x, cy + int(play_h * 0.014)),
                s, font=f_step, fill=(255, 255, 255),
            )
        step_path = f"{out_base}_step{j}.png"
        step.save(step_path)
        step_paths.append(step_path)

    # buraco transparente onde entra o vídeo do card
    hole = int(max(4, play_w // 240))
    d.rectangle([card_x + hole, card_y + hole,
                 card_x + card_w - hole, card_y + card_h - hole],
                fill=(0, 0, 0, 0))

    # borda arredondada do card: PNG do TAMANHO do card (canto em 0,0) —
    # o overlay posiciona com x animado + card_y (evita offset duplo)
    frame = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
    df = ImageDraw.Draw(frame)
    df.rounded_rectangle(
        [0, 0, card_w - 1, card_h - 1],
        radius=int(play_w * 0.03),
        outline=accent,
        width=max(4, play_w // 240),
    )

    base.save(f"{out_base}_bg.png")
    panel.save(f"{out_base}_panel.png")
    frame.save(f"{out_base}_frame.png")
    return {
        "card_x": card_x,
        "card_w": card_w,
        "card_y": card_y,
        "card_h": card_h,
        "gap": gap,
        "panel_x": panel_x,
        "panel_w": panel_w,
        "steps": step_paths,
        "center_x": (play_w - card_w) // 2,
    }


def apply_layouts(
    video_in,
    video_out,
    layouts: list[LayoutScene],
    play_w: int,
    play_h: int,
    fonts_dir,
    ffmpeg_bin: str = "ffmpeg",
) -> None:
    """Queima as cenas de layout no vídeo final (FFmpeg + overlays PNG).

    O vídeo de entrada é o arquivo já renderizado (tempos pós-cortes) —
    os `start/end` das cenas DEVEM vir remapeados antes desta chamada.
    Usa apenas crop/scale/overlay (o ffmpeg empacotado não tem drawtext).
    """
    import shutil
    import subprocess
    from pathlib import Path

    if not layouts:
        shutil.copyfile(video_in, video_out)
        return

    tmp = Path(video_out).parent
    chains: list[str] = []
    inputs: list[str] = ["-i", str(video_in)]
    n = len(layouts)

    # divide o vídeo original: um stream por cena (p/ recorte do card)
    # + um que segue a cadeia principal dos overlays
    split_out = "".join(f"[src{i}]" for i in range(n)) + "[main0]"
    chains.append(f"[0:v]split={n + 1}{split_out}")

    for i, sc in enumerate(layouts):
        geo = _render_scene_pngs(
            sc, play_w, play_h, Path(fonts_dir), str(tmp / f"lay{i}")
        )
        card_x, card_w = geo["card_x"], geo["card_w"]
        card_y, card_h = geo["card_y"], geo["card_h"]
        base_idx = len(inputs) // 2
        inputs += ["-i", f"{tmp / ('lay%d_bg.png' % i)}"]
        panel_idx = len(inputs) // 2
        inputs += ["-i", f"{tmp / ('lay%d_panel.png' % i)}"]
        frame_idx = len(inputs) // 2
        inputs += ["-i", f"{tmp / ('lay%d_frame.png' % i)}"]

        en = f"between(t,{sc.start:.3f},{sc.end:.3f})"
        # 1) fundo/grade cobrem o frame (com buraco no card)
        chains.append(
            f"[main{i}][{base_idx}:v]overlay=0:0:enable='{en}'[mb{i}]"
        )
        # 2) vídeo original escalado para o card (cabe no card sem zoom:
        #    cabeça + ombros visíveis) e recortado no centro; o apresentador
        #    "sai do centro" deslizando até a posição final (0.6s, ease-out)
        chains.append(
            f"[src{i}]scale={card_w}:{card_h}:force_original_aspect_ratio="
            f"increase,crop={card_w}:{card_h}[cv{i}]"
        )
        slide_dur = 0.6
        # ease-out quadrático: x(t) = final + (inicial-final)*(1-p)^2
        card_x_expr = (
            f"'{card_x}+pow(max(0,({slide_dur}-(t-{sc.start:.3f}))"
            f"/{slide_dur}),2)*({geo['center_x']}-{card_x})'"
        )
        chains.append(
            f"[mb{i}][cv{i}]overlay=x={card_x_expr}:{card_y}:"
            f"enable='{en}'[mc{i}]"
        )
        # 3) borda arredondada do card, acompanhando a posição
        frame_x_expr = (
            f"'{card_x}+pow(max(0,({slide_dur}-(t-{sc.start:.3f}))"
            f"/{slide_dur}),2)*({geo['center_x']}-{card_x})'"
        )
        chains.append(
            f"[mc{i}][{frame_idx}:v]overlay=x={frame_x_expr}:{card_y}:"
            f"enable='{en}'[mf{i}]"
        )
        # 4) painel desliza do lado de fora + fade de entrada (0.5s)
        p_in = (
            f"pow(max(0,1-(t-{sc.start:.3f})/0.5),2)"
        )
        # Com o apresentador à esquerda, o painel entra pela direita; com
        # o apresentador à direita, entra pela esquerda.
        panel_dir = "+" if sc.side == "left" else "-"
        panel_x_expr = (
            f"'{panel_dir}({p_in}*{int(play_w * 0.12)})'"
        )
        chains.append(
            f"[{panel_idx}:v]format=rgba[pf{i}]"
        )
        chains.append(
            f"[mf{i}][pf{i}]overlay=x={panel_x_expr}:0:enable='{en}'[mp{i}]"
        )
        current = f"mp{i}"
        scene_len = max(0.5, sc.end - sc.start)
        for j, step_path in enumerate(geo["steps"]):
            step_idx = len(inputs) // 2
            inputs += ["-i", step_path]
            step_start = sc.start + scene_len * (
                (j + 0.5) / (len(geo["steps"]) + 0.5)
            )
            step_en = f"between(t,{step_start:.3f},{sc.end:.3f})"
            output = f"ms{i}_{j}"
            chains.append(
                f"[{current}][{step_idx}:v]overlay=0:0:"
                f"enable='{step_en}'[{output}]"
            )
            current = output
        chains.append(f"[{current}]null[main{i + 1}]")

    cmd = [
        ffmpeg_bin, "-y", "-loglevel", "error", *inputs,
        "-filter_complex", ";".join(chains) + f";[main{n}]null[out]",
        "-map", "[out]", "-map", "0:a?", "-c:v", "libx264", "-preset", "fast",
        "-crf", "20", "-c:a", "copy", str(video_out),
    ]
    logger.info("Aplicando %d cena(s) de layout", len(layouts))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"FFmpeg (layouts) falhou: {proc.stderr[-800:]}")
