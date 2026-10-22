"""Shared helpers for the shorts scripts. Every script takes the WORK dir as argv[1]."""
import os, sys, json, subprocess, re

FILLER_RE = re.compile(r"^(u+m+|u+h+m*|h+m+|m+h*m+|e+r+m*|a+h+|e+h+|ugh)[,.?!;:]*$", re.I)
OH_RE = re.compile(r"^oh[,.?!;:]*$", re.I)
OH_QUOTE_CTX = re.compile(r"\b(like|said|say|says|thinks|think|goes|went|was)[,]?$", re.I)
OH_REPLY_NEXT = re.compile(r"^(no|yeah|yes|really|damn|god|my|okay|ok|wow)\b", re.I)
LEVEL_FILTER = "dynaudnorm=f=150:g=15,loudnorm=I=-16:TP=-1.5:LRA=11"   # same chain as a podcast master: -16 LUFS
HOP = 0.010
SKILL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def work(argv=None):
    argv = argv or sys.argv
    if len(argv) < 2 or argv[1].startswith("-"):
        sys.exit(f"usage: {os.path.basename(argv[0])} WORK_DIR [...]")
    w = os.path.abspath(argv[1]); os.makedirs(w, exist_ok=True)
    return w


def arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def load(w, name, default=None):
    p = os.path.join(w, name)
    if not os.path.exists(p):
        if default is not None: return default
        sys.exit(f"missing {p} (run prepare.py first, or write it)")
    return json.load(open(p))


def save(w, name, obj):
    json.dump(obj, open(os.path.join(w, name), "w"), indent=1)


def sh(cmd, check=True):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if check and r.returncode:
        sys.exit(f"command failed: {' '.join(cmd)}\n{r.stderr[-2000:]}")
    return r


def probe(path, entries, stream="v:0"):
    """ffprobe values of the first video stream, e.g. probe(p, "width,height") -> ["1080", "1920"]"""
    return sh(["ffprobe", "-v", "error", "-select_streams", stream, "-show_entries", f"stream={entries}", "-of", "csv=p=0", path]).stdout.strip().split(",")


def duration(path):
    return float(sh(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path]).stdout)


def loudness(path, pre=()):
    """ffmpeg loudnorm analysis -> dict(i, tp, lra). pre: input options, e.g. ["-ss", "21"] to measure a section."""
    r = sh(["ffmpeg", "-v", "info", *pre, "-i", path, "-vn", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"], check=False)
    m = re.search(r"\{.*?\}", r.stderr, re.S)
    d = json.loads(m.group(0)) if m else {}
    return {"i": float(d.get("input_i", "nan")), "tp": float(d.get("input_tp", "nan")), "lra": float(d.get("input_lra", "nan"))}


def read_wav_mono16k(path):
    import numpy as np, wave
    w = wave.open(path); assert w.getnchannels() == 1 and w.getframerate() == 16000, path
    return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768


def envelope_db(x, sr=16000, hop_s=HOP, win_s=0.025):
    import numpy as np
    hop, win = int(hop_s * sr), int(win_s * sr)
    n = (len(x) - win) // hop
    fr = np.lib.stride_tricks.as_strided(x, (n, win), (x.strides[0] * hop, x.strides[0]))
    return 20 * np.log10(np.sqrt(np.mean(fr ** 2, axis=1) + 1e-12) + 1e-9)


def runs(mask, hop_s=HOP):
    """boolean array -> list of (start_s, end_s) for True runs."""
    out, start = [], None
    for i, v in enumerate(mask):
        if v and start is None: start = i
        if not v and start is not None: out.append((start * hop_s, i * hop_s)); start = None
    if start is not None: out.append((start * hop_s, len(mask) * hop_s))
    return out


def merge(intervals, gap=0.0):
    out = []
    for s, e in sorted(intervals):
        if out and s <= out[-1][1] + gap: out[-1] = (out[-1][0], max(out[-1][1], e))
        else: out.append((s, e))
    return out


def intersect(a, b):
    out, i, j = [], 0, 0
    a, b = sorted(a), sorted(b)
    while i < len(a) and j < len(b):
        s, e = max(a[i][0], b[j][0]), min(a[i][1], b[j][1])
        if e > s: out.append((s, e))
        if a[i][1] < b[j][1]: i += 1
        else: j += 1
    return out


def speech_thr(db):
    """Speech threshold relative to the audio's own level (a fixed -42 dB eats soft speech on a quiet mic).
    Equals about -42 for normally loud speech (p95 near -17 dB)."""
    import numpy as np
    v = db[db > -70]
    return float(np.percentile(v, 95) - 25) if len(v) else -42.0


def speech_activity(db, thr=None, hop_s=HOP):
    """Speech intervals for an envelope: raw runs, and padded (0.25 s) intervals with gaps < 0.6 s bridged."""
    if thr is None: thr = speech_thr(db)
    raw = [(s, e) for s, e in runs(db > thr, hop_s) if e - s >= 0.12]
    return raw, [(max(0.0, s - 0.25), e + 0.25) for s, e in merge(raw, gap=0.6) if e - s >= 0.15]
