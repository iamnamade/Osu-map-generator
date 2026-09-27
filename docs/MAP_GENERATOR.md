# Map Generator

## What This Phase Implements

This phase adds the first in-house audio analyzer and automatic beatmap generator for the browser rhythm game. It analyzes local audio, selects playable rhythm events, generates deterministic circle positions, writes browser-compatible JSON beatmaps, and keeps the existing manual test map working.

## Built From Scratch

The generator in `tools/map_generator/` is algorithmic and built from scratch for this project.

It does not use:

- machine learning
- pretrained models
- remote APIs
- copied external map-generation repositories

## Python Version

Use Python 3.10 or newer.

The current project scripts are Windows-friendly and can use a local virtual environment when one exists.

## FFmpeg Setup

The analyzer tries to decode audio locally through the Python audio stack first.

FFmpeg is still recommended, especially for MP3-heavy workflows:

1. Install FFmpeg.
2. Make sure `ffmpeg` is available on your `PATH`.
3. Restart your terminal after installation.

If MP3 decoding fails and FFmpeg is unavailable, the CLI prints a readable error instead of a raw traceback.

## Create a Virtual Environment

PowerShell:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

## Install Generator Dependencies

PowerShell:

```powershell
python -m pip install --upgrade pip
python -m pip install -r tools/map_generator/requirements.txt
```

If you are not using an activated virtual environment, you can use:

```powershell
py -3 -m pip install -r tools/map_generator/requirements.txt
```

## Analyze an Audio File

PowerShell:

```powershell
python -m tools.map_generator.cli analyze `
  --audio public/audio/test-song.mp3 `
  --output public/analysis/test-song-analysis.json
```

## Generate Easy, Normal, and Hard Maps

PowerShell:

```powershell
python -m tools.map_generator.cli generate `
  --audio public/audio/test-song.mp3 `
  --title "Test Song" `
  --artist "Unknown Artist" `
  --difficulty easy `
  --seed 42 `
  --output public/maps/generated/test-song-easy.json `
  --analysis-output public/analysis/test-song-analysis.json
```

```powershell
python -m tools.map_generator.cli generate `
  --audio public/audio/test-song.mp3 `
  --title "Test Song" `
  --artist "Unknown Artist" `
  --difficulty normal `
  --seed 42 `
  --output public/maps/generated/test-song-normal.json `
  --analysis-output public/analysis/test-song-analysis.json
```

```powershell
python -m tools.map_generator.cli generate `
  --audio public/audio/test-song.mp3 `
  --title "Test Song" `
  --artist "Unknown Artist" `
  --difficulty hard `
  --seed 42 `
  --output public/maps/generated/test-song-hard.json `
  --analysis-output public/analysis/test-song-analysis.json
```

You can also use the npm scripts added to `package.json`.

## Difficulty Presets

`easy`

- focuses mostly on strong primary beats
- uses large circles and long approach time
- prefers smoother motion and wider timing gaps

`normal`

- keeps most important beats
- allows some strong off-beat onsets
- uses moderate circle size, approach time, and jumps

`hard`

- keeps more rhythmic detail
- uses shorter approach time and smaller circles
- allows more movement variation while still enforcing speed limits

These presets are custom project rules, not official osu! star ratings.

## How the Seed Works

The `--seed` value controls deterministic position generation.

For the same:

- audio
- difficulty
- configuration
- seed

the generator produces the same object positions and timing choices.

Changing only the seed keeps timing selection the same and changes placement patterns.

## Where Generated Files Are Written

- analysis JSON: `public/analysis/`
- generated beatmaps: `public/maps/generated/`

## How the Audio Path Inside the Beatmap Works

The generator converts an audio file under `public/` into a browser path such as:

```json
"/audio/test-song.mp3"
```

That path is what the Phaser frontend loads at runtime.

## Current Limitations

This first generator:

- generates circles only
- uses algorithmic rules rather than ML
- does not understand lyrics
- does not perfectly detect song sections
- may misinterpret unusual time signatures
- may require manual timing correction
- does not calculate official osu! star rating
- is intended as the foundation for later validation and improvement phases

## How to Tune Generator Configuration

Edit `tools/map_generator/config.py`.

The main tuning knobs live in the difficulty presets:

- `min_gap_ms`
- `target_gap_ms`
- `onset_strength_threshold`
- `circle_radius`
- `approach_time_ms`
- `preferred_jump_distance`
- `max_jump_distance`
- `max_cursor_speed`
- `pattern_variation`
- `start_padding_ms`
- `end_padding_ms`

For deeper behavior changes, the selection rules live in `event_selector.py` and the placement heuristics live in `position_generator.py`.
