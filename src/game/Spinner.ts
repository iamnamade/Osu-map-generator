import Phaser from "phaser";

import { PLAYFIELD_HEIGHT, PLAYFIELD_WIDTH, type BeatmapSpinnerHitObject } from "./types";

const APPROACH_RING_SCALE = 2.2;
const SPIN_RING_RADIUS = 56;

/** Revolutions per second required to complete a spinner (scaled by difficulty). */
const BASE_SPIN_SPEED_RPS = 3.2;
const SPIN_SPEED_BY_APPROACH_MS: Record<number, number> = {
  1200: 2.6, // easy
  950: 3.2, // normal
  720: 3.8, // hard
};

function requiredRotationsFor(spinner: BeatmapSpinnerHitObject, approachTime: number): number {
  const durationSeconds = Math.max(0.25, (spinner.endTime - spinner.time) / 1000);
  const spinSpeed =
    SPIN_SPEED_BY_APPROACH_MS[approachTime] ?? BASE_SPIN_SPEED_RPS;
  return Math.max(2, Math.round(durationSeconds * spinSpeed));
}

export class Spinner extends Phaser.GameObjects.Container {
  public readonly hitObject: BeatmapSpinnerHitObject;

  private readonly radius: number;
  private readonly requiredRotations: number;
  private readonly approachRing: Phaser.GameObjects.Arc;
  private readonly outerRing: Phaser.GameObjects.Arc;
  private readonly disc: Phaser.GameObjects.Arc;
  private readonly progressRing: Phaser.GameObjects.Arc;
  private readonly spinnerKnob: Phaser.GameObjects.Arc;
  private readonly fillArc: Phaser.GameObjects.Arc;

  private accumulatedAngle = 0;
  private lastPointerAngle: number | null = null;
  private isSpinning = false;

  public constructor(
    scene: Phaser.Scene,
    hitObject: BeatmapSpinnerHitObject,
    approachTime: number,
  ) {
    super(scene, PLAYFIELD_WIDTH / 2, PLAYFIELD_HEIGHT / 2);

    this.hitObject = hitObject;
    this.radius = SPIN_RING_RADIUS;
    this.requiredRotations = requiredRotationsFor(hitObject, approachTime);

    this.approachRing = scene.add
      .circle(0, 0, this.radius, 0x000000, 0)
      .setStrokeStyle(4, 0x9be8ff, 0.95);

    this.outerRing = scene.add
      .circle(0, 0, this.radius, 0x000000, 0)
      .setStrokeStyle(3, 0xf4f7ff, 0.9);

    this.disc = scene.add.circle(0, 0, this.radius - 8, 0x1c3a55, 0.85);

    this.fillArc = scene.add
      .arc(0, 0, this.radius - 12, 90, 90, false, 0x2dd4a7, 0.5)
      .setStrokeStyle(0, 0x000000, 0);

    this.progressRing = scene.add
      .circle(0, 0, this.radius + 10, 0x000000, 0)
      .setStrokeStyle(3, 0x2dd4a7, 0.9);

    this.spinnerKnob = scene.add
      .circle(0, -this.radius + 10, 9, 0x9be8ff, 1)
      .setStrokeStyle(2, 0xffffff, 0.9);

    this.add([
      this.approachRing,
      this.disc,
      this.fillArc,
      this.outerRing,
      this.progressRing,
      this.spinnerKnob,
    ]);

    this.setDepth(3);
    scene.add.existing(this);
  }

  public containsPoint(x: number, y: number): boolean {
    return Phaser.Math.Distance.Between(this.x, this.y, x, y) <= this.radius;
  }

  public updateForSongTime(songTimeMs: number): void {
    const timeUntilStart = this.hitObject.time - songTimeMs;
    const normalizedLead = Phaser.Math.Clamp(timeUntilStart / 1800, 0, 1);
    const approachScale = 1 + normalizedLead * (APPROACH_RING_SCALE - 1);
    const active =
      songTimeMs >= this.hitObject.time && songTimeMs <= this.hitObject.endTime;
    const progress = this.completion();

    this.approachRing.setScale(approachScale);
    this.approachRing.setAlpha(active ? 0 : 0.75 + normalizedLead * 0.25);
    this.progressRing.setScale(1 + progress * 0.08);
    this.progressRing.setAlpha(active ? 0.9 : 0.55);
    this.progressRing.setStrokeStyle(3, active ? 0x2dd4a7 : 0x5f7fa3, 0.9);

    this.spinnerKnob.setVisible(active);
    this.outerRing.setAlpha(active ? 1 : 0.85);
    this.disc.setFillStyle(active ? 0x1c3a55 : 0x122338, active ? 0.85 : 0.7);
  }

  public beginSpin(): void {
    this.isSpinning = true;
    this.lastPointerAngle = null;
  }

  public updateSpin(pointerX: number, pointerY: number): void {
    if (!this.isSpinning) {
      return;
    }

    const angle = Math.atan2(pointerY - this.y, pointerX - this.x);
    if (this.lastPointerAngle !== null) {
      let delta = angle - this.lastPointerAngle;
      // Normalize the delta to the shortest rotation direction.
      while (delta > Math.PI) {
        delta -= Math.PI * 2;
      }
      while (delta < -Math.PI) {
        delta += Math.PI * 2;
      }
      this.accumulatedAngle += delta;
    }
    this.lastPointerAngle = angle;

    // Rotate the knob to visually reflect the spinning direction.
    this.spinnerKnob.setPosition(
      Math.cos(angle) * -(this.radius - 10),
      Math.sin(angle) * -(this.radius - 10),
    );
  }

  public endSpin(): void {
    this.isSpinning = false;
    this.lastPointerAngle = null;
  }

  public completion(): number {
    return Phaser.Math.Clamp(
      this.accumulatedAngle / (this.requiredRotations * Math.PI * 2),
      0,
      1,
    );
  }

  public isComplete(): boolean {
    return this.completion() >= 1;
  }

  public extraRotations(): number {
    const totalRotations = this.accumulatedAngle / (Math.PI * 2);
    return Math.max(0, Math.floor(totalRotations - this.requiredRotations));
  }

  public resetSpin(): void {
    this.accumulatedAngle = 0;
    this.lastPointerAngle = null;
    this.isSpinning = false;
  }
}
