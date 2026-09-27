import { describe, expect, it } from "vitest";

import { loadEditorBundleFromFile } from "../../src/editor/EditorMapLoader";
import { parseBeatmapDocument } from "../../src/shared/beatmapSchema";
import {
  buildOsuFilename,
  convertProjectBeatmapToOsuText,
  importOsuBeatmapText,
  toOsuAudioFilename,
  toProjectAudioPath,
  validateOsuBeatmapText,
} from "../../src/shared/osuInterop";

describe("browser osu interoperability", () => {
  it("exports a valid browser .osu file with normalized audio and derived metadata", () => {
    const beatmap = parseBeatmapDocument({
      title: "Test Song",
      artist: "AI Generated",
      audio: "/audio/test-song.mp3",
      approachTime: 950,
      circleRadius: 40,
      hybrid: {
        version: 1,
        difficulty: "normal",
        sectionCount: 2,
      },
      objects: [
        { id: 2, type: "circle", x: 256, y: 192, time: 1400 },
        { id: 1, type: "circle", x: 96, y: 96, time: 1000 },
      ],
    });

    const result = convertProjectBeatmapToOsuText(beatmap, {
      bpm: 120,
      offsetMs: 300,
    });

    expect(result.filename).toBe(
      "AI Generated - Test Song (osu-map-ai) [Hybrid Normal].osu",
    );
    expect(result.text).toContain("AudioFilename: test-song.mp3");
    expect(result.text).toContain("Version: Hybrid Normal");
    expect(result.text).toContain("[TimingPoints]\n300,500");
    expect(result.text).toContain("[HitObjects]\n96,96,1000,1,0,0:0:0:0:");
    expect(result.report.validation.valid).toBe(true);
  });

  it("keeps hybrid difficulty labels when exporting real hybrid project metadata", () => {
    const beatmap = parseBeatmapDocument({
      title: "Hybrid Catalog Map",
      artist: "AI Generated",
      audio: "/audio/test-song.mp3",
      approachTime: 1200,
      circleRadius: 46,
      hybrid: {
        version: 1,
        difficulty: "easy",
        sectionCount: 2,
        sourceCandidates: [1, 3],
        transitionCorrections: 0,
      },
      objects: [
        { id: 1, type: "circle", x: 96, y: 96, time: 1000 },
        { id: 2, type: "circle", x: 256, y: 192, time: 1400 },
      ],
    });

    const result = convertProjectBeatmapToOsuText(beatmap, {
      bpm: 120,
      offsetMs: 300,
    });

    expect(result.filename).toBe(
      "AI Generated - Hybrid Catalog Map (osu-map-ai) [Hybrid Easy].osu",
    );
    expect(result.text).toContain("Version: Hybrid Easy");
  });

  it("imports circle-only osu text while preserving coordinates, timestamps, and metadata", () => {
    const result = importOsuBeatmapText(makeCircleOnlyOsuText(), {
      filename: "sample.osu",
    });

    expect(result.beatmap.title).toBe("Imported Song");
    expect(result.beatmap.artist).toBe("Unit Test Artist");
    expect(result.beatmap.audio).toBe("/audio/test-song.mp3");
    expect(
      result.beatmap.objects.map((object) => ({
        x: object.x,
        y: object.y,
        time: object.time,
      })),
    ).toEqual([
      { x: 96, y: 96, time: 1000 },
      { x: 256, y: 192, time: 1400 },
    ]);
    expect(result.report.metadata.version).toBe("Edited Normal");
    expect(result.report.circleCount).toBe(2);
  });

  it("rejects unsupported sliders by default", () => {
    expect(() =>
      importOsuBeatmapText(makeUnsupportedOsuText(), {
        filename: "unsupported.osu",
      }),
    ).toThrow("Unsupported hit object types were found: 1 slider");
  });

  it("supports explicit skip mode for unsupported hit objects", async () => {
    const imported = importOsuBeatmapText(makeUnsupportedOsuText(), {
      filename: "unsupported.osu",
      unsupported: "skip",
    });
    const bundle = await loadEditorBundleFromFile(
      new File([makeUnsupportedOsuText()], "unsupported.osu", {
        type: "text/plain",
      }),
      {
        kind: "osu",
        unsupportedMode: "skip",
      },
    );

    expect(imported.report.sliderCount).toBe(1);
    expect(imported.report.skippedCount).toBe(1);
    expect(imported.report.conversionWarnings[0]).toContain(
      "Skipped 1 unsupported hit object",
    );
    expect(imported.beatmap.objects).toHaveLength(1);
    expect(bundle.source.kind).toBe("imported");
    expect(bundle.source.description).toContain("skipped");
  });

  it("normalizes audio paths and osu export filenames deterministically", () => {
    expect(toOsuAudioFilename("/audio/folder/test-song.mp3")).toBe(
      "test-song.mp3",
    );
    expect(toProjectAudioPath("folder\\test-song.mp3")).toBe(
      "/audio/folder/test-song.mp3",
    );
    expect(
      buildOsuFilename(
        'Artist:Name',
        "Title*Name",
        "osu-map-ai",
        "Hybrid Normal",
      ),
    ).toBe("Artist Name - Title Name (osu-map-ai) [Hybrid Normal].osu");
  });

  it("escapes Windows reserved names and caps exported filenames", () => {
    expect(buildOsuFilename("CON", "nul.txt", "aux", "PRN")).toBe(
      "_CON - _nul.txt (_aux) [_PRN].osu",
    );
    const longName = buildOsuFilename("A".repeat(300), "B".repeat(300), "C", "Hard");
    expect(longName.endsWith(".osu")).toBe(true);
    expect(longName.length).toBeLessThanOrEqual(200);
  });

  it("surfaces validation failures for invalid runtime .osu content", () => {
    const validation = validateOsuBeatmapText(`osu file format v14

[General]
AudioFilename: bad.mp3

[Metadata]
Title: Bad Map
Artist: Unit Test
Creator: osu-map-ai
Version: Broken

[Difficulty]
HPDrainRate: 5
CircleSize: 4
OverallDifficulty: 5
ApproachRate: 5
SliderMultiplier: 1.4
SliderTickRate: 1

[TimingPoints]
0,500,4,2,0,70,1,0

[HitObjects]
640,96,-10,1,0,0:0:0:0:
`);

    expect(validation.valid).toBe(false);
    expect(validation.warnings).toContain("Circle at -10ms is out of bounds.");
    expect(validation.warnings).toContain("Hit object times must be non-negative.");
  });

  it("exports spinner objects as valid spinner hit object lines", () => {
    const beatmap = parseBeatmapDocument({
      title: "Spinner Song",
      artist: "AI Generated",
      audio: "/audio/test-song.mp3",
      approachTime: 950,
      circleRadius: 40,
      objects: [
        { id: 1, type: "circle", x: 96, y: 96, time: 1000 },
        { id: 2, type: "spinner", time: 4400, endTime: 5000 },
        { id: 3, type: "circle", x: 420, y: 144, time: 5600 },
      ],
    });

    const result = convertProjectBeatmapToOsuText(beatmap, {
      bpm: 120,
      offsetMs: 300,
    });

    expect(result.report.validation.valid).toBe(true);
    expect(result.text).toContain("256,192,4400,8,0,5000");
    expect(result.text.split("\n")).toContain("256,192,4400,8,0,5000");
  });

  it("round-trips spinner objects through browser export and import", () => {
    const beatmap = parseBeatmapDocument({
      title: "Round Trip",
      artist: "AI Generated",
      audio: "/audio/test-song.mp3",
      approachTime: 950,
      circleRadius: 40,
      objects: [
        { id: 1, type: "circle", x: 96, y: 96, time: 1000 },
        { id: 2, type: "spinner", time: 4400, endTime: 5000 },
      ],
    });

    const exported = convertProjectBeatmapToOsuText(beatmap, {
      bpm: 120,
      offsetMs: 300,
    });
    const imported = importOsuBeatmapText(exported.text, {
      filename: "roundtrip.osu",
    });

    expect(imported.report.spinnerCount).toBe(1);
    expect(imported.report.circleCount).toBe(1);
    const spinner = imported.beatmap.objects.find(
      (object) => object.type === "spinner",
    );
    expect(spinner).toMatchObject({
      type: "spinner",
      time: 4400,
      endTime: 5000,
    });
  });

  it("imports spinner objects from osu text and loads them in the editor", async () => {
    const result = importOsuBeatmapText(makeSpinnerOsuText(), {
      filename: "spinner.osu",
    });
    const bundle = await loadEditorBundleFromFile(
      new File([makeSpinnerOsuText()], "spinner.osu", {
        type: "text/plain",
      }),
      {
        kind: "osu",
        unsupportedMode: "reject",
      },
    );

    expect(result.report.spinnerCount).toBe(1);
    expect(bundle.workingMap.objects.some((object) => object.type === "spinner")).toBe(
      true,
    );
    const spinner = bundle.workingMap.objects.find(
      (object) => object.type === "spinner",
    );
    expect(spinner).toMatchObject({ time: 4400, endTime: 5000 });
  });

  it("rejects duplicate or non-increasing project objects during browser export", () => {
    const beatmap = parseBeatmapDocument(
      {
        title: "Broken Export",
        artist: "Unit Test",
        audio: "/audio/test-song.mp3",
        approachTime: 900,
        circleRadius: 36,
        objects: [
          { id: 1, type: "circle", x: 96, y: 96, time: 1200 },
          { id: 2, type: "circle", x: 156, y: 156, time: 1200 },
        ],
      },
      {
        requireUniqueTimestamps: false,
      },
    );

    expect(() =>
      convertProjectBeatmapToOsuText(beatmap, {
        bpm: 100,
        offsetMs: 0,
      }),
    ).toThrow("strictly increasing in time");
  });
});

function makeCircleOnlyOsuText(): string {
  return `osu file format v14

// Local parser should ignore comments and blank lines.
[General]
AudioFilename: test-song.mp3

[Editor]
BeatDivisor: 4

[Metadata]
Title: Imported Song
Artist: Unit Test Artist
Creator: osu-map-ai
Version: Edited Normal

[Difficulty]
HPDrainRate: 5
CircleSize: 4
OverallDifficulty: 6
ApproachRate: 5
SliderMultiplier: 1.4
SliderTickRate: 1

[Events]
0,0,"bg.png",0,0

[TimingPoints]
300,500,4,2,0,70,1,0

[Colours]
Combo1 : 255,0,0

[HitObjects]
96,96,1000,1,0,0:0:0:0:
256,192,1400,5,0,0:0:0:0:
`;
}

function makeSpinnerOsuText(): string {
  return `osu file format v14

[General]
AudioFilename: test-song.mp3

[Metadata]
Title: Spinner Song
Artist: Unit Test Artist
Creator: osu-map-ai
Version: Edited Normal

[Difficulty]
HPDrainRate: 5
CircleSize: 4
OverallDifficulty: 6
ApproachRate: 5
SliderMultiplier: 1.4
SliderTickRate: 1

[TimingPoints]
300,500,4,2,0,70,1,0

[HitObjects]
96,96,1000,1,0,0:0:0:0:
256,192,4400,8,0,5000
`;
}

function makeUnsupportedOsuText(): string {
  return `osu file format v14

[General]
AudioFilename: test-song.mp3

[Metadata]
Title: Unsupported Song
Artist: Unit Test Artist
Creator: osu-map-ai
Version: Hard

[Difficulty]
HPDrainRate: 6
CircleSize: 4
OverallDifficulty: 6
ApproachRate: 7
SliderMultiplier: 1.4
SliderTickRate: 1

[TimingPoints]
0,500,4,2,0,70,1,0

[HitObjects]
96,96,1000,1,0,0:0:0:0:
256,192,1400,2,0,B|320:192|384:128,1,200
`;
}
