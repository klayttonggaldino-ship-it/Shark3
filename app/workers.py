"""Tarefas em segundo plano (QRunnable): ExtractTask e DownloadTask.

Decisões importantes (ver especificação):
- QRunnable + QThreadPool (setAutoDelete(False)) em vez de QThread.
- Nada de atualizar a UI aqui: só emitir signals (e checar shiboken6.isValid antes).
- A conversão é feita por um postprocessor próprio (ConvertAudioPP), que aplica
  formato/bitrate/EQ/loudnorm só ao áudio e nunca "vaza" argumentos para outros passos.
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
import urllib.parse
from pathlib import Path

import shiboken6
import yt_dlp
from PySide6.QtCore import QObject, QRunnable, Signal
from yt_dlp.postprocessor import EmbedThumbnailPP, FFmpegMetadataPP
from yt_dlp.postprocessor.ffmpeg import FFmpegPostProcessor
from yt_dlp.utils import DownloadCancelled, PostProcessingError, parse_bytes

from . import audio
from .paths import TMP_DIR

log = logging.getLogger("workers")
MAX_PLAYLIST = 3000


class UserCancelled(DownloadCancelled):
    msg = "Cancelado pelo usuário"


# ----------------------------------------------------------------------------- signals
class ExtractSignals(QObject):
    done = Signal(int, dict)      # req_id, resultado
    failed = Signal(int, str)     # req_id, mensagem amigável


class DownloadSignals(QObject):
    stage = Signal(int, str, str)       # item_id, chave de status, texto
    progress = Signal(int, float, str)  # item_id, %, detalhe (velocidade / ETA)
    finished = Signal(int, str)         # item_id, caminho final
    failed = Signal(int, str)
    cancelled = Signal(int)
    skipped = Signal(int, str)
    conflict = Signal(int, str)         # o worker fica bloqueado até resolve_conflict()
    log = Signal(int, str, str)         # item_id, nível, mensagem


# ----------------------------------------------------------------------------- URLs
_CHANNEL_BARE = re.compile(r"^/(@[^/]+|channel/[^/]+|c/[^/]+|user/[^/]+)/?$")
_CHANNEL_TAB = re.compile(r"^/(@[^/]+|channel/[^/]+|c/[^/]+|user/[^/]+)/(videos|shorts|streams|releases|playlists)/?$")
_YT_HOST = re.compile(r"^(www\.|m\.|music\.)?(youtube\.com|youtu\.be|youtube-nocookie\.com)/", re.I)


def normalize_url(token: str) -> str | None:
    t = token.strip().strip("<>\"'")
    if re.match(r"^https?://\S+$", t, re.I):
        return t
    if _YT_HOST.match(t):
        return "https://" + t
    return None


def split_urls(text: str) -> list[str]:
    urls: list[str] = []
    for tok in re.split(r"[\s,]+", text.strip()):
        u = normalize_url(tok)
        if u and u not in urls:
            urls.append(u)
    return urls


def classify_url(url: str) -> str:
    """'mix' | 'playlist' | 'video'."""
    u = urllib.parse.urlparse(url)
    q = urllib.parse.parse_qs(u.query)
    lst = (q.get("list") or [""])[0]
    has_video = bool((q.get("v") or [""])[0]) or u.netloc.lower().endswith("youtu.be")
    if lst.startswith("RD") and has_video:
        return "mix"
    if lst or u.path.startswith("/playlist") or _CHANNEL_BARE.match(u.path) or _CHANNEL_TAB.match(u.path):
        return "playlist"
    return "video"


def prepare_playlist_url(url: str) -> str:
    u = urllib.parse.urlparse(url)
    if _CHANNEL_BARE.match(u.path):
        return urllib.parse.urlunparse(u._replace(path=u.path.rstrip("/") + "/videos", query=""))
    return url


def mix_url_from(url: str) -> str:
    u = urllib.parse.urlparse(url)
    q = urllib.parse.parse_qs(u.query)
    vid = (q.get("v") or [u.path.strip("/")])[0]
    return f"https://www.youtube.com/watch?v={vid}&list={(q.get('list') or [''])[0]}"


# ----------------------------------------------------------------------------- erros
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def friendly_error(exc: BaseException) -> str:
    raw = _ANSI.sub("", str(exc)).strip()
    raw = re.sub(r"^ERROR:\s*", "", raw)
    low = raw.lower()
    rules = [
        (("sign in to confirm", "not a bot"),
         "O YouTube pediu login (verificação anti-robô). Em Configurações > Avançado, escolha o navegador onde você está logado "
         "(ou um arquivo cookies.txt) e tente de novo."),
        (("javascript runtime", "js runtime", "n challenge", "signature solving", "ejs"),
         "O yt-dlp não encontrou um runtime JavaScript (Deno). Instale com: winget install DenoLand.Deno "
         "ou use a versão instalada do programa, que já o inclui."),
        (("private video",), "Este vídeo é privado."),
        (("members-only", "join this channel"), "Vídeo exclusivo para membros do canal."),
        (("confirm your age", "age-restricted", "inappropriate for some users"),
         "Vídeo com restrição de idade: use cookies de um navegador onde você está logado."),
        (("not available in your country", "geo", "blocked it in your country"), "Vídeo bloqueado na sua região."),
        (("video unavailable", "has been removed", "no longer available"), "Vídeo indisponível ou removido."),
        (("http error 429", "too many requests"), "O YouTube limitou as requisições (HTTP 429). Aguarde alguns minutos."),
        (("requested format is not available",),
         "Nenhum formato de áudio disponível. Atualize o yt-dlp e confira o runtime JavaScript (Deno)."),
        (("getaddrinfo", "urlopen error", "unable to download webpage", "timed out", "connection"),
         "Sem conexão com o YouTube. Verifique a internet/proxy."),
        (("winerror 32", "being used by another process", "permission denied"),
         "O arquivo está em uso por outro programa (um player?). Feche-o e tente novamente."),
        (("ffmpeg", "audio conversion"), "Falha ao converter o áudio com o FFmpeg. Veja a aba Logs."),
    ]
    for keys, msg in rules:
        if any(k in low for k in keys):
            return msg
    return raw[-300:] or exc.__class__.__name__


# ----------------------------------------------------------------------------- opções do yt-dlp
class YDLLogger:
    """Encaminha as mensagens do yt-dlp para um callback (nível, texto)."""

    def __init__(self, emit):
        self._emit = emit

    def debug(self, msg: str) -> None:
        if msg.startswith("[debug]"):
            return
        self._emit("info", _ANSI.sub("", msg))

    def info(self, msg: str) -> None:
        self._emit("info", _ANSI.sub("", msg))

    def warning(self, msg: str) -> None:
        self._emit("warn", _ANSI.sub("", msg))

    def error(self, msg: str) -> None:
        self._emit("error", _ANSI.sub("", msg))


def base_opts(cfg: dict) -> dict:
    opts: dict = {
        "quiet": True,
        "noprogress": True,
        "color": "no_color",
        "socket_timeout": 25,
        "retries": int(cfg.get("retries", 5)),
        "fragment_retries": 5,
        "extractor_retries": 3,
    }
    ff = audio.find_ffmpeg()
    if ff:
        opts["ffmpeg_location"] = ff
    js, _ = audio.find_js_runtimes(cfg)
    if js:
        opts["js_runtimes"] = js
    if cfg.get("allow_remote_components"):
        opts["remote_components"] = ["ejs:github"]
    cookie_file = (cfg.get("cookies_file") or "").strip().strip('"')
    if cookie_file and Path(cookie_file).exists():
        opts["cookiefile"] = cookie_file
    elif cfg.get("cookies_browser"):
        opts["cookiesfrombrowser"] = (cfg["cookies_browser"],)
    if cfg.get("proxy"):
        opts["proxy"] = cfg["proxy"].strip()
    rl = (cfg.get("rate_limit") or "").strip()
    if rl:
        rate = parse_bytes(rl)
        if rate:
            opts["ratelimit"] = rate
    return opts


# ----------------------------------------------------------------------------- análise (ExtractTask)
def _bad_title(title: str) -> bool:
    return title.strip().lower() in ("[private video]", "[deleted video]", "[unavailable video]")


def _norm_entry(e: dict, index: int) -> dict | None:
    vid = e.get("id")
    if not vid or _bad_title(e.get("title") or ""):
        return None
    return {
        "video_id": vid,
        "title": e.get("title") or vid,
        "channel": audio.clean_topic(e.get("channel") or e.get("uploader") or ""),
        "duration": int(e.get("duration") or 0),
        "url": e.get("webpage_url") or e.get("url") or f"https://www.youtube.com/watch?v={vid}",
        "thumb": f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg",
        "index": index,
    }


def extract(url: str, cfg: dict, mode: str = "auto", limit: int = 0) -> dict:
    """Analisa um link. mode='mix_more' busca `limit` itens de um Mix já conhecido."""
    kind = "playlist" if mode == "mix_more" else classify_url(url)
    opts = base_opts(cfg)
    opts.update({"skip_download": True, "extract_flat": "in_playlist", "lazy_playlist": True,
                 "noplaylist": kind != "playlist"})
    if kind == "playlist":
        opts["playlistend"] = limit or MAX_PLAYLIST
        url = prepare_playlist_url(url)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if not info:
        raise RuntimeError("O link não retornou nenhum conteúdo.")
    if info.get("entries") is not None:
        entries = []
        for i, e in enumerate(info["entries"], 1):
            ne = _norm_entry(e or {}, i)
            if ne:
                entries.append(ne)
        return {"kind": "playlist", "title": info.get("title") or "Playlist", "url": url, "entries": entries}
    entry = _norm_entry(info, 0)
    if not entry:
        raise RuntimeError("Não foi possível identificar o vídeo.")
    entry["thumb"] = f"https://i.ytimg.com/vi/{entry['video_id']}/mqdefault.jpg"
    if kind == "mix":
        return {"kind": "mix", "title": f"Mix: {entry['title']}", "url": mix_url_from(url), "entries": [entry]}
    return {"kind": "video", "title": entry["title"], "url": url, "entries": [entry]}


class ExtractTask(QRunnable):
    def __init__(self, req_id: int, url: str, cfg: dict, signals: ExtractSignals, mode: str = "auto", limit: int = 0):
        super().__init__()
        self.setAutoDelete(False)
        self.req_id, self.url, self.cfg, self.signals = req_id, url, cfg, signals
        self.mode, self.limit = mode, limit

    def run(self) -> None:
        try:
            result = extract(self.url, self.cfg, self.mode, self.limit)
            if shiboken6.isValid(self.signals):
                self.signals.done.emit(self.req_id, result)
        except Exception as exc:  # noqa: BLE001
            log.warning("Falha ao analisar %s: %s", self.url, exc)
            if shiboken6.isValid(self.signals):
                self.signals.failed.emit(self.req_id, friendly_error(exc))


# ----------------------------------------------------------------------------- planejamento de saída
def plan_output(item: dict, cfg: dict) -> dict:
    """Define pasta e nome base (sem extensão) do arquivo final."""
    base = Path(cfg["download_dir"]).expanduser()
    artist = audio.clean_topic(item.get("channel") or "")
    org = cfg.get("organize", "none")
    sub = ""
    if org == "playlist" and item.get("group_title"):
        sub = audio.sanitize_filename(item["group_title"], 80)
    elif org == "channel" and artist:
        sub = audio.sanitize_filename(artist, 80)
    out_dir = base / sub if sub else base
    title = item.get("title") or item.get("video_id") or "audio"
    stem = title
    if cfg.get("name_style") == "artist_title" and artist and not title.lower().startswith(artist.lower()):
        stem = f"{artist} - {title}"
    idx = int(item.get("index") or 0)
    if cfg.get("number_prefix", True) and item.get("group_kind") == "playlist" and idx > 0:
        width = max(2, len(str(int(item.get("group_total") or idx))))
        stem = f"{idx:0{width}d} - {stem}"
    max_len = max(40, min(150, 235 - len(str(out_dir))))  # margem para o limite de 260 do Windows
    return {"dir": out_dir, "stem": audio.sanitize_filename(stem, max_len)}


def unique_stem(out_dir: Path, stem: str, exts: list[str]) -> str:
    n = 1
    while True:
        cand = f"{stem} ({n})"
        if not any((out_dir / f"{cand}.{e}").exists() for e in exts):
            return cand
        n += 1


# ----------------------------------------------------------------------------- postprocessors próprios
class ConvertAudioPP(FFmpegPostProcessor):
    """Converte o áudio baixado para o formato/qualidade escolhidos (com EQ/loudnorm opcionais)."""

    def __init__(self, downloader, *, out_dir: Path, stem: str, fmt: str, quality: str,
                 filters: list[str], normalize: bool, cancel: threading.Event):
        super().__init__(downloader)
        self.out_dir, self.stem, self.fmt, self.quality = out_dir, stem, fmt, quality
        self.filters, self.normalize, self.cancel = filters, normalize, cancel
        self.final_path: Path | None = None

    def run(self, information):
        if self.cancel.is_set():
            raise UserCancelled()
        src = Path(information["filepath"])
        src_ext = (information.get("ext") or src.suffix.lstrip(".")).lower()
        acodec = information.get("acodec") or ""
        if self.fmt == "best" and (not acodec or acodec == "none"):
            acodec = self.get_audio_codec(str(src)) or ""
        ext, args, is_copy = audio.encoder_plan(self.fmt, self.quality, src_ext, acodec, bool(self.filters))
        final = self.out_dir / f"{self.stem}.{ext}"
        tmp = self.out_dir / f"{self.stem}.converting.{ext}"
        opts = ["-vn", "-sn", "-dn", "-map", "0:a:0", "-map_metadata", "-1", *args]
        if self.filters and not is_copy:
            opts += ["-af", ",".join(self.filters)]
            if self.normalize:  # o loudnorm sobe internamente para 192 kHz: fixar a taxa de saída
                rate = 48000 if ext == "opus" else int(information.get("asr") or 48000)
                opts += ["-ar", str(rate)]
        self.to_screen(f"Convertendo para {ext.upper()}: {final.name}")
        try:
            self.run_ffmpeg(str(src), str(tmp), opts)
            os.replace(tmp, final)  # troca atômica (também cobre o modo "substituir")
        except PostProcessingError:
            tmp.unlink(missing_ok=True)
            raise
        except OSError as exc:
            tmp.unlink(missing_ok=True)
            raise PostProcessingError(f"Não foi possível gravar {final.name}: {exc}") from exc
        self.final_path = final
        information["filepath"] = str(final)
        information["ext"] = ext
        return [str(src)], information


class CoverPrepPP(FFmpegPostProcessor):
    """Converte a miniatura (webp) para JPG, opcionalmente recortando em quadrado."""

    def __init__(self, downloader, square: bool = True):
        super().__init__(downloader)
        self.square = square

    def run(self, information):
        thumbs = information.get("thumbnails") or []
        path = next((t["filepath"] for t in reversed(thumbs)
                     if t.get("filepath") and os.path.exists(t["filepath"])), None)
        if not path:
            return [], information
        out = os.path.splitext(path)[0] + ".cover.jpg"
        opts = ["-frames:v", "1", "-q:v", "2"]
        if self.square:
            opts += ["-vf", "crop='min(iw,ih)':'min(iw,ih)'"]
        try:
            self.run_ffmpeg(path, out, opts)
        except PostProcessingError as exc:
            self.report_warning(f"Capa ignorada: {exc}")
            return [], information
        for t in thumbs:
            if t.get("filepath") == path:
                t["filepath"] = out
        return [path], information


# ----------------------------------------------------------------------------- download (DownloadTask)
PP_STAGES = {
    "ConvertAudio": ("converting", "Convertendo…", 92.0),
    "FFmpegMetadata": ("converting", "Gravando tags…", 96.0),
    "CoverPrep": ("converting", "Preparando capa…", 97.0),
    "EmbedThumbnail": ("converting", "Inserindo capa…", 98.0),
}


class DownloadTask(QRunnable):
    def __init__(self, item: dict, cfg: dict, signals: DownloadSignals):
        super().__init__()
        self.setAutoDelete(False)
        self.item, self.cfg, self.signals = item, cfg, signals
        self.item_id = item["id"]
        self.cancel_event = threading.Event()
        self._conflict_event = threading.Event()
        self._conflict_choice = "skip"
        self.final_path: Path | None = None
        self._tmp_prefix = f"st{self.item_id}_{int(time.time())}"

    # --- comunicação segura com a UI
    def _emit(self, name: str, *args) -> None:
        if shiboken6.isValid(self.signals):
            getattr(self.signals, name).emit(*args)

    def _stage(self, key: str, text: str) -> None:
        self._emit("stage", self.item_id, key, text)

    def cancel(self) -> None:
        self.cancel_event.set()
        self._conflict_event.set()

    def resolve_conflict(self, choice: str) -> None:
        self._conflict_choice = choice
        self._conflict_event.set()

    # --- hooks do yt-dlp
    def _progress_hook(self, d: dict) -> None:
        if self.cancel_event.is_set():
            raise UserCancelled()
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            done = d.get("downloaded_bytes") or 0
            if total:
                pct = done / total * 100
            elif d.get("fragment_count"):
                pct = (d.get("fragment_index") or 0) / d["fragment_count"] * 100
            else:
                pct = 0.0
            eta = d.get("eta")
            detail = " · ".join(x for x in (audio.fmt_speed(d.get("speed")), f"ETA {eta}s" if eta else "") if x)
            self._emit("progress", self.item_id, min(pct * 0.9, 90.0), detail)
        elif d.get("status") == "finished":
            self._emit("progress", self.item_id, 90.0, "")

    def _pp_hook(self, d: dict) -> None:
        if d.get("status") != "started":
            return
        stage = PP_STAGES.get(d.get("postprocessor", ""))
        if stage:
            self._stage(stage[0], stage[1])
            self._emit("progress", self.item_id, stage[2], "")

    def _check_cancel(self) -> None:
        if self.cancel_event.is_set():
            raise UserCancelled()

    # --- execução
    def run(self) -> None:
        try:
            self._check_cancel()
            self._run()
        except DownloadCancelled:
            self._emit("cancelled", self.item_id)
        except Exception as exc:  # noqa: BLE001
            log.exception("Falha no item %s", self.item_id)
            self._emit("failed", self.item_id, friendly_error(exc))

    def _run(self) -> None:
        item, cfg = self.item, self.cfg
        self._stage("downloading", "Analisando…")
        plan = plan_output(item, cfg)
        out_dir, stem = plan["dir"], plan["stem"]
        exts = audio.final_exts(cfg["format"])

        existing = [out_dir / f"{stem}.{e}" for e in exts if (out_dir / f"{stem}.{e}").exists()]
        if existing:
            action = cfg.get("existing_file_action", "ask")
            if action == "ask":
                self._conflict_event.clear()
                self._emit("conflict", self.item_id, str(existing[0]))
                while not self._conflict_event.wait(0.25):
                    pass
                self._check_cancel()
                action = self._conflict_choice
            if action == "skip":
                self._emit("skipped", self.item_id, str(existing[0]))
                return
            if action == "rename":
                stem = unique_stem(out_dir, stem, exts)
        out_dir.mkdir(parents=True, exist_ok=True)
        TMP_DIR.mkdir(parents=True, exist_ok=True)

        fmt = cfg["format"]
        quality = audio.normalize_quality(fmt, cfg.get("quality", ""))
        filters = audio.build_filters(cfg)
        want_cover = bool(cfg.get("embed_thumbnail")) and fmt != "wav"

        def ylog(level: str, msg: str) -> None:
            self._emit("log", self.item_id, level, msg)

        opts = base_opts(cfg)
        opts.update({
            "logger": YDLLogger(ylog),
            "noplaylist": True,
            "overwrites": True,
            "continuedl": True,
            "format": audio.format_selector(cfg.get("source", "best")),
            "paths": {"home": str(out_dir), "temp": str(TMP_DIR)},
            "outtmpl": {"default": self._tmp_prefix + ".%(ext)s"},
            "writethumbnail": want_cover,
            "progress_hooks": [self._progress_hook],
            "postprocessor_hooks": [self._pp_hook],
        })

        convert = None
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(item["url"], download=False)
                if not info:
                    raise RuntimeError("Não foi possível obter as informações do vídeo.")
                if info.get("entries"):
                    info = next(iter(info["entries"]))
                self._check_cancel()
                self._inject_metadata(info)

                convert = ConvertAudioPP(
                    ydl, out_dir=out_dir, stem=stem, fmt=fmt, quality=quality, filters=filters,
                    normalize=bool(cfg.get("normalize")), cancel=self.cancel_event)
                ydl.add_post_processor(convert)
                if cfg.get("embed_metadata", True):
                    ydl.add_post_processor(FFmpegMetadataPP(ydl, add_metadata=True, add_chapters=False, add_infojson=False))
                if want_cover:
                    ydl.add_post_processor(CoverPrepPP(ydl, square=bool(cfg.get("square_cover", True))))
                    ydl.add_post_processor(EmbedThumbnailPP(ydl, already_have_thumbnail=False))

                self._stage("downloading", "Baixando")
                ydl.process_ie_result(info, download=True)
            self.final_path = convert.final_path
            if not self.final_path or not self.final_path.exists():
                raise RuntimeError("O arquivo final não foi criado.")
            self._emit("progress", self.item_id, 100.0, "")
            self._emit("finished", self.item_id, str(self.final_path))
        finally:
            self._cleanup_tmp()

    def _inject_metadata(self, info: dict) -> None:
        """Define título/artista/álbum/faixa antes do passo de tags (vide F-03 da especificação)."""
        item, cfg = self.item, self.cfg
        artists = info.get("artists") or []
        artist = audio.clean_topic(
            info.get("artist") or (artists[0] if artists else "") or info.get("channel")
            or info.get("uploader") or item.get("channel") or "")
        info["track"] = info.get("track") or info.get("title") or item.get("title")
        info["artist"] = artist
        if cfg.get("album_from_playlist", True) and item.get("group_title") and item.get("group_kind") == "playlist":
            info["album"] = item["group_title"]
        if item.get("index"):
            info["track_number"] = item["index"]
        info["description"] = None  # evita gravar textos enormes nas tags

    def _cleanup_tmp(self) -> None:
        for p in TMP_DIR.glob(self._tmp_prefix + "*"):
            try:
                p.unlink()
            except OSError:
                pass
