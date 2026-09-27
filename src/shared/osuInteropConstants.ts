import rawConstants from "./osuInteropConstants.json";

export interface OsuInteropConstants {
  version: number;
  fileFormatVersion: number;
  creatorDefault: string;
  generalDefaults: {
    audioLeadIn: number;
    previewTime: number;
    countdown: number;
    sampleSet: string;
    stackLeniency: number;
    mode: number;
    letterboxInBreaks: number;
    specialStyle: number;
    widescreenStoryboard: number;
    samplesMatchPlaybackRate: number;
  };
  editorDefaults: {
    distanceSpacing: number;
    beatDivisor: number;
    gridSize: number;
    timelineZoom: number;
  };
  timingDefaults: {
    meter: number;
    sampleSetId: number;
    sampleIndex: number;
    volume: number;
    uninherited: number;
    effects: number;
  };
  difficultyDefaults: {
    sliderMultiplier: number;
    sliderTickRate: number;
  };
  circleSizeFormula: {
    radiusBase: number;
    radiusStep: number;
    minimum: number;
    maximum: number;
  };
  approachRateFormula: {
    minimum: number;
    maximum: number;
    slowReferenceMs: number;
    slowPivotMs: number;
    slowStepMsPerAr: number;
    fastPivotMs: number;
    fastStepMsPerAr: number;
  };
  difficultyPresets: Record<
    "easy" | "normal" | "hard",
    {
      hpDrainRate: number;
      overallDifficulty: number;
    }
  >;
  deterministicArchive: {
    year: number;
    month: number;
    day: number;
    hour: number;
    minute: number;
    second: number;
  };
}

export const OSU_INTEROP_CONSTANTS: OsuInteropConstants =
  rawConstants as OsuInteropConstants;
