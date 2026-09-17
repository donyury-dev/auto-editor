# Auto Editor — Edição de vídeo viral automática com IA

Programa de edição automática no estilo CapCut, focado em automação máxima:
o usuário sobe um vídeo e recebe de volta um vídeo pronto, editado no estilo
"viral/reels", com legendas palavra por palavra queimadas na tela.

**Fase atual: 2** — upload → transcrição (Whisper local) → sugestões de cortes,
zooms e transições → revisão manual obrigatória → renderização → legenda viral
e exportação (vertical, horizontal ou original).

## Requisitos

- Python 3.10+
- FFmpeg instalado e no PATH ([download](https://ffmpeg.org))
  - Ubuntu/Debian: `sudo apt install ffmpeg`
  - macOS: `brew install ffmpeg`
  - Windows: baixe o build em https://ffmpeg.org e adicione ao PATH

## Instalação

```bash
pip install -r requirements.txt        # app
pip install -r requirements-dev.txt    # testes (opcional)
cp .env.example .env                   # opcional (fallback de API key)
```

## Uso

```bash
python main.py
```

1. Arraste um vídeo (ou clique em **Procurar…**)
2. Escolha o formato de saída (vertical 9:16, horizontal 16:9 ou original)
3. Clique em **Editar vídeo automaticamente**
4. O vídeo final é salvo em `output/`

A transcrição roda 100% local com Whisper (gratuito). Se houver GPU CUDA, o
app detecta e usa automaticamente (`float16`); sem GPU, cai para CPU
(`int8`).

## Configurações (menu Configurações → Provedores de IA)

- Escolha o provedor de IA (padrão: **Claude / Anthropic**)
- Insira a API key — salva no **cofre do sistema operacional** (keyring),
  com fallback para arquivo com permissões restritas (`chmod 600`)
- Troque de provedor a qualquer momento, sem perder configurações
- Escolha o modelo do Whisper (`tiny` … `large-v3`)

## Arquitetura

```
main.py                 # Ponto de entrada (UI)
config/settings.py      # Configurações + formato de saída (parâmetro central)
core/
  pipeline.py           # ORQUESTRADOR: transcrever -> legendas -> render -> export
  edit_plan.py          # Plano F2: cortes, zooms, transições e remapeamento de tempo
  transcriber.py        # Motor de transcrição (faster-whisper, GPU auto-detecção)
  subtitle_engine.py    # Motor de legendas (ASS palavra a palavra, estilo viral)
  video_processor.py    # Motor de vídeo (FFmpeg: cortes, zoom, xfade e legendas)
  exporter.py           # Exportação final para output/
ai/
  base_provider.py      # CONTRATO: interface AIProvider (analyze_transcript, etc.)
  claude_provider.py    # Provedor padrão (Anthropic Messages API)
  provider_manager.py   # Troca de provedor dinâmica + API keys seguras (keyring)
ui/
  main_window.py        # Janela principal (pipeline em QThread + progresso)
  review_dialog.py      # Revisão/aprovação manual do plano antes do render
  settings_dialog.py    # Tela de configurações de provedores
tests/                  # Testes unitários (pytest)
logs/                   # Logs de execução (autoeditor.log)
```

### Camada de IA plugável

Todo o programa depende apenas do contrato `AIProvider`
(`ai/base_provider.py`). Para adicionar um provedor novo (GPT, Gemini,
Llama local…):

1. Crie `ai/meu_provider.py` herdando de `AIProvider` e implemente os 4
   métodos do contrato
2. Registre-o em `ProviderManager.register(MeuProvider)`

Nada mais precisa mudar — motores e UI continuam intactos.

### Processamento em thread separada

O pipeline roda em uma `QThread` (`ui/main_window.py`), mantendo a
interface fluida e reportando progresso agregado por etapa (pesos:
análise/transcrição 45%, revisão 10%, renderização 40%, exportação 5%).

## Testes

```bash
python -m pytest tests/ -q
```

## Roadmap

- **Fase 2**: cortes automáticos + zoom automático + transições (em validação)
- **Fase 3**: efeitos sonoros + música de fundo com ducking
- **Fase 4**: inserção automática de imagens durante a fala
- **Fase 5**: múltiplos provedores de IA na tela de configuração
- **Fase 6**: templates de estilo prontos (podcast, motivacional, notícia)

## Notas

- A Claude (IA de linguagem) não faz transcrição nem processa vídeo: ela
  atua sobre o texto já transcrito pelo Whisper. Na Fase 1 o pipeline é
  determinístico; na Fase 2 ela pode sugerir cortes, destaques e zooms,
  sempre passando pela tela de revisão antes do render.
- As transições `xfade` encurtam a timeline em sua duração de sobreposição;
  o plano remapeia as legendas para compensar esse encurtamento.
- Na Fase 3, normalize o volume da voz original antes de aplicar ducking:
  o vídeo de teste apresentou média aproximada de `-34 dB`, baixa para competir
  diretamente com uma música de fundo.
- `temp/`, `output/`, `logs/`, `.env` e `config/providers.json` estão no
  `.gitignore` — nada de segredo ou artefato vai para o Git.
- Para fontes customizadas nas legendas, coloque arquivos `.ttf`/`.otf` em
  `assets/fonts/` (veja o README da pasta).
