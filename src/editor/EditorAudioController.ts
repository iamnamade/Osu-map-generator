import type { EditorWaveformPeaks } from "./models/EditorModels";

interface EditorAudioCallbacks {
  onTimeUpdate: (timeMs: number) => void;
  onReady: (durationMs: number) => void;
  onEnded: () => void;
  onError: (message: string) => void;
}

export class EditorAudioController {
  private audio: HTMLAudioElement | null = null;
  private rafId: number | null = null;
  private readonly audioContext =
    typeof AudioContext !== "undefined" ? new AudioContext() : undefined;

  constructor(private readonly callbacks: EditorAudioCallbacks) {}

  async load(audioPath: string): Promise<void> {
    this.disposeAudio();

    const audio = new Audio(audioPath);
    audio.preload = "auto";

    await new Promise<void>((resolve, reject) => {
      const cleanup = () => {
        audio.removeEventListener("canplaythrough", handleReady);
        audio.removeEventListener("loadedmetadata", handleReady);
        audio.removeEventListener("error", handleError);
      };

      const handleReady = () => {
        cleanup();
        resolve();
      };

      const handleError = () => {
        cleanup();
        reject(
          new Error(
            `Audio file could not be loaded from ${audioPath}. Put a valid MP3 at public${audioPath}.`,
          ),
        );
      };

      audio.addEventListener("canplaythrough", handleReady, { once: true });
      audio.addEventListener("loadedmetadata", handleReady, { once: true });
      audio.addEventListener("error", handleError, { once: true });
      audio.load();
    }).catch((error: unknown) => {
      this.callbacks.onError(
        error instanceof Error ? error.message : "Audio failed to load.",
      );
      throw error;
    });

    audio.addEventListener("ended", () => {
      this.stopTick();
      this.callbacks.onEnded();
    });

    this.audio = audio;
    this.callbacks.onReady(Math.round(audio.duration * 1000));
  }

  async play(): Promise<void> {
    if (!this.audio) {
      return;
    }

    await this.audio.play();
    this.startTick();
  }

  pause(): void {
    if (!this.audio) {
      return;
    }

    this.audio.pause();
    this.stopTick();
    this.callbacks.onTimeUpdate(this.currentTimeMs());
  }

  stop(): void {
    if (!this.audio) {
      return;
    }

    this.audio.pause();
    this.audio.currentTime = 0;
    this.stopTick();
    this.callbacks.onTimeUpdate(0);
  }

  restart(): void {
    this.seek(0);
  }

  seek(timeMs: number): void {
    if (!this.audio) {
      return;
    }

    this.audio.currentTime = Math.max(0, timeMs) / 1000;
    this.callbacks.onTimeUpdate(this.currentTimeMs());
  }

  setPlaybackRate(rate: number): void {
    if (!this.audio) {
      return;
    }

    this.audio.playbackRate = rate;
  }

  isPlaying(): boolean {
    return Boolean(this.audio && !this.audio.paused);
  }

  currentTimeMs(): number {
    return Math.round((this.audio?.currentTime ?? 0) * 1000);
  }

  durationMs(): number {
    return Math.round((this.audio?.duration ?? 0) * 1000);
  }

  dispose(): void {
    this.stopTick();
    this.disposeAudio();
  }

  async decodeWaveformPeaks(sampleCount = 1200): Promise<EditorWaveformPeaks | undefined> {
    if (!this.audioContext || !this.audio?.src) {
      return undefined;
    }

    const response = await fetch(this.audio.src);
    if (!response.ok) {
      return undefined;
    }

    const arrayBuffer = await response.arrayBuffer();
    const decoded = await this.audioContext.decodeAudioData(arrayBuffer.slice(0));
    const channel = decoded.getChannelData(0);
    const blockSize = Math.max(1, Math.floor(channel.length / sampleCount));
    const peaks: number[] = [];

    for (let offset = 0; offset < channel.length; offset += blockSize) {
      let peak = 0;
      const end = Math.min(channel.length, offset + blockSize);

      for (let index = offset; index < end; index += 1) {
        peak = Math.max(peak, Math.abs(channel[index]));
      }

      peaks.push(peak);
    }

    return {
      sampleCount: peaks.length,
      peaks,
    };
  }

  private disposeAudio(): void {
    if (!this.audio) {
      return;
    }

    this.audio.pause();
    this.audio.src = "";
    this.audio.load();
    this.audio = null;
  }

  private startTick(): void {
    if (this.rafId !== null) {
      return;
    }

    const tick = () => {
      this.callbacks.onTimeUpdate(this.currentTimeMs());
      if (this.audio && !this.audio.paused) {
        this.rafId = requestAnimationFrame(tick);
        return;
      }

      this.rafId = null;
    };

    this.rafId = requestAnimationFrame(tick);
  }

  private stopTick(): void {
    if (this.rafId === null) {
      return;
    }

    cancelAnimationFrame(this.rafId);
    this.rafId = null;
  }
}
