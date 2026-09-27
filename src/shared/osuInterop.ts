import {
  parseBeatmapDocument,
  type BeatmapDocument,
  type BeatmapDocumentCircleObject,
  type BeatmapDocumentObject,
  serializeBeatmapDocument,
} from "./beatmapSchema";
import { isJsonObject, type JsonObject, type JsonValue } from "./JsonTypes";
import { OSU_INTEROP_CONSTANTS } from "./osuInteropConstants";

export type UnsupportedObjectMode = "reject" | "skip";
export type SupportedProjectDifficulty = "easy" | "normal" | "hard";
export type UnsupportedOsuObjectKind = "slider" | "spinner" | "hold" | "unknown";

interface OsuSectionMap {
  General: Record<string, string>;
  Editor: Record<string, string>;
  Metadata: Record<string, string>;
  Difficulty: Record<string, string>;
}

export interface OsuTimingPoint {
  time: number;
  beatLength: number;
  meter: number;
  sampleSet: number;
  sampleIndex: number;
  volume: number;
  uninherited: number;
  effects: number;
}

export interface OsuCircleHitObject {
  x: number;
  y: number;
  time: number;
  typeFlags: number;
  hitSound: number;
  hitSample: string;
  newCombo: boolean;
  rawLine: string;
}

export interface OsuSpinnerHitObject {
  time: number;
  endTime: number;
  typeFlags: number;
  hitSound: number;
  newCombo: boolean;
  rawLine: string;
}

export interface OsuUnsupportedHitObject {
  kind: UnsupportedOsuObjectKind;
  lineIndex: number;
  line: string;
  time: number | null;
  typeFlags: number;
}

export interface ParsedOsuBeatmap {
  formatVersion: number;
  sectionsFound: string[];
  general: Record<string, string>;
  editor: Record<string, string>;
  metadata: Record<string, string>;
  difficulty: Record<string, string>;
  events: string[];
  timingPoints: OsuTimingPoint[];
  colours: string[];
  circles: OsuCircleHitObject[];
  spinners: OsuSpinnerHitObject[];
  unsupportedHitObjects: OsuUnsupportedHitObject[];
  extraSections: Record<string, string[]>;
  backgroundFilename?: string;
  warnings: string[];
}

export interface OsuValidationResult {
  valid: boolean;
  warnings: string[];
  unsupportedCounts: Record<UnsupportedOsuObjectKind, number>;
}

export interface OsuImportOptions {
  unsupported?: UnsupportedObjectMode;
  filename?: string;
  outputPath?: string;
}

export interface OsuImportReport {
  sourceOsuPath: string;
  formatVersion: number;
  sectionsFound: string[];
  metadata: {
    title: string;
    artist: string;
    version: string;
    creator?: string;
    audioFilename: string;
  };
  circleCount: number;
  sliderCount: number;
  spinnerCount: number;
  holdCount: number;
  unsupportedCount: number;
  skippedCount: number;
  timingPointCount: number;
  conversionWarnings: string[];
  outputJsonPath?: string;
  validation: OsuValidationResult;
}

export interface BrowserExportAnalysis {
  bpm?: number;
  offsetMs?: number;
}

export interface OsuDifficultyValues {
  hpDrainRate: number;
  circleSize: number;
  overallDifficulty: number;
  approachRate: number;
  sliderMultiplier: number;
  sliderTickRate: number;
}

export interface OsuExportOptions {
  creator?: string;
  versionName?: string;
  sourcePath?: string;
  outputPath?: string;
  beatmapId?: string | number;
  beatmapSetId?: string | number;
  backgroundFilename?: string;
}

export interface OsuExportReport {
  sourceJsonPath: string;
  outputOsuPath: string;
  title: string;
  artist: string;
  version: string;
  objectCount: number;
  bpm: number;
  offsetMs: number;
  difficultyValues: OsuDifficultyValues;
  warnings: string[];
  unsupportedProjectFeatures: string[];
  validation: OsuValidationResult;
  filename: string;
  audioFilename: string;
}

export interface OsuExportResult {
  filename: string;
  text: string;
  report: OsuExportReport;
}

export function normalizeOsuRelativePath(value: string): string {
  const normalized = value.replaceAll("\\", "/").trim().replace(/^"+|"+$/g, "");
  if (!normalized) {
    throw new Error("Audio filename must be a non-empty relative path.");
  }
  if (/^[a-z]:/i.test(normalized) || normalized.startsWith("/") || normalized.startsWith("../")) {
    throw new Error(`Audio filename must stay relative inside the mapset: ${value}`);
  }
  const segments = normalized
    .split("/")
    .map((segment) => segment.trim())
    .filter((segment) => segment.length > 0);
  if (segments.length === 0 || segments.some((segment) => segment === "." || segment === "..")) {
    throw new Error(`Audio filename must stay relative inside the mapset: ${value}`);
  }
  return segments.join("/");
}

export function toProjectAudioPath(osuAudioFilename: string): string {
  return `/audio/${normalizeOsuRelativePath(osuAudioFilename)}`;
}

export function toOsuAudioFilename(browserAudioPath: string): string {
  const trimmed = browserAudioPath.trim();
  if (!trimmed) {
    throw new Error("Project audio path must be a non-empty string.");
  }
  const normalized = trimmed.replaceAll("\\", "/");
  const segments = normalized.split("/").filter((segment) => segment.length > 0);
  const filename = segments[segments.length - 1];
  if (!filename) {
    throw new Error(`Project audio path is missing a filename: ${browserAudioPath}`);
  }
  return filename;
}

export function projectRadiusToOsuCircleSize(radius: number): number {
  ensureFinite(radius, "Circle radius");
  const formula = OSU_INTEROP_CONSTANTS.circleSizeFormula;
  return roundClamp(
    (formula.radiusBase - radius) / formula.radiusStep,
    formula.minimum,
    formula.maximum,
  );
}

export function osuCircleSizeToProjectRadius(circleSize: number): number {
  ensureFinite(circleSize, "Circle size");
  const formula = OSU_INTEROP_CONSTANTS.circleSizeFormula;
  return Math.round(formula.radiusBase - circleSize * formula.radiusStep);
}

export function projectApproachTimeToOsuApproachRate(approachTimeMs: number): number {
  ensureFinite(approachTimeMs, "Approach time");
  const formula = OSU_INTEROP_CONSTANTS.approachRateFormula;
  const value =
    approachTimeMs >= formula.slowPivotMs
      ? (formula.slowReferenceMs - approachTimeMs) / formula.slowStepMsPerAr
      : 5 + (formula.fastPivotMs - approachTimeMs) / formula.fastStepMsPerAr;
  return roundClamp(value, formula.minimum, formula.maximum);
}

export function osuApproachRateToProjectApproachTime(approachRate: number): number {
  ensureFinite(approachRate, "Approach rate");
  const formula = OSU_INTEROP_CONSTANTS.approachRateFormula;
  const clamped = clamp(approachRate, formula.minimum, formula.maximum);
  const result =
    clamped <= 5
      ? formula.slowReferenceMs - clamped * formula.slowStepMsPerAr
      : formula.fastPivotMs - (clamped - 5) * formula.fastStepMsPerAr;
  return Math.round(result);
}

export function inferProjectDifficultyName(
  beatmap: BeatmapDocument,
): SupportedProjectDifficulty | undefined {
  const generator = readNestedObject(beatmap.extraFields, ["generator"]);
  const hybrid = readNestedObject(beatmap.extraFields, ["hybrid"]);
  const editor = readNestedObject(beatmap.extraFields, ["editor"]);
  const metadataVersion = readNestedString(beatmap.extraFields, ["osu", "beatmapVersion"]);
  const explicitDifficulty = firstDefinedString(
    readNestedString(generator, ["difficulty"]),
    readNestedString(hybrid, ["difficulty"]),
    readNestedString(editor, ["sourceDifficulty"]),
  );
  const normalizedExplicit = normalizeDifficultyName(explicitDifficulty);
  if (normalizedExplicit) {
    return normalizedExplicit;
  }
  const normalizedVersion = normalizeDifficultyName(metadataVersion);
  if (normalizedVersion) {
    return normalizedVersion;
  }

  const presetEntries = [
    { name: "easy" as const, approachTime: 1200, circleRadius: 46 },
    { name: "normal" as const, approachTime: 950, circleRadius: 40 },
    { name: "hard" as const, approachTime: 720, circleRadius: 34 },
  ];
  const nearest = presetEntries
    .map((preset) => ({
      name: preset.name,
      score:
        Math.abs(preset.approachTime - beatmap.approachTime) +
        Math.abs(preset.circleRadius - beatmap.circleRadius) * 12,
    }))
    .sort((left, right) => left.score - right.score)[0];
  return nearest?.name;
}

export function convertProjectBeatmapToOsuText(
  beatmap: BeatmapDocument,
  analysis: BrowserExportAnalysis | undefined,
  options: OsuExportOptions = {},
): OsuExportResult {
  const sortedObjects = beatmap.objects
    .slice()
    .sort((left, right) => {
      if (left.time !== right.time) {
        return left.time - right.time;
      }
      return left.id - right.id;
    });
  validateProjectObjectsForOsuExport(sortedObjects);

  const audioFilename = toOsuAudioFilename(beatmap.audio);
  const difficultyName = inferProjectDifficultyName(beatmap);
  const metadataVersion =
    options.versionName ??
    deriveVersionName(beatmap, difficultyName) ??
    "Imported";
  const creator =
    options.creator ??
    readNestedString(beatmap.extraFields, ["osu", "creator"]) ??
    OSU_INTEROP_CONSTANTS.creatorDefault;
  const titleUnicode = readNestedString(beatmap.extraFields, ["osu", "titleUnicode"]);
  const artistUnicode = readNestedString(beatmap.extraFields, ["osu", "artistUnicode"]);
  const source = readNestedString(beatmap.extraFields, ["osu", "source"]) ?? "";
  const tags = readNestedString(beatmap.extraFields, ["osu", "tags"]) ?? "pulse-practice circle-only";
  const beatmapId = normalizeOptionalText(options.beatmapId ?? readNestedJsonValue(beatmap.extraFields, ["osu", "beatmapId"]));
  const beatmapSetId = normalizeOptionalText(options.beatmapSetId ?? readNestedJsonValue(beatmap.extraFields, ["osu", "beatmapSetId"]));
  const backgroundFilename =
    options.backgroundFilename ??
    readNestedString(beatmap.extraFields, ["osu", "backgroundFilename"]);
  const bpm = analysis?.bpm && analysis.bpm > 0 ? analysis.bpm : 120;
  const offsetMs = analysis?.offsetMs ?? 0;
  const difficultyValues = convertProjectDifficultyToOsuValues(beatmap, difficultyName);
  const warnings: string[] = [];
  if (!analysis?.bpm || analysis.bpm <= 0) {
    warnings.push("No positive BPM estimate was available. Export fell back to 120 BPM.");
  }

  const topLevelOsu = readNestedObject(beatmap.extraFields, ["osu"]);
  const preservedGeneral = sanitizeKeyValueSection(readNestedObject(topLevelOsu, ["general"]));
  const preservedEditor = sanitizeKeyValueSection(readNestedObject(topLevelOsu, ["editor"]));
  const preservedMetadata = sanitizeKeyValueSection(readNestedObject(topLevelOsu, ["metadata"]));
  const preservedDifficulty = sanitizeKeyValueSection(readNestedObject(topLevelOsu, ["difficulty"]));
  const preservedColours = sanitizeStringArray(readNestedJsonValue(topLevelOsu, ["colours"]));

  const lines: string[] = [];
  lines.push(`osu file format v${OSU_INTEROP_CONSTANTS.fileFormatVersion}`, "");

  writeSection(lines, "General", {
    ...preservedGeneral,
    AudioFilename: audioFilename,
    AudioLeadIn: String(OSU_INTEROP_CONSTANTS.generalDefaults.audioLeadIn),
    PreviewTime: String(OSU_INTEROP_CONSTANTS.generalDefaults.previewTime),
    Countdown: String(OSU_INTEROP_CONSTANTS.generalDefaults.countdown),
    SampleSet: OSU_INTEROP_CONSTANTS.generalDefaults.sampleSet,
    StackLeniency: fixedDecimal(OSU_INTEROP_CONSTANTS.generalDefaults.stackLeniency),
    Mode: String(OSU_INTEROP_CONSTANTS.generalDefaults.mode),
    LetterboxInBreaks: String(OSU_INTEROP_CONSTANTS.generalDefaults.letterboxInBreaks),
    SpecialStyle: String(OSU_INTEROP_CONSTANTS.generalDefaults.specialStyle),
    WidescreenStoryboard: String(OSU_INTEROP_CONSTANTS.generalDefaults.widescreenStoryboard),
    SamplesMatchPlaybackRate: String(
      OSU_INTEROP_CONSTANTS.generalDefaults.samplesMatchPlaybackRate,
    ),
  });
  writeSection(lines, "Editor", {
    ...preservedEditor,
    DistanceSpacing: fixedDecimal(OSU_INTEROP_CONSTANTS.editorDefaults.distanceSpacing),
    BeatDivisor: String(OSU_INTEROP_CONSTANTS.editorDefaults.beatDivisor),
    GridSize: String(OSU_INTEROP_CONSTANTS.editorDefaults.gridSize),
    TimelineZoom: fixedDecimal(OSU_INTEROP_CONSTANTS.editorDefaults.timelineZoom),
  });
  writeSection(lines, "Metadata", {
    ...preservedMetadata,
    Title: beatmap.title,
    ...(titleUnicode ? { TitleUnicode: titleUnicode } : {}),
    Artist: beatmap.artist,
    ...(artistUnicode ? { ArtistUnicode: artistUnicode } : {}),
    Creator: creator,
    Version: metadataVersion,
    Source: source,
    Tags: tags,
    BeatmapID: beatmapId ?? "0",
    BeatmapSetID: beatmapSetId ?? "-1",
  });
  writeSection(lines, "Difficulty", {
    ...preservedDifficulty,
    HPDrainRate: fixedDecimal(difficultyValues.hpDrainRate),
    CircleSize: fixedDecimal(difficultyValues.circleSize),
    OverallDifficulty: fixedDecimal(difficultyValues.overallDifficulty),
    ApproachRate: fixedDecimal(difficultyValues.approachRate),
    SliderMultiplier: fixedDecimal(difficultyValues.sliderMultiplier),
    SliderTickRate: fixedDecimal(difficultyValues.sliderTickRate),
  });

  lines.push("[Events]");
  if (backgroundFilename) {
    lines.push(`0,0,"${normalizeOsuRelativePath(backgroundFilename)}",0,0`);
  }
  lines.push("");

  lines.push("[TimingPoints]");
  lines.push(
    [
      Math.round(offsetMs),
      fixedDecimal(60000 / bpm),
      OSU_INTEROP_CONSTANTS.timingDefaults.meter,
      OSU_INTEROP_CONSTANTS.timingDefaults.sampleSetId,
      OSU_INTEROP_CONSTANTS.timingDefaults.sampleIndex,
      OSU_INTEROP_CONSTANTS.timingDefaults.volume,
      OSU_INTEROP_CONSTANTS.timingDefaults.uninherited,
      OSU_INTEROP_CONSTANTS.timingDefaults.effects,
    ].join(","),
  );
  lines.push("");

  lines.push("[Colours]");
  for (const colourLine of preservedColours) {
    lines.push(colourLine);
  }
  lines.push("");

  lines.push("[HitObjects]");
  for (const object of sortedObjects) {
    const osuObject = readNestedObject(object.extraFields, ["osu"]);
    const hitsound = normalizeInteger(readNestedJsonValue(osuObject, ["hitSound"])) ?? 0;
    const newCombo = readNestedBoolean(osuObject, ["newCombo"]) ?? false;
    if (object.type === "spinner") {
      lines.push(
        [
          256,
          192,
          Math.round(object.time),
          8 | (newCombo ? 4 : 0),
          hitsound,
          Math.round(object.endTime),
        ].join(","),
      );
      continue;
    }

    const hitSample = normalizeHitSample(
      readNestedString(osuObject, ["hitSample"]) ?? "0:0:0:0:",
    );
    const typeFlags = 1 | (newCombo ? 4 : 0);
    lines.push(
      [
        Math.round(object.x),
        Math.round(object.y),
        Math.round(object.time),
        typeFlags,
        hitsound,
        hitSample,
      ].join(","),
    );
  }
  lines.push("");

  const text = lines.join("\n");
  const validation = validateOsuBeatmapText(text);
  const filename = buildOsuFilename(beatmap.artist, beatmap.title, creator, metadataVersion);
  return {
    filename,
    text,
    report: {
      sourceJsonPath: options.sourcePath ?? "(browser import)",
      outputOsuPath: options.outputPath ?? filename,
      title: beatmap.title,
      artist: beatmap.artist,
      version: metadataVersion,
      objectCount: sortedObjects.length,
      bpm: roundClamp(bpm, 1, Number.POSITIVE_INFINITY),
      offsetMs: Math.round(offsetMs),
      difficultyValues,
      warnings,
      unsupportedProjectFeatures: [],
      validation,
      filename,
      audioFilename,
    },
  };
}

export function importOsuBeatmapText(
  text: string,
  options: OsuImportOptions = {},
): { beatmap: BeatmapDocument; report: OsuImportReport } {
  const unsupportedMode = options.unsupported ?? "reject";
  const parsed = parseOsuBeatmapText(text);
  const validation = validateParsedOsuBeatmap(parsed);
  const sliderCount = parsed.unsupportedHitObjects.filter((item) => item.kind === "slider").length;
  const spinnerCount = parsed.spinners.length;
  const holdCount = parsed.unsupportedHitObjects.filter((item) => item.kind === "hold").length;
  const unsupportedCount = parsed.unsupportedHitObjects.length;
  if (unsupportedMode === "reject" && unsupportedCount > 0) {
    throw new Error(
      buildUnsupportedRejectMessage({
        sliderCount,
        spinnerCount,
        holdCount,
        unknownCount: parsed.unsupportedHitObjects.filter((item) => item.kind === "unknown").length,
      }),
    );
  }

  const audioFilename = requiredString(parsed.general.AudioFilename, "AudioFilename");
  const title = parsed.metadata.Title?.trim() || "Imported Beatmap";
  const artist = parsed.metadata.Artist?.trim() || "Unknown Artist";
  const version = parsed.metadata.Version?.trim() || "Imported";
  const approachRate =
    parseOptionalNumber(parsed.difficulty.ApproachRate) ??
    parseOptionalNumber(parsed.difficulty.OverallDifficulty) ??
    5;
  const circleSize = parseOptionalNumber(parsed.difficulty.CircleSize) ?? 4;

  // Merge circles and spinners, sort by start time, then assign sequential ids
  // so a spinner between circles never leaves ids out of time order (matching
  // the Python import path and keeping editor display ids consistent).
  const mergedImportedObjects: Array<
    | {
        type: "circle";
        x: number;
        y: number;
        time: number;
        osu: {
          hitSound: number;
          hitSample: string;
          newCombo: boolean;
          typeFlags: number;
        };
      }
    | {
        type: "spinner";
        time: number;
        endTime: number;
        osu: {
          hitSound: number;
          newCombo: boolean;
          typeFlags: number;
        };
      }
  > = [
    ...parsed.circles.map((circle) => ({
      type: "circle" as const,
      x: circle.x,
      y: circle.y,
      time: circle.time,
      osu: {
        hitSound: circle.hitSound,
        hitSample: circle.hitSample,
        newCombo: circle.newCombo,
        typeFlags: circle.typeFlags,
      },
    })),
    ...parsed.spinners.map((spinner) => ({
      type: "spinner" as const,
      time: spinner.time,
      endTime: spinner.endTime,
      osu: {
        hitSound: spinner.hitSound,
        newCombo: spinner.newCombo,
        typeFlags: spinner.typeFlags,
      },
    })),
  ].sort((left, right) => left.time - right.time);
  const objects: unknown[] = mergedImportedObjects.map((item, index) => ({
    id: index + 1,
    ...item,
  }));

  const beatmap: BeatmapDocument = parseBeatmapDocument(
    {
      title,
      artist,
      audio: toProjectAudioPath(audioFilename),
      approachTime: osuApproachRateToProjectApproachTime(approachRate),
      circleRadius: osuCircleSizeToProjectRadius(circleSize),
      osu: buildImportedOsuMetadata(parsed, options.filename, validation.warnings),
      objects,
    },
    {
      requireObjects: true,
      requireUniqueTimestamps: true,
    },
  );

  return {
    beatmap,
    report: {
      sourceOsuPath: options.filename ?? "(browser import)",
      formatVersion: parsed.formatVersion,
      sectionsFound: parsed.sectionsFound,
      metadata: {
        title,
        artist,
        version,
        creator: parsed.metadata.Creator?.trim(),
        audioFilename,
      },
      circleCount: parsed.circles.length,
      sliderCount,
      spinnerCount,
      holdCount,
      unsupportedCount,
      skippedCount: unsupportedMode === "skip" ? unsupportedCount : 0,
      timingPointCount: parsed.timingPoints.length,
      conversionWarnings: unsupportedMode === "skip" && unsupportedCount > 0
        ? [
            `Skipped ${unsupportedCount} unsupported hit object${
              unsupportedCount === 1 ? "" : "s"
            } while importing circles and spinners only.`,
            ...validation.warnings,
          ]
        : validation.warnings,
      outputJsonPath: options.outputPath,
      validation,
    },
  };
}

export function parseOsuBeatmapText(text: string): ParsedOsuBeatmap {
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  const headerLine = lines.find((line) => line.trim().length > 0);
  if (!headerLine) {
    throw new Error("The .osu file is empty.");
  }
  const headerMatch = /^osu file format v(\d+)$/i.exec(headerLine.trim());
  if (!headerMatch) {
    throw new Error("The .osu file is missing a valid format header.");
  }

  const sections: OsuSectionMap = {
    General: {},
    Editor: {},
    Metadata: {},
    Difficulty: {},
  };
  const events: string[] = [];
  const timingPoints: OsuTimingPoint[] = [];
  const colours: string[] = [];
  const circles: OsuCircleHitObject[] = [];
  const spinners: OsuSpinnerHitObject[] = [];
  const unsupportedHitObjects: OsuUnsupportedHitObject[] = [];
  const extraSections: Record<string, string[]> = {};
  const sectionsFound = new Set<string>();
  const warnings: string[] = [];
  let currentSection = "";
  let backgroundFilename: string | undefined;

  for (let index = 0; index < lines.length; index += 1) {
    const rawLine = lines[index]!;
    const trimmed = rawLine.trim();
    if (!trimmed || trimmed.startsWith("//")) {
      continue;
    }
    if (trimmed.toLowerCase().startsWith("osu file format")) {
      continue;
    }
    const sectionMatch = /^\[(.+)\]$/.exec(trimmed);
    if (sectionMatch) {
      currentSection = sectionMatch[1] ?? "";
      sectionsFound.add(currentSection);
      if (
        currentSection !== "General" &&
        currentSection !== "Editor" &&
        currentSection !== "Metadata" &&
        currentSection !== "Difficulty" &&
        currentSection !== "Events" &&
        currentSection !== "TimingPoints" &&
        currentSection !== "Colours" &&
        currentSection !== "HitObjects"
      ) {
        extraSections[currentSection] = [];
      }
      continue;
    }

    switch (currentSection) {
      case "General":
      case "Editor":
      case "Metadata":
      case "Difficulty":
        parseKeyValueLine(rawLine, sections[currentSection], currentSection, index + 1);
        break;
      case "Events":
        events.push(rawLine);
        backgroundFilename ??= parseBackgroundFilename(rawLine);
        break;
      case "TimingPoints":
        timingPoints.push(parseTimingPoint(rawLine, index + 1));
        break;
      case "Colours":
        colours.push(rawLine.trim());
        break;
      case "HitObjects": {
        const parsedObject = parseHitObject(rawLine, index + 1);
        if (parsedObject.kind === "circle") {
          circles.push(parsedObject.circle);
        } else if (parsedObject.kind === "spinner") {
          spinners.push(parsedObject.spinner);
        } else {
          unsupportedHitObjects.push(parsedObject.unsupported);
        }
        break;
      }
      default:
        if (currentSection) {
          extraSections[currentSection]?.push(rawLine);
          break;
        }
        warnings.push(`Ignored line outside a section at ${index + 1}.`);
        break;
    }
  }

  circles.sort((left, right) => {
    if (left.time !== right.time) {
      return left.time - right.time;
    }
    if (left.x !== right.x) {
      return left.x - right.x;
    }
    return left.y - right.y;
  });
  spinners.sort((left, right) => left.time - right.time);

  return {
    formatVersion: Number(headerMatch[1]),
    sectionsFound: Array.from(sectionsFound),
    general: sections.General,
    editor: sections.Editor,
    metadata: sections.Metadata,
    difficulty: sections.Difficulty,
    events,
    timingPoints,
    colours,
    circles,
    spinners,
    unsupportedHitObjects,
    extraSections,
    backgroundFilename,
    warnings,
  };
}

export function validateOsuBeatmapText(text: string): OsuValidationResult {
  return validateParsedOsuBeatmap(parseOsuBeatmapText(text));
}

export function validateParsedOsuBeatmap(parsed: ParsedOsuBeatmap): OsuValidationResult {
  const warnings = [...parsed.warnings];
  if (!Number.isInteger(parsed.formatVersion) || parsed.formatVersion <= 0) {
    warnings.push("The format header version is invalid.");
  }

  for (const requiredSection of ["General", "Metadata", "Difficulty", "TimingPoints", "HitObjects"]) {
    if (!parsed.sectionsFound.includes(requiredSection)) {
      warnings.push(`Required section [${requiredSection}] is missing.`);
    }
  }

  if (!parsed.general.AudioFilename?.trim()) {
    warnings.push("AudioFilename is required.");
  } else {
    try {
      normalizeOsuRelativePath(parsed.general.AudioFilename);
    } catch (error) {
      warnings.push(error instanceof Error ? error.message : "AudioFilename is invalid.");
    }
  }

  for (const difficultyKey of [
    "HPDrainRate",
    "CircleSize",
    "OverallDifficulty",
    "ApproachRate",
    "SliderMultiplier",
    "SliderTickRate",
  ]) {
    if (parseOptionalNumber(parsed.difficulty[difficultyKey]) === undefined) {
      warnings.push(`Difficulty field ${difficultyKey} is missing or invalid.`);
    }
  }

  if (parsed.timingPoints.length === 0) {
    warnings.push("At least one timing point is required.");
  }

  for (const circle of parsed.circles) {
    if (circle.x < 0 || circle.x > 512 || circle.y < 0 || circle.y > 384) {
      warnings.push(`Circle at ${circle.time}ms is out of bounds.`);
    }
    if (circle.time < 0) {
      warnings.push("Hit object times must be non-negative.");
    }
  }

  for (const spinner of parsed.spinners) {
    if (spinner.time < 0 || spinner.endTime < 0) {
      warnings.push("Spinner times must be non-negative.");
    }
    if (spinner.endTime <= spinner.time) {
      warnings.push(`Spinner at ${spinner.time}ms must end after it starts.`);
    }
  }

  // Ordering and duplicate detection must interleave circles and spinners so a
  // spinner between two circles never triggers a spurious "not sorted" warning.
  const mergedHitObjects = [
    ...parsed.circles.map((circle) => ({ time: circle.time, rawLine: circle.rawLine })),
    ...parsed.spinners.map((spinner) => ({ time: spinner.time, rawLine: spinner.rawLine })),
  ].sort((left, right) => left.time - right.time);
  const seenLines = new Set<string>();
  let previousTime = -1;
  for (const hitObject of mergedHitObjects) {
    if (hitObject.time < previousTime) {
      warnings.push("Hit objects are not sorted by time.");
    }
    previousTime = hitObject.time;
    if (seenLines.has(hitObject.rawLine)) {
      warnings.push(`Duplicate hit object line detected at ${hitObject.time}ms.`);
    }
    seenLines.add(hitObject.rawLine);
  }

  const unsupportedCounts = countUnsupportedKinds(parsed.unsupportedHitObjects);
  return {
    valid: warnings.length === 0,
    warnings,
    unsupportedCounts,
  };
}

const WINDOWS_RESERVED_FILENAME_STEMS = new Set([
  "con", "prn", "aux", "nul",
  ...Array.from({ length: 9 }, (_value, index) => `com${index + 1}`),
  ...Array.from({ length: 9 }, (_value, index) => `lpt${index + 1}`),
]);

const OSZ_FILENAME_MAX_LENGTH = 200;

/**
 * Shared filename sanitizer mirroring `tools/text_utils.py` so the browser and
 * Python exporters produce identical, filesystem-safe names:
 * NFC-normalize, replace forbidden characters, trim dots/spaces, escape
 * Windows reserved device names, and bound the length.
 */
export function sanitizeFilenameComponent(
  value: string,
  fallback = "untitled",
): string {
  const normalized = (value ?? "").normalize("NFC");
  const cleaned = Array.from(normalized.trim())
    .map((character) =>
      '<>:"/\\|?*'.includes(character) || character.codePointAt(0)! < 32
        ? " "
        : character,
    )
    .join("");
  let compact = cleaned.split(/\s+/).filter(Boolean).join(" ").replace(/^[. ]+|[. ]+$/g, "");
  if (!compact) {
    return fallback;
  }
  const stem = compact.split(".")[0].trim().toLowerCase();
  if (WINDOWS_RESERVED_FILENAME_STEMS.has(stem)) {
    compact = `_${compact}`;
  }
  return compact;
}

export function buildOsuFilename(
  artist: string,
  title: string,
  creator: string,
  versionName: string,
): string {
  const parts = [artist, title, creator, versionName].map((value) =>
    sanitizeFilenameComponent(value, "Unknown"),
  );
  const extension = ".osu";
  let stem = `${parts[0]} - ${parts[1]} (${parts[2]}) [${parts[3]}]`;
  if (stem.length + extension.length > OSZ_FILENAME_MAX_LENGTH) {
    stem = stem
      .slice(0, OSZ_FILENAME_MAX_LENGTH - extension.length)
      .replace(/[\s\-(\[\]]+$/g, "")
      .replace(/^[. ]+|[. ]+$/g, "");
    if (!stem) {
      stem = "map";
    }
  }
  return `${stem}${extension}`;
}

export function convertProjectDifficultyToOsuValues(
  beatmap: BeatmapDocument,
  difficultyName: SupportedProjectDifficulty | undefined,
): OsuDifficultyValues {
  const fallbackPreset =
    difficultyName && difficultyName in OSU_INTEROP_CONSTANTS.difficultyPresets
      ? OSU_INTEROP_CONSTANTS.difficultyPresets[difficultyName]
      : OSU_INTEROP_CONSTANTS.difficultyPresets.normal;
  return {
    hpDrainRate: fallbackPreset.hpDrainRate,
    circleSize: projectRadiusToOsuCircleSize(beatmap.circleRadius),
    overallDifficulty: fallbackPreset.overallDifficulty,
    approachRate: projectApproachTimeToOsuApproachRate(beatmap.approachTime),
    sliderMultiplier: OSU_INTEROP_CONSTANTS.difficultyDefaults.sliderMultiplier,
    sliderTickRate: OSU_INTEROP_CONSTANTS.difficultyDefaults.sliderTickRate,
  };
}

function deriveVersionName(
  beatmap: BeatmapDocument,
  difficultyName: SupportedProjectDifficulty | undefined,
): string | undefined {
  const osuVersion = readNestedString(beatmap.extraFields, ["osu", "beatmapVersion"]);
  if (osuVersion) {
    return osuVersion;
  }
  const editorSourceType = readNestedString(beatmap.extraFields, ["editor", "sourceType"]);
  const hasHybridMetadata = readNestedObject(beatmap.extraFields, ["hybrid"]) !== undefined;
  if ((editorSourceType === "hybrid" || hasHybridMetadata) && difficultyName) {
    return `Hybrid ${capitalize(difficultyName)}`;
  }
  if (editorSourceType === "imported") {
    return "Imported";
  }
  if (editorSourceType === "champion" && difficultyName) {
    return capitalize(difficultyName);
  }
  if (difficultyName) {
    return capitalize(difficultyName);
  }
  return undefined;
}

function validateProjectObjectsForOsuExport(
  objects: BeatmapDocumentObject[],
): asserts objects is (BeatmapDocumentCircleObject | BeatmapDocumentObject & { type: "spinner" })[] {
  const seenIds = new Set<number>();
  let previousTime = -1;
  for (const object of objects) {
    if (object.type !== "circle" && object.type !== "spinner") {
      throw new Error(`Unsupported project object type "${object.type}" cannot be exported to .osu.`);
    }
    if (!Number.isInteger(object.id) || seenIds.has(object.id)) {
      throw new Error("Every exported hit object must keep a unique integer id.");
    }
    if (!Number.isFinite(object.time) || !Number.isInteger(object.time)) {
      throw new Error(`Hit object ${object.id} must use a non-negative integer time.`);
    }
    if (object.time <= previousTime) {
      throw new Error("Exported .osu hit objects must be strictly increasing in time.");
    }
    previousTime = object.time;
    seenIds.add(object.id);

    if (object.type === "circle") {
      if (!Number.isFinite(object.x) || !Number.isFinite(object.y)) {
        throw new Error(`Hit object ${object.id} contains a non-finite value.`);
      }
      if (object.x < 0 || object.x > 512 || object.y < 0 || object.y > 384) {
        throw new Error(`Hit object ${object.id} is outside the 512x384 playfield.`);
      }
    } else {
      if (
        !Number.isFinite(object.endTime) ||
        !Number.isInteger(object.endTime) ||
        object.endTime <= object.time
      ) {
        throw new Error(`Hit object ${object.id} spinner endTime must be a greater integer time.`);
      }
    }
  }
}

function buildImportedOsuMetadata(
  parsed: ParsedOsuBeatmap,
  filename: string | undefined,
  warnings: string[],
): JsonObject {
  return {
    formatVersion: parsed.formatVersion,
    sourceFilename: filename ?? null,
    creator: parsed.metadata.Creator ?? null,
    beatmapVersion: parsed.metadata.Version ?? null,
    source: parsed.metadata.Source ?? null,
    tags: parsed.metadata.Tags ?? null,
    titleUnicode: parsed.metadata.TitleUnicode ?? null,
    artistUnicode: parsed.metadata.ArtistUnicode ?? null,
    beatmapId: parsed.metadata.BeatmapID ?? null,
    beatmapSetId: parsed.metadata.BeatmapSetID ?? null,
    audioFilename: parsed.general.AudioFilename ?? null,
    backgroundFilename: parsed.backgroundFilename ?? null,
    general: sanitizeJsonRecord(parsed.general),
    editor: sanitizeJsonRecord(parsed.editor),
    metadata: sanitizeJsonRecord(parsed.metadata),
    difficulty: sanitizeJsonRecord(parsed.difficulty),
    colours: parsed.colours,
    events: parsed.events,
    importWarnings: warnings,
  };
}

function parseKeyValueLine(
  rawLine: string,
  output: Record<string, string>,
  sectionName: string,
  lineNumber: number,
): void {
  const separatorIndex = rawLine.indexOf(":");
  if (separatorIndex < 0) {
    throw new Error(`[${sectionName}] line ${lineNumber} is missing a key/value separator.`);
  }
  const key = rawLine.slice(0, separatorIndex).trim();
  const value = rawLine.slice(separatorIndex + 1).trim();
  if (!key) {
    throw new Error(`[${sectionName}] line ${lineNumber} is missing a key.`);
  }
  output[key] = value;
}

function parseTimingPoint(rawLine: string, lineNumber: number): OsuTimingPoint {
  const fields = rawLine.split(",").map((value) => value.trim());
  if (fields.length < 8) {
    throw new Error(`[TimingPoints] line ${lineNumber} is incomplete.`);
  }
  return {
    time: parseRequiredNumber(fields[0], `[TimingPoints] line ${lineNumber} time`),
    beatLength: parseRequiredNumber(fields[1], `[TimingPoints] line ${lineNumber} beatLength`),
    meter: parseRequiredInteger(fields[2], `[TimingPoints] line ${lineNumber} meter`),
    sampleSet: parseRequiredInteger(fields[3], `[TimingPoints] line ${lineNumber} sampleSet`),
    sampleIndex: parseRequiredInteger(fields[4], `[TimingPoints] line ${lineNumber} sampleIndex`),
    volume: parseRequiredInteger(fields[5], `[TimingPoints] line ${lineNumber} volume`),
    uninherited: parseRequiredInteger(fields[6], `[TimingPoints] line ${lineNumber} uninherited`),
    effects: parseRequiredInteger(fields[7], `[TimingPoints] line ${lineNumber} effects`),
  };
}

function parseHitObject(
  rawLine: string,
  lineNumber: number,
):
  | { kind: "circle"; circle: OsuCircleHitObject }
  | { kind: "spinner"; spinner: OsuSpinnerHitObject }
  | { kind: "unsupported"; unsupported: OsuUnsupportedHitObject } {
  const fields = rawLine.split(",").map((value) => value.trim());
  if (fields.length < 5) {
    throw new Error(`[HitObjects] line ${lineNumber} is incomplete.`);
  }
  const x = parseRequiredInteger(fields[0], `[HitObjects] line ${lineNumber} x`);
  const y = parseRequiredInteger(fields[1], `[HitObjects] line ${lineNumber} y`);
  const time = parseRequiredInteger(fields[2], `[HitObjects] line ${lineNumber} time`);
  const typeFlags = parseRequiredInteger(fields[3], `[HitObjects] line ${lineNumber} type`);
  const hitSound = parseRequiredInteger(fields[4], `[HitObjects] line ${lineNumber} hitSound`);

  const isCircle = (typeFlags & 1) !== 0;
  const isSlider = (typeFlags & 2) !== 0;
  const isSpinner = (typeFlags & 8) !== 0;
  const isHold = (typeFlags & 128) !== 0;
  if (isCircle && !isSlider && !isSpinner && !isHold) {
    return {
      kind: "circle",
      circle: {
        x,
        y,
        time,
        typeFlags,
        hitSound,
        hitSample: normalizeHitSample(fields.slice(5).join(",") || "0:0:0:0:"),
        newCombo: (typeFlags & 4) !== 0,
        rawLine,
      },
    };
  }

  if (isSpinner && !isCircle && !isSlider && !isHold) {
    if (fields.length < 6) {
      throw new Error(
        `[HitObjects] line ${lineNumber} is incomplete (spinner end time missing).`,
      );
    }
    const endTime = parseRequiredInteger(
      fields[5],
      `[HitObjects] line ${lineNumber} endTime`,
    );
    return {
      kind: "spinner",
      spinner: {
        time,
        endTime,
        typeFlags,
        hitSound,
        newCombo: (typeFlags & 4) !== 0,
        rawLine,
      },
    };
  }

  return {
    kind: "unsupported",
    unsupported: {
      kind: isSlider ? "slider" : isHold ? "hold" : "unknown",
      lineIndex: lineNumber,
      line: rawLine,
      time,
      typeFlags,
    },
  };
}

function parseBackgroundFilename(rawLine: string): string | undefined {
  const fields = rawLine.split(",").map((value) => value.trim());
  if (fields.length < 3 || fields[0] !== "0") {
    return undefined;
  }
  const rawFilename = fields[2]?.replace(/^"+|"+$/g, "");
  return rawFilename ? normalizeOsuRelativePath(rawFilename) : undefined;
}

function writeSection(lines: string[], name: string, values: Record<string, string>): void {
  lines.push(`[${name}]`);
  for (const [key, value] of Object.entries(values)) {
    lines.push(`${key}: ${value}`);
  }
  lines.push("");
}

function sanitizeKeyValueSection(value: JsonObject | undefined): Record<string, string> {
  if (!value) {
    return {};
  }
  const output: Record<string, string> = {};
  for (const [key, item] of Object.entries(value)) {
    const normalized = normalizeOptionalText(item);
    if (normalized !== undefined) {
      output[key] = normalized;
    }
  }
  return output;
}

function sanitizeJsonRecord(record: Record<string, string>): JsonObject {
  const output: JsonObject = {};
  for (const [key, value] of Object.entries(record)) {
    output[key] = value;
  }
  return output;
}

function sanitizeStringArray(value: JsonValue | undefined): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) => (typeof item === "string" ? item.trim() : ""))
    .filter((item) => item.length > 0);
}

function normalizeHitSample(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) {
    return "0:0:0:0:";
  }
  const parts = trimmed.split(":");
  while (parts.length < 5) {
    parts.push("");
  }
  return parts.slice(0, 5).join(":");
}

function countUnsupportedKinds(
  items: OsuUnsupportedHitObject[],
): Record<UnsupportedOsuObjectKind, number> {
  return items.reduce<Record<UnsupportedOsuObjectKind, number>>(
    (accumulator, item) => {
      accumulator[item.kind] += 1;
      return accumulator;
    },
    { slider: 0, spinner: 0, hold: 0, unknown: 0 },
  );
}

export function toOsuSpinnerLine(spinner: OsuSpinnerHitObject): string {
  return [256, 192, spinner.time, spinner.typeFlags, spinner.hitSound, spinner.endTime].join(",");
}

function buildUnsupportedRejectMessage(counts: {
  sliderCount: number;
  spinnerCount: number;
  holdCount: number;
  unknownCount: number;
}): string {
  const fragments = [
    counts.sliderCount > 0 ? `${counts.sliderCount} slider${counts.sliderCount === 1 ? "" : "s"}` : "",
    counts.spinnerCount > 0 ? `${counts.spinnerCount} spinner${counts.spinnerCount === 1 ? "" : "s"}` : "",
    counts.holdCount > 0 ? `${counts.holdCount} hold object${counts.holdCount === 1 ? "" : "s"}` : "",
    counts.unknownCount > 0 ? `${counts.unknownCount} unknown object${counts.unknownCount === 1 ? "" : "s"}` : "",
  ].filter(Boolean);
  return `Unsupported hit object types were found: ${fragments.join(", ")}. Re-run with skip mode to import circles only.`;
}

function normalizeDifficultyName(value: string | undefined): SupportedProjectDifficulty | undefined {
  if (!value) {
    return undefined;
  }
  const normalized = value.trim().toLowerCase();
  if (normalized.includes("easy")) {
    return "easy";
  }
  if (normalized.includes("hard")) {
    return "hard";
  }
  if (normalized.includes("normal")) {
    return "normal";
  }
  return undefined;
}

function requiredString(value: string | undefined, label: string): string {
  if (!value?.trim()) {
    throw new Error(`${label} is required.`);
  }
  return value.trim();
}

function parseRequiredNumber(value: string | undefined, label: string): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) {
    throw new Error(`${label} must be numeric.`);
  }
  return parsed;
}

function parseRequiredInteger(value: string | undefined, label: string): number {
  const parsed = parseRequiredNumber(value, label);
  if (!Number.isInteger(parsed)) {
    throw new Error(`${label} must be an integer.`);
  }
  return parsed;
}

function parseOptionalNumber(value: string | undefined): number | undefined {
  if (value === undefined) {
    return undefined;
  }
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function readNestedObject(
  value: JsonObject | undefined,
  path: string[],
): JsonObject | undefined {
  let current: JsonValue | undefined = value;
  for (const key of path) {
    if (!isJsonObject(current)) {
      return undefined;
    }
    current = current[key];
  }
  return isJsonObject(current) ? current : undefined;
}

function readNestedString(
  value: JsonObject | undefined,
  path: string[],
): string | undefined {
  const item = readNestedJsonValue(value, path);
  return typeof item === "string" && item.trim().length > 0 ? item.trim() : undefined;
}

function readNestedBoolean(
  value: JsonObject | undefined,
  path: string[],
): boolean | undefined {
  const item = readNestedJsonValue(value, path);
  return typeof item === "boolean" ? item : undefined;
}

function readNestedJsonValue(
  value: JsonObject | undefined,
  path: string[],
): JsonValue | undefined {
  let current: JsonValue | undefined = value;
  for (const key of path) {
    if (!isJsonObject(current)) {
      return undefined;
    }
    current = current[key];
  }
  return current;
}

function normalizeOptionalText(value: JsonValue | string | number | undefined): string | undefined {
  if (typeof value === "string") {
    const trimmed = value.trim();
    return trimmed.length > 0 ? trimmed : undefined;
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    return String(value);
  }
  return undefined;
}

function normalizeInteger(value: JsonValue | undefined): number | undefined {
  return typeof value === "number" && Number.isInteger(value) ? value : undefined;
}

function fixedDecimal(value: number): string {
  const rounded = Math.round(value * 100) / 100;
  return Number.isInteger(rounded) ? `${rounded.toFixed(0)}` : `${rounded}`;
}

function roundClamp(value: number, minimum: number, maximum: number): number {
  return Math.round(clamp(value, minimum, maximum) * 100) / 100;
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.max(minimum, Math.min(maximum, value));
}

function ensureFinite(value: number, label: string): void {
  if (!Number.isFinite(value)) {
    throw new Error(`${label} must be finite.`);
  }
}

function capitalize(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function firstDefinedString(...values: Array<string | undefined>): string | undefined {
  return values.find((value) => typeof value === "string" && value.trim().length > 0);
}

export function cloneImportedBeatmapForRoundTrip(beatmap: BeatmapDocument): BeatmapDocument {
  return parseBeatmapDocument(serializeBeatmapDocument(beatmap));
}
