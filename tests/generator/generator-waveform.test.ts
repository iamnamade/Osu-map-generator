import { describe, expect, it } from "vitest";

import {
  computeWaveformPeaks,
  extractPeaksFromChannel,
} from "../../src/generator/components/GeneratorWaveform";

describe("generator waveform peaks", () => {
  it("reduces a channel to max-abs peaks per block", () => {
    const channel = new Float32Array([0, 0.5, -0.9, 0.2, 0.4, -0.1, 0.8, -0.3]);

    const peaks = extractPeaksFromChannel(channel, 4);

    // Float32 storage makes exact equality brittle; compare rounded values.
    expect(peaks.map((peak) => Number(peak.toFixed(4)))).toEqual([
      0.5, 0.9, 0.4, 0.8,
    ]);
  });

  it("never uses a block size below one sample", () => {
    const channel = new Float32Array([0.2, -0.7]);

    const peaks = extractPeaksFromChannel(channel, 10);

    expect(peaks.map((peak) => Number(peak.toFixed(4)))).toEqual([0.2, 0.7]);
  });

  it("returns undefined when no browser audio decoder is available", async () => {
    const peaks = await computeWaveformPeaks(
      new File(["data"], "song.mp3", { type: "audio/mpeg" }),
    );

    expect(peaks).toBeUndefined();
  });
});
