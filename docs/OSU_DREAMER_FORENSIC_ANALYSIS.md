# osu!dreamer — Forensic Analysis & Extraction Guide

Target: `osu-dreamer` (jb2170), source snapshot `osu-dreamer-main` (no `.git`, so no commit hash;
`pyproject.toml` version `0.1.0`). 41 Python modules, **4011 LOC**, no bundled weights
(`inference.pt` / `*.ckpt` are absent — training or a download is required to generate anything).

Companion to: `docs/ARCHITECTURE.md`, `docs/MAP_GENERATOR.md`, `docs/OSU_FORMAT_INTEROPERABILITY.md`.

Everything below is read off the source, not the README. File references are relative to the
`osu_dreamer/` package unless stated otherwise. Numeric constants were recomputed independently —
see [Appendix A](#appendix-a--constant-verification).

---

## 1. High-Level Pipeline & Architecture

### 1.1 Execution flow (inference: audio → `.osz`)

`scripts/predict.py::predict`

| # | Step | Code |
|---|------|------|
| 1 | Read `Title` / `Artist` from audio tags (`tinytag`); CLI overrides win, else hard error | `predict.py` |
| 2 | Load `inference.pt` → rebuild `LDM` from stored hparams + state dict | `models/inference/artifact.py::load_inference` |
| 3 | Decode audio to **16 kHz mono**, build a 72-band log-power "spectrogram" | `data/load_audio.py::load_wave`, `make_spec` |
| 4 | Shape the requested difficulty tuple `(sr, ar, od, cs, hp)` into a `B×5` label tensor | `predict.py` |
| 5 | `LDM.sample`: encode audio once → per-label style code `s` → sample chart latent `z` with 8 sphere-tracing steps → decode `z` → 9-channel signal | `models/inference/model.py` |
| 6 | Turn the 9-channel signal back into hit objects (peak-picking, extent edges, per-slider curve fitting) | `data/beatmap/decode.py` |
| 7 | Synthesise timing points from slider geometry, fill the `v14` template | `data/beatmap/decode.py` |
| 8 | Zip audio + one `.osu` per `--diff` into `_<hex7> Artist - Title.osz` | `predict.py` |

Note step 7: **timing is an *output* of geometry, not an input to placement.** This is the single
most important architectural fact about this generator (§2.4).

### 1.2 Training pipeline (5 stages, strictly ordered)

```
Songs/*.osu ──► generate-data ──► data/<audio_hash>/{spec.npy, <id>.map.npy}
                                        │
                                        ├──► fit-latent    (chart AA / WAE, 3^3=27-frame chunks)
                                        │        │
                                        │        └──► encode-latents ──► *.latent.npz + h.npy
                                        │                                   │
                                        │                                   ├──► fit-denoiser (diffusion in z)
                                        │                                   └──► fit-style   (diffusion in s)
                                        │
                                        └──► export-inference ──► inference.pt (EMA weights only)
```

- Dataset source is hardcoded: HuggingFace `project-riz/osu-beatmaps` (`compressed`), streaming,
  mapped via `torchcodec` + `datasets`. Only `mode == 0` (osu!std) and `approved == 1` (ranked) are kept.
- Split is **by mapset**, not by map (`hold_out_mapsets`), to prevent audio leakage across diffs.
- 5 stages × 3 models is the practical cost. This is *not* something we can retrain casually.

### 1.3 Underlying paradigm

**Latent diffusion (a learned distance field), not heuristics, not DSP beat-tracking.**

Three models, all trained independently:

1. **LatentModel** — a deterministic chart autoencoder (WAE-MMD, *no* per-sample KL, no reparameterization).
   `(audio, chart) → (z, s)` where `z` is a temporally-varying latent at 161.5 ms resolution and
   `s` is a **32-dim time-invariant style code** for the whole difficulty.
2. **DiffusionModel** — generates `z` conditioned on audio features `h` + style `s`.
3. **StyleModel** — generates `s` conditioned on the difficulty tuple.

Two things make it *not* standard DDPM:
- the network predicts a **distance to the data manifold** `u` and a unit **direction** `v`, not noise `ε`;
- sampling is **fixed-step sphere tracing**, not an ancestor sampler (`models/diffusion/model.py::sample`). See §7.3.

Crucially, **there is zero signal processing for rhythm**. No onset/beat library, no tempo estimation,
no quantisation. The model learns rhythm statistically from spectrogram → onset-activation correlation.
`librosa` is declared in `[dependency-groups].dev` and **imported nowhere** in the tree; `aubio`,
`madmom`, `essentia` are absent. FFmpeg is required only as `torchcodec`'s decoder backend.

### 1.4 Dependency graph (runtime)

| Dependency | Used for | Portability to us |
|---|---|---|
| `torch==2.11` (cu130 index) | all three models | **blocking** for the generative core |
| `torchcodec` | audio decode → 16 kHz mono | replaceable (`ffmpeg`/`soundfile`) |
| `resonators` | 72-band resonator-bank spectrogram | replaceable, non-trivial (see §2.1) |
| `pytorch-lightning`, `jsonargparse` | training CLI only | not needed for inference |
| `rosu-pp-py` | star rating + parsed `AR/OD/CS/HP/SM` | used only at dataset-encode time |
| `datasets` (HF), `einops`, `scipy`, `tinytag`, `click`, `tqdm` | data/glue | `scipy` only for `find_peaks`, `comb`, `zeta` |

The **geometry/formatting third** of the codebase has **no torch dependency at all** —
`osu/bezier.py`, `osu/sliders.py`, `osu/hit_objects.py`, `data/beatmap/slider/fit_arc.py`,
`fit_bezier.py`, `slider_prior.py`, `decode_slider.py` need only `numpy` (+`scipy.special` for 3 calls).
That is the extractable subset, and it is the subset worth extracting.

---

## 2. Audio Signal Processing & Timing Detection

### 2.1 The "spectrogram" — resonator bank, not STFT

`data/load_audio.py`:

```python
F_MIN, BINS_PER_OCTAVE, N_OCTAVES = 32, 9, 8
N_BINS = A_DIM = 72                       # 8 octaves × 9 bins/octave
F_MAX = F_MIN * (1 << N_OCTAVES)          # 8192 Hz
SR    = 2 * F_MAX                         # 16384 Hz
MS_PER_FRAME = 6
HOP_LEN = (SR * 6 + 500) // 1000          # 98 samples
```

- Frequencies are **log-spaced**: `np.geomspace(32, 8192, 72, endpoint=False)` — a constant-Q-ish grid
  (9 bins/octave ≈ 1.33 semitone resolution).
- Magnitudes come from `ResonatorBank(freqs, SR).resonate(wave, hop=98)` — an IIR resonator-bank filter
  (gammatone-like), **not** `np.fft`. This gives better transient localisation at low latency than a
  windowed STFT, at O(N·bands) cost.
- Frame period: `98 / 16384 = 5.9814 ms` → **167.18 fps**. This is the *entire* temporal resolution of
  the system for both input and output.

Normalisation (this is the whole dynamic-range story):

```python
sig = |spec|²                       # power
sig = max(1e-10, sig)
sig = log10(sig) - log10(sig.max())  # ≤ 0, in decades
sig = (15 * sig + 60) / 60
sig = clip(sig, 0, 1)
```

`15/60 = 0.25` per decade; `sig == 0` at `-4` decades → **the image is a 40 dB-window
log-power spectrogram, 72×L, uint8 on disk** (`0` at −40 dB re peak, `1` at peak).

### 2.2 Onset & beat tracking

**There is none.** No spectral-flux, no comb filter, no autocorrelation tempo estimate, no
dynamic-programming beat tracker. Concretely:

- `data/beatmap/timing.py::timing_signal` (beat phase + measure phase, the only beat-grid code in the
  repo) is **dead code** — imported by nobody.
- `Beatmap.beat_divisor` is parsed from `[Editor]` and **never read**.
- `Beatmap.uninherited_timing_points()` exists and is **never called**.

What actually happens: the network learns an implicit audio→onset mapping, and "onsets" are then
recovered from its output by peak-picking a 1-D activation curve:

```python
def events(ts, frame_times, sigma=10):          # data/beatmap/hit.py
    return np.exp(-0.5 / sigma**2 * (ts[:,None] - frame_times[None])**2).max(axis=1)

def decode_events(events):
    return scipy.signal.find_peaks(events, height=0.7)[0].tolist()
```

So the "onset detector" is: *one Gaussian bump per hit (σ = 10 ms, hard max-combined), then a fixed
0.7 amplitude threshold*. No minimum-distance, no prominence, no adaptation. Two hits < ~6 ms apart
merge; the 10 ms σ also smears adjacent 1/16 notes.

### 2.3 BPM & offset

**BPM is never detected.** It is *derived from slider geometry* at export time (`decode.py`):

```python
slider_ts.append(t);  slider_vels.append(length * num_slides / (u - t))   # px per ms
base_slider_vel = sqrt(min(slider_vels) * max(slider_vels))               # geometric mean
beat_len = 100 / base_slider_vel                                          # slider_mult forced to 1
```

- `offset = 0`, always. One uninherited timing point for the entire map.
- The algebra is sound and self-documenting in the comments: with `SliderMultiplier = 1`,
  `slide_duration = length/100 * beat_length`, so `velocity = 100/beat_length` and
  `SV = velocity / base_velocity`. Choosing the **geometric mean** of observed velocities as the base is
  a deliberate, clever choice: it equalises `max(SV, 1/SV)` in log space, minimising the worst-case
  distance to osu!'s `[0.1, 10]` SV clamp. (§7.4)
- **Failure mode:** maps with zero sliders hit the `1 if len(slider_vels) == 0` branch →
  `beat_len = 100 ms` → **600 BPM**, and every hit object is now mis-timed relative to any real grid.
  A circle-only map is a completely ordinary generation outcome.

### 2.4 Timing point mechanics

Written in `data/beatmap/decode.py`:

```
0,{beat_len},4,0,0,50,1,0                          # single red line at t=0, meter always 4
{t_slider},{-100/SV},4,0,0,50,0,0                  # one green line *per slider*
```

- Uninherited: exactly one, at `t = 0`. `meter = 4` unconditionally. No BPM changes, ever.
- Inherited: **one per slider**, keyed to that slider's start time, `SV = vel / base_slider_vel`.
  A 400-slider map emits 400 green lines. Volume is hardcoded `50`; kiai/effects hardcoded `0`.
- `SV > 10 or SV < 0.1` only **warns to stdout** and writes the illegal value anyway; osu! will clamp it,
  silently changing the slider's real duration.

So the exported map has *no* meaningful timing structure — it is a per-slider velocity ledger.
`docs/OSU_FORMAT_INTEROPERABILITY.md` should be read as the correct approach here; ours is strictly better.

### 2.5 Quantisation & beat snapping

**None exists.** Snap divisors 1/1 … 1/8 are never computed or used. Object times are
`round(frame_times[i])`, i.e. multiples of **5.981 ms**, then rounded to integer ms:

```python
frame_times = get_frame_times(enc.shape[1]).round().astype(int)
```

Consequences:
- At 180 BPM, 1/4 = 83.333 ms = 13.93 frames → any snapped time lands up to **±3 ms** off the true grid.
- At 120 BPM, 1/8 = 62.5 ms = 10.45 frames → likewise off-grid.
- No grid means no way to express "this pattern is a 1/3 triplet burst" — it can only be approximately
  placed, and the whole map inherits a fixed non-musical quantisation lattice.

This is the clearest functional gap versus our `rhythm/` stack, and it is the reason a pure port of
osu!dreamer's placement cannot replace our rhythm layer.

---

## 3. Hit Object Generation & Geometry Mathematics

### 3.1 The intermediate representation

The model never emits hit objects. It emits a **9 × L signal** at 5.98 ms/frame
(`data/beatmap/encode.py`):

| idx | channel | encoding |
|---|---|---|
| 0 | `ONSET` | Gaussian impulse bank, σ=10 ms, max-combined |
| 1 | `COMBO` | same, only for `new_combo` objects |
| 2 | `SLIDE` | `1` on `[t, t+slide_duration)` for sliders |
| 3 | `SUSTAIN` | `1` on `[t, end_time)` for sliders **and** spinners |
| 4–6 | `WHISTLE`/`FINISH`/`CLAP` | impulse banks |
| 7–8 | `X`/`Y` | normalised cursor position |

Cursor signal construction (`data/beatmap/cursor.py`) — a hand-built piecewise-linear "bot replay":

```
preempt = 1200 + (120 if ar <= 5 else 150) * (5 - ar)      # osu! AR→preempt, correct
for each object:  [t, end)      → on the object (spinner: centre; slider: triangle-wave along path)
                  [end, max(end, next.t - preempt)) → hold at end_pos
                  [approach_start, next.t) → linear lerp end_pos → next.start_pos
```

On disk each axis is min/max-normalised per map to `uint16`, with `xy_min`/`xy_rng` stored alongside.

**Why this matters for us:** the map is a *dense, differentiable, frame-aligned signal*. Every quality
question — onset alignment with the audio, cursor-velocity profile, slider density — becomes a
vectorised array operation instead of an object walk. That is a genuinely better substrate for
scoring/benchmarking than our object-list validator. (§7.2)

### 3.2 Object type selection

Pure threshold cascade over the decoded signal (`data/beatmap/hit.py::decode_hit_signal`):

```
onsets = find_peaks(ONSET, height=0.7)
properties (combo/whistle/finish/clap) matched to the nearest onset within ±ONSET_TOL=2 frames
sustain_end  ← rising/falling edges of SUSTAIN (threshold 0.5)
slide_end    ← rising/falling edges of SLIDE

if sustain_end == -1 or sustain_end - onset < 4:        → HIT CIRCLE      (4 frames ≈ 24 ms)
elif slide_end == -1:                                   → SPINNER
else: num_slides = round((sustain_end - onset) / (slide_end - onset))
                                                        → SLIDER (repeats = num_slides)
```

There is **no playability reasoning**: no min-gap check, no "spinner must be ≥ 1 s", no
"no object during a spinner", no distance/flow constraint, no stack detection. A spinner that is
40 ms long is emitted as a spinner.

### 3.3 Playfield modelling (512×384)

- **Boundary clamping: absent.** `cursor_signal` is multiplied by `[[512],[384]]` and rounded; the
  network's `X`/`Y` heads are **linear, not sigmoid-bounded** (`latent/model.py::decode`), so decoded
  positions can fall outside `[0,512]×[0,384]`. osu! then clamps them on load → objects collapse onto
  the edges. This is a real, observable bug, not a theoretical one.
- **Margin padding: absent.** Objects are routinely placed at x≈0 or y≈384 with a CS-dependent radius
  that then extends off-screen (unreadable).
- **Flow dynamics: emergent only.** There is no angle model, no zig-zag/stream/jump construct, no
  anti-repetition penalty. Flow is whatever the learned cursor distribution produces. Because `X` and `Y`
  are trained with independent random flips (`modules/beatmap.py`: `chart[X] = 1 - chart[X]` with p=0.5),
  the model is explicitly **invariant to mirroring**, which removes a whole class of positional bias but
  also permits perfectly symmetric, flow-dead patterns.
- **Distance/speed control: absent.** No DS link. Cursor travel speed is whatever the interpolation
  produces; there is no `speed > max_cursor_speed → reject` gate (which our `_score_candidate` does have).
- **Stacks: absent.** `StackLeniency` is never written, and nothing generates 0-distance stacks
  (`slisliders/` and `hit_objects.py` have no stack concept).

### 3.4 Distance spacing / SV ↔ BPM link

The only distance↔time coupling is post-hoc and per-slider:

```
duration_single_slide = length / (slider_mult * 100) * beat_length
SV_i                  = (length_i * slides_i / duration_total_i) / base_slider_vel
```

For hit circles, **nothing** links spacing to SV/BPM. So the map has no distance-snap consistency at
all: two consecutive circles 300 px apart at 180 BPM are possible and common.

### 3.5 Slider construction

This is where the engineering effort went, and it is the strongest part of the repo. Three pieces:

**(a) Curve family selection by MAP estimate** (`slider/decode_slider.py`)

Every candidate curve type is scored, not tested against a threshold:

```
cost(type) = SSE / (2σ²) − log P(type),      σ = 16 px  (expected cursor noise)
```

with the prior `P(type)` measured over the training corpus (`slider_prior.py`):

```
P (perfect arc) 938141 | L (line) 672639 | PL (poly-line) 165541 | PB (poly-bezier) 73003 | B (bezier) 55957
m (segments) ~ Zeta(s=4), m ≥ 2
n_ctrl (single bezier) ~ 0.5991·[n==4] + 0.4009·(1-0.7431)·0.7431^(n-3),  n ≥ 3
```

Plus an exact **branch-and-bound shortcut**: since `SSE ≥ 0`, `cost ≥ −log P(type)`. Candidates are
visited in *increasing prior penalty* (sorted, because the cubic spike makes penalty non-monotonic in
degree), and the loop breaks as soon as `−log P ≥ best_cost`. Same answer as exhaustive search,
typically 2–4 fits instead of 14.

**(b) Arc fit** (`slider/fit_arc.py`) — algebraic circle fit:

```
solve  [2x  2y  1] · [cx cy c]ᵀ = x² + y²      (linear least squares)
r² = cx² + cy² + c ;  radius = √r²
reject if  r² ≤ 0
        or radius > 320                       # osu!'s own perfect-circle limit
        or ‖end − start‖ < 15                 # degenerate chord
        or |sweep| < 0.05 rad                 # ~3°
        or > 25 % of Δangle have opposite sign  # not monotone → not an arc
length  = |sweep| · radius
control = [start, centre + R·(cos θ_mid, sin θ_mid), end]       # osu "P" = exactly 3 points
```

**(c) Bezier fit** (`slider/fit_bezier.py`) — Bernstein-basis, linearly-constrained LSQ:

```
t  = linspace(0, 1, L)                       # NOTE: this is the *bezier parameter*, not time
B  = Bernstein(t, n_ctrl)                    # L × n_ctrl,  B_ij = C(d,i) t^i (1−t)^(d−i)
P  = c0 + N·z,   N = selector for the free control points (endpoints pinned when joining)
z  = lstsq(B·N, pointsᵀ − B·c0)              # falls back to pinv on LinAlgError
SSE = ‖B·P − pointsᵀ‖²
c0 = linear interpolation between the two data endpoints   # initial guess, then solved exactly
```

The subtle part — and the reason a naive port underperforms: `t = linspace(0, 1, L)` is only
exact when the caller's samples are uniform in the **bezier parameter**. Upstream's own cursor
signal satisfies this *within a segment* (`Bezier.lerp` maps path fraction → segment parameter
linearly), so its fit is essentially exact on its own training data. Feed it samples spaced by
arc length from an arbitrary dense path and the same code is biased (measured on a test cubic:
SSE 289 instead of ~0, length 174.8 px instead of 168.9 px, i.e. **+3.5 %**). The port in §8
therefore fits twice — uniform and chord-length parameters — and keeps whichever is
geometrically better, which is exact for parameter-uniform input and stable for anything else.

The second subtlety: the objective really ought to be point-to-**curve** distance, not a
residual at a fixed parameter. Upstream's parameter-space SSE can be driven to zero by a
degenerate parameterisation (free reparameterisation converges to SSE 0 while the path
*loops*, reporting 183 px for a 169 px curve). The port scores geometric distance for exactly
this reason.

Poly-bezier growth is **greedy worst-segment splitting**: repeatedly split the segment with the largest
SSE at its max-residual interior sample, pinning shared endpoints (`constrain_start`/`constrain_end`) so
segments stay joined. `n_ctrl = 2` yields a poly-line, `n_ctrl = 4` a poly-bezier.

Slider **length** is computed exactly, by Gauss–Legendre quadrature of the hodograph
(`osu/bezier.py::length`):

```python
T, C = leggauss(int(5 * sqrt(degree)))       # degree 4 → 10 nodes
t = 0.5 * (T + 1)
length = 0.5 * Σ C · ‖B'(t)‖                 # B' = degree·(p[i+1] − p[i])
```

**Repeats:** `num_slides` comes from the sustain/slide ratio (§3.2). `end_pos` is
`lerp(slides % 2)` — i.e. the cursor ends at the head for an even repeat count, the tail for odd.
`lerp` for sliders applies a triangle wave `((f % 2)` folded at 1) — correct osu! reverse semantics.

---

## 4. Difficulty Tiers & Parameter Curves

### 4.1 There are no hard-coded difficulty tiers

Nothing in the repo maps `easy`/`normal`/`hard`/`insane` to numbers. Difficulty is a **continuous
5-vector** and every value is *learned*:

```
labels = [sr, ar, od, cs, hp]          # data/beatmap/encode.py::get_labels, via rosu_pp_py
```

- `sr` (star rating) is a **computed output** of `rosu_pp_py` at dataset-build time — so the model is
  trained to associate a style code with a *nonlinear derived property* of the map, not with a knob.
- `ar`/`od`/`cs`/`hp` are read straight from the source map's `[Difficulty]`.

Conditioning path (`models/style/model.py`):

```
labels/10  →  FourierFeatures(1 → 128, n_bins=32)          # cos(xWᵀ+b), W~N(0,32²), scale √(2/128)
           →  per-label einsum with a learned (5, 128, 256) tensor  + bias
           →  sum over the 5 labels  →  c  (B × 256)
           →  adaLN-zero (scale, shift, gate) in every one of 8 MLP blocks
labels < 0 → learned `null_labels` embedding                 # classifier-free guidance, drop p = 0.2
```

So the difficulty "curve" is a 128-dim random-Fourier embedding of each knob, summed — smooth and
interpolable, with no piecewise clamp anywhere.

### 4.2 What actually reaches the `.osu` file

`decode.py` writes `ar=labels[1], od=labels[2], cs=labels[3], hp=labels[4]` — from **`pred_labels`**
(the model's own prediction from `s`, clamped to `[0,10]`), **not** from the requested `--diff` vector.
`sr` is discarded entirely.

Two consequences worth knowing before benchmarking:
1. The emitted metadata can differ from the request; only the style code is actually conditioned on.
2. `clamp(0,10)` is applied uniformly, but legal ranges differ (`HP` realistically ≤ 6, `CS` ≤ 7),
   so `CS 9.8` / `HP 9.4` maps are producible.

### 4.3 Intensity / density behaviour

Also learned, not formulaic. The nearest thing to a hand-built intensity curve is in training:

- windows are 152 latent frames ≈ **24.6 s** (`models/diffusion/model.yml`), random-phase cropped
  (`BatchedSignalDataset.make_samples`), so the model never sees song-level structure;
- the latent `z` is randomly zeroed over a contiguous `z_mask_frac = 0.25` span, forcing
  time-invariant information up into `s` — which is *why* a single style code can control global
  density/AR-OD-consistency across the whole map;
- kiai/chorus/verse are not modelled at all — there is no section, phrase, or energy-section concept.
  Density follows audio salience because onsets correlate with salience, not because anything
  implements a section curve.

Versus our `rhythm/rhythm_density.py` (energy→density with `exponent 0.7` over
`[energy_floor 0.03, energy_ceiling 0.72]`, phrase adjustments, 2 smoothing passes): ours is explicit
and auditable; theirs is implicit and unreproducible without weights.

---

## 5. osu! Format Compliance & Packaging

### 5.1 `.osu` v14 template

`data/beatmap/decode.py::map_template` — emitted sections: `[General]`, `[Metadata]`, `[Difficulty]`,
`[Events]`, `[TimingPoints]`, `[HitObjects]`. Header line is `osu file format v14`.

| Section | Emitted | Missing / notable |
|---|---|---|
| `[General]` | `AudioFilename`, `AudioLeadIn: 0`, `Mode: 0` | no `PreviewTime`, `Countdown`, `SampleSet`, `StackLeniency`, `LetterboxInBreaks`, `EpilepsyWarning`, `WidescreenStoryboard` |
| `[Metadata]` | `Title`, `TitleUnicode`, `Artist`, `ArtistUnicode`, `Creator`, `Version`, `Tags` | no `Source`, `BeatmapID`, `BeatmapSetID`; `TitleUnicode = Title` verbatim |
| `[Difficulty]` | `HPDrainRate`, `CircleSize`, `OverallDifficulty`, `ApproachRate`, `SliderMultiplier: 1`, `SliderTickRate: 1` | no `SliderTickRate` variation |
| `[Events]` | breaks only, `2,start,end` when the inter-object gap > 5000 ms | **no background, no video, no storyboard** |
| `[Editor]` | **absent** | no `BeatDivisor`/`GridSize`/`TimelineZoom` (osu! defaults to 4/4) |
| `[Colours]` | **absent** | default combo colours |
| `[TimingPoints]` | 1 red + 1 green per slider | see §2.4 |
| `[HitObjects]` | circles `x,y,t,type,hitSound,0:0:0:0:`; sliders `x,y,t,type,hitSound,curveType\|pts,slides,length`; spinners `256,192,t,type,hitSound,endTime` | sliders/spinners omit `hitSample` (legal, but inconsistent with circles) |

Bit flags are correct: `type = 1<<0 circle | 1<<1 slider | 1<<3 spinner | 1<<2 new combo`;
`hitSound = (whistle?1<<1) + (finish?1<<2) + (clap?1<<3)` (`hit_objects.py::HitObject`).

### 5.2 Audio & video bindings

- `AudioFilename: {audio_file.name}` — basename only, no escaping. A title containing a newline or a
  `/` produces a corrupt `.osu`; a name that collides with the `.osu` filename overwrites it in the zip.
- **Video is not supported at all.** `[Events]` never emits `Video,0,"video.mp4"` or
  `0,0,"bg.jpg",0,0`; the template's `{{breaks}}` slot is only ever fed `2,...` lines.
- No `[General] SampleSet`/hitsound sample files are packaged → all hitsounds are the default skin.

### 5.3 Packaging

`scripts/predict.py` builds a real `.osz` (zip):

```python
mapset = Path(f"_{hex(random.randrange(16**7))[2:]} {artist} - {title}.osz")
with ZipFile(mapset, 'x') as z:
    z.write(audio_file, audio_file.name)                       # original file, original codec
    for i, (label, signal) in enumerate(zip(...)):
        z.writestr(f"{artist} - {title} (osu!dreamer) [version {i}].osu", decode_beatmap(...))
```

- One archive per invocation, containing **audio + N `.osu`** — no background, no video, no storyboard.
- Written with mode `'x'`; a pre-existing name raises `FileExistsError` (the existence loop is racy).
- The hex suffix is variable-length (`hex()` drops leading zeros), so names are `_0` … `_fffffff`.
- **No CLI escape hatch** for `Creator`, `Source`, `Tags`, `PreviewTime`, or an output directory.

Verdict: format-legal and importable, but a **minimal** mapset. Ours (`docs/OSU_FORMAT_INTEROPERABILITY.md`,
`osz` packaging) is materially more complete.

---

## 6. Architectural Flaws & Bottlenecks

### 6.1 Correctness / output defects

| # | Defect | Where | Severity | Effect |
|---|---|---|---|---|
| 1 | **600 BPM when there are no sliders** (`beat_len = 100/1`) | `decode.py` | **high** | every object mis-timed; circle-only maps are a normal outcome |
| 2 | **One green line per slider** | `decode.py` | **high** | hundreds/thousands of timing points; osu! editor lag; no real SV structure; SV values >10 silently clamped by the client |
| 3 | **Off-screen hit objects** — cursor heads are unbounded linear outputs, no clamp to `[0,512]×[0,384]` | `latent/model.py::decode`, `decode.py` | **high** | objects collapse onto the playfield edge after osu!'s own clamp; unreadable unless the map is edited |
| 4 | **Systematic −2-frame (~12 ms) duration bias** — `decode_extents` records the rising edge as `i` (the frame *before* entry) and the falling edge as the last inside frame, so `sustain_end − onset ≈ duration − 2` frames | `hit.py::decode_extents` | medium | slider durations short → derived `SV` biased high by `d/(d−12)` (a 250 ms slider gets +5 %), which also skews `beat_len` |
| 5 | **Overlapping objects** — a slider's `end_time` can exceed the next onset; nothing rejects it (the *training* parser rejects it in `osu/beatmap.py`, the *generator* does not) | `decode.py` | medium | unplayable overlaps, cursor teleports |
| 6 | **Zero-length slider → circle**, but the cursor signal was drawn along a real path for the full duration | `decode_slider` + `decode.py` | low | generated cursor and emitted map disagree at that time |
| 7 | **Rounding drift between fitted curve and declared length** — control points are `.round().astype(int)`, length is computed from the *unrounded* curve; for `P` osu! recomputes the circle from the 3 rounded points | `decode_slider`, `fit_arc` | low | sub-pixel to few-pixel length error → minor desync on long sliders |
| 8 | **`decode_extents` pairing loop mutates `end_idxs` while indexing it** (`end_idxs.pop(cursor)` inside `for cursor, start in enumerate(start_idxs)`) | `hit.py` | low | mis-paired sustain spans on malformed signals |
| 9 | **`tqdm` progress bar inside the decoder** writes `\r` to stdout per hit | `decode.py` | low | corrupts non-interactive/logged runs |
| 10 | **No metadata escaping / sanitisation**; title with `\n`, `:`, `/` breaks the file or the zip | `decode.py`, `predict.py` | low | corrupt output |

### 6.2 Representational limits

- **No channel for SV, volume, kiai, or effects.** `X_DIM = 9` covers hits + cursor and nothing else, so
  these cannot ever be *generated* — only reconstructed from geometry (§2.4).
- **No beat grid** → no quantisation, no triplets, no downbeat/meter awareness (§2.5).
- **No map-level structure**: 24.6 s training windows and a single global style code mean the model has
  no explicit notion of "verse → build → chorus"; kiai cannot be requested.
- **One timing point** means the model implicitly assumes constant tempo — fine for EDM, wrong for
  anything with a ritardando or a BPM change.
- **Stacks are unrepresentable** (`StackLeniency` unwritten, no stacking pass).

### 6.3 Performance / engineering debt

- **Dead code**: `data/beatmap/timing.py` (whole module), `common/attn.py::LInfSA`,
  `Beatmap.uninherited_timing_points()`, `Beatmap.beat_divisor`, `get_frame_for_time`,
  `librosa` in `pyproject.toml`. Roughly 150 LOC of abandoned directions.
- **`data/reclaim_memory.py` runs `os.system("uname -r | grep microsoft")` at import time** — a shell
  spawn on every import, on every platform; on non-WSL it is a no-op that still forks.
- **Decode is serial and unbatched** across diffs; curve fitting is a Python loop over sliders
  (`find_peaks` + per-candidate `lstsq`), which dominates export time on dense maps.
- **`os/beatmap.py` parsing is line-based regex** with `cfg[section]`/`cfg[section][m.group(1)]`
  dict indexing — `KeyError` instead of a parse error on malformed input.
- **`hold_out_mapsets` iterates `data_dir.iterdir()` and calls `.glob()`** — a stray file in `data/`
  raises `AttributeError`.
- **`encode_latents` assumes all diffs in a mapset share a shape** and `th.stack`s them; true only
  because chart length is derived from audio length.
- **Heavy dependency surface for a light output path**: `predict` needs torch + CUDA + `resonators` +
  `torchcodec` + `pytorch-lightning` (imported transitively via `LatentTrainer` in
  `scripts/encode_latents.py`, and via `artifact.py`'s `dataclass_from_dict` chain) to write a text file
  and zip it.
- **Windows scripts are stale**: `windows_scripts/Generate Beatmap.bat` invokes
  `python -m model predict --num_samples ...` — a module name (`model`) and a flag (`--num_samples`)
  that **no longer exist**. The README also still documents `osu_dreamer.model generate-data` while
  `__main__.py` exposes `generate-data` via `osu_dreamer`.
- **No tests.** Zero test files, zero CI test job (`.github/ISSUE_TEMPLATE` only).

---

## 7. "Golden Nuggets"

Four mechanisms here are genuinely better than what a rule-based generator does, and all four are
**model-agnostic** — they work on geometry and signals, not on weights.

### 7.1 MAP slider-type selection with prior-based branch & bound

*Why it wins:* it replaces the usual "try curves of increasing degree until error < threshold"
(hand-tuned, order-dependent, over-fits noise) with a decision-theoretic choice that is biased toward
the slider types real mappers actually emit, and it is provably equivalent to exhaustive search while
being 3–5× cheaper.

```python
NOISE_SCALE = 16.0      # px; larger => trust the prior more, fit looser
MAX_CTRL, MAX_SEG = 8, 16

def fit_slider(points, noise_scale=NOISE_SCALE):
    """points: 2×L, order follows the path; any monotone sampling works."""
    inv2v = 1 / (2 * noise_scale**2)
    found = []                                      # (cost, type, ctrl, length, sse)

    def consider(cost, ptype, ctrl, length, sse):
        found.append((cost, ptype, ctrl, length, sse))

    arc = fit_arc(points)                                            # §3.5(b)
    if arc is not None:
        sse, length, ctrl = arc
        consider(sse * inv2v - log_prior_arc(), "P", ctrl, length, sse)

    # sorted: prior penalty is NOT monotonic in degree (cubic spike is cheapest)
    for penalty, n_ctrl in sorted((-log_prior_single_bezier(n), n)
                                  for n in range(2, min(MAX_CTRL, L) + 1)):
        if found and penalty >= min(c[0] for c in found):
            break                                    # sse >= 0 => no later candidate can win
        curve, sse = fit_bezier(points, n_ctrl)      # best of {uniform, chord} params
        consider(sse * inv2v + penalty, "L" if n_ctrl == 2 else "B",
                 ctrl_of([curve]), curve.length, sse)

    for n_ctrl, all_lines in ((2, True), (4, False)):                # poly-line / poly-bezier
        if found and -log_prior_poly(2, all_lines) >= min(c[0] for c in found):
            continue
        for curves, sse in fit_poly_bezier(points, n_ctrl, MAX_SEG):
            m = len(curves)
            consider(sse * inv2v - log_prior_poly(m, all_lines), "B",
                     ctrl_of(curves), sum(c.length for c in curves), sse)
            if found and -log_prior_poly(m + 1, all_lines) >= min(c[0] for c in found):
                break                                # penalty grows with m

    # among visually identical candidates, prefer the one with fewest control points
    floor = min(c[4] / L for c in found)
    keep = [c for c in found if c[4] / L <= floor + EQUIVALENCE_MSQE]   # 0.25 px²
    return min(keep, key=lambda c: (len(c[2]), c[0]))
```

Priors (measured on the corpus; re-measure on ours before trusting the constants):

```python
TYPE_COUNTS = {"P": 938141, "L": 672639, "PL": 165541, "PB": 73003, "B": 55957}
ZETA_S      = 4                      # P(m segments) ∝ m^-4, m >= 2
B_CUBIC_WEIGHT, B_TAIL_DECAY = 0.5991, 0.7431
```

A numpy-only, drop-in port of this lives at `tools/map_generator/sliders/curve_fit.py`
(added alongside this doc, with `tests/test_curve_fit.py`, 23 cases). It deviates from upstream in
three deliberate, documented ways:

1. **Geometric objective** — `SSE` is the sum of squared point-to-curve distances, so `P`, `L`,
   `B` and poly candidates are actually comparable, and a looping control polygon cannot score
   well. (Upstream's parameter-space residual is gameable — see §3.5(c).)
2. **Dual parameterisation** — every curved candidate is fitted with both uniform and
   chord-length parameters and scored by geometric error, which makes the fitter exact for
   parameter-uniform input and stable for arbitrarily resampled paths.
3. **Equivalence preference** — candidates within 0.25 px² mean squared error of the best are
   treated as visually identical and the one with fewest control points wins. Without this, an
   exact single cubic loses to an equally exact 2-segment poly-bezier, purely because the corpus
   prior likes `PB/2` (P = 0.031) more than `B` with a cubic spike (P = 0.019) — correct by the
   prior, but 8 control points where 4 suffice.

### 7.2 Map-as-signal: the Gaussian-impulse / extent encoding

*Why it wins:* it converts the whole quality question into dense array algebra — no object-list walking,
no tolerance windows, no peak-matching heuristics. It is the natural substrate for benchmarking two
generators against the same audio, and it is the only representation in either codebase that is
simultaneously (a) frame-aligned with the audio, (b) differentiable, and (c) invertible.

```python
SIGMA = 10.0  # ms

def impulse_curve(times_ms, frame_times_ms, sigma=SIGMA):
    """1-D activation: max-combined Gaussian bumps, one per event."""
    if len(times_ms) == 0:
        return np.zeros_like(frame_times_ms)
    d = times_ms[:, None] - frame_times_ms[None, :]
    return np.exp(-0.5 * (d / sigma) ** 2).max(axis=0)

def extent_curve(regions, frame_times_ms):
    """box function: 1 on [start, end), 0 elsewhere."""
    out = np.zeros_like(frame_times_ms)
    for s, e in regions:
        out[(frame_times_ms >= s) & (frame_times_ms < e)] = 1.0
    return out
```

Inverse (used for decoding), and the **metric** that makes it useful to us — threshold-free onset
alignment between a generated map and a reference:

```python
def soft_dice(p, t):
    """2<p,t> / (<p,p> + <t,t>) in [0,1]; equals F1 for binary curves, no peak-picking needed."""
    return 2 * float((p * t).sum()) / max(float((p*p).sum() + (t*t).sum()), 1e-8)
```

This is exactly osu!dreamer's validation metric (`models/latent/train.py::on_validation_epoch_end`),
and it is a drop-in replacement for the tolerance-window onset matching in our validators.

The companion idea — **cursor quality must be measured on velocity, not position** — is worth stealing
outright: position R² saturates near 1 because the low-frequency trajectory dominates the variance.
osu!dreamer computes R² on the first difference *and* trains on `diff(n=0,1,2)` (position, velocity,
acceleration), weighted 2× each.

### 7.3 Self-calibrating fixed-step sphere tracing

*Why it wins:* it removes the two worst hyperparameters of diffusion sampling (step schedule, number of
steps ↔ quality trade-off) and **deliberately stops at the noise floor instead of converging to 0**,
which is what prevents over-sharpened, jittery outputs. 8 steps, no schedule, no CFG scale sweep.

```python
c0   = (1 - sigmoid(ndtri(0.99)))**2 * 2 * dim      # noise floor, from the training time distribution
u_scale = sqrt(2 * dim)                             # E[d²] between N(0,I) and RMS-normalised data

def sample(x, cond, steps, c0):
    u0  = predict_distance_and_direction(x, cond)[0].mean().item()
    eta = 1 - (sqrt(c0) / max(u0, sqrt(c0) + 1e-6)) ** (1 / steps)   # geometric contraction
    for _ in range(steps):
        u, v = predict_distance_and_direction(x, cond)
        x = x - eta * u * v                          # step a *fraction* of the predicted distance
    return x                                         # residual ≈ sqrt(c0), by construction
```

Geometry of the trick: each step removes `eta·u`, so the distance contracts geometrically as
`d ← d(1−eta)`; after `N` steps the residual is exactly `sqrt(c0)`. `eta` is solved in closed form from
the *measured* initial distance `u0`, so it adapts to the sample without a schedule. Training is
correspondingly simple — two losses, no noise-prediction MSE:

```
u_target = sqrt(‖x_t − x₁‖²_metric + c0)         # per-frame metric: sum over channels, mean over time
v_target = (x_t − x₁) / u_target
osl      = ‖(x_t − u·v) − x₁‖² / (‖x_t − x₁‖² + c0)         # one-step denoise, inverse-distance weighted
del      = ‖v − v_target‖²                                  # directional eikonal, weight 30
```

Applicability to us: **low for placement** (we have no learned field), **high as a case study** if we
ever add a learned scorer. The transferable lesson is the *metric normalisation*: `frame_dist_sq`
(sum over channels, **mean over time**) makes all distance statistics independent of sequence length,
and hence of song duration.

### 7.4 Geometric-mean SV calibration (timing from geometry)

*Why it wins:* it is a one-line solution to "I have arbitrary per-slider pixel-length/duration pairs and
I must emit a *single* red line plus conforming green lines". Picking the base velocity as the
**geometric mean** of observed velocities minimises `max_i |log(SV_i)|`, so it is the choice that keeps
the most sliders inside osu!'s `[0.1, 10]` SV clamp. Any `map()` that produces free-form
length↔duration pairs (wave/zigzag/loop shapes) needs exactly this.

```python
def synthesise_timing(sliders, slider_mult=1.0):
    """sliders: [(t_ms, length_px, slides, duration_ms)] -> (beat_len_ms, [(t, sv)])"""
    if not sliders:
        raise ValueError("no sliders: refusing to invent a BPM")
    vels = [length * slides / duration for _, length, slides, duration in sliders]
    base = math.sqrt(min(vels) * max(vels))          # geometric mean
    beat_len = slider_mult * 100.0 / base            # from duration = length/(SM*100) * beat_length
    greens = []
    for (t, *_), v in zip(sliders, vels):
        sv = v / base
        if not (0.1 <= sv <= 10.0):                  # do NOT emit out-of-range SV: osu! clamps it
            sv = min(10.0, max(0.1, sv))
        greens.append((t, sv))
    return beat_len, greens
```

Two hardening changes over the original, which we should keep: **fail loudly when there are no sliders**
(instead of the 600 BPM default) and **clamp rather than warn-and-emit** (so the exported duration
matches what the client will actually play).

### 7.5 Bonus: style-latent factorisation recipe

Not geometry, but the cleanest idea in the ML half, and its *label budget* is transferable to any
conditioning we add: `s` must be time-invariant for "difficulty" to mean anything. They enforce it three
ways — **swap** style codes between the two halves of a window (so reconstruction is only possible if
`s` is global), **mask** a contiguous 25 % of `z` (so time-invariant info must route through `s`), and
regularise the aggregate posterior with **MMD** (inverse-multiquadratic kernel, 7 bandwidth scales,
unbiased estimator) instead of a per-sample KL. The `−entropy(target)` trick on the BCE is a neat
micro-optimisation: subtracting the target's own entropy makes 0 the true optimum for soft targets, so
the loss is interpretable and gradients are proportional to *excess* error.

---

## 8. Extraction & Integration Guide

### 8.0 What to port, what to leave

| Component | Verdict | Why |
|---|---|---|
| MAP slider-type selector + priors | **port now** (§8.2) | numpy-only, immediately useful, self-contained |
| Bezier arc-length via Gauss–Legendre hodograph | **port now** (§8.3) | exact and cheaper than sampling; fixes our length estimates |
| `path → control points` fitter | **port now** (§8.2) | lets us compress generated wave/zigzag/loop paths and re-derive declared length |
| Geometric-mean SV calibration | **port now** (§8.4) | 15 LOC, closes our own length↔duration loop |
| Soft-Dice onset metric + cursor-velocity R² | **port now** (§8.5) | benchmark both generators in the same space |
| Gaussian-impulse / extent encoder | **port as an optional analysis util** | needs a frame grid; low cost, high diagnostic value |
| Sphere-tracing sampler / distance-field loss | **do not port** | requires a trained network; no weights shipped |
| Spectrogram (resonator bank) | **do not port** | `resonators` is a native dep; our existing analyser is sufficient |
| Timing-point synthesis (1 red + N greens) | **do not port** | ours is already correct (§2.4); only the geometric-mean *trick* is worth keeping |
| osu! file emission | **do not port** | ours is more complete (no video/bg/editor sections, no metadata control here) |

### 8.1 Where these plug into `PlacementStrategy`

`PlacementStrategy.generate()` in `tools/map_generator/placement/base.py` returns
`PositionGenerationResult(objects=[...])`. Placement is *positions only*; sliders are built later by
`sliders/slider_pipeline.py::_build_slider`, which currently:

1. picks an endpoint (`_choose_slider_endpoint`),
2. builds a dense path per shape (`slider_geometry.generate_shape_path`),
3. **estimates** `pixel_length` by sampling (`compute_slider_length`) and hard-clamps it to `[20, 400]`,
4. passes control points straight through.

That is exactly the seam. The ported fitter is a **post-processor on (2)+(3)**, not a new placement
strategy — which means it works for *every* existing and future strategy without touching them:

```
generate_shape_path(...) ──► dense path
                              │
                              ├─ exact arc length (Gauss–Legendre hodograph)  ← replaces sampling
                              ├─ MAP fit → minimal control points + path type  ← replaces _path_type_for_shape
                              └─ declared length == measured length            ← removes step 3's clamp drift
```

If you *do* want a strategy that emits sliders directly (rather than circle-first + conversion),
add it as a subclass and keep `transform_position` for catch/mania: the existing
`OsuCatchPlacementStrategy`/`OsuManiaPlacementStrategy` pattern still applies, because slider geometry
is resolved in standard coordinates before `transform_position` is applied.

#### Status: seam closed (Phase 25)

The steps above shipped as **`sliders/slider_geometry_fit.py::resolve_slider_geometry`** — a single
call that `_build_slider` now makes in place of steps (2)+(3):

1. **clamps** every anchor into the playfield minus ``DifficultyPreset.safe_margin`` (the previous
   clamping happened at *serialisation*, so the declared `pixel_length` described a path that was
   never exported);
2. **resolves family + exact length** through `curve_fit.fit_known_family` (hodograph quadrature);
3. **optionally collapses** a multi-anchor chain to one cubic when that stays within
   `SliderPipelineConfig.curve_fit_tolerance` px.

Guarantees, all covered by `tests/test_slider_integration.py`:

| property | how it is enforced |
|---|---|
| never raises | any failure returns the clamped legacy anchors + legacy sampled length with `method="fallback-sampled"`, `fallback=True` |
| anchors inside the field | proven for all six shape families at all three difficulty margins |
| declared length == emitted length | length is measured on the clamped float path, then clamped by `min/max_pixel_length` (config, not inline) |
| deterministic | same seed ⇒ identical anchors, through `process_sliders` and through the `.osu` export |

Also closed in the same pass:

* **SV ↔ timing** (§8.4): `osu_format/timing_converter.build_slider_velocity_points` emits one
  *inherited* (green) point per distinct slider velocity, resolved per slider against the
  uninherited beat length **active at that slider** — so SV tracks BPM regions as well as the
  audio-intensity-driven geometry (`energy`/`sustained_score` → `length_ms` → `pixel_length` →
  measured velocity). No global fallback constant is assumed.
* **Cached-node cost, measured**: node/binomial caches are keyed by degree (bounded, see the cache
  audit test). `leggauss` and friends are *not* cached per curve.

Throughput on this machine (best of three, Windows/Python 3.10):

| path | mean |
|---|---|
| `resolve_slider_geometry` as `_build_slider` calls it | **29–37 µs** |
| … with `curve_fit_simplify=True` (opt-in) | ~110 µs |
| whole `_build_slider` (geometry + quality scoring) | ~280 µs |

The 50 µs budget is met by the geometric work this pass added. The remainder is the pre-existing
quality scorer, which samples each path three times (smoothness + both flow directions). Two
sampling hot spots were fixed on the way:

1. **Per-sample De Casteljau list rebuilds** → flat `xs`/`ys` evaluation
   (`_de_casteljau_coords`). Verified bit-for-bit identical over 20 000 random degrees/t values, so
   it cannot move a score.
2. **Closure-allocating O(n²) self-intersection scan** → inlined orientation test with a bounding-box
   rejection. This one *does* change results, in exactly one place: 3 of 4000 random shape/endpoint
   combinations, all straight (`linear`) paths, went from smoothness 70 → 100. The 70 was a false
   positive: float cancellation on collinear sample points flipped an orientation sign, so a straight
   slider was reported as crossing itself. Bounding boxes make that impossible. Covered by
   `test_straight_path_is_never_scored_as_self_intersecting`.

Together: ~760 µs → ~280 µs per `_build_slider`.

### 8.2 Step 1 — drop in the curve fitter

New file: `tools/map_generator/sliders/curve_fit.py` (shipped with this analysis; numpy + `math` only —
`scipy.special.comb` replaced by `math.comb`, `scipy.special.zeta` replaced by a closed-form truncation).

Public surface:

```python
fit_slider_path(points, noise_scale=16.0, equivalence_msqe=0.25) -> FittedSlider
    # points: (2, L) or (L, 2); order follows the path, sampling method does not matter
    # FittedSlider: path_type "P" | "L" | "B", control_points [(x, y), ...] (unrounded),
    #               length (px), sse (geometric, px²), cost (MAP)
    #   .rounded_control_points() -> [(int, int), ...]   # for emission

fit_bezier_curve(points, n_ctrl) -> (BezierFit, sse)   # best of {uniform, chord} parameters
fit_poly_bezier(points, n_ctrl, max_segments)           # yields (segments, sse), monotone
fit_arc(points) -> (sse, length, [start, mid, end]) | None
geometric_sse(curves, points) -> float                  # point-to-curve, subsampled >96 pts
max_geometric_error(curves, points) -> float            # worst-case px, for QA
resample_by_arclength(points, n) -> (2, n)
sample_path(fitted, n) -> (2, n)                        # round-trip validation
bezier_length(ctrl) -> float                            # Gauss–Legendre on the hodograph
```

Three integration rules, only one of which is about geometry:

1. **Any monotone sampling works** — the fitter tries both uniform and chord-length parameters and
   picks by geometric error. You do *not* need arc-length-uniform input (though
   `resample_by_arclength` is still the sane default when converting from a time-parameterised
   sample stream).
2. **Fit before rounding.** Round control points to int only at emission; `length` is measured on
   the float curve. osu! renders from the *rounded* points, so a long slider's declared length can
   drift from its rendered length (osu!dreamer does not re-measure, §6.1 #7). Re-measure after
   rounding if you care about sub-pixel duration fidelity.
3. **Perfect (`P`) sliders need exactly 3 control points** — `[start, mid, end]`, never 4, or osu!
   will not treat it as an arc. `fit_slider_path` guarantees this.

Wire-in (minimal diff to `_build_slider`):

```python
from .curve_fit import fit_slider_path

path = resample_by_arclength(sampled_points)          # (2, L)
fitted = fit_slider_path(path)
path_type   = PATH_TYPE_TO_OSU[fitted.path_type]      # {"P": "perfect", "L": "linear", "B": "bezier"}
pixel_length = int(round(fitted.length))              # exact, no [20, 400] clamp needed
control_points = [HitObjectPoint(x=x, y=y) for x, y in fitted.control_points]
```

### 8.3 Step 2 — replace sampled length with exact length

`compute_slider_length` currently integrates by dense sampling. The hodograph + Gauss–Legendre version is
exact for the polynomial family and cheaper than a polyline at comparable accuracy. Measured on a cubic
against a 200k-sample reference (error = |L − L_ref|, per call, cached nodes):

| method | error | cost |
|---|---|---|
| quadrature, 10 nodes | 3.6e-3 px | 24 µs |
| polyline, 100 segments | 8.9e-3 px | 48 µs |
| polyline, 200 segments | 2.2e-3 px | 62 µs |

So ~2× cheaper than the polyline that is *less* accurate, and ~2.5× cheaper than the one that is
comparable. **Do cache the Legendre nodes** (`leggauss` is an eigensolve: 321 µs → 24 µs here) —
upstream gets that for free from `@cached_property` per curve instance, which is not enough for a
fitter that constructs hundreds of `BezierCurve`s per slider.

```python
def bezier_length(p: np.ndarray) -> float:
    deg = p.shape[1]
    n = max(2, int(5 * math.sqrt(deg)))              # matches upstream's node-count heuristic
    T, C = np.polynomial.legendre.leggauss(n)
    t = 0.5 * (T + 1)                                # map [-1, 1] -> [0, 1]
    hodo = (deg - 1) * (p[:, 1:] - p[:, :-1])        # derivative control points
    vel = hodo @ _bernstein(t, deg - 1).T            # (2, n)
    return 0.5 * float((C * np.linalg.norm(vel, axis=0)).sum())
```

Keep the existing `[20, 400]` clamp as a *policy* guard, but assert that it is not binding — a clamp
that fires means the geometry or the duration is wrong.

### 8.4 Step 3 — geometric-mean SV calibration in the exporter

Shipped as `tools/map_generator/sliders/sv_calibration.py` (`synthesise_timing`, `dedupe_sv_lines`).
In our `osu_format/` timing writer, replace any per-slider `SV = 1.0` assumption with §7.4. Order of
operations matters:

1. build all sliders (real `pixel_length`, real `end_time`),
2. `beat_len, greens = synthesise_timing(...)`, with the no-sliders case **raising** or falling back to
   our *detected* BPM (we have one — use it; osu!dreamer does not),
3. emit red lines from our existing multi-BPM timing analysis, and use the geometric-mean `beat_len`
   only as the *scale* that keeps `SV ∈ [0.1, 10]`,
4. emit at most one green line per distinct `(timestamp, SV)` pair — dedupe, do not emit one per slider.

### 8.5 Step 4 — adopt the signal-space benchmark

Add to `tools/map_generator/validation/` (or reuse `difficulty/metrics.py`):

```python
FRAME_MS = 5.9814453125                     # 98/16384*1000 — match the grid if you compare with them

def onset_curve(objects, frame_ms=FRAME_MS, sigma=10.0, duration_ms=None): ...
def soft_dice(p, t): ...
def velocity_r2(pred_xy, true_xy):          # R² on first differences, per axis, then combined
    ...
```

Then a single comparison harness can score: our map vs. their map vs. the raw audio salience, on the same
axis, with no tolerance parameters. This is the piece that makes the two generators directly
comparable — which is the stated goal of this analysis.

### 8.6 Verification — measured results (not estimates)

`tools/map_generator/tests/test_curve_fit.py` — **23 tests, all passing**:

```
python -m unittest tools.map_generator.tests.test_curve_fit    → Ran 23 tests ... OK
python -m unittest tools.map_generator.tests.test_sliders \
                   ...test_placement_strategy ...test_osu_format → Ran 41 tests ... OK
```

Behaviour on representative paths (round-trip = max/mean distance from the input path to the
re-sampled fitted path, in px):

| input | type | ctrl pts | length (px) | round-trip max/mean | note |
|---|---|---|---|---|---|
| cubic, parameter-uniform (80 pt) | `B` | 4 | 168.905 (exact) | 0.02 / 0.01 | reproduces the cubic |
| cubic, arc-length-resampled (80 pt) | `B` | 8 | 171.30 (true 168.90, +1.4 %) | 1.39 / 0.59 | no cubic can match this parameterisation |
| quarter arc, R=100 | `P` | 3 | 157.080 (exact) | 0.02 / 0.01 | `sse ≈ 3e-24` |
| 3-corner staircase (90 pt) | `B` (poly) | 6 | 297.53 (true 300) | 1.09 / 0.32 | multi-segment |
| sine wave (200 pt) | `B` | 6 | 358.82 | 2.16 / 0.34 | |
| 2-point segment | `L` | 2 | 141.421 (exact) | 0.00 / 0.00 | |

Cost: **~16–18 ms per fit** for 90–200-point paths (single arc: 0.7 ms), i.e. roughly 7 s for a
400-slider map if every slider needs the full search. Poly candidates are the expensive branch;
the prior-based early exit usually stops at 2–4 segments.

Acceptance criteria the tests enforce:

- arc → `"P"`, 3 control points, `|length − R·Δθ| < 0.5`, `sse < 1e-6`
- radius > 320 px → **not** `"P"` (osu!'s own limit)
- parameter-uniform cubic → `"B"` with exactly 4 control points, length within 0.01 px, round-trip < 0.1 px
- arc-length cubic → round-trip max < 3 px, mean < 1 px, length within 5 %
- collinear input → `"L"`, 2 control points, exact length
- poly-bezier error strictly non-increasing in segment count (guaranteed by the yield contract),
  ending > 10× better than the 2-segment fit
- translation / ×1.7 scale / x-mirror / y-mirror all preserve `path_type`
- `< 2` points raises `ValueError`
- `synthesise_timing`: one slider → `beat_len` equals its duration and `SV = 1`; three sliders →
  emitted `(beat_len, SV)` reproduces each original duration to 1e-6; empty list raises.

Remaining regression work before enabling by default: run our existing `slider_pipeline` quality
scores with the fitter used *only* for length (path type forced to the candidate's
`preferred_path_type`) and confirm the score distribution does not shift.

### 8.7 Migration risks

| Risk | Mitigation |
|---|---|
| Prior constants were measured on *human ranked maps*, not our generator's output — they may be miscalibrated for short/clamped paths | re-measure `TYPE_COUNTS` on our last 200 exports before trusting; keep them in one dict |
| `[20, 400]` pixel-length clamp in `_build_slider` can make declared length < fitted length | treat a binding clamp as a warning and log it; fix the underlying duration instead |
| Path type names differ (`perfect` vs our `SliderPathType` literal) | map explicitly; do not pass `"P"` into our `GeneratedSliderHitObject.path_type` |
| osu!'s `P` (perfect) requires exactly 3 control points and re-derives the circle | always emit `[start, mid, end]`, never 4; re-measure length after rounding for long sliders |
| Numpy-only port drops `scipy` — `find_peaks` is *not* ported | we already have peak picking in `rhythm/`; do not duplicate it here |

---

## Appendix A — Constant verification

Recomputed from source (no repo deps), to confirm the numbers used above:

```
SR            = 2 * 32 << 8        = 16384 Hz
HOP_LEN       = (16384*6+500)//1000 = 98 samples
frame period  = 98/16384*1000      = 5.9814453125 ms      → 167.184 fps
F_MAX         = 32 << 8            = 8192 Hz
N_BINS/A_DIM  = 8 * 9              = 72
chunk         = 3^3 = 27 frames    = 161.499 ms           → latent rate 6.19 Hz
sigmoid(ndtri(0.99))               = 0.9110358
c0 (E=6)      = (1-0.9110358)^2*2*6 = 0.094980            → sqrt(c0) = 0.30819
c0 (S=32)     = ... * 2*32          = 0.506536            → sqrt(c0) = 0.71171
preempt(AR)   = 1200 + (120|150)*(5-AR)  → AR4: 1320 ms, AR9.3: 555 ms, AR10: 450 ms
beat_len      = 100 / base_slider_vel; no sliders → 100 ms → 600 BPM   (defect #1)
sustain bias  ≈ 2 frames = 11.96 ms per slider                          (defect #4)
```

## Appendix B — Module → concern map

```
scripts/predict.py        inference entry, .osz packaging
models/inference/         LDM assembly + artifact (EMA-only state dict)
models/diffusion/         distance-field trainer + backbone + sampler
models/style/             optional-difficulty conditioning diffusion
models/latent/            chart autoencoder (UNet + attn-pool style head)
data/load_audio.py        72-band resonator spectrogram, frame grid
data/beatmap/encode.py    9-channel signal encoding + uint8/uint16 disk format
data/beatmap/decode.py    signal → hit objects → .osu v14 template → timing synthesis
data/beatmap/hit.py       Gaussian impulse / box extent encoding + inverse
data/beatmap/cursor.py    piecewise-linear cursor replay (preempt, lerp, triangle wave)
data/beatmap/slider/      MAP curve-family selection, arc + bezier fits, empirical priors
osu/                      .osu parser, exact bezier/line/perfect slider math, rosu integration
common/                   RoPE attention, SwiGLU, RMSNorm, MMD, Fourier features
```

## Appendix C — Comparison at a glance

| Axis | osu!dreamer | ours (`tools/map_generator`) |
|---|---|---|
| Paradigm | latent diffusion, learned distance field | heuristic + DSP, explicit rules |
| Lines of code | 4 k | ~56 k |
| Reproducibility | needs weights or a 5-stage training run | deterministic from `--seed` |
| Onset source | learned spectrogram→activation correlation | spectral-flux/energy onset pipeline (`rhythm/`) |
| Beat grid / quantisation | none; 5.98 ms lattice | multi-layer rhythm analysis + timing quality |
| BPM / offset | derived from slider geometry, one red line | detected, multi-BPM (`02afa59`) |
| Object selection | signal thresholds | `event_selector` + `slider_decision` + `spinner` rules |
| Flow / spacing control | none | jump curves, flow angles, DS scaling (`b83e314`) |
| Slider geometry | **MAP curve fitting (best in class)** | deterministic shape families + sampled length |
| Timing points | 1 red + 1 green/slider | full red/green synthesis |
| Difficulty scaling | learned 5-vector conditioning | `DifficultyPreset` matrix + curves |
| Video / background / storyboard | none | via `EditorExporter` / `[Events]` |
| Benchmarking surface | dense frame-aligned signals | object lists + validators |
| Tests | none | 47 test files |

**Bottom line:** the generative core is not portable and not worth porting. The *geometry* third is the
crown jewel — a MAP curve fitter with empirical priors, exact arc-length integration, and a one-line SV
calibration that solves a problem we have. Take those three, take the signal-space benchmark, and leave
the rest.
