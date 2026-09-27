import type {
  ValidationIssueCategory,
  ValidationSeverity,
} from "../../game/types";

export interface EditorObjectMetrics {
  previousGapMs?: number;
  nextGapMs?: number;
  previousDistancePx?: number;
  nextDistancePx?: number;
  previousCursorSpeed?: number;
  nextCursorSpeed?: number;
  nearestBeatTimeMs?: number;
  nearestBeatDeltaMs?: number;
  nearestBeatStrength?: number;
  nearestOnsetTimeMs?: number;
  nearestOnsetDeltaMs?: number;
  nearestOnsetStrength?: number;
  localEnergy?: number;
  selectedAnchor?: "beat" | "onset" | "none";
  timingConfidence?: "low" | "medium" | "high";
}

export interface EditorValidationIssue {
  id: string;
  severity: ValidationSeverity;
  category: ValidationIssueCategory;
  code: string;
  message: string;
  objectId?: string;
  timeMs?: number;
  measuredValue?: number;
  allowedValue?: number;
}

export interface EditorValidationSummary {
  critical: number;
  errors: number;
  warnings: number;
  info: number;
  total: number;
}

export interface EditorLiveValidation {
  issues: EditorValidationIssue[];
  issuesByObjectId: Record<string, EditorValidationIssue[]>;
  summary: EditorValidationSummary;
  metricsByObjectId: Record<string, EditorObjectMetrics>;
}
