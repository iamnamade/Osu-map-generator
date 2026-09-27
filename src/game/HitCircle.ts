import Phaser from "phaser";

import type { PositionedBeatmapHitObject } from "./types";

const APPROACH_RING_SCALE = 2.2;

export class HitCircle extends Phaser.GameObjects.Container {
  public readonly hitObject: PositionedBeatmapHitObject;

  private readonly radius: number;
  private readonly approachTime: number;
  private readonly approachRing: Phaser.GameObjects.Arc;
  private readonly hitGlow: Phaser.GameObjects.Arc;
  private readonly hitRing: Phaser.GameObjects.Arc;
  private readonly hitCore: Phaser.GameObjects.Arc;

  public constructor(
    scene: Phaser.Scene,
    hitObject: PositionedBeatmapHitObject,
    radius: number,
    approachTime: number,
  ) {
    super(scene, hitObject.x, hitObject.y);

    this.hitObject = hitObject;
    this.radius = radius;
    this.approachTime = approachTime;

    this.approachRing = scene.add
      .circle(0, 0, radius, 0x000000, 0)
      .setStrokeStyle(4, 0x57e7c6, 0.95);

    this.hitGlow = scene.add.circle(0, 0, radius + 10, 0x57e7c6, 0.14);
    this.hitRing = scene.add
      .circle(0, 0, radius, 0x000000, 0)
      .setStrokeStyle(3, 0xffffff, 0.9);
    this.hitCore = scene.add.circle(0, 0, radius - 5, 0x15324a, 0.92);

    this.add([this.approachRing, this.hitGlow, this.hitCore, this.hitRing]);

    this.setDepth(3);
    scene.add.existing(this);
  }

  public containsPoint(x: number, y: number): boolean {
    return Phaser.Math.Distance.Between(this.x, this.y, x, y) <= this.radius;
  }

  public updateForSongTime(songTimeMs: number): void {
    const timeUntilHit = this.hitObject.time - songTimeMs;
    const normalizedLead = Phaser.Math.Clamp(timeUntilHit / this.approachTime, 0, 1);
    const approachScale =
      1 + normalizedLead * (APPROACH_RING_SCALE - 1);
    const lateAmount =
      songTimeMs > this.hitObject.time
        ? Phaser.Math.Clamp((songTimeMs - this.hitObject.time) / 180, 0, 1)
        : 0;

    this.approachRing.setScale(approachScale);
    this.approachRing.setAlpha(0.75 + normalizedLead * 0.25);
    this.hitGlow.setAlpha(0.1 + (1 - normalizedLead) * 0.12);
    this.hitRing.setStrokeStyle(3, 0xffffff, 0.9 - lateAmount * 0.4);
  }
}
