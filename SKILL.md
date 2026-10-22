---
name: making-youtube-shorts-from-recordings
description: Use when asked to cut YouTube Shorts, Reels or TikTok clips from a recorded podcast, interview, talk or livestream video - picking the best moments, burning in captions, bleeping swear words, or making vertical 9:16 clips from a long recording.
---

# Making YouTube Shorts from Recordings

## Overview

Scripted pipeline with one judgment step. Whisper transcribes the recording verbatim. An energy analysis finds speech,
filler words (um/uh) and long pauses. You pick the moments from the transcript. `make_shorts.py` cuts them with the
fillers and pauses removed, burns in styled captions, crops to 1080x1920 and levels the audio to -16 LUFS.
No video editor needed: Python, ffmpeg and Pillow only.

**Input:** a video file. A vertical 1080x1920 recording is ideal (e.g. Ecamm's "(Vertical)" output). Other sizes are
scaled and cropped to 9:16. A recording split into several files (restart mid-session) is passed as several files in order.

## Workflow

```bash
SK=~/.claude/skills/making-youtube-shorts-from-recordings
PY=$(sh $SK/scripts/setup.sh | tail -1)       # venv with Whisper + Pillow; idempotent, ~1 min first time; needs ffmpeg
WORK="$(dirname "$VIDEO")/_shorts_work"   # VIDEO = the recording; any empty folder works
```

| Step | Command | Output / check |
|---|---|---|
| 1 Prepare | `$PY $SK/scripts/prepare.py "$WORK" VIDEO [VIDEO2 ...] --name ep_12` | `transcript.txt`, `cuts.json` (fillers and pauses), `speech.json`, `source.json`. About 1 min per 5 min of audio on Apple silicon. Long recordings: run with `nohup ... &` and poll. Options: `--out DIR` (default `<video folder>/shorts`), `--style NAME`, `--language xx`; saved in `source.json` for step 3. |
| 2 Pick | read `"$WORK/transcript.txt"` in full, write `"$WORK/shorts.json"` | see below |
| 3 Render | `$PY $SK/scripts/make_shorts.py "$WORK"` (`--only N` renders one) | `<out>/<name>_short_NN_<slug>.mp4` plus `<name>_shorts.md` (titles, descriptions, tags, hashtags). Prints length and loudness per short; exits 1 if any is out of spec: check the exit code (don't pipe through `tail`). |

Several recordings: moment picking is independent work. Use one subagent per recording, each reading one transcript.

## Step 2: picking moments (the judgment call)

Pick 8-15 moments unless the user names a count: each guest's self-introduction, plus any insightful, funny or quotable moment from anyone.

```json
[{"slug": "thermostat-bug", "title": "My thermostat bug left my house freezing in December",
  "description": "Davide Bettio, creator of AtomVM, on the first device that ever ran it.",
  "tags": ["AtomVM", "Erlang", "IoT"], "ranges": [[79.26, 97.0], [148.9, 208.0]],
  "fix": {"atom vm": "AtomVM"}, "bleep": ["shit"], "focus_x": 0.5}]
```

- `ranges`: recording seconds, joined in order. Use several ranges to skip interjections and tangents. Take boundaries
  from the word times in `whisper.json`, not the segment lines
  (`python3 -c "import json,sys;[print('%.2f %.2f %s' % (x['start'], x['end'], x['word'])) for s in json.load(open(sys.argv[1]))['segments'] for x in s['words'] if float(sys.argv[2])<=x['start']<=float(sys.argv[3])]" "$WORK/whisper.json" 90 150`). The script snaps each edge to the nearest speech
  onset/offset and drops the fillers and pauses in `cuts.json`. Final length must be <= 175 s (asserted; YouTube's limit is 180 s).
  A short cannot span two parts of a split recording.
- `fix` (optional): lowercase word or two-word key Whisper misheard -> correct caption text. `""` drops the word.
  Names and jargon are usually wrong: check every name in the chosen ranges. Fixes needed in every short can go once in
  `source.json` `"fix"`; both are applied, the short's entry wins on the same key.
- `bleep` (optional): keep the moment, bleep the word. It is muted under a 1 kHz tone and starred in the caption
  ("s***"). Scan every chosen range for profanity before rendering.
- `focus_x` (optional, non-vertical sources only): horizontal crop centre, 0 = left edge, 1 = right, default 0.5.
  Point it at the speaker: grab a frame (`ffmpeg -ss T -i VIDEO -frames:v 1 f.png`) and look. The crop can cut off a
  name tag baked into a horizontal recording.
- Title <= 80 characters, true to what is said, no emoji. Tags 6-10.

## Caption style

`source.json` `"style"` or `--style` names a file in `styles/` or gives a path to a JSON file.
`default.json`: white on a translucent black box. `beam_there.json`: example brand preset with a gradient border.
To make a brand style, copy `default.json` and change it. Fields: `font` (path relative to the style file),
`size`, `weight` (variable-font axis), `text`/`box` RGBA, `border_width`, `border` gradient stops, `radius`, `pad_x`,
`pad_y`, `line_height`, `y` (top of the caption strip on the 1920 px canvas), `strip_height`, `max_width`,
`max_words`/`max_chars` per caption. Put `y` above any name tag or lower third baked into the recording.

## Using cut plans from another tool

`make_shorts.py` reads only `WORK/source.json`, `whisper.json` (Whisper JSON with word timestamps), `speech.json`
(`[[start, end], ...]` speech intervals) and `cuts.json` (`[[start, end, label], ...]` removed ranges). An editing
pipeline that already has a transcript and a cut list can write these four files instead of running `prepare.py`.
`source.json`: `{"name", "fps", "out", "style", "fix": {}, "parts": [{"video", "start", "end"}]}` (part times in seconds).

## Pitfalls

| Symptom | Cause / fix |
|---|---|
| Transcript has no "um/uh" | Whisper drops fillers without a prompt; `prepare.py` passes a filler prompt |
| Captions misspell names | Whisper guesses names; add `fix` entries |
| Some fillers stay in | Whisper's word times are +-0.3 s; fillers whose boundaries can't be found on the audio are kept, not cut mid-word (`prepare.py` prints the count) |
| ffmpeg has no `subtitles`/`drawtext` filter (Homebrew build without libass) | Not needed: captions are drawn as PNGs with Pillow and overlaid through the concat demuxer |
| Short sounds louder or quieter than the episode | Both use `dynaudnorm` + two-pass `loudnorm` to -16 LUFS; AAC can overshoot the true peak by ~0.2 dB |
| Wrong person framed in a cropped horizontal recording | Set `focus_x`; for speaker-switching layouts record a vertical version instead |

## Report to the user

The shorts folder, count, each title with its length, the `_shorts.md` path, and any names you were unsure of.
