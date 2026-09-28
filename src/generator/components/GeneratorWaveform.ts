import { renderWaveformPeaks } from "../../editor/timeline/WaveformRenderer";

/**
 * P1.2: reusable generator waveform.
 *
 * The old step-4 "waveform" was 18 hardcoded bars; this decodes the uploaded
 * audio into real peaks and draws them through the editor's
 * ``renderWaveformPeaks`` so both surfaces share one rendering path.
 */
export const GENERATOR_WAVEFORM_SAMPLE_COUNT = 900;

export function renderGeneratorWaveform(hasAudio: boolean): string {
  const caption = hasAudio
    ? "Live waveform decoded from the uploaded track."
    : "Upload audio to render the song waveform.";

  return `
    <div class="generation-waveform">
      <div class="generation-waveform-grid"></div>
      <canvas
        class="generation-waveform-canvas"
        data-role="generator-waveform"
        aria-label="Song waveform preview"
        role="img"
      ></canvas>
      <span class="generation-waveform-caption">${caption}</span>
    </div>
  `;
}

export function drawGeneratorWaveform(
  canvas: HTMLCanvasElement,
  peaks: readonly number[] | undefined,
): void {
  const context = canvas.getContext("2d");
  if (!context) {
    return;
  }

  const ratio = typeof window !== "undefined" ? window.devicePixelRatio || 1 : 1;
  const width = Math.max(1, Math.floor(canvas.clientWidth || 320));
  const height = Math.max(1, Math.floor(canvas.clientHeight || 148));
  canvas.width = Math.floor(width * ratio);
  canvas.height = Math.floor(height * ratio);

  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  context.clearRect(0, 0, width, height);

  if (!peaks || peaks.length < 2) {
    drawGeneratorWaveformPlaceholder(context, width, height);
    return;
  }

  renderWaveformPeaks(context, peaks, {
    x: 6,
    y: 10,
    width: width - 12,
    height: height - 20,
    visibleStartMs: 0,
    visibleEndMs: 1,
  });
}

export async function computeWaveformPeaks(
  source: File | string,
  sampleCount = GENERATOR_WAVEFORM_SAMPLE_COUNT,
): Promise<number[] | undefined> {
  const AudioContextConstructor = resolveAudioContextConstructor();
  if (!AudioContextConstructor) {
    return undefined;
  }

  try {
    const arrayBuffer =
      typeof source === "string"
        ? await (await fetch(source)).arrayBuffer()
        : await source.arrayBuffer();
    const audioContext = new AudioContextConstructor();
    try {
      const decoded = await audioContext.decodeAudioData(arrayBuffer.slice(0));
      return extractPeaksFromChannel(decoded.getChannelData(0), sampleCount);
    } finally {
      void audioContext.close?.();
    }
  } catch {
    return undefined;
  }
}

export function extractPeaksFromChannel(
  channel: Float32Array,
  sampleCount: number,
): number[] {
  const blockSize = Math.max(1, Math.floor(channel.length / Math.max(1, sampleCount)));
  const peaks: number[] = [];

  for (let offset = 0; offset < channel.length; offset += blockSize) {
    let peak = 0;
    const end = Math.min(channel.length, offset + blockSize);
    for (let index = offset; index < end; index += 1) {
      peak = Math.max(peak, Math.abs(channel[index]));
    }
    peaks.push(peak);
  }

  return peaks;
}

function drawGeneratorWaveformPlaceholder(
  context: CanvasRenderingContext2D,
  width: number,
  height: number,
): void {
  context.strokeStyle = "rgba(55, 242, 160, 0.35)";
  context.lineWidth = 1.5;
  context.beginPath();
  context.moveTo(6, height / 2);
  context.lineTo(width - 6, height / 2);
  context.stroke();
}

function resolveAudioContextConstructor(): typeof AudioContext | undefined {
  if (typeof globalThis === "undefined") {
    return undefined;
  }

  const candidate = globalThis as {
    AudioContext?: typeof AudioContext;
    webkitAudioContext?: typeof AudioContext;
  };
  return candidate.AudioContext ?? candidate.webkitAudioContext;
}
