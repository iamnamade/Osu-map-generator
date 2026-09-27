import type Phaser from "phaser";

export function drawSelectionOverlay(
  graphics: Phaser.GameObjects.Graphics,
  x: number,
  y: number,
  radius: number,
): void {
  graphics.lineStyle(3, 0xa678ff, 0.95);
  graphics.strokeCircle(x, y, radius + 8);
  graphics.lineStyle(1, 0xf3ecff, 0.6);
  graphics.strokeCircle(x, y, radius + 13);
}
