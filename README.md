# \Shark3 🦈

Programa para **Windows 10/11** que converte vídeos, playlists e Mix do YouTube em arquivos de áudio
**em todas as qualidades**: MP3, M4A (AAC), Opus, OGG, FLAC, WAV ou o áudio original sem reconverter.
Interface escura (PySide6), fila com downloads simultâneos, tags e capa embutidas e equalizador
paramétrico de 6 bandas. *(Shark3 é um nome provisório: troque em `app/paths.py`, `build.spec` e `installer.iss`.)*

Baseado na especificação do projeto (PySide6 + yt-dlp + FFmpeg + SQLite).

## Como usar (código-fonte)

1. Instale o **Python 3.10+** (marque *Add to PATH*).
2. Dê dois cliques em **`setup.bat`**: cria o ambiente, instala as dependências e baixa o **Deno**.
3. Dê dois cliques em **`run.bat`**.

Cole um link (vídeo, playlist, Mix ou canal), escolha formato/qualidade na barra superior e clique em **Baixar**.
Também dá para arrastar links para a janela.

## Formatos e qualidades

| Formato | Qualidades |
|---|---|
| MP3 | 64–320 kbps (CBR) ou VBR V0/V2/V4 |
| M4A (AAC) | 64–320 kbps |
| Opus | 48–256 kbps |
| OGG (Vorbis) | 64–320 kbps |
| FLAC / WAV | sem perdas / PCM 16 bits |
| Original | copia o áudio do YouTube sem reconverter (m4a ou opus) |

> **Importante:** o YouTube entrega áudio de ~128 kbps (AAC) ou até ~160 kbps (Opus). Converter para 320 kbps
> ou FLAC não melhora a qualidade além da fonte: só aumenta o arquivo. Para o melhor custo-benefício use
> *Original* ou Opus/MP3 em 160–192 kbps.

## Recursos

- Vídeo único, playlist (com janela para escolher faixas), **Mix** (com “♪ Carregar mais…” de 25 a 300 faixas) e canais.
- Fila com 1–8 downloads simultâneos, cancelar, repetir falhas, remover, filtrar; a lista é salva entre execuções.
- Tags (título, artista sem “- Topic”, álbum = playlist, nº da faixa) e capa (opcionalmente recortada em quadrado).
- Subpastas por playlist ou canal, numeração `07 - Título`, nomes seguros para o Windows.
- Arquivo já existe: perguntar / pular / substituir / renomear (com “aplicar a todos”).
- Deduplicação por ID do vídeo e por título + duração (±3 s), em memória e no banco SQLite.
- Normalização de volume (EBU R128) e equalizador (Bell, shelves, passa-altas/baixas) com limitador anti-clipping.
- Cookies do navegador ou `cookies.txt` para quando o YouTube pedir login.

## Requisitos que o YouTube impõe hoje

- **Deno** (ou Node ≥ 22): o yt-dlp precisa de um runtime JavaScript para o YouTube. O `setup.bat`/`build.bat`
  baixam o Deno para `bin\deno.exe`; o instalador já o inclui. Em Configurações > Avançado dá para ver o que foi detectado.
- **yt-dlp atualizado**: se os downloads pararem de funcionar, atualize: `.venv\Scripts\pip install -U "yt-dlp[default]"`
  (versão em código-fonte) ou refaça o build/instalador (versão empacotada não se atualiza sozinha).

## Gerar o executável e o instalador

Execute **`build.bat`**: instala as dependências de build, baixa o Deno, roda o PyInstaller (modo *onedir*) e,
se o [Inno Setup 6](https://jrsoftware.org/isinfo.php) estiver instalado, gera `installer\SharkTune_Setup_1.0.0.exe`.

## Testes

`python tests/smoke_test.py` roda um teste **offline** do pipeline (gera áudio, serve por HTTP local e converte
em todos os formatos conferindo bitrate, tags, capa, EQ, conflitos e organização). Não acessa o YouTube.

## Estrutura

```
main.py                 ponto de entrada (instância única, logs, tema)
app/paths.py            caminhos/constantes (código-fonte e EXE)
app/config.py           configurações em ~/.ytmusic_downloader/config.json
app/database.py         SQLite (WAL, chaves estrangeiras, cascata)
app/audio.py            formatos, qualidades, EQ/DSP, detecção de ffmpeg e Deno
app/workers.py          ExtractTask / DownloadTask (QRunnable) e conversão
app/main_window.py      janela principal, fila, dedupe, conflitos
app/dialogs.py          seleção de faixas e configurações
app/eq_widget.py        equalizador desenhado com QPainter
app/delegates.py, theme.py, thumbs.py, logsetup.py
```

## Problemas comuns

| Sintoma | O que fazer |
|---|---|
| “Confirme que você não é um robô” | Configurações > Avançado: escolha o navegador logado (Firefox costuma ser o mais confiável) ou um `cookies.txt`. |
| “Runtime JavaScript não encontrado” | Rode `setup.bat` (baixa o Deno) ou `winget install DenoLand.Deno`. |
| “Formato não disponível” / falhas gerais | Atualize o yt-dlp (veja acima). |
| Arquivo em uso | Feche o player que está tocando o arquivo a ser substituído. |

Logs e dados: `%USERPROFILE%\.ytmusic_downloader\` (botão em Configurações > Avançado).

## Aviso

Baixe apenas conteúdo que você tem direito de baixar (seu, licenciado, domínio público ou onde os termos permitirem).
O uso é de sua responsabilidade.
