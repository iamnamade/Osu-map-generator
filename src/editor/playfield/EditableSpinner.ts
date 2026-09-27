import type Phaser from "phaser";

const SPINNER_STROKE = 0x9be8ff;
const SPINNER_FILL = 0x122338;

export function drawSpinnerObject(
  graphics: Phaser.GameObjects.Graphics,
  overlayGraphics: Phaser.GameObjects.Graphics,
  options: {
    x: number;
    y: number;
    radius: number;
    isSelected: boolean;
    isHovered: boolean;
  },
): void {
  const { x, y, radius } = options;
  const strokeColor = options.isSelected
    ? 0xf4ebff
    : options.isHovered
      ? 0xd8c4ff
      : SPINNER_STROKE;
  const fillColor = options.isSelected ? 0x5731ad : SPINNER_FILL;

  graphics.fillStyle(fillColor, 0.92);
  graphics.lineStyle(3, strokeColor, 0.95);
  graphics.fillCircle(x, y, radius);
  graphics.strokeCircle(x, y, radius);

  // Inner ring + center dot hint at "spin this" motion.
  graphics.lineStyle(1, strokeColor, 0.55);
  graphics.strokeCircle(x, y, radius - 10);

  graphics.fillStyle(0x9be8ff, 0.9);
  graphics.fillCircle(x, y - (radius - 12), 6);

  // Arc wedges suggesting rotation.
  overlayGraphics.lineStyle(2, 0xa855f7, 0.4);
  overlayGraphics.beginPath();
  overlayGraphics.arc(x, y, radius + 14, 0.15, 1.2, false);
  overlayGraphics.strokePath();
  overlayGraphics.beginPath();
  overlayGraphics.arc(x, y, radius + 14, Math.PI + 0.4, Math.PI + 1.6, false);
  overlayGraphics.strokePath();
}
