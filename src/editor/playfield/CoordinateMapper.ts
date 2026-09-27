import type Phaser from "phaser";

export interface LogicalPoint {
  x: number;
  y: number;
}

export function pointerToLogical(
  pointer: Phaser.Input.Pointer,
  scaleManager: Phaser.Scale.ScaleManager,
): LogicalPoint {
  const scaleX = scaleManager.displayScale.x || 1;
  const scaleY = scaleManager.displayScale.y || 1;

  return {
    x: pointer.x / scaleX,
    y: pointer.y / scaleY,
  };
}
