# Auto Editor — Edição de vídeo viral automática com IA

Programa de edição automática no estilo CapCut, focado em automação máxima:
o usuário sobe um vídeo e recebe de volta um vídeo pronto, editado no estilo
"viral/reels", com legendas palavra por palavra queimadas na tela.

**Fase atual: Pacote standalone** — executável Windows pronto para abrir e
usar, com FFmpeg, modelo Whisper `small` e trilhas de exemplo embutidos.

## Versão "abrir e usar" (Windows)

Baixe e execute o instalador:

```
AutoEditorSetup-1.0.0.exe
```

O instalador cria um atalho no menu iniciar e um desinstalador. Não é
necessário instalar Python, FFmpeg nem baixar modelos. O pacote já inclui:

- Executável do app (PyInstaller)
- FFmpeg estático (`ffmpeg.exe`, `ffprobe.exe`)
- Modelo Whisper `small` para transcrição offline
- 3 trilhas de exemplo sem direitos autorais (calma, energética, neutra)

O instalador ocupa aproximadamente **350-450 MB** no disco (principalmente
pelo modelo Whisper e pelo FFmpeg).

### Aviso do Windows / antivírus

Como o instalador não está assinado com um certificado de assinatura de
código (pago), o Windows pode mostrar a tela **"O Windows protegeu seu PC"**
(SmartScreen). Isso é normal para executáveis independentes. Para prosseguir,
clique em **"Mais informações" → "Executar assim mesmo"**. Nenhum antivírus
deve detectar o app como malicioso, mas o aviso do SmartScreen para
executáveis não assinados é esperado.

### Como baixar o instalador pronto (GitHub Actions)

Você não precisa instalar nada na sua máquina. O instalador é gerado
automaticamente pelo GitHub Actions:

1. Vá até a aba **Actions** do repositório.
2. Escolha o workflow **"Build Windows Installer"**.
3. Clique em **Run workflow**, informe a versão desejada e confirme.
4. Aguarde alguns minutos.
5. Baixe o instalador em:
   - **Aba Releases**: o arquivo `AutoEditorSetup-1.0.0.exe` anexo ao release
     `v1.0.0`.
   - **Ou na aba Actions**: clique no run concluído e baixe o artifact
     `AutoEditorSetup-1.0.0`.

Também é possível fazer push para uma branch `release/*` (ex:
`release/v1.0.0`) — o workflow roda automaticamente e deixa o artifact
pronto para download.

### Como gerar o instalador localmente (opcional)

Se quiser gerar na sua máquina, precisa do Python 3.10+ e do Inno Setup:

```cmd
git clone <repo>
cd auto-editor
build.bat
```

O resultado fica em `dist/AutoEditorSetup-1.0.0.exe`.

> **Importante sobre o repositório Git:** os arquivos grandes (FFmpeg,
> modelo Whisper e trilhas) **não são versionados**. Eles são baixados
> automaticamente pelos scripts durante o build, evitando problemas com o
> limite de 100 MB do GitHub.

## Requisitos para desenvolvimento

- Python 3.10+
- FFmpeg instalado e no PATH ([download](https://ffmpeg.org)) — **não é
  necessário no pacote final**, apenas para desenvolvimento
  - Ubuntu/Debian: `sudo apt install ffmpeg`
  - macOS: `brew install ffmpeg`
  - Windows: baixe o build em https://ffmpeg.org e adicione ao PATH

## Instalação para desenvolvimento

```bash
pip install -r requirements.txt        # app
pip install -r requirements-dev.txt    # testes + PyInstaller
python scripts/download_sample_music.py
```

## Uso

```bash
python main.py
```

1. Arraste um vídeo (ou clique em **Procurar…**)
2. Escolha o formato de saída (vertical 9:16, horizontal 16:9 ou original)
3. (opcional) Escolha um **Template de estilo** no menu Configurações
4. Clique em **Analisar e sugerir edição**
5. Revise as sugestões de cortes, zooms, destaques e áudio
6. O vídeo final é salvo em `output/`

A transcrição roda 100% local com Whisper (gratuito). Se houver GPU CUDA, o
app detecta e usa automaticamente (`float16`); sem GPU, cai para CPU
(`int8`).

## Configurações (menu Configurações)

### Provedores de IA

- Escolha o provedor de IA: **Claude (Anthropic)**, **OpenAI/GPT** ou **Ollama (local)**
- Informe o modelo e, para Ollama/OpenAI compatíveis, uma URL base customizada
- Insira a API key — salva no **cofre do sistema operacional** (keyring),
  com fallback para arquivo com permissões restritas (`chmod 600`)
- Troque de provedor a qualquer momento, sem perder configurações dos demais
- Escolha o modelo do Whisper (`tiny` … `large-v3`)

### Templates de estilo

- Escolha entre presets built-in: **Podcast / Entrevista**, **Motivacional / Viral**
  e **Notícia / Informativo**
- Edite qualquer parâmetro (fonte, cores, ritmo de cortes/zooms, densidade de
  destaques) e **salve como um novo preset customizado**
- O preview estático mostra como a legenda e o call-out ficarão antes de você
  aplicar o template
- Templates built-in não podem ser sobrescritos; para alterá-los, use
  "Salvar como novo…"

## Arquitetura

```
main.py                 # Ponto de entrada (UI)
config/settings.py      # Configurações + formato de saída (parâmetro central)
core/
  pipeline.py           # ORQUESTRADOR: transcrever -> legendas -> render -> export
  edit_plan.py          # Plano F2: cortes, zooms, transições e remapeamento de tempo
  illustration_plan.py  # Momentos revisáveis: imagem, call-out ou nenhum
  callout_engine.py     # Camada ASS de texto grande com pop/fade
  templates.py          # Presets de estilo editáveis e salváveis
  template_preview.py   # Preview estático de legenda/call-out do template
  transcriber.py        # Motor de transcrição (faster-whisper, GPU auto-detecção)
  subtitle_engine.py    # Motor de legendas (ASS palavra a palavra, estilo viral)
  video_processor.py    # Motor de vídeo (FFmpeg: edição, overlays e legendas)
  exporter.py           # Exportação final para output/
ai/
  base_provider.py      # CONTRATO: interface AIProvider (analyze_transcript, etc.)
  claude_provider.py    # Provedor padrão (Anthropic Messages API)
  openai_provider.py    # Provedor OpenAI/GPT e compatíveis
  ollama_provider.py    # Provedor local via servidor Ollama
  provider_manager.py   # Troca de provedor dinâmica + API keys seguras (keyring)
ui/
  main_window.py        # Janela principal (pipeline em QThread + progresso)
  review_dialog.py      # Revisão/aprovação manual de cortes e destaques
  settings_dialog.py    # Tela de configurações de provedores
  templates_dialog.py   # Escolha, edição e preview de templates de estilo
images/                 # Contrato e provedores de imagens/B-roll
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

- **Concluída**: cortes automáticos + zoom por rosto + transições, com revisão
- **Concluída**: áudio com SFX, normalização da voz e ducking da música
- **Concluída**: destaques (call-out de texto, imagem ou nenhum), com revisão por item
- **Concluída**: múltiplos provedores de IA plugáveis na interface
- **Concluída**: templates de estilo editáveis e salváveis (podcast, motivacional, notícia)
- **Futuro**: editor pós-geração para ajustar texto e posição de legendas

## Notas

- A Claude (IA de linguagem) não faz transcrição nem processa vídeo: ela
  atua sobre o texto já transcrito pelo Whisper. Ela pode sugerir cortes,
  destaques e zooms, sempre passando pela tela de revisão antes do render.
- Cada destaque pode ser aprovado como **call-out de texto**, **imagem** ou
  **nenhum**. O call-out usa Archivo Black, contorno forte, entrada com pop e
  fade de saída na faixa superior, separado da legenda contínua.
- A aba **Destaques** permite editar tipo, texto, prompt e timestamps antes da
  renderização; trocar para imagem continua disponível por item.
- As transições `xfade` encurtam a timeline em sua duração de sobreposição;
  o plano remapeia as legendas para compensar esse encurtamento.
- Na Fase 3, normalize o volume da voz original antes de aplicar ducking:
  o vídeo de teste apresentou média aproximada de `-34 dB`, baixa para competir
  diretamente com uma música de fundo.
- `temp/`, `output/`, `logs/`, `.env` e `config/providers.json` estão no
  `.gitignore` — nada de segredo ou artefato vai para o Git.
- Para fontes customizadas nas legendas, coloque arquivos `.ttf`/`.otf` em
  `assets/fonts/` (veja o README da pasta).
