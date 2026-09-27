import Phaser from "phaser";

import { PLAYFIELD_HEIGHT, PLAYFIELD_WIDTH } from "../../game/types";
import { clamp } from "../../shared/format";
import type { EditorController } from "../EditorController";
import type { EditorStore } from "../EditorStore";
import type { EditorRootState } from "../EditorState";
import type { CandidateVisualDiffItem } from "../candidates/candidateModels";
import type { EditorHitObject } from "../models/EditorModels";
import { drawBaselineGhost } from "./BaselineOverlay";
import { pointerToLogical } from "./CoordinateMapper";
import { drawHitCircle } from "./EditableHitCircle";
import { drawSelectionOverlay } from "./SelectionOverlay";
import { drawSpinnerObject } from "./EditableSpinner";

const LABEL_LIMIT = 180;

export class EditorScene extends Phaser.Scene {
  private controller?: EditorController;
  private unsubscribe?: () => void;
  private state?: EditorRootState;
  private safetyGraphics?: Phaser.GameObjects.Graphics;
  private pathGraphics?: Phaser.GameObjects.Graphics;
  private baselineGraphics?: Phaser.GameObjects.Graphics;
  private objectGraphics?: Phaser.GameObjects.Graphics;
  private overlayGraphics?: Phaser.GameObjects.Graphics;
  private diffGraphics?: Phaser.GameObjects.Graphics;
  private labelPool: Phaser.GameObjects.Text[] = [];
  private draggingObjectId?: string;
  private hoveredObjectId?: string;
  private dirty = true;
  private lastRenderedPlayheadMs = -1;

  constructor() {
    super("EditorScene");
  }

  bind(store: EditorStore, controller: EditorController): void {
    this.controller = controller;
    this.unsubscribe?.();
    this.unsubscribe = store.subscribe((state) => {
      this.state = state;
      this.dirty = true;
    });
  }

  create(): void {
    this.cameras.main.setBackgroundColor("#07101b");
    this.safetyGraphics = this.add.graphics();
    this.pathGraphics = this.add.graphics();
    this.baselineGraphics = this.add.graphics();
    this.objectGraphics = this.add.graphics();
    this.overlayGraphics = this.add.graphics();
    this.diffGraphics = this.add.graphics();

    this.input.on("pointerdown", (pointer: Phaser.Input.Pointer) => {
      const controller = this.controller;
      const state = this.state;
      if (!controller || !state?.session.workingMap) {
        return;
      }

      if (isComparisonReadOnly(state)) {
        return;
      }

      const point = pointerToLogical(pointer, this.scale);
      const picked = pickObjectAtPoint(
        state.session.workingMap.objects,
        point.x,
        point.y,
        state.session.playheadMs,
        state.session.workingMap.circleRadius,
      );

      if (state.ui.mode === "add-circle") {
        controller.addCircleAtPlayhead(point.x, point.y);
        return;
      }

      if (!picked) {
        controller.clearSelection();
        return;
      }

      controller.selectObject(picked.editorId);
      controller.beginObjectDrag(picked.editorId);
      this.draggingObjectId = picked.editorId;
    });

    this.input.on("pointermove", (pointer: Phaser.Input.Pointer) => {
      const controller = this.controller;
      const state = this.state;
      if (!controller || !state?.session.workingMap) {
        return;
      }

      if (isComparisonReadOnly(state)) {
        return;
      }

      const point = pointerToLogical(pointer, this.scale);
      if (this.draggingObjectId) {
        controller.updateDraggedObjectPosition(this.draggingObjectId, point.x, point.y);
        return;
      }

      const picked = pickObjectAtPoint(
        state.session.workingMap.objects,
        point.x,
        point.y,
        state.session.playheadMs,
        state.session.workingMap.circleRadius,
      );
      const nextHovered = picked?.editorId;
      if (nextHovered !== this.hoveredObjectId) {
        this.hoveredObjectId = nextHovered;
        this.dirty = true;
      }
    });

    this.input.on("pointerup", () => {
      if (!this.draggingObjectId) {
        return;
      }

      this.controller?.commitDraggedObject();
      this.draggingObjectId = undefined;
    });

    this.input.on("pointerupoutside", () => {
      if (!this.draggingObjectId) {
        return;
      }

      this.controller?.commitDraggedObject();
      this.draggingObjectId = undefined;
    });
  }

  update(): void {
    const playheadMs = this.state?.session.playheadMs ?? -1;
    if (!this.dirty && playheadMs === this.lastRenderedPlayheadMs) {
      return;
    }

    this.lastRenderedPlayheadMs = playheadMs;
    this.redraw();
    this.dirty = false;
  }

  shutdown(): void {
    this.unsubscribe?.();
  }

  private redraw(): void {
    const state = this.state;
    if (
      !state ||
      !this.safetyGraphics ||
      !this.pathGraphics ||
      !this.baselineGraphics ||
      !this.objectGraphics ||
      !this.overlayGraphics
    ) {
      return;
    }

    const workingMap = state.session.workingMap;
    const baselineMap = state.session.baselineMap;
    this.safetyGraphics.clear();
    this.pathGraphics.clear();
    this.baselineGraphics.clear();
    this.objectGraphics.clear();
    this.overlayGraphics.clear();
    this.diffGraphics?.clear();
    this.hideUnusedLabels(0);

    this.drawPlayfieldBounds(state);

    if (!workingMap) {
      return;
    }

    this.drawPathConnections(workingMap.objects);
    this.drawBaseline(workingMap, baselineMap, state);
    this.drawObjects(workingMap, state);
    this.drawComparisonDiff(state);
  }

  private drawComparisonDiff(state: EditorRootState): void {
    const comparison = state.candidates.comparison;
    const diffGraphics = this.diffGraphics;
    if (
      !diffGraphics ||
      !state.candidates.diffModeEnabled ||
      !state.candidates.comparisonEnabled ||
      comparison.state !== "ready" ||
      !comparison.visualDiff
    ) {
      return;
    }

    for (const item of comparison.visualDiff.items) {
      drawDiffItem(diffGraphics, item, state.session.workingMap?.circleRadius ?? 40);
    }
  }

  private drawPlayfieldBounds(state: EditorRootState): void {
    const workingMap = state.session.workingMap;
    const radius = workingMap?.circleRadius ?? 40;
    const legalMin = radius;
    const legalWidth = PLAYFIELD_WIDTH - radius * 2;
    const legalHeight = PLAYFIELD_HEIGHT - radius * 2;

    this.safetyGraphics?.fillStyle(0x06111d, 1);
    this.safetyGraphics?.fillRect(0, 0, PLAYFIELD_WIDTH, PLAYFIELD_HEIGHT);
    this.safetyGraphics?.lineStyle(2, 0x263448, 1);
    this.safetyGraphics?.strokeRect(0, 0, PLAYFIELD_WIDTH, PLAYFIELD_HEIGHT);
    this.safetyGraphics?.fillStyle(0xeab308, 0.05);
    this.safetyGraphics?.fillRect(0, 0, PLAYFIELD_WIDTH, legalMin);
    this.safetyGraphics?.fillRect(0, PLAYFIELD_HEIGHT - legalMin, PLAYFIELD_WIDTH, legalMin);
    this.safetyGraphics?.fillRect(0, legalMin, legalMin, legalHeight);
    this.safetyGraphics?.fillRect(PLAYFIELD_WIDTH - legalMin, legalMin, legalMin, legalHeight);
    this.safetyGraphics?.lineStyle(1, 0xa78bfa, 0.35);
    this.safetyGraphics?.strokeRect(legalMin, legalMin, legalWidth, legalHeight);
  }

  private drawPathConnections(objects: EditorHitObject[]): void {
    if (objects.length < 2 || !this.pathGraphics) {
      return;
    }

    this.pathGraphics.lineStyle(1, 0x7c8aa3, 0.24);
    for (let index = 1; index < objects.length; index += 1) {
      const previous = objects[index - 1];
      const current = objects[index];
      if (
        typeof previous.x !== "number" ||
        typeof previous.y !== "number" ||
        typeof current.x !== "number" ||
        typeof current.y !== "number"
      ) {
        continue;
      }
      this.pathGraphics.lineBetween(previous.x, previous.y, current.x, current.y);
    }
  }

  private drawBaseline(
    workingMap: NonNullable<EditorRootState["session"]["workingMap"]>,
    baselineMap: EditorRootState["session"]["baselineMap"],
    state: EditorRootState,
  ): void {
    if (!state.ui.baselineOverlayEnabled || !baselineMap || !this.baselineGraphics) {
      return;
    }

    const baselineById = new Map(
      baselineMap.objects.map((object) => [object.editorId, object]),
    );

    for (const object of workingMap.objects) {
      const baseline = baselineById.get(object.editorId);
      if (!baseline) {
        continue;
      }
      if (
        typeof object.x !== "number" ||
        typeof object.y !== "number" ||
        typeof baseline.x !== "number" ||
        typeof baseline.y !== "number"
      ) {
        continue;
      }

      const isChanged =
        baseline.x !== object.x ||
        baseline.y !== object.y ||
        baseline.time !== object.time;

      drawBaselineGhost(this.baselineGraphics, {
        baselineX: baseline.x,
        baselineY: baseline.y,
        currentX: object.x,
        currentY: object.y,
        radius: workingMap.circleRadius,
        isChanged,
      });
    }
  }

  private drawObjects(
    workingMap: NonNullable<EditorRootState["session"]["workingMap"]>,
    state: EditorRootState,
  ): void {
    if (!this.objectGraphics || !this.overlayGraphics) {
      return;
    }

    const objectGraphics = this.objectGraphics;
    const overlayGraphics = this.overlayGraphics;
    const playheadMs = state.session.playheadMs;
    const selectedId = state.ui.selectedObjectId;
    const objectsToLabel =
      workingMap.objects.length <= LABEL_LIMIT
        ? workingMap.objects
        : workingMap.objects.filter(
            (object) =>
              object.editorId === selectedId ||
              Math.abs(object.time - playheadMs) < workingMap.approachTime * 1.15,
          );

    this.syncLabelPool(objectsToLabel.length);

    workingMap.objects.forEach((object, index) => {
      const isSelected = object.editorId === selectedId;
      const isHovered = object.editorId === this.hoveredObjectId;
      const isActive = object.time >= playheadMs && object.time - playheadMs <= workingMap.approachTime;

      if (object.type === "spinner") {
        drawSpinnerObject(objectGraphics, overlayGraphics, {
          x: PLAYFIELD_WIDTH / 2,
          y: PLAYFIELD_HEIGHT / 2,
          radius: 48,
          isSelected,
          isHovered,
        });
        if (isSelected) {
          drawSelectionOverlay(overlayGraphics, PLAYFIELD_WIDTH / 2, PLAYFIELD_HEIGHT / 2, 54);
        }
        const label = objectsToLabel.findIndex((item) => item.editorId === object.editorId);
        if (label !== -1) {
          const text = this.labelPool[label];
          if (text) {
            text.setVisible(true);
            text.setText("S");
            text.setPosition(PLAYFIELD_WIDTH / 2, PLAYFIELD_HEIGHT / 2 - 1);
            text.setStyle({ color: isSelected ? "#f8fbff" : "#c9b8ff" });
          }
        }
        return;
      }

      if (typeof object.x !== "number" || typeof object.y !== "number") {
        return;
      }
      const fillColor = isSelected
        ? 0x5731ad
        : isHovered
          ? 0x38508f
          : 0x121e35;
      const strokeColor = isActive ? 0xf7fafc : 0xd6d9e2;
      const alpha = isActive ? 0.95 : 0.82;

      drawHitCircle(objectGraphics, {
        x: object.x,
        y: object.y,
        radius: workingMap.circleRadius,
        fillColor,
        fillAlpha: alpha,
        strokeColor,
        strokeWidth: 2,
      });

      if (isActive) {
        const progress = clamp((object.time - playheadMs) / workingMap.approachTime, 0, 1);
        overlayGraphics.lineStyle(2, 0xa855f7, 0.75);
        overlayGraphics.strokeCircle(
          object.x,
          object.y,
          workingMap.circleRadius + 12 + progress * 32,
        );
      }

      if (isSelected) {
        drawSelectionOverlay(overlayGraphics, object.x, object.y, workingMap.circleRadius);
      }

      const label = objectsToLabel.findIndex((item) => item.editorId === object.editorId);
      if (label !== -1) {
        const text = this.labelPool[label];
        if (!text) {
          return;
        }
        text.setVisible(true);
        text.setText(String(index + 1));
        text.setPosition(object.x, object.y - 1);
        text.setStyle({
          color: isSelected ? "#f8fbff" : "#eef3ff",
        });
      }
    });
  }

  private syncLabelPool(requiredCount: number): void {
    while (this.labelPool.length < requiredCount) {
      const label = this.add.text(0, 0, "", {
        color: "#eef3ff",
        fontFamily: "Bahnschrift, 'Segoe UI', sans-serif",
        fontSize: "20px",
        fontStyle: "700",
        stroke: "#050913",
        strokeThickness: 4,
      });
      label.setOrigin(0.5);
      this.labelPool.push(label);
    }
  }

  private hideUnusedLabels(usedCount: number): void {
    for (let index = usedCount; index < this.labelPool.length; index += 1) {
      this.labelPool[index].setVisible(false);
    }
  }
}

function pickObjectAtPoint(
  objects: EditorHitObject[],
  x: number,
  y: number,
  playheadMs: number,
  radius: number,
): EditorHitObject | undefined {
  const candidates = objects.filter((object) => {
    if (object.type === "spinner") {
      return (
        Phaser.Math.Distance.Between(
          PLAYFIELD_WIDTH / 2,
          PLAYFIELD_HEIGHT / 2,
          x,
          y,
        ) <= 54
      );
    }
    return (
      typeof object.x === "number" &&
      typeof object.y === "number" &&
      Phaser.Math.Distance.Between(object.x, object.y, x, y) <= radius + 8
    );
  });

  if (candidates.length === 0) {
    return undefined;
  }

  candidates.sort((left, right) => {
    const leftDelta = Math.abs(left.time - playheadMs);
    const rightDelta = Math.abs(right.time - playheadMs);
    if (leftDelta !== rightDelta) {
      return leftDelta - rightDelta;
    }

    return left.time - right.time;
  });

  return candidates[0];
}

function isComparisonReadOnly(state: EditorRootState): boolean {
  return (
    state.candidates.comparisonEnabled &&
    state.candidates.comparison.state === "ready"
  );
}

function drawDiffItem(
  graphics: Phaser.GameObjects.Graphics,
  item: CandidateVisualDiffItem,
  radius: number,
): void {
  const smallRadius = Math.max(5, Math.round(radius * 0.42));

  switch (item.kind) {
    case "shared": {
      if (item.aX !== undefined && item.aY !== undefined) {
        graphics.fillStyle(0x6ee7b7, 0.5);
        graphics.fillCircle(item.aX, item.aY, 3);
      }
      break;
    }
    case "a-only": {
      if (item.aX !== undefined && item.aY !== undefined) {
        graphics.lineStyle(2, 0xa78bfa, 0.75);
        graphics.strokeCircle(item.aX, item.aY, smallRadius);
      }
      break;
    }
    case "b-only": {
      if (item.bX !== undefined && item.bY !== undefined) {
        drawDiamond(graphics, item.bX, item.bY, smallRadius, 0x22d3ee, 0.85);
      }
      break;
    }
    case "moved":
    case "retimed":
    case "moved-retimed": {
      if (item.aX !== undefined && item.aY !== undefined) {
        graphics.lineStyle(1, 0xa78bfa, 0.45);
        graphics.strokeCircle(item.aX, item.aY, smallRadius);
      }
      if (item.bX !== undefined && item.bY !== undefined) {
        drawDiamond(graphics, item.bX, item.bY, smallRadius, 0x22d3ee, 0.85);
      }
      if (
        item.aX !== undefined &&
        item.aY !== undefined &&
        item.bX !== undefined &&
        item.bY !== undefined
      ) {
        graphics.lineStyle(1, 0xf59e0b, 0.6);
        graphics.lineBetween(item.aX, item.aY, item.bX, item.bY);
      }
      break;
    }
  }
}

function drawDiamond(
  graphics: Phaser.GameObjects.Graphics,
  x: number,
  y: number,
  radius: number,
  color: number,
  alpha: number,
): void {
  graphics.lineStyle(2, color, alpha);
  graphics.beginPath();
  graphics.moveTo(x, y - radius);
  graphics.lineTo(x + radius, y);
  graphics.lineTo(x, y + radius);
  graphics.lineTo(x - radius, y);
  graphics.closePath();
  graphics.strokePath();
}
