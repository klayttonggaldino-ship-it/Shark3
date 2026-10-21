"""Formatos de saída, qualidades, DSP (EQ/loudnorm), utilitários e detecção de ferramentas."""
from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
import unicodedata
from pathlib import Path

from .paths import BIN_DIRS

_NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# ----------------------------------------------------------------------------- formatos
FORMATS: dict[str, dict] = {
    "mp3": {"label": "MP3", "ext": "mp3", "bitrates": [64, 96, 128, 160, 192, 224, 256, 320], "vbr": True, "default": "192"},
    "m4a": {"label": "M4A (AAC)", "ext": "m4a", "bitrates": [64, 96, 128, 160, 192, 256, 320], "vbr": False, "default": "192"},
    "opus": {"label": "Opus", "ext": "opus", "bitrates": [48, 64, 96, 128, 160, 192, 256], "vbr": False, "default": "160"},
    "ogg": {"label": "OGG (Vorbis)", "ext": "ogg", "bitrates": [64, 96, 128, 160, 192, 256, 320], "vbr": False, "default": "192"},
    "flac": {"label": "FLAC (sem perdas)", "ext": "flac", "bitrates": [], "vbr": False, "default": ""},
    "wav": {"label": "WAV (sem compressão)", "ext": "wav", "bitrates": [], "vbr": False, "default": ""},
    "best": {"label": "Original (sem reconverter)", "ext": "", "bitrates": [], "vbr": False, "default": ""},
}
MP3_VBR = [("v0", "VBR V0 · ~245 kbps"), ("v2", "VBR V2 · ~190 kbps"), ("v4", "VBR V4 · ~165 kbps")]
ORIGINAL_EXTS = ["m4a", "opus", "ogg"]  # possíveis extensões no modo "Original"


def quality_options(fmt: str) -> list[tuple[str, str]]:
    """Lista [(valor, rótulo)] das qualidades disponíveis para o formato."""
    f = FORMATS.get(fmt, FORMATS["mp3"])
    if fmt == "best":
        return [("", "Qualidade original do YouTube")]
    if not f["bitrates"]:
        return [("", "Sem perdas")]
    opts = [(str(b), f"{b} kbps") for b in reversed(f["bitrates"])]
    if f["vbr"]:
        opts += MP3_VBR
    return opts


def normalize_quality(fmt: str, quality: str) -> str:
    valid = [v for v, _ in quality_options(fmt)]
    return quality if quality in valid else FORMATS.get(fmt, FORMATS["mp3"])["default"]


def final_exts(fmt: str) -> list[str]:
    return ORIGINAL_EXTS if fmt == "best" else [FORMATS[fmt]["ext"]]


def format_selector(source: str) -> str:
    if source == "m4a":
        return "bestaudio[ext=m4a]/bestaudio/best"
    if source == "opus":
        return "bestaudio[acodec=opus]/bestaudio/best"
    return "bestaudio/best"


def encoder_plan(fmt: str, quality: str, src_ext: str, src_acodec: str, has_dsp: bool):
    """Retorna (extensão final, argumentos de saída do ffmpeg, é_cópia_sem_reencode)."""
    codec = (src_acodec or "").lower()
    if codec == "none":
        codec = ""
    if fmt == "best":
        if codec.startswith("opus") or (not codec and src_ext in ("webm", "opus")):
            if not has_dsp:
                return "opus", ["-c:a", "copy"], True
            fmt, quality = "opus", "160"
        elif codec.startswith(("mp4a", "aac")) or (not codec and src_ext in ("m4a", "mp4")):
            if not has_dsp:
                return "m4a", ["-c:a", "copy"], True
            fmt, quality = "m4a", "192"
        elif codec.startswith("vorbis"):
            if not has_dsp:
                return "ogg", ["-c:a", "copy"], True
            fmt, quality = "ogg", "192"
        else:
            fmt, quality = "mp3", "v0"
    q = normalize_quality(fmt, quality)
    if fmt == "mp3":
        rate = ["-q:a", q[1:]] if q.startswith("v") else ["-b:a", f"{q}k"]
        return "mp3", ["-c:a", "libmp3lame", *rate], False
    if fmt == "m4a":
        return "m4a", ["-c:a", "aac", "-b:a", f"{q}k"], False
    if fmt == "opus":
        return "opus", ["-c:a", "libopus", "-b:a", f"{q}k", "-vbr", "on", "-application", "audio"], False
    if fmt == "ogg":
        return "ogg", ["-c:a", "libvorbis", "-b:a", f"{q}k"], False
    if fmt == "flac":
        return "flac", ["-c:a", "flac"], False
    return "wav", ["-c:a", "pcm_s16le"], False


# ----------------------------------------------------------------------------- EQ / DSP
EQ_TYPES = [
    ("bell", "Sino (Bell)"),
    ("lowshelf", "Shelf de graves"),
    ("highshelf", "Shelf de agudos"),
    ("highpass", "Passa-altas (HP)"),
    ("lowpass", "Passa-baixas (LP)"),
]
GAIN_TYPES = ("bell", "lowshelf", "highshelf")


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _biquad(kind: str, f0: float, gain_db: float, q: float, fs: float):
    """Coeficientes normalizados (RBJ Audio EQ Cookbook): b0, b1, b2, a1, a2."""
    f0 = _clamp(f0, 10.0, fs * 0.45)
    q = _clamp(q, 0.1, 18.0)
    w0 = 2 * math.pi * f0 / fs
    cw, sw = math.cos(w0), math.sin(w0)
    alpha = sw / (2 * q)
    A = 10 ** (gain_db / 40)
    if kind == "lowshelf":
        sA = 2 * math.sqrt(A) * alpha
        b0 = A * ((A + 1) - (A - 1) * cw + sA)
        b1 = 2 * A * ((A - 1) - (A + 1) * cw)
        b2 = A * ((A + 1) - (A - 1) * cw - sA)
        a0 = (A + 1) + (A - 1) * cw + sA
        a1 = -2 * ((A - 1) + (A + 1) * cw)
        a2 = (A + 1) + (A - 1) * cw - sA
    elif kind == "highshelf":
        sA = 2 * math.sqrt(A) * alpha
        b0 = A * ((A + 1) + (A - 1) * cw + sA)
        b1 = -2 * A * ((A - 1) + (A + 1) * cw)
        b2 = A * ((A + 1) + (A - 1) * cw - sA)
        a0 = (A + 1) - (A - 1) * cw + sA
        a1 = 2 * ((A - 1) - (A + 1) * cw)
        a2 = (A + 1) - (A - 1) * cw - sA
    elif kind == "highpass":
        b0, b1, b2 = (1 + cw) / 2, -(1 + cw), (1 + cw) / 2
        a0, a1, a2 = 1 + alpha, -2 * cw, 1 - alpha
    elif kind == "lowpass":
        b0, b1, b2 = (1 - cw) / 2, 1 - cw, (1 - cw) / 2
        a0, a1, a2 = 1 + alpha, -2 * cw, 1 - alpha
    else:  # bell
        b0, b1, b2 = 1 + alpha * A, -2 * cw, 1 - alpha * A
        a0, a1, a2 = 1 + alpha / A, -2 * cw, 1 - alpha / A
    return b0 / a0, b1 / a0, b2 / a0, a1 / a0, a2 / a0


def _mag_db(c, f: float, fs: float) -> float:
    b0, b1, b2, a1, a2 = c
    w = 2 * math.pi * f / fs
    c1, s1, c2, s2 = math.cos(w), math.sin(w), math.cos(2 * w), math.sin(2 * w)
    nr, ni = b0 + b1 * c1 + b2 * c2, -(b1 * s1 + b2 * s2)
    dr, di = 1 + a1 * c1 + a2 * c2, -(a1 * s1 + a2 * s2)
    return 10 * math.log10(max(nr * nr + ni * ni, 1e-20) / max(dr * dr + di * di, 1e-20))


def band_response_db(band: dict, freqs, fs: float = 48000.0) -> list[float]:
    c = _biquad(band["type"], band["freq"], band.get("gain", 0.0), band.get("q", 1.0), fs)
    return [_mag_db(c, f, fs) for f in freqs]


def total_response_db(bands, freqs, fs: float = 48000.0) -> list[float]:
    coefs = [
        _biquad(b["type"], b["freq"], b.get("gain", 0.0), b.get("q", 1.0), fs)
        for b in bands if b.get("on", True)
    ]
    return [sum(_mag_db(c, f, fs) for c in coefs) for f in freqs]


def eq_filters(bands) -> list[str]:
    """Converte as bandas da interface em filtros do ffmpeg (ignora bandas neutras/desligadas)."""
    out: list[str] = []
    for b in bands:
        if not b.get("on", True):
            continue
        kind = b["type"]
        f = _clamp(float(b["freq"]), 20.0, 20000.0)
        g = _clamp(float(b.get("gain", 0.0)), -24.0, 24.0)
        q = _clamp(float(b.get("q", 1.0)), 0.1, 18.0)
        if kind in GAIN_TYPES:
            if abs(g) < 0.05:
                continue
            name = {"bell": "equalizer", "lowshelf": "lowshelf", "highshelf": "highshelf"}[kind]
            out.append(f"{name}=f={f:.1f}:width_type=q:width={q:.3f}:g={g:.2f}")
        elif kind in ("highpass", "lowpass"):
            out.append(f"{kind}=f={f:.1f}:poles=2:width_type=q:width={q:.3f}")
    return out


def eq_headroom_db(bands) -> float:
    """Maior ganho positivo da curva total (usado para evitar clipping)."""
    freqs = [20.0 * (1000.0 ** (i / 120)) for i in range(121)]
    peak = max(total_response_db(bands, freqs))
    return _clamp(peak, 0.0, 18.0)


def build_filters(cfg: dict) -> list[str]:
    """Cadeia de filtros -af: EQ -> folga + limitador -> (ou) loudnorm."""
    filters: list[str] = []
    if cfg.get("eq_enabled"):
        eq = eq_filters(cfg.get("eq_bands") or [])
        filters += eq
        if eq and not cfg.get("normalize"):
            # Pequena folga + limitador de picos: evita clipping sem "achatar" o volume geral.
            hr = eq_headroom_db(cfg["eq_bands"])
            if hr > 0.1:
                filters.append(f"volume={-min(hr, 3.0):.2f}dB")
                filters.append("alimiter=limit=0.97:level=0")
    if cfg.get("normalize"):
        filters.append("loudnorm=I=-14:TP=-1.5:LRA=11")
    return filters


# ----------------------------------------------------------------------------- texto
_ILLEGAL = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def sanitize_filename(name: str, max_len: int = 150) -> str:
    s = unicodedata.normalize("NFC", str(name or ""))
    s = s.replace("/", "-").replace("\\", "-").replace(":", " -").replace('"', "'").replace("|", "-")
    s = _ILLEGAL.sub("", s)
    s = re.sub(r"\s+", " ", s).strip(" .")
    if s.split(".")[0].upper() in _RESERVED:
        s = f"_{s}"
    if len(s) > max_len:
        s = s[:max_len].rstrip(" .")
    return s or "sem titulo"


def clean_topic(name: str) -> str:
    """Remove o sufixo ' - Topic' dos canais gerados automaticamente pelo YouTube Music."""
    return re.sub(r"\s*-\s*Topic\s*$", "", name or "", flags=re.I).strip()


def norm_title(title: str) -> str:
    return re.sub(r"[\W_]+", "", (title or "").casefold())


def fmt_duration(sec) -> str:
    try:
        sec = int(sec or 0)
    except (TypeError, ValueError):
        return ""
    if sec <= 0:
        return ""
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_speed(bps) -> str:
    if not bps:
        return ""
    for unit in ("B/s", "KB/s", "MB/s", "GB/s"):
        if bps < 1024 or unit == "GB/s":
            return f"{bps:.1f} {unit}" if unit != "B/s" else f"{bps:.0f} {unit}"
        bps /= 1024
    return ""


# ----------------------------------------------------------------------------- ferramentas
_cache: dict = {}


def reset_tool_cache() -> None:
    _cache.clear()


def _exe(name: str) -> str:
    return name + (".exe" if os.name == "nt" else "")


def _bundled(name: str) -> str | None:
    for d in BIN_DIRS:
        p = d / _exe(name)
        if p.exists():
            return str(p)
    return None


def find_ffmpeg() -> str | None:
    """ffmpeg embutido (imageio-ffmpeg) -> pasta bin -> PATH."""
    if "ffmpeg" in _cache:
        return _cache["ffmpeg"]
    path = _bundled("ffmpeg")
    if not path:
        try:
            import imageio_ffmpeg

            path = imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            path = None
    path = path or shutil.which("ffmpeg")
    _cache["ffmpeg"] = path
    return path


def _first_line(path: str, arg: str = "--version") -> str:
    try:
        r = subprocess.run([path, arg], capture_output=True, text=True, timeout=10, creationflags=_NOWIN)
        out = (r.stdout or r.stderr or "").strip()
        return out.splitlines()[0] if out else ""
    except Exception:
        return ""


def find_js_runtimes(cfg: dict) -> tuple[dict, str]:
    """Runtimes JavaScript que o yt-dlp usa para o YouTube. Retorna (js_runtimes, descrição)."""
    key = ("js", cfg.get("js_runtime_path", ""))
    if key in _cache:
        return _cache[key]
    found: dict[str, dict] = {}
    notes: list[str] = []

    def add(name: str, path: str | None) -> None:
        if name in found or not path:
            return
        ver = _first_line(path)
        if not ver and name != "quickjs":
            return
        if name == "node":
            m = re.match(r"v?(\d+)", ver)
            if not m or int(m.group(1)) < 22:  # yt-dlp exige Node >= 22
                return
        found[name] = {"path": path}
        short = ver.split()[1] if name == "deno" and len(ver.split()) > 1 else ver
        notes.append(f"{name} {short}".strip())

    custom = (cfg.get("js_runtime_path") or "").strip().strip('"')
    if custom and Path(custom).exists():
        stem = Path(custom).stem.lower()
        kind = "node" if stem.startswith("node") else "quickjs" if stem.startswith(("qjs", "quickjs")) else "bun" if stem.startswith("bun") else "deno"
        add(kind, custom)
    add("deno", _bundled("deno"))
    add("deno", shutil.which("deno"))
    add("node", shutil.which("node"))
    result = (found, ", ".join(notes) if notes else "")
    _cache[key] = result
    return result
