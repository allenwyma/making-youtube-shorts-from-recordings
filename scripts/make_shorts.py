"""Step 3: YouTube Shorts: cut the chosen moments (fillers and long pauses dropped through cuts.json), burn in captions,
crop to 1080x1920, level to -16 LUFS, save to the out folder with a titles/tags file.
usage (venv python: needs Pillow):  make_shorts.py WORK_DIR [--only N] [--out DIR] [--style NAME|FILE]
reads WORK/source.json, whisper.json, speech.json, cuts.json (prepare.py writes them) and WORK/shorts.json:
  [{"slug": "...", "title": "...", "description": "...", "tags": ["..."], "ranges": [[start_s, end_s], ...]}]
optional per short: "fix" {"misheard": "right"} corrects caption words (lowercase "word" or "two words"; "" drops it),
  "bleep" ["word"] mutes those words under a tone and stars them in the captions, "focus_x" 0..1 (crop centre, 0.5 default).
ranges are recording seconds (transcript.txt time); several ranges are joined in order (skips interjections)."""
import os, sys, re, json, shutil
from PIL import Image, ImageDraw, ImageFont
from shortlib import work, arg, load, sh, probe, loudness, intersect, merge, LEVEL_FILTER, SKILL
w = work(); src = load(w, "source.json"); shorts = load(w, "shorts.json"); FPS = src["fps"]; name = src["name"]; PARTS = src["parts"]
MAX_S, MIN_KEEP = 175.0, 0.3                                                 # YouTube limit is 180 s; shorter fragments flash on screen
W, H = 1080, 1920
st = arg("--style", src.get("style", "default")); sf = st if os.path.isfile(st) else os.path.join(SKILL, "styles", st + ".json")
if not os.path.isfile(sf): sys.exit(f"no caption style {st}: pass a file or one of {sorted(x[:-5] for x in os.listdir(os.path.join(SKILL, 'styles')))}")
S = json.load(open(sf)); font = os.path.join(os.path.dirname(os.path.abspath(sf)), S["font"])
FONT = ImageFont.truetype(font, S["size"])
if S.get("weight"): FONT.set_variation_by_axes([S["weight"]])
CAP_Y, CAP_H = S["y"], S["strip_height"]
FILLER = re.compile(r"^(um+|uh+|hm+|ah+|er+)$")
total = PARTS[-1]["end"]; cut = merge([(s, e) for s, e, *_ in load(w, "cuts.json")], gap=MIN_KEEP)
keeps, pos = [], 0.0
for s, e in cut:
    if s > pos: keeps.append((pos, s))
    pos = max(pos, e)
if pos < total: keeps.append((pos, total))
words = [x for seg in load(w, "whisper.json")["segments"] for x in seg.get("words", [])]
speech = load(w, "speech.json"); onsets = sorted(s for s, _ in speech); offsets = sorted(e for _, e in speech)
def snap(x, cands):
    """Move a range edge to the nearest speech onset/offset (whisper times are +-0.3 s); leave it when none is within 0.8 s."""
    c = min(cands, key=lambda c: abs(c - x)); return c if abs(c - x) <= 0.8 else x

def cues_for(segs, fix, bleep=()):
    """whisper words inside the kept segments -> [(start, end, text)] in short time, 2 lines max"""
    toks, pos, core = [], 0.0, lambda t: re.sub(r"^\W+|\W+$", "", t)
    for s, e in segs:
        for x in words:
            mid = (x["start"] + x["end"]) / 2; txt = x["word"].strip()
            if s <= mid < e and txt and not FILLER.match(re.sub(r"\W", "", txt).lower()): toks.append([pos + max(x["start"], s) - s, pos + min(x["end"], e) - s, txt])
        pos += e - s
    out, cur, i, beeps = [], [], 0, []
    while i < len(toks):
        a, b, txt = toks[i]; c = core(txt).lower(); i += 1
        pair = c + " " + core(toks[i][2]).lower() if i < len(toks) else None
        if pair in fix: b, txt = toks[i][1], fix[pair] + re.search(r"\W*$", toks[i][2]).group(); i += 1   # two words Whisper split
        elif c in fix: txt = txt.replace(core(txt), fix[c])
        if c in bleep: beeps.append((a, b)); txt = txt.replace(core(txt), core(txt)[0] + "*" * (len(core(txt)) - 1))
        if not core(txt): continue                                                                       # "fix" to "" drops the word
        if cur and (a - cur[-1][1] > 0.5 or len(cur) >= S["max_words"] or len(" ".join(x[2] for x in cur)) + len(txt) > S["max_chars"] or cur[-1][2][-1] in ".?!"):
            out.append(cur); cur = []
        cur.append((a, b, txt))
    if cur: out.append(cur)
    cues = [[c[0][0], c[-1][1] + 0.3, " ".join(x[2] for x in c)] for c in out]
    for i in range(len(cues) - 1): cues[i][1] = min(cues[i][1], cues[i + 1][0]) if cues[i + 1][0] - cues[i][1] > 0.3 else cues[i + 1][0]
    return cues, pos, beeps

def cue_png(text, path):
    img = Image.new("RGBA", (W, CAP_H), (0, 0, 0, 0)); d = ImageDraw.Draw(img); lines, line = [], ""
    for wd in text.split():
        if line and d.textlength(line + " " + wd, font=FONT) > S["max_width"]: lines.append(line); line = wd
        else: line = (line + " " + wd).strip()
    lines.append(line); LINE, PX, PY, R, B = S["line_height"], S["pad_x"], S["pad_y"], S["radius"], S.get("border_width", 0)
    bw = int(max(d.textlength(l, font=FONT) for l in lines)) + 2 * PX; bh = LINE * len(lines) + 2 * PY
    x0, y0 = (W - bw) // 2, (CAP_H - bh) // 2; box = (x0, y0, x0 + bw, y0 + bh)
    d.rounded_rectangle(box, R, fill=tuple(S["box"]))
    stops = S.get("border") or []
    if B and stops:                                                           # border colour: one stop = solid, more = gradient across the box
        stops = [(0.0, stops[0][1])] + stops if len(stops) == 1 else stops
        grad = Image.new("RGB", (W, 1)); px = grad.load()
        for x in range(W):
            t = min(1.0, max(0.0, (x - x0) / bw)); (t0, c0), (t1, c1) = next((a, b) for a, b in zip(stops, stops[1:]) if t <= b[0])
            px[x, 0] = tuple(int(c0[i] + (c1[i] - c0[i]) * (t - t0) / max(t1 - t0, 1e-9)) for i in range(3))
        ring = Image.new("L", img.size, 0); ImageDraw.Draw(ring).rounded_rectangle(box, R, outline=255, width=B)
        img.paste(grad.resize(img.size), (0, 0), ring)
    for i, l in enumerate(lines):
        d.text((W / 2, y0 + PY + LINE * i + LINE / 2), l, font=FONT, fill=tuple(S["text"]), anchor="mm")
    img.save(path)

dest = os.path.abspath(arg("--out", src["out"])); only = int(arg("--only", 0)) or None; fix_all = {k.lower(): v for k, v in src.get("fix", {}).items()}
tmp = os.path.join(w, "shorts"); os.makedirs(tmp, exist_ok=True); os.makedirs(dest, exist_ok=True); md = [f"# {name} shorts\n"]; fail = False
for n, sh_ in enumerate(shorts, 1):
    ranges = [(snap(s, onsets), snap(e, offsets)) for s, e in sh_["ranges"]]
    segs = [(s, e) for s, e in intersect(ranges, keeps) if e - s >= MIN_KEEP]
    part = [q for q in PARTS if q["start"] <= segs[0][0] and segs[-1][1] <= q["end"]]
    if len(part) != 1: sys.exit(f"short {n} spans two recording parts: split it")
    cues, dur, beeps = cues_for(segs, {**fix_all, **{k.lower(): v for k, v in sh_.get("fix", {}).items()}}, [b.lower() for b in sh_.get("bleep", [])])
    assert dur <= MAX_S, f"short {n} '{sh_['slug']}' is {dur:.0f}s: over {MAX_S:.0f}s, trim its ranges"
    fname = f"{name}_short_{n:02d}_{sh_['slug']}.mp4"; out = os.path.join(tmp, fname)
    if only not in (None, n): continue
    blank = os.path.join(tmp, "blank.png"); Image.new("RGBA", (W, CAP_H), (0, 0, 0, 0)).save(blank)
    lst, t = ["ffconcat version 1.0"], 0.0
    for i, (a, b, text) in enumerate(cues):
        if a > t: lst += [f"file '{blank}'", f"duration {a - t:.3f}"]
        p = os.path.join(tmp, f"cue_{n}_{i}.png"); cue_png(text, p); lst += [f"file '{p}'", f"duration {b - a:.3f}"]; t = b
    lst += [f"file '{blank}'", f"duration {max(dur - t, 0.04):.3f}", f"file '{blank}'"]
    open(os.path.join(tmp, f"cues_{n}.txt"), "w", encoding="utf-8").write("\n".join(lst) + "\n")
    p0 = part[0]["start"]; t0 = max(0.0, segs[0][0] - p0 - 1.0); rel = [(s - p0 - t0, e - p0 - t0) for s, e in segs]; K = len(rel)
    src_in = ["-ss", f"{t0:.3f}", "-t", f"{rel[-1][1] + 1:.3f}", "-i", part[0]["video"]]; pre = os.path.join(tmp, f"pre_{n}.wav"); dyn, norm = LEVEL_FILTER.split(",", 1)
    # audio first: joined pieces, bleeps, dynaudnorm -> wav; measure it so loudnorm can hit the target in its two-pass mode
    fa = f"[0:a]asplit={K}" + "".join(f"[sa{k}]" for k in range(K)) + ";" + "".join(f"[sa{k}]atrim={s:.3f}:{e:.3f},asetpts=PTS-STARTPTS[a{k}];" for k, (s, e) in enumerate(rel))
    fa += "".join(f"[a{k}]" for k in range(K)) + f"concat=n={K}:v=0:a=1,aresample=48000[a];"
    if beeps:   # mute each bleeped word and put a 1 kHz tone over it
        on = "+".join(f"between(t,{a - 0.15:.3f},{b + 0.05:.3f})" for a, b in beeps)
        fa += (f"[a]volume=0:enable='{on}'[am];sine=frequency=1000:sample_rate=48000:duration={dur:.3f},volume=0.08,volume=0:enable='not({on})'[bz];"
               f"[am][bz]amix=inputs=2:normalize=0:duration=first[a];")
    sh(["ffmpeg", "-v", "error", "-y", *src_in, "-filter_complex", fa + f"[a]{dyn}[ao]", "-map", "[ao]", "-c:a", "pcm_s24le", pre])
    m = json.loads(re.search(r"\{[^{}]*\}", sh(["ffmpeg", "-v", "info", "-i", pre, "-af", norm + ":print_format=json", "-f", "null", "-"]).stderr, re.S).group(0))
    norm += f":measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:offset={m['target_offset']}"
    vw, vh = map(int, probe(part[0]["video"], "width,height")[:2]); fx = float(sh_.get("focus_x", 0.5))
    fit = "" if (vw, vh) == (W, H) else f",scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}:(iw-{W})*{fx}:(ih-{H})/2"   # cover 9:16
    fc = f"[0:v]split={K}" + "".join(f"[sv{k}]" for k in range(K)) + ";" + "".join(f"[sv{k}]trim={s:.3f}:{e:.3f},setpts=PTS-STARTPTS[v{k}];" for k, (s, e) in enumerate(rel))
    fc += "".join(f"[v{k}]" for k in range(K)) + f"concat=n={K}:v=1:a=0{fit}[v];[1:v]fps={FPS:g}[c];[v][c]overlay=0:{CAP_Y}:eof_action=pass[vo];[2:a]{norm}[ao]"
    sh(["ffmpeg", "-v", "error", "-y", *src_in, "-f", "concat", "-safe", "0", "-i", os.path.join(tmp, f"cues_{n}.txt"), "-i", pre,
        "-filter_complex", fc, "-map", "[vo]", "-map", "[ao]", "-r", f"{FPS:g}", "-c:v", "libx264", "-crf", "18", "-preset", "fast", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "256k", "-ar", "48000", "-movflags", "+faststart", out])
    shutil.copy(out, os.path.join(dest, fname))
    L = loudness(out); real = float(sh(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", out]).stdout)
    ok = abs(L["i"] + 16) <= 1.0 and L["tp"] <= -1.0 and real < 180 and abs(real - dur) < 0.5; fail |= not ok
    print(f"{fname}: {real:.1f}s ({len(segs)} pieces, {len(cues)} captions)  I={L['i']:.2f} LUFS TP={L['tp']:+.2f}  {'OK' if ok else 'OUT OF SPEC'}", flush=True)
    tags = sh_.get("tags", [])
    md.append(f"## {n}. {sh_['title']}\n\n- file: `{fname}` ({real:.0f} s, {L['i']:.1f} LUFS)\n- source: " + ", ".join("%d:%02d-%d:%02d" % (s // 60, s % 60, e // 60, e % 60) for s, e in ranges)
              + f"\n- description: {sh_.get('description', '')}\n- tags: {', '.join(tags)}\n- hashtags: {' '.join('#' + re.sub(r'[^A-Za-z0-9]', '', t) for t in tags[:5])} #Shorts\n")
if only is None: open(os.path.join(dest, f"{name}_shorts.md"), "w", encoding="utf-8").write("\n".join(md))
print("shorts folder:", dest, "| titles and tags:", f"{name}_shorts.md"); sys.exit(1 if fail else 0)
