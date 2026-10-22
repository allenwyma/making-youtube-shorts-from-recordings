# Making YouTube Shorts from Recordings

A [Claude Code](https://claude.com/claude-code) skill that turns a long recording (podcast, interview, talk, livestream)
into YouTube Shorts, Reels or TikTok clips.

Claude reads the transcript and picks the best moments. Scripts do the rest:

- verbatim transcription with Whisper, including "um" and "uh"
- filler words and long pauses cut out of every clip
- several ranges joined into one short, to skip interjections and tangents
- burned-in captions in a style you set (font, colours, box, gradient border, position)
- caption fixes for names and jargon Whisper gets wrong
- swear words muted under a tone and starred in the caption
- 1080x1920 output; horizontal recordings are cropped to 9:16
- audio leveled to -16 LUFS, checked after rendering
- a Markdown file with a title, description, tags and hashtags for each short

No video editor needed.

## Requirements

- Claude Code
- Python 3.11 or newer
- ffmpeg (macOS: `brew install ffmpeg`)
- Transcription runs locally: mlx-whisper on Apple silicon Macs, faster-whisper elsewhere. The first run downloads the
  Whisper large-v3-turbo model (about 1.6 GB).

## Install

```bash
git clone git@github.com:allenwyma/making-youtube-shorts-from-recordings.git ~/.claude/skills/making-youtube-shorts-from-recordings
sh ~/.claude/skills/making-youtube-shorts-from-recordings/scripts/setup.sh
```

`setup.sh` creates a Python virtual environment in the skill folder (`.venv`, git-ignored). Restart Claude Code so it
loads the skill.

## Use

Ask Claude Code, for example:

> Make YouTube Shorts from ~/Movies/episode-12.mp4

Claude transcribes the recording, picks 8-15 moments (or the number you ask for), writes titles and tags, and renders
the clips to a `shorts` folder next to the video.

## Use without Claude

```bash
SK=~/.claude/skills/making-youtube-shorts-from-recordings
PY=$SK/.venv/bin/python
WORK=~/Movies/_shorts_work

$PY $SK/scripts/prepare.py $WORK ~/Movies/episode-12.mp4 --name ep_12   # transcript.txt, cuts, speech
# write $WORK/shorts.json (format in SKILL.md)
$PY $SK/scripts/make_shorts.py $WORK
```

Example `shorts.json`:

```json
[{"slug": "thermostat-bug", "title": "My thermostat bug left my house freezing in December",
  "description": "On the first device that ever ran it.", "tags": ["IoT", "debugging"],
  "ranges": [[79.26, 97.0], [148.9, 208.0]], "fix": {"atom vm": "AtomVM"}, "bleep": []}]
```

`ranges` are seconds in the recording, as shown in `transcript.txt`.

## Caption styles

Styles are JSON files in `styles/`. Use `--style NAME` or a path to your own file on `prepare.py` or `make_shorts.py`.

- `default.json`: white text on a translucent black box
- `beam_there.json`: an example brand style with a gradient border

Copy `default.json` to start your own. `SKILL.md` lists every field.

## Using your own editing pipeline

If your editor already has a transcript and a cut list, skip `prepare.py` and write the four input files
`make_shorts.py` reads (`source.json`, `whisper.json`, `speech.json`, `cuts.json`). `SKILL.md` describes their format.

## Font

Inter by Rasmus Andersson, SIL Open Font License 1.1. See `assets/FONT-LICENSE.md`.
