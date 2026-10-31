"""Whisper-driven lyric extraction and PNG sprite rendering.

Storyboard lyrics need two things the generator does not have: timed text, and
that text as an image.  This module produces both.

* :meth:`LyricGenerator.extract_lyrics` transcribes the track with OpenAI's
  Whisper and returns ``[{"text", "start_ms", "end_ms"}]`` segments.
* :meth:`LyricGenerator.render_lyric_sprites` draws each segment with Pillow into
  a transparent PNG sized for a 640x480 storyboard, with a dark outline and a
  soft drop shadow so white text stays readable over any background.

Whisper is an optional, heavy dependency (torch plus model weights) and is
imported only inside the transcription call, so importing the generator stays
cheap and text-only rendering still works without it.  When Whisper is missing,
``extract_lyrics`` raises ``MapGeneratorError`` with an install hint; callers
such as the packager catch that and continue with a background-only storyboard.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..utils import MapGeneratorError

#: Storyboard coordinate space the sprites are authored for.
SB_WIDTH = 640
SB_HEIGHT = 480

#: Horizontal padding inside each sprite canvas.
SPRITE_PADDING = 12

#: Font sizes tried, largest first, when fitting a lyric to the canvas.
MAX_FONT_SIZE = 52
MIN_FONT_SIZE = 20

#: Widest a rendered line may be, in pixels.
MAX_TEXT_WIDTH = int(SB_WIDTH * 0.8)

#: Segments shorter than this are breath/noise, not lyrics worth showing.
MIN_SEGMENT_MS = 250

#: Font files tried in order; the first that loads wins.
_FONT_CANDIDATES: tuple[str, ...] = (
    "arial.ttf",
    "Arial.ttf",
    "DejaVuSans-Bold.ttf",
    "DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/arial.ttf",
)


def whisper_available() -> bool:
    """Whether OpenAI Whisper can be imported."""
    try:
        import importlib.util

        return importlib.util.find_spec("whisper") is not None
    except (ImportError, ValueError):  # pragma: no cover - broken install
        return False


class LyricGenerator:
    """Transcribe a track and render its lines as storyboard sprites.

    Parameters
    ----------
    audio_path:
        Source track handed to Whisper.
    output_dir:
        Storyboard work directory; sprites land in ``<output_dir>/sb/lyrics/``.
    model_size:
        Whisper model name (``tiny``/``base``/``small``/...).  ``base`` keeps
        the first run small while still handling clear vocals.
    """

    def __init__(
        self,
        audio_path: str | Path,
        output_dir: str | Path,
        *,
        model_size: str = "base",
        language: str | None = None,
    ) -> None:
        self.audio_path = Path(audio_path)
        self.output_dir = Path(output_dir)
        self.model_size = model_size
        self.language = language

        self.sb_dir = self.output_dir / "sb"
        self.sprites_dir = self.sb_dir / "lyrics"
        self.sprites_dir.mkdir(parents=True, exist_ok=True)
        self._lyrics: list[dict[str, Any]] | None = None

    # ------------------------------------------------------------------
    # Transcription
    # ------------------------------------------------------------------
    def extract_lyrics(self) -> list[dict[str, Any]]:
        """Transcribe the track into timed segments.

        Returns ``[{"text": str, "start_ms": int, "end_ms": int}]`` in play
        order.  Word timestamps are requested so future karaoke-style effects
        have them available, but segments are what the storyboard consumes.
        """
        if self._lyrics is not None:
            return [dict(item) for item in self._lyrics]

        if not self.audio_path.is_file():
            raise MapGeneratorError(f"Audio file for lyric extraction does not exist: {self.audio_path}")

        try:
            import whisper  # type: ignore[import-not-found]
        except ImportError as error:
            raise MapGeneratorError(
                "Lyric extraction needs OpenAI Whisper (`pip install openai-whisper`). "
                "Packaging continues without lyrics when it is unavailable."
            ) from error

        model = whisper.load_model(self.model_size)
        transcription = model.transcribe(
            self.audio_path.as_posix(),
            language=self.language,
            word_timestamps=True,
            verbose=False,
        )

        lyrics: list[dict[str, Any]] = []
        for segment in transcription.get("segments") or []:
            text = str(segment.get("text", "")).strip()
            if not text:
                continue
            start_ms = int(round(float(segment.get("start", 0.0)) * 1_000.0))
            end_ms = int(round(float(segment.get("end", 0.0)) * 1_000.0))
            if end_ms - start_ms < MIN_SEGMENT_MS:
                continue
            lyrics.append({"text": text, "start_ms": start_ms, "end_ms": end_ms})

        lyrics.sort(key=lambda item: (item["start_ms"], item["end_ms"]))
        self._lyrics = lyrics
        return [dict(item) for item in lyrics]

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def render_lyric_sprites(
        self,
        lyrics_data: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Draw every lyric into ``sb/lyrics/lyric_<n>.png``.

        Returns copies of the input dictionaries with ``sprite_path`` (relative
        to the storyboard root), ``sprite_width`` and ``sprite_height`` added.
        """
        try:
            from PIL import Image, ImageDraw, ImageFont  # noqa: F401 - availability probe
        except ImportError as error:  # pragma: no cover - Pillow is a hard requirement here
            raise MapGeneratorError(
                "Rendering lyric sprites needs Pillow (`pip install pillow`)."
            ) from error

        rendered: list[dict[str, Any]] = []
        for index, lyric in enumerate(lyrics_data):
            text = str(lyric.get("text", "")).strip()
            if not text:
                continue
            image, width, height = self._render_text_image(text)
            filename = f"lyric_{index}.png"
            image.save(self.sprites_dir / filename)

            entry = dict(lyric)
            entry["sprite_path"] = f"sb/lyrics/{filename}"
            entry["sprite_width"] = width
            entry["sprite_height"] = height
            rendered.append(entry)
        return rendered

    def _render_text_image(self, text: str) -> tuple[Any, int, int]:
        """Render one line (wrapped if needed) onto a transparent canvas."""
        from PIL import Image, ImageDraw, ImageFont

        font, lines = self._fit_text(text, ImageFont)
        measure = ImageDraw.Draw(Image.new("RGBA", (1, 1), (0, 0, 0, 0)))
        bbox = measure.multiline_textbbox((0, 0), lines, font=font, spacing=6, align="center")
        text_width = int(bbox[2] - bbox[0])
        text_height = int(bbox[3] - bbox[1])

        width = text_width + SPRITE_PADDING * 2
        height = text_height + SPRITE_PADDING * 2
        image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)

        # Soft drop shadow first, then outlined white text on top: readable over
        # bright gameplay backgrounds without needing an opaque plate.
        draw.multiline_text(
            (SPRITE_PADDING + 3, SPRITE_PADDING + 3),
            lines,
            font=font,
            fill=(0, 0, 0, 170),
            spacing=6,
            align="center",
        )
        draw.multiline_text(
            (SPRITE_PADDING, SPRITE_PADDING),
            lines,
            font=font,
            fill=(255, 255, 255, 255),
            spacing=6,
            align="center",
            stroke_width=3,
            stroke_fill=(0, 0, 0, 220),
        )
        return image, width, height

    def _fit_text(self, text: str, image_font_module: Any) -> tuple[Any, str]:
        """Shrink the font, then wrap words, until the lyric fits the canvas."""
        from PIL import Image, ImageDraw

        measure = ImageDraw.Draw(Image.new("RGBA", (1, 1), (0, 0, 0, 0)))
        size = MAX_FONT_SIZE
        while size > MIN_FONT_SIZE:
            font = _load_font(size)
            if measure.textlength(text, font=font) <= MAX_TEXT_WIDTH:
                return font, text
            size -= 4

        font = _load_font(MIN_FONT_SIZE)
        words = text.split()
        lines: list[str] = []
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if current and measure.textlength(candidate, font=font) > MAX_TEXT_WIDTH:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
        return font, "\n".join(lines) if lines else text


def _load_font(size: int) -> Any:
    """Load the first usable TrueType font, falling back to Pillow's default."""
    from PIL import ImageFont

    for candidate in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()
