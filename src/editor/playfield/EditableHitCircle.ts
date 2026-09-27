import type Phaser from "phaser";

export function drawHitCircle(
  graphics: Phaser.GameObjects.Graphics,
  options: {
    x: number;
    y: number;
    radius: number;
    fillColor: number;
    fillAlpha?: number;
    strokeColor: number;
    strokeAlpha?: number;
    strokeWidth?: number;
  },
): void {
  graphics.fillStyle(options.fillColor, options.fillAlpha ?? 1);
  graphics.lineStyle(
    options.strokeWidth ?? 2,
    options.strokeColor,
    options.strokeAlpha ?? 1,
  );
  graphics.fillCircle(options.x, options.y, options.radius);
  graphics.strokeCircle(options.x, options.y, options.radius);
}
