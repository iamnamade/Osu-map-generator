"""``.osb`` storyboard scripting: pulsing background and animated lyrics.

Two effects, both driven by data the pipeline already has:

* **Kiai pulse** -- every high-energy window scales the background in short
  bounces, so drops breathe with the music instead of sitting statically.
* **Lyric animation** -- each rendered lyric sprite fades in just before its
  line starts, drifts upward while it is sung, and fades out after it ends.

Coordinates are authored in osu!'s 640x480 storyboard space (the 4:3 space the
client has always used; 854x480 maps are letterboxed into it), and lyric sprites
are placed slightly below centre (``320,380``) so they do not cover the
playfield's aim area.

Command syntax reference: ``Sprite,<layer>,<origin>,"<path>",<x>,<y>`` then
``F,<layer>,<start>,<end>,<from>,<to>`` for fades, ``M,0,...`` for movement and
``S,<layer>,<start>,<end>,<from>,<to>`` for scaling.  Time values are
milliseconds.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Sequence

from ..utils import MapGeneratorError

#: Storyboard coordinate space.
SB_WIDTH = 640
SB_HEIGHT = 480

#: Lyric anchor: horizontally centred, below the aim area.
LYRIC_X = 320
LYRIC_Y = 380

#: How far a lyric drifts upward while it is displayed.
LYRIC_FLOAT_DISTANCE = 10

#: Fade duration applied before/after each lyric.
FADE_MS = 200

#: Background bounce cadence inside a kiai window.
PULSE_INTERVAL_MS = 250
PULSE_RISE_MS = 100

#: Scale at the peak of each bounce, returning to 1.0.
PULSE_SCALE = 1.05


class StoryboardGenerator:
    """Writes an ``.osb`` file from lyrics and kiai windows."""

    def __init__(
        self,
        *,
        width: int = SB_WIDTH,
        height: int = SB_HEIGHT,
        pulse_interval_ms: int = PULSE_INTERVAL_MS,
        pulse_scale: float = PULSE_SCALE,
    ) -> None:
        self.width = int(width)
        self.height = int(height)
        self.pulse_interval_ms = max(60, int(pulse_interval_ms))
        self.pulse_scale = float(pulse_scale)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def write_osb(
        self,
        lyrics_data: list[dict[str, Any]],
        bg_path: str,
        kiai_times: list[tuple],
        output_osb_path: str,
    ) -> str:
        """Write the storyboard and return its path.

        Args:
            lyrics_data: Segments with ``start_ms``/``end_ms`` and
                ``sprite_path`` (relative to the storyboard root).
            bg_path: Background image reference, relative (``"bg.jpg"``) or a
                filesystem path whose basename is used.
            kiai_times: ``(start_ms, end_ms)`` windows that get the pulse.
            output_osb_path: Destination ``.osb`` file.
        """
        destination = Path(output_osb_path)
        destination.parent.mkdir(parents=True, exist_ok=True)

        lines: list[str] = ["[Events]", "//Background and Video events"]
        background_name = _background_reference(bg_path)
        if background_name:
            lines.append(f'Sprite,Background,Centre,"{background_name}",0,0')

        lines.append("//Background pulsing (kiai / drops)")
        lines.extend(self._pulse_commands(kiai_times))

        lines.append("//Lyrics")
        lines.extend(self._lyric_commands(lyrics_data))

        try:
            destination.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError as error:
            raise MapGeneratorError(f"Could not write storyboard to {destination}: {error}") from error
        return destination.as_posix()

    # ------------------------------------------------------------------
    # Background pulse
    # ------------------------------------------------------------------
    def _pulse_commands(self, kiai_times: Iterable[tuple]) -> list[str]:
        """Scale bounces across each kiai window.

        Background sprites take storyboard commands on layer ``0`` (the
        Background layer); the layer field identifies which sprite the command
        applies to, not the effect strength.
        """
        commands: list[str] = []
        for window in kiai_times or []:
            start, end = _normalise_window(window)
            if start is None or end is None or end <= start:
                continue
            moment = start
            while moment + PULSE_RISE_MS <= end:
                commands.append(
                    f"S,0,{moment},{moment + PULSE_RISE_MS},{self.pulse_scale:.2f},1.00"
                )
                moment += self.pulse_interval_ms
        return commands

    # ------------------------------------------------------------------
    # Lyrics
    # ------------------------------------------------------------------
    def _lyric_commands(self, lyrics_data: list[dict[str, Any]]) -> list[str]:
        commands: list[str] = []
        for index, lyric in enumerate(lyrics_data or []):
            sprite = lyric.get("sprite_path")
            if not isinstance(sprite, str) or not sprite:
                continue
            try:
                start_ms = int(round(float(lyric["start_ms"])))
                end_ms = int(round(float(lyric["end_ms"])))
            except (KeyError, TypeError, ValueError):
                continue
            if end_ms <= start_ms:
                continue

            fade_in_start = max(0, start_ms - FADE_MS)
            fade_out_end = end_ms + FADE_MS
            layer = 0 if index == 0 else index  # each lyric gets its own command layer

            commands.append(
                f'Sprite,Foreground,Centre,"{sprite}",{LYRIC_X},{LYRIC_Y}'
            )
            commands.append(f"F,{layer},{fade_in_start},{start_ms},0,1")
            commands.append(f"F,{layer},{end_ms},{fade_out_end},1,0")
            commands.append(
                f"M,{layer},{start_ms},{end_ms},"
                f"{LYRIC_X},{LYRIC_Y},{LYRIC_X},{LYRIC_Y - LYRIC_FLOAT_DISTANCE}"
            )
        return commands


def _background_reference(bg_path: str) -> str:
    """Use the file's basename for the storyboard reference."""
    if not bg_path:
        return ""
    return Path(str(bg_path).replace("\\", "/")).name


def _normalise_window(window: Any) -> tuple[int | None, int | None]:
    """Coerce a kiai window into integer milliseconds."""
    try:
        start, end = window
        return int(round(float(start))), int(round(float(end)))
    except (TypeError, ValueError):
        return None, None
