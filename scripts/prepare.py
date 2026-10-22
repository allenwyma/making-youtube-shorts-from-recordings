"""Step 1: everything make_shorts.py needs from a recording, without any editor.
Transcribes verbatim (keeps um/uh), finds speech, filler words and long pauses on the audio, writes the cut list.
usage (venv python):  prepare.py WORK_DIR VIDEO [VIDEO ...] [--name NAME] [--language en] [--pause-min 1.0] [--out DIR] [--style NAME]
  VIDEO: the recording the shorts are cut from (vertical 1080x1920 is ideal; other sizes are cropped to 9:16).
         Several files = one recording split into parts, played back to back (a short cannot span two parts).
  -> WORK/source.json, whisper.json, speech.json, cuts.json, transcript.txt (read this to pick the moments)"""
import os, sys, json, time, numpy as np, wave
from shortlib import (work, arg, save, sh, probe, duration, read_wav_mono16k, envelope_db, merge, speech_activity, speech_thr,
                      FILLER_RE, OH_RE, OH_QUOTE_CTX, OH_REPLY_NEXT, HOP)
w = work()
videos, i = [], 2
while i < len(sys.argv):
    if sys.argv[i].startswith("--"): i += 2; continue
    videos.append(os.path.abspath(sys.argv[i])); i += 1
if not videos: sys.exit(__doc__)
for v in videos:
    if not os.path.isfile(v): sys.exit(f"not a file: {v}")
PAUSE_MIN, KEEP_GAP = float(arg("--pause-min", 1.0)), 0.5            # pauses >= 1.0 s are trimmed to 0.5 s
num, den = probe(videos[0], "r_frame_rate")[0].split("/"); FPS = round(float(num) / float(den), 3)

# ---- audio: 16 kHz mono of every part, back to back ----
parts, xs, pos = [], [], 0.0
for j, v in enumerate(videos):
    d = duration(v); p = os.path.join(w, f"mix_p{j}.wav")
    if not os.path.exists(p): sh(["ffmpeg", "-v", "error", "-y", "-i", v, "-vn", "-ac", "1", "-ar", "16000", "-af", "apad", "-t", f"{d:.6f}", p])
    xs.append(read_wav_mono16k(p)); parts.append({"video": v, "start": round(pos, 3), "end": round(pos + d, 3)}); pos += d
mix = os.path.join(w, "mix16k.wav"); f = wave.open(mix, "wb"); f.setnchannels(1); f.setsampwidth(2); f.setframerate(16000)
x = np.concatenate(xs); f.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes()); f.close()
src = {"name": arg("--name", os.path.splitext(os.path.basename(videos[0]))[0]), "fps": FPS, "parts": parts,
       "out": os.path.abspath(arg("--out", os.path.join(os.path.dirname(videos[0]), "shorts"))), "style": arg("--style", "default"), "fix": {}}
save(w, "source.json", src); print(f"{len(parts)} part(s), {pos / 60:.1f} min at {FPS:g} fps -> shorts go to {src['out']}", flush=True)

# ---- transcription: Whisper with a filler prompt, otherwise it drops um/uh ----
out = os.path.join(w, "whisper.json"); PROMPT = "Um, uh, so, um, I think, uh, you know, hmm, it's like, uh... Oh, ah, okay. Umm, yeah."
if os.path.exists(out): print("exists, reusing", out)
else:
    t0 = time.time(); lang = arg("--language", "en")
    try:
        import mlx_whisper                                                    # Apple silicon
        res = mlx_whisper.transcribe(mix, path_or_hf_repo="mlx-community/whisper-large-v3-turbo", language=lang, word_timestamps=True,
                                     initial_prompt=PROMPT, condition_on_previous_text=True, verbose=False)
    except ImportError:
        from faster_whisper import WhisperModel                               # everything else
        segs, _ = WhisperModel("large-v3-turbo", compute_type="auto").transcribe(mix, language=lang, word_timestamps=True, initial_prompt=PROMPT)
        res = {"segments": [{"start": s.start, "end": s.end, "text": s.text,
                             "words": [{"start": x.start, "end": x.end, "word": x.word} for x in s.words or []]} for s in segs]}
    json.dump(res, open(out, "w")); print(f"transcribed: {len(res['segments'])} segments in {time.time() - t0:.0f}s", flush=True)
res = json.load(open(out))

# ---- speech, fillers, pauses ----
db = envelope_db(x); THR = speech_thr(db); raw, act = speech_activity(db, THR); n = len(db)
save(w, "speech.json", [[round(s, 3), round(e, 3)] for s, e in act])
words = sorted([{"s": float(x["start"]), "e": float(x["end"]), "t": x["word"].strip()} for sg in res["segments"] for x in sg.get("words", [])], key=lambda x: x["s"])
voiced = db > THR; sm = np.convolve(db, np.ones(5) / 5, mode="same"); fi = lambda t: int(max(0, min(n - 1, round(t / HOP))))
def refine(ws, we, pe, ns):
    """Cut range for a filler Whisper put at ws-we (times are +-0.3 s) between neighbour words ending pe / starting ns,
    from the energy envelope: the voiced blob around it, else the quietest points around its edges."""
    ci = fi((ws + we) / 2)
    if voiced[max(0, ci - 20):ci + 21].any():
        k = ci if voiced[ci] else min([j for j in range(max(0, ci - 20), min(n, ci + 21)) if voiced[j]], key=lambda j: abs(j - ci))
        b0 = k
        while b0 > 0 and voiced[b0 - 1]: b0 -= 1
        b1 = k
        while b1 < n - 1 and voiced[b1 + 1]: b1 += 1
        bs, be = b0 * HOP, (b1 + 1) * HOP
        if be - bs <= 0.8 and bs >= pe - 0.25 and be <= ns + 0.25:          # a blob > 0.8 s is the filler glued to a word
            s_, e_ = max(bs, pe - 0.06), min(be, ns + 0.06)
            j = b0
            while j > 0 and not voiced[j - 1]: j -= 1
            j2 = b1 + 1
            while j2 < n and not voiced[j2]: j2 += 1
            s_ -= max(0.0, (b0 - j) * HOP - 0.08); e_ += max(0.0, (j2 - b1 - 1) * HOP - 0.08)
            if e_ - s_ >= 0.10: return s_, e_
    if we - ws >= 0.05:
        def argmin_t(a, b):
            ia, ib = fi(a), fi(b)
            return None if ib <= ia else (ia + int(np.argmin(sm[ia:ib + 1]))) * HOP
        s_ = argmin_t(max(pe - 0.10, ws - 0.25), ws + 0.15); e_ = argmin_t(we - 0.15, min(ns + 0.10, we + 0.25))
        if s_ is not None and e_ is not None and 0.12 <= e_ - s_ <= 0.9 and voiced[fi(s_):fi(e_)].mean() > 0.5: return s_, e_
    return None, None
cuts, skipped = [], 0
for i, wd in enumerate(words):
    is_f = bool(FILLER_RE.match(wd["t"]))
    if not is_f and OH_RE.match(wd["t"]):                                     # standalone "oh", not quoted speech or a reply
        prev = " ".join(x["t"] for x in words[max(0, i - 3):i]); nxt = " ".join(x["t"] for x in words[i + 1:i + 4])
        is_f = not (OH_QUOTE_CTX.search(prev) or OH_REPLY_NEXT.match(nxt))
    if not is_f: continue
    pe = words[i - 1]["e"] if i > 0 else 0.0; ns = words[i + 1]["s"] if i + 1 < len(words) else n * HOP
    s_, e_ = refine(wd["s"], wd["e"], pe, ns)
    pm = (words[i - 1]["s"] + words[i - 1]["e"]) / 2 if i > 0 else -1; nm = (words[i + 1]["s"] + words[i + 1]["e"]) / 2 if i + 1 < len(words) else 1e9
    if s_ is None or not (s_ > pm and e_ < nm): skipped += 1; continue      # timing unreliable: keep the filler
    cuts.append([round(s_, 3), round(e_, 3), "filler"])
nf = len(cuts); speech, gap0 = merge(raw, gap=0.25), 0.0
for s, e in speech + [(n * HOP, n * HOP)]:
    if s - gap0 >= PAUSE_MIN: cuts.append([round(gap0 + KEEP_GAP / 2, 3), round(s - KEEP_GAP / 2, 3), "pause"])
    gap0 = max(gap0, e)
save(w, "cuts.json", sorted(cuts))
print(f"speech threshold {THR:.1f} dB | fillers cut {nf}, kept (timing unsure) {skipped} | pauses >= {PAUSE_MIN}s: {len(cuts) - nf}")

def tc(t): t = max(t, 0); return "%02d:%02d:%05.2f" % (t // 3600, t % 3600 // 60, t % 60)
with open(os.path.join(w, "transcript.txt"), "w") as f:
    for s in res["segments"]:
        if s["text"].strip(): f.write(f"[{tc(s['start'])}-{tc(s['end'])}] {s['text'].strip()}\n")
print("wrote", os.path.join(w, "transcript.txt"))
