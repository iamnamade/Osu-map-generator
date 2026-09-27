import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const currentFile = fileURLToPath(import.meta.url);
const currentDir = path.dirname(currentFile);
const rootDir = path.resolve(currentDir, "..");
const mapPath = path.join(rootDir, "public", "maps", "test-map.json");
const audioPath = path.join(rootDir, "public", "audio", "test-song.mp3");
const lameBundlePath = path.join(rootDir, "node_modules", "lamejs", "lame.all.js");

const lameBundleSource = await fs.readFile(lameBundlePath, "utf8");
vm.runInThisContext(lameBundleSource);

const { Mp3Encoder } = globalThis.lamejs;

const sampleRate = 44_100;
const leadInMs = 700;
const tailMs = 2_200;
const clickDurationMs = 140;

const beatmap = JSON.parse(await fs.readFile(mapPath, "utf8"));
const beatTimesMs = beatmap.objects.map((object) => object.time + leadInMs);
const durationMs = beatTimesMs.at(-1) + tailMs;
const totalSamples = Math.ceil((durationMs / 1000) * sampleRate);
const samples = new Int16Array(totalSamples);

for (let index = 0; index < totalSamples; index += 1) {
  const timeSeconds = index / sampleRate;
  let sampleValue =
    Math.sin(2 * Math.PI * 110 * timeSeconds) * 0.05 +
    Math.sin(2 * Math.PI * 220 * timeSeconds) * 0.03;

  for (let beatIndex = 0; beatIndex < beatTimesMs.length; beatIndex += 1) {
    const beatTimeSeconds = beatTimesMs[beatIndex] / 1000;
    const offsetSeconds = timeSeconds - beatTimeSeconds;

    if (offsetSeconds < -0.012 || offsetSeconds > clickDurationMs / 1000) {
      continue;
    }

    const attack = offsetSeconds < 0 ? 1 + offsetSeconds / 0.012 : 1;
    const decay = Math.exp(-Math.max(offsetSeconds, 0) * 24);
    const accent = beatIndex % 4 === 0 ? 1 : 0.8;
    const tone = Math.sin(2 * Math.PI * 880 * (offsetSeconds + 0.012));
    sampleValue += tone * attack * decay * 0.32 * accent;
  }

  const clamped = Math.max(-1, Math.min(1, sampleValue));
  samples[index] = Math.round(clamped * 32_767);
}

const encoder = new Mp3Encoder(1, sampleRate, 128);
const chunks = [];
const blockSize = 1_152;

for (let index = 0; index < samples.length; index += blockSize) {
  const block = samples.subarray(index, index + blockSize);
  const encoded = encoder.encodeBuffer(block);

  if (encoded.length > 0) {
    chunks.push(Buffer.from(encoded));
  }
}

const flushed = encoder.flush();

if (flushed.length > 0) {
  chunks.push(Buffer.from(flushed));
}

await fs.writeFile(audioPath, Buffer.concat(chunks));

console.log(`Generated test audio at ${audioPath}`);
