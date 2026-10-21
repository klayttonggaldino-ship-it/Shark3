"""Teste de fumaça OFFLINE do pipeline (sem YouTube).

Gera áudio de teste com o FFmpeg embutido, serve por HTTP local e roda o DownloadTask real
para cada formato/qualidade, conferindo arquivo, tags, capa, EQ e tratamento de conflitos.

Uso:  python tests/smoke_test.py
"""
from __future__ import annotations

import functools
import http.server
import os
import re
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QCoreApplication  # noqa: E402

from app import audio, workers  # noqa: E402
from app.config import DEFAULTS  # noqa: E402

app = QCoreApplication.instance() or QCoreApplication([])
FF = audio.find_ffmpeg()
work = Path(tempfile.mkdtemp(prefix="sharktune_test_"))
www, out = work / "www", work / "out"
www.mkdir()
out.mkdir()


def ff(*args: str) -> str:
    r = subprocess.run([FF, "-y", "-hide_banner", *args], capture_output=True, text=True)
    return r.stderr


# Fonte: ruído rosa estéreo de 6 s (Opus/WebM) e AAC/M4A, mais uma capa 16:9
ff("-f", "lavfi", "-i", "anoisesrc=d=6:c=pink:r=48000:a=0.3", "-ac", "2", "-c:a", "libopus", "-b:a", "128k", str(www / "src.webm"))
ff("-f", "lavfi", "-i", "anoisesrc=d=6:c=pink:r=44100:a=0.3", "-ac", "2", "-c:a", "aac", "-b:a", "128k", str(www / "src.m4a"))
ff("-f", "lavfi", "-i", "testsrc2=s=640x360:d=1", "-frames:v", "1", str(www / "cover.webp"))

class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a, **k):
        pass


class _Srv(http.server.ThreadingHTTPServer):
    def handle_error(self, *a):  # ignora "Broken pipe" quando o cliente fecha antes
        pass


srv = _Srv(("127.0.0.1", 0), functools.partial(_Quiet, directory=str(www)))
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{srv.server_address[1]}"


class TestTask(workers.DownloadTask):
    def _inject_metadata(self, info):  # adiciona a capa que o generic extractor não conhece
        super()._inject_metadata(info)
        info["thumbnails"] = [{"url": f"{BASE}/cover.webp", "id": "0"}]


def run_task(src: str, cfg_over: dict, title: str, **item_over):
    cfg = {**DEFAULTS, "download_dir": str(out), "auto_start": False, "existing_file_action": "rename", **cfg_over}
    sig = workers.DownloadSignals()
    ev: dict = {"stages": [], "log": []}
    sig.finished.connect(lambda i, p: ev.update(finished=p))
    sig.failed.connect(lambda i, m: ev.update(failed=m))
    sig.skipped.connect(lambda i, p: ev.update(skipped=p))
    sig.stage.connect(lambda i, k, t: ev["stages"].append(t))
    sig.log.connect(lambda i, lv, m: ev["log"].append(f"{lv}: {m}"))
    item = {"id": 1, "url": f"{BASE}/{src}", "video_id": "t1", "title": title, "channel": "Canal Teste - Topic",
            "duration": 6, "index": 0, "group_title": "", "group_kind": "", "group_total": 0, **item_over}
    TestTask(item, cfg, sig).run()
    return ev


def probe(path: str) -> str:
    return subprocess.run([FF, "-hide_banner", "-i", path], capture_output=True, text=True).stderr


def tags(path: str) -> dict:
    import mutagen

    f = mutagen.File(path, easy=False)
    items: dict = {}
    if f is not None and f.tags is not None:
        pairs = f.tags.items() if hasattr(f.tags, "items") else list(f.tags)
        for k, v in pairs:
            items[str(k)] = v
    keys = {k.lower() for k in items}
    items["_has_pic"] = bool(getattr(f, "pictures", None)) or "metadata_block_picture" in keys or \
        any(k.startswith(("apic", "covr")) for k in keys)
    return items


fails: list[str] = []


def check(cond: bool, msg: str) -> None:
    print(("  OK   " if cond else "  FALHOU ") + msg)
    if not cond:
        fails.append(msg)


# ---------------------------------------------------------------- 1) todos os formatos e qualidades
cases = [
    ("src.webm", "mp3", "320", r"320 kb/s"), ("src.webm", "mp3", "128", r"128 kb/s"), ("src.webm", "mp3", "v0", r"Audio: mp3"),
    ("src.m4a", "m4a", "64", r"Audio: aac"), ("src.webm", "opus", "96", r"Audio: opus"),
    ("src.webm", "ogg", "192", r"Audio: vorbis"), ("src.webm", "flac", "", r"Audio: flac"),
    ("src.webm", "wav", "", r"pcm_s16le"), ("src.webm", "best", "", r"Audio: opus"), ("src.m4a", "best", "", r"Audio: aac"),
]
print("== Formatos e qualidades")
for i, (src, fmt, q, pat) in enumerate(cases):
    title = f"Faixa {i} {fmt} {q}"
    ev = run_task(src, {"format": fmt, "quality": q}, title)
    p = ev.get("finished")
    check(bool(p) and Path(p).exists(), f"{fmt} {q or '-'} ({src}) gerou arquivo" + ("" if p else f" [{ev.get('failed')}]"))
    if p:
        info = probe(p)
        check(re.search(pat, info) is not None, f"   conteúdo confere ({pat})")
        if fmt != "wav":
            t = tags(p)
            flat = " ".join(str(v) for v in t.values())
            check("Canal Teste" in flat and "Topic" not in flat, "   artista sem '- Topic'")
            check(t.get("_has_pic") is True, "   capa embutida")

# ---------------------------------------------------------------- 2) EQ e normalização
print("== EQ / loudnorm")
bands = [dict(b) for b in DEFAULTS["eq_bands"]]
bands[0]["gain"] = 12.0
base = run_task("src.webm", {"format": "flac"}, "EQ base")["finished"]
eq = run_task("src.webm", {"format": "flac", "eq_enabled": True, "eq_bands": bands, "embed_thumbnail": False}, "EQ graves")["finished"]


def band_rms(path: str, flt: str) -> float:
    err = ff("-i", path, "-af", flt + ",astats=metadata=0", "-f", "null", "-")
    return float(re.findall(r"RMS level dB: (-?[\d.]+)", err)[0])


def tilt(path: str) -> float:
    """Graves (<120 Hz) menos médios (1-4 kHz), em dB."""
    return band_rms(path, "lowpass=f=120") - band_rms(path, "highpass=f=1000,lowpass=f=4000")


def peak_db(path: str) -> float:
    err = ff("-i", path, "-af", "volumedetect", "-f", "null", "-")
    return float(re.findall(r"max_volume: (-?[\d.]+) dB", err)[0])


t0, t1 = tilt(base), tilt(eq)
print(f"   inclinação graves-médios: sem EQ {t0:.1f} dB, com EQ {t1:.1f} dB; pico {peak_db(eq):.1f} dBFS")
check(t1 - t0 > 6.0, "EQ reforçou os graves em mais de 6 dB (relativo aos médios)")
check(peak_db(eq) <= 0.0, "sem clipping após o EQ")
hr = audio.eq_headroom_db(bands)
check(hr > 5, f"ganho de segurança calculado ({hr:.1f} dB)")
norm = run_task("src.webm", {"format": "mp3", "quality": "192", "normalize": True}, "Normalizada")
check(bool(norm.get("finished")), "loudnorm + mp3 concluiu" + ("" if norm.get("finished") else f" [{norm.get('failed')}]"))
if norm.get("finished"):
    check("Stream #0:0" in probe(norm["finished"]) and re.search(r"(44100|48000) Hz", probe(norm["finished"])) is not None,
          "taxa de amostragem fixada (sem 192 kHz)")

# ---------------------------------------------------------------- 3) conflitos
print("== Conflitos")
ev1 = run_task("src.webm", {"format": "mp3", "existing_file_action": "rename"}, "Duplicada")
ev2 = run_task("src.webm", {"format": "mp3", "existing_file_action": "rename"}, "Duplicada")
check(ev2.get("finished", "").endswith("Duplicada (1).mp3"), "renomear cria '(1)'")
ev3 = run_task("src.webm", {"format": "mp3", "existing_file_action": "skip"}, "Duplicada")
check("skipped" in ev3, "pular não baixa de novo")
ev4 = run_task("src.webm", {"format": "mp3", "existing_file_action": "replace"}, "Duplicada")
check(ev4.get("finished", "").endswith("Duplicada.mp3"), "substituir sobrescreve")

# ---------------------------------------------------------------- 4) pasta por playlist + prefixo
print("== Organização")
ev5 = run_task("src.webm", {"format": "mp3", "organize": "playlist"}, "Música: ao vivo?",
               index=7, group_title="Minha Lista", group_kind="playlist", group_total=120)
p5 = ev5.get("finished", "")
check(p5.endswith(os.path.join("Minha Lista", "007 - Música - ao vivo.mp3")), f"subpasta + prefixo + nome limpo ({Path(p5).name})")

leftover = [p.name for p in out.rglob("*") if p.suffix in (".webp", ".jpg", ".part") or ".converting." in p.name]
check(not leftover, f"sem arquivos temporários sobrando {leftover}")

print("\nRESULTADO:", "TUDO OK" if not fails else f"{len(fails)} falha(s)")
srv.shutdown()
sys.exit(1 if fails else 0)
