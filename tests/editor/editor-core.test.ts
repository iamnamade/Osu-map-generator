import { afterEach, describe, expect, it } from "vitest";

import { parseBeatmapDocument } from "../../src/shared/beatmapSchema";
import { normalizeMapForExport, summarizeChanges } from "../../src/editor/EditorExporter";
import {
  deserializeHistory,
  pushHistoryEntry,
  serializeHistory,
} from "../../src/editor/EditorHistory";
import { shouldIgnoreShortcut, stepSize } from "../../src/editor/EditorKeyboard";
import {
  createBundle,
  loadEditorBundleFromFile,
} from "../../src/editor/EditorMapLoader";
import type { EditorHistoryEntry } from "../../src/editor/models/EditorActions";
import {
  isEditorAutosavePayload,
  type EditorMapDocument,
  type EditorProjectExport,
  type EditorSourceIdentity,
} from "../../src/editor/models/EditorModels";
import { pointerToLogical } from "../../src/editor/playfield/CoordinateMapper";
import { validateEditorMap } from "../../src/editor/EditorValidator";

const originalHTMLElement = globalThis.HTMLElement;

afterEach(() => {
  if (originalHTMLElement) {
    globalThis.HTMLElement = originalHTMLElement;
    return;
  }

  delete (globalThis as { HTMLElement?: unknown }).HTMLElement;
});

describe("editor map loading", () => {
  it("rejects invalid imported maps with duplicate timestamps", async () => {
    const invalidMap = {
      title: "Broken",
      artist: "Test",
      audio: "/audio/test-song.mp3",
      approachTime: 900,
      circleRadius: 36,
      objects: [
        { id: 1, type: "circle", x: 96, y: 96, time: 1000 },
        { id: 2, type: "circle", x: 196, y: 196, time: 1000 },
      ],
    };
    const file = new File([JSON.stringify(invalidMap)], "broken.json", {
      type: "application/json",
    });

    await expect(loadEditorBundleFromFile(file)).rejects.toThrow(
      "duplicated at 1000ms",
    );
  });

  it("preserves stable editor ids when importing an editor project", async () => {
    const project = makeProjectExport();
    const file = new File([JSON.stringify(project)], "session.editor.json", {
      type: "application/json",
    });

    const bundle = await loadEditorBundleFromFile(file);

    expect(bundle.restoredProject).toBeDefined();
    expect(bundle.baselineMap.objects[0]?.editorId).toBe("obj-000001");
    expect(bundle.workingMap.objects[1]?.editorId).toBe("add-000002");
  });

  it("keeps the baseline frozen and the working copy isolated", () => {
    const beatmap = parseBeatmapDocument(makeRawBeatmap());
    const bundle = createBundle({
      beatmap,
      source: makeSource(),
    });

    expect(Object.isFrozen(bundle.baselineMap)).toBe(true);
    expect(Object.isFrozen(bundle.baselineMap.objects)).toBe(true);

    bundle.workingMap.objects[0]!.x = 240;

    expect(bundle.baselineMap.objects[0]!.x).toBe(96);
    expect(bundle.workingMap.objects[0]!.x).toBe(240);
  });
});

describe("editor history and export logic", () => {
  it("serializes and restores full history, including reset-map entries", () => {
    const beforeMap = makeEditorMap();
    const afterMap: EditorMapDocument = {
      ...makeEditorMap(),
      title: "Edited Session",
      objects: makeEditorMap().objects.map((object, index) =>
        index === 0 ? { ...object, x: 132 } : object,
      ),
    };
    const entries: EditorHistoryEntry[] = [
      {
        action: "move_object",
        objectId: "obj-000001",
        before: { x: 96, y: 96, time: 1000 },
        after: { x: 132, y: 96, time: 1000 },
        sequence: 1,
        timeMs: 1000,
        summary: "Moved object 1",
      },
      {
        action: "add_object",
        objectId: "add-000002",
        objectSnapshot: {
          editorId: "add-000002",
          id: 9,
          type: "circle",
          x: 320,
          y: 180,
          time: 1400,
          extraFields: {},
        },
        objectIndex: 1,
        sequence: 2,
        timeMs: 1400,
        summary: "Added object",
      },
      {
        action: "reset_map",
        beforeMap,
        afterMap,
        sequence: 3,
        summary: "Reset map to baseline",
      },
    ];

    const serialized = serializeHistory(entries, 2, 4);
    const restored = deserializeHistory(serialized);

    expect(restored).toHaveLength(3);
    expect(restored[1]).toMatchObject({
      action: "add_object",
      objectId: "add-000002",
      objectIndex: 1,
    });
    expect(restored[2]).toMatchObject({
      action: "reset_map",
      summary: "Reset map to baseline",
    });
    expect(
      (restored[2] as Extract<EditorHistoryEntry, { action: "reset_map" }>).beforeMap.objects[0]
        ?.editorId,
    ).toBe("obj-000001");
  });

  it("applies the history limit and clears redo entries after a new edit", () => {
    const entryA = makeMoveEntry(1, "obj-000001", 96, 128);
    const entryB = makeMoveEntry(2, "obj-000002", 256, 280);
    const entryC = makeMoveEntry(3, "obj-000003", 420, 400);

    const redoCleared = pushHistoryEntry([entryA, entryB], 1, entryC, 5);
    expect(redoCleared.entries.map((entry) => entry.sequence)).toEqual([1, 3]);
    expect(redoCleared.cursor).toBe(2);

    const limited = pushHistoryEntry([entryA, entryB], 2, entryC, 2);
    expect(limited.entries.map((entry) => entry.sequence)).toEqual([2, 3]);
    expect(limited.cursor).toBe(2);
  });

  it("normalizes exported maps and summarizes baseline changes deterministically", () => {
    const baseline = makeEditorMap();
    const working: EditorMapDocument = {
      ...makeEditorMap(),
      objects: [
        { ...makeEditorMap().objects[2]!, time: 1825 },
        { ...makeEditorMap().objects[0]!, x: 120 },
        {
          editorId: "add-000002",
          id: 99,
          type: "circle",
          x: 318.6,
          y: 181.2,
          time: 1455.8,
          extraFields: {},
        },
      ],
    };

    const normalized = normalizeMapForExport(working, makeSource(), 3);
    const objects = normalized.objects as Array<Record<string, unknown>>;
    const summary = summarizeChanges(baseline, working);

    expect(objects.map((object) => object.id)).toEqual([1, 2, 3]);
    expect(objects.map((object) => object.time)).toEqual([1000, 1456, 1825]);
    expect(objects.every((object) => !("editorId" in object))).toBe(true);
    expect(normalized.editor).toMatchObject({
      name: "osu-map-ai-editor",
      sourceType: "champion",
      editCount: 3,
    });
    expect(summary).toEqual({
      unchanged: 0,
      moved: 1,
      retimed: 1,
      movedAndRetimed: 0,
      added: 1,
      removed: 1,
    });
  });
});

describe("editor validation and utility helpers", () => {
  it("flags stacking and cursor-speed problems in the lightweight validator", () => {
    const map: EditorMapDocument = {
      ...makeEditorMap(),
      objects: [
        {
          editorId: "obj-000001",
          id: 1,
          type: "circle",
          x: 96,
          y: 96,
          time: 1000,
          extraFields: {},
        },
        {
          editorId: "obj-000002",
          id: 2,
          type: "circle",
          x: 96,
          y: 96,
          time: 1100,
          extraFields: {},
        },
        {
          editorId: "obj-000003",
          id: 3,
          type: "circle",
          x: 452,
          y: 320,
          time: 1180,
          extraFields: {},
        },
      ],
    };

    const validation = validateEditorMap(map, {
      difficulty: "normal",
      audioDurationMs: 2400,
      beats: [{ timeMs: 1000, strength: 1 }],
      onsets: [{ timeMs: 1100, strength: 0.92 }],
    });

    expect(validation.issues.some((issue) => issue.code === "stacking")).toBe(true);
    expect(validation.issues.some((issue) => issue.code === "cursor_speed")).toBe(true);
  });

  it("flags radius-aware physical overlaps between discs", () => {
    const map: EditorMapDocument = {
      ...makeEditorMap(),
      objects: [
        {
          editorId: "obj-000001",
          id: 1,
          type: "circle",
          x: 120,
          y: 120,
          time: 1000,
          extraFields: {},
        },
        {
          editorId: "obj-000002",
          id: 2,
          type: "circle",
          x: 150,
          y: 120,
          time: 1250,
          extraFields: {},
        },
        {
          editorId: "obj-000003",
          id: 3,
          type: "circle",
          x: 400,
          y: 300,
          time: 1500,
          extraFields: {},
        },
      ],
    };

    const validation = validateEditorMap(map, {
      difficulty: "normal",
      audioDurationMs: 2400,
      beats: [{ timeMs: 1000, strength: 1 }],
      onsets: [{ timeMs: 1100, strength: 0.92 }],
    });

    const collision = validation.issues.find((issue) => issue.code === "collision_overlap");
    expect(collision).toBeDefined();
    expect(collision?.severity).toBe("error");
    expect(collision?.objectId).toBe("obj-000002");
    expect(collision?.message).toContain("overlaps");
  });

  it("flags a circle that overlaps a slider body", () => {
    const map: EditorMapDocument = {
      ...makeEditorMap(),
      objects: [
        {
          editorId: "obj-000001",
          id: 1,
          type: "slider",
          x: 100,
          y: 100,
          time: 1000,
          endTime: 1500,
          pathType: "linear",
          controlPoints: [{ x: 300, y: 100 }],
          repeats: 1,
          pixelLength: 200,
          extraFields: {},
        },
        {
          editorId: "obj-000002",
          id: 2,
          type: "circle",
          x: 200,
          y: 122,
          time: 1250,
          extraFields: {},
        },
      ],
    };

    const validation = validateEditorMap(map, {
      difficulty: "normal",
      audioDurationMs: 2400,
      beats: [{ timeMs: 1000, strength: 1 }],
      onsets: [{ timeMs: 1100, strength: 0.92 }],
    });

    const collision = validation.issues.find((issue) => issue.code === "collision_overlap");
    expect(collision).toBeDefined();
    expect(collision?.message).toContain("disc-slider");
  });

  it("leaves a clean, time-separated map without collision issues", () => {
    const map: EditorMapDocument = {
      ...makeEditorMap(),
      objects: [
        {
          editorId: "obj-000001",
          id: 1,
          type: "circle",
          x: 120,
          y: 120,
          time: 1000,
          extraFields: {},
        },
        {
          editorId: "obj-000002",
          id: 2,
          type: "circle",
          x: 200,
          y: 200,
          time: 3400,
          extraFields: {},
        },
      ],
    };

    const validation = validateEditorMap(map, {
      difficulty: "normal",
      audioDurationMs: 6000,
      beats: [{ timeMs: 1000, strength: 1 }],
      onsets: [{ timeMs: 1100, strength: 0.92 }],
    });

    expect(validation.issues.some((issue) => issue.code === "collision_overlap")).toBe(false);
  });

  it("validates spinner objects for duration, overlap, and transition safety", () => {
    const map: EditorMapDocument = {
      ...makeEditorMap(),
      objects: [
        {
          editorId: "obj-000001",
          id: 1,
          type: "circle",
          x: 96,
          y: 96,
          time: 1000,
          extraFields: {},
        },
        {
          editorId: "obj-000002",
          id: 2,
          type: "spinner",
          time: 4400,
          endTime: 4100,
          extraFields: {},
        },
        {
          editorId: "obj-000003",
          id: 3,
          type: "circle",
          x: 200,
          y: 200,
          time: 4700,
          extraFields: {},
        },
        {
          editorId: "obj-000004",
          id: 4,
          type: "spinner",
          time: 5000,
          endTime: 5600,
          extraFields: {},
        },
        {
          editorId: "obj-000005",
          id: 5,
          type: "circle",
          x: 320,
          y: 240,
          time: 5200,
          extraFields: {},
        },
        {
          editorId: "obj-000006",
          id: 6,
          type: "spinner",
          time: 6000,
          endTime: 6300,
          extraFields: {},
        },
        {
          editorId: "obj-000007",
          id: 7,
          type: "circle",
          x: 420,
          y: 144,
          time: 6350,
          extraFields: {},
        },
      ],
    };

    const validation = validateEditorMap(map, {
      difficulty: "normal",
      audioDurationMs: 7000,
      beats: [{ timeMs: 1000, strength: 1 }],
      onsets: [{ timeMs: 4400, strength: 0.9 }],
    });

    expect(
      validation.issues.some((issue) => issue.code === "spinner_end_before_start"),
    ).toBe(true);
    expect(
      validation.issues.some((issue) => issue.code === "spinner_overlaps_next"),
    ).toBe(true);
    expect(
      validation.issues.some((issue) => issue.code === "spinner_recovery_tight"),
    ).toBe(true);
  });

  it("accepts well-formed spinners with comfortable transitions", () => {
    const map: EditorMapDocument = {
      ...makeEditorMap(),
      objects: [
        {
          editorId: "obj-000001",
          id: 1,
          type: "circle",
          x: 96,
          y: 96,
          time: 1000,
          extraFields: {},
        },
        {
          editorId: "obj-000002",
          id: 2,
          type: "spinner",
          time: 4400,
          endTime: 5400,
          extraFields: {},
        },
        {
          editorId: "obj-000003",
          id: 3,
          type: "circle",
          x: 420,
          y: 144,
          time: 5800,
          extraFields: {},
        },
      ],
    };

    const validation = validateEditorMap(map, {
      difficulty: "normal",
      audioDurationMs: 6000,
      beats: [{ timeMs: 1000, strength: 1 }],
      onsets: [{ timeMs: 4400, strength: 0.9 }],
    });

    expect(
      validation.issues.some((issue) =>
        issue.code.startsWith("spinner"),
      ),
    ).toBe(false);
  });

  it("converts pointer coordinates back into logical playfield space", () => {
    const logical = pointerToLogical(
      { x: 256, y: 192 } as never,
      { displayScale: { x: 2, y: 4 } } as never,
    );

    expect(logical).toEqual({ x: 128, y: 48 });
  });

  it("validates autosave payloads and protects shortcuts while typing", () => {
    const payload = {
      ...makeProjectExport(),
      autosave: {
        version: 1,
        savedRevision: 4,
      },
    };

    expect(isEditorAutosavePayload(payload)).toBe(true);
    expect(
      isEditorAutosavePayload({
        ...payload,
        autosave: { version: 2, savedRevision: 4 },
      }),
    ).toBe(false);

    class FakeInputElement {
      readonly tagName = "INPUT";
      readonly isContentEditable = false;
    }

    globalThis.HTMLElement = FakeInputElement as unknown as typeof HTMLElement;

    expect(
      shouldIgnoreShortcut({ target: new FakeInputElement() } as KeyboardEvent),
    ).toBe(true);
    expect(stepSize({ shiftKey: false } as KeyboardEvent)).toBe(1);
    expect(stepSize({ shiftKey: true } as KeyboardEvent)).toBe(10);
  });
});

function makeRawBeatmap() {
  return {
    title: "Test Song",
    artist: "AI Generated",
    audio: "/audio/test-song.mp3",
    approachTime: 900,
    circleRadius: 36,
    objects: [
      { id: 1, type: "circle", x: 96, y: 96, time: 1000 },
      { id: 2, type: "circle", x: 256, y: 192, time: 1400 },
      { id: 3, type: "circle", x: 420, y: 144, time: 1700 },
    ],
  };
}

function makeEditorMap(): EditorMapDocument {
  return {
    title: "Test Song",
    artist: "AI Generated",
    audio: "/audio/test-song.mp3",
    approachTime: 900,
    circleRadius: 36,
    extraFields: {},
    objects: [
      {
        editorId: "obj-000001",
        id: 1,
        type: "circle",
        x: 96,
        y: 96,
        time: 1000,
        extraFields: {},
      },
      {
        editorId: "obj-000002",
        id: 2,
        type: "circle",
        x: 256,
        y: 192,
        time: 1400,
        extraFields: {},
      },
      {
        editorId: "obj-000003",
        id: 3,
        type: "circle",
        x: 420,
        y: 144,
        time: 1700,
        extraFields: {},
      },
    ],
  };
}

function makeSource(): EditorSourceIdentity {
  return {
    id: "champion-normal",
    label: "Champion Normal",
    kind: "champion",
    path: "/maps/champions/test-song-normal.json",
    difficulty: "normal",
    description: "Tournament winner",
    reportPath: "/reports/champions/test-song-normal-report.json",
    tournamentReportPath: "/tournaments/test-song-normal-tournament.json",
    analysisPath: "/analysis/test-song-analysis.json",
  };
}

function makeProjectExport(): EditorProjectExport {
  const baselineMap = makeEditorMap();
  const workingMap: EditorProjectExport["workingMap"] = {
    title: baselineMap.title,
    artist: baselineMap.artist,
    audio: baselineMap.audio,
    approachTime: baselineMap.approachTime,
    circleRadius: baselineMap.circleRadius,
    objects: [
      {
        editorId: "obj-000001",
        id: 1,
        type: "circle",
        x: 96,
        y: 96,
        time: 1000,
      },
      {
        editorId: "add-000002",
        id: 8,
        type: "circle",
        x: 300,
        y: 188,
        time: 1300,
      },
    ],
  };

  return {
    editorProject: {
      name: "pulse-practice-editor",
      version: 1,
      source: makeSource(),
    },
    baselineMap: {
      title: baselineMap.title,
      artist: baselineMap.artist,
      audio: baselineMap.audio,
      approachTime: baselineMap.approachTime,
      circleRadius: baselineMap.circleRadius,
      objects: baselineMap.objects.map((object) => ({
        editorId: object.editorId,
        id: object.id,
        type: object.type,
        x: object.x,
        y: object.y,
        time: object.time,
      })),
    },
    workingMap,
    history: {
      entries: [
        {
          sequence: 1,
          action: "add_object",
          objectId: "add-000002",
          objectSnapshot: {
            editorId: "add-000002",
            id: 8,
            type: "circle",
            x: 300,
            y: 188,
            time: 1300,
            extraFields: {},
          },
          objectIndex: 1,
          timeMs: 1300,
          summary: "Added object",
        },
      ],
      cursor: 1,
      nextSequence: 2,
    },
    timeline: {
      visibleStartMs: 0,
      visibleDurationMs: 5000,
    },
    selectedObjectId: "add-000002",
    playheadMs: 1300,
    mode: "select",
    snapMode: "beat",
    snapToleranceMs: 90,
    baselineOverlayEnabled: true,
    validationEnabled: true,
    playbackRate: 1,
  };
}

function makeMoveEntry(
  sequence: number,
  objectId: string,
  beforeX: number,
  afterX: number,
): EditorHistoryEntry {
  return {
    action: "move_object",
    objectId,
    before: { x: beforeX, y: 100, time: 1000 + sequence * 100 },
    after: { x: afterX, y: 100, time: 1000 + sequence * 100 },
    sequence,
    timeMs: 1000 + sequence * 100,
    summary: `Moved ${objectId}`,
  };
}
