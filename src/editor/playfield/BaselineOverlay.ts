import type Phaser from "phaser";

export function drawBaselineGhost(
  graphics: Phaser.GameObjects.Graphics,
  options: {
    baselineX: number;
    baselineY: number;
    currentX: number;
    currentY: number;
    radius: number;
    isChanged: boolean;
  },
): void {
  graphics.lineStyle(2, 0xa78bfa, options.isChanged ? 0.6 : 0.22);
  graphics.strokeCircle(options.baselineX, options.baselineY, options.radius);

  if (!options.isChanged) {
    return;
  }

  graphics.lineStyle(1, 0xa78bfa, 0.35);
  graphics.lineBetween(
    options.baselineX,
    options.baselineY,
    options.currentX,
    options.currentY,
  );
}
