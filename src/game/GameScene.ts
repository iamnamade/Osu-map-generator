import Phaser from "phaser";

import { HitCircle } from "./HitCircle";
import { ScoreManager, TIMING_WINDOWS } from "./ScoreManager";
import { Spinner } from "./Spinner";
import {
  PLAYFIELD_HEIGHT,
  PLAYFIELD_WIDTH,
  getHitObjectEndTime,
  hasHitObjectPosition,
  isSpinnerHitObject,
  type Beatmap,
  type GameSceneCallbacks,
  type Judgment,
  type PositionedBeatmapHitObject,
  type SceneBindings,
  type BeatmapSpinnerHitObject,
} from "./types";

const JUDGMENT_COLORS: Record<Judgment, string> = {
  Perfect: "#57e7c6",
  Good: "#74b7ff",
  Okay: "#ffd166",
  Miss: "#ff6487",
};

export class GameScene extends Phaser.Scene {
  private beatmap: Beatmap | null = null;
  private audio: HTMLAudioElement | null = null;
  private callbacks: GameSceneCallbacks | null = null;
  private scoreManager: ScoreManager | null = null;
  private activeCircles = new Map<number, HitCircle>();
  private activeSpinners = new Map<number, Spinner>();
  private spinningSpinnerId: number | null = null;
  private playableObjects: PositionedBeatmapHitObject[] = [];
  private spinnerObjects: BeatmapSpinnerHitObject[] = [];
  private resolvedIds = new Set<number>();
  private nextObjectIndex = 0;
  private isRunning = false;
  private audioEnded = false;
  private durationMs = 0;
  private totalObjectCount = 0;
  private helperText?: Phaser.GameObjects.Text;
  private judgmentText?: Phaser.GameObjects.Text;

  public constructor() {
    super("game");
  }

  public create(): void {
    this.cameras.main.setBackgroundColor("#050a11");
    this.drawBackdrop();

    this.helperText = this.add
      .text(PLAYFIELD_WIDTH / 2, PLAYFIELD_HEIGHT / 2 - 14, "Load a map, then press Start Game", {
        color: "#9fb1c9",
        fontFamily: "Bahnschrift, 'Trebuchet MS', sans-serif",
        fontSize: "20px",
        align: "center",
      })
      .setOrigin(0.5)
      .setDepth(5);

    this.judgmentText = this.add
      .text(PLAYFIELD_WIDTH / 2, 46, "", {
        color: "#ffffff",
        fontFamily: "Bahnschrift, 'Trebuchet MS', sans-serif",
        fontSize: "26px",
        fontStyle: "bold",
      })
      .setOrigin(0.5)
      .setAlpha(0)
      .setDepth(6);

    this.input.on("pointerdown", this.handlePointerDown, this);
    this.input.on("pointermove", this.handlePointerMove, this);
    this.input.on("pointerup", this.handlePointerUp, this);
    this.input.on("pointerupoutside", this.handlePointerUp, this);
  }

  public bindSession(bindings: SceneBindings, callbacks: GameSceneCallbacks): void {
    this.beatmap = bindings.beatmap;
    this.audio = bindings.audio;
    this.callbacks = callbacks;
    this.playableObjects = bindings.beatmap.objects.filter(hasHitObjectPosition);
    this.spinnerObjects = bindings.beatmap.objects.filter(isSpinnerHitObject);
    this.totalObjectCount = this.playableObjects.length + this.spinnerObjects.length;
    this.scoreManager = new ScoreManager(this.totalObjectCount);
    this.durationMs = Math.max(
      Math.ceil(bindings.audio.duration * 1000),
      bindings.beatmap.objects.reduce(
        (maxTime, hitObject) => Math.max(maxTime, getHitObjectEndTime(hitObject)),
        0,
      ),
    );

    this.resetToReady();
  }

  public resetToReady(): void {
    this.clearActiveObjects();
    this.resolvedIds.clear();
    this.nextObjectIndex = 0;
    this.isRunning = false;
    this.audioEnded = false;
    this.spinningSpinnerId = null;

    if (this.beatmap) {
      this.scoreManager = new ScoreManager(this.totalObjectCount);
      this.emitHud(0, "Ready");
    }

    this.helperText?.setText("Press Start Game to begin").setVisible(true);
    this.judgmentText?.setAlpha(0);
  }

  public startRun(): void {
    if (!this.beatmap || !this.audio || !this.callbacks) {
      this.callbacks?.onError("Game scene was started before the beatmap and audio were ready.");
      return;
    }

    this.clearActiveObjects();
    this.resolvedIds.clear();
    this.nextObjectIndex = 0;
    this.audioEnded = false;
    this.spinningSpinnerId = null;
    this.scoreManager = new ScoreManager(this.totalObjectCount);
    this.isRunning = true;
    this.helperText?.setVisible(false);
    this.emitHud(0, "Go");
    this.callbacks.onStateChange?.("playing");
  }

  public stopRun(): void {
    this.isRunning = false;
    this.audioEnded = false;
    this.spinningSpinnerId = null;
    this.clearActiveObjects();
    this.helperText?.setVisible(true);
  }

  public handleAudioEnded(): void {
    if (!this.isRunning || !this.beatmap || !this.scoreManager) {
      return;
    }

    this.audioEnded = true;

    for (const hitObject of this.playableObjects) {
      if (!this.resolvedIds.has(hitObject.id)) {
        this.resolveObject(hitObject, "Miss", TIMING_WINDOWS.Okay + 1);
      }
    }

    for (const spinner of this.spinnerObjects) {
      if (!this.resolvedIds.has(spinner.id)) {
        this.resolveSpinner(spinner, false, TIMING_WINDOWS.Okay + 1);
      }
    }

    this.finishRun();
  }

  public update(): void {
    if (!this.isRunning || !this.beatmap || !this.audio || !this.scoreManager) {
      return;
    }

    const songTimeMs = this.getSongTimeMs();

    this.spawnVisibleObjects(songTimeMs);

    for (const circle of this.activeCircles.values()) {
      circle.updateForSongTime(songTimeMs);
    }

    for (const spinner of this.activeSpinners.values()) {
      spinner.updateForSongTime(songTimeMs);
    }

    for (const circle of Array.from(this.activeCircles.values())) {
      if (songTimeMs > circle.hitObject.time + TIMING_WINDOWS.Okay) {
        this.resolveObject(circle.hitObject, "Miss", songTimeMs - circle.hitObject.time);
      }
    }

    for (const spinner of Array.from(this.activeSpinners.values())) {
      if (songTimeMs > spinner.hitObject.endTime) {
        this.resolveSpinner(spinner.hitObject, spinner.isComplete(), songTimeMs - spinner.hitObject.endTime);
      }
    }

    this.emitHud(songTimeMs, this.scoreManager.snapshot().lastJudgment ?? "Playing");

    if (this.resolvedIds.size === this.totalObjectCount) {
      const songFinished = this.audioEnded || this.audio.ended || songTimeMs >= this.durationMs;

      if (songFinished) {
        this.finishRun();
      }
    }
  }

  private drawBackdrop(): void {
    const graphics = this.add.graphics();

    graphics.fillStyle(0x09121d, 1);
    graphics.fillRoundedRect(0, 0, PLAYFIELD_WIDTH, PLAYFIELD_HEIGHT, 26);

    graphics.fillStyle(0x132338, 0.65);
    graphics.fillRoundedRect(18, 18, PLAYFIELD_WIDTH - 36, PLAYFIELD_HEIGHT - 36, 20);

    graphics.lineStyle(2, 0x23405d, 0.9);
    graphics.strokeRoundedRect(18, 18, PLAYFIELD_WIDTH - 36, PLAYFIELD_HEIGHT - 36, 20);

    graphics.lineStyle(1, 0x1b3048, 0.4);

    for (let x = 48; x < PLAYFIELD_WIDTH; x += 64) {
      graphics.lineBetween(x, 18, x, PLAYFIELD_HEIGHT - 18);
    }

    for (let y = 48; y < PLAYFIELD_HEIGHT; y += 64) {
      graphics.lineBetween(18, y, PLAYFIELD_WIDTH - 18, y);
    }
  }

  private spawnVisibleObjects(songTimeMs: number): void {
    if (!this.beatmap) {
      return;
    }

    const orderedObjects = [...this.playableObjects, ...this.spinnerObjects].sort(
      (left, right) => left.time - right.time,
    );

    while (this.nextObjectIndex < orderedObjects.length) {
      const hitObject = orderedObjects[this.nextObjectIndex];

      if (songTimeMs < hitObject.time - this.beatmap.approachTime) {
        break;
      }

      if (this.resolvedIds.has(hitObject.id)) {
        this.nextObjectIndex += 1;
        continue;
      }

      if (isSpinnerHitObject(hitObject)) {
        if (!this.activeSpinners.has(hitObject.id)) {
          this.activeSpinners.set(hitObject.id, new Spinner(this, hitObject, this.beatmap.approachTime));
        }
      } else if (!this.activeCircles.has(hitObject.id)) {
        const circle = new HitCircle(
          this,
          hitObject,
          this.beatmap.circleRadius,
          this.beatmap.approachTime,
        );

        this.activeCircles.set(hitObject.id, circle);
      }

      this.nextObjectIndex += 1;
    }
  }

  private handlePointerDown(pointer: Phaser.Input.Pointer): void {
    if (!this.isRunning || !this.audio || !this.scoreManager) {
      return;
    }

    const worldPoint = this.cameras.main.getWorldPoint(pointer.x, pointer.y);
    const songTimeMs = this.getSongTimeMs();

    const activeSpinner = this.activeSpinnerAtPoint(worldPoint.x, worldPoint.y, songTimeMs);
    if (activeSpinner) {
      activeSpinner.beginSpin();
      this.spinningSpinnerId = activeSpinner.hitObject.id;
      return;
    }

    const candidates = Array.from(this.activeCircles.values()).filter((circle) =>
      circle.containsPoint(worldPoint.x, worldPoint.y),
    );

    if (candidates.length === 0) {
      return;
    }

    candidates.sort(
      (left, right) =>
        Math.abs(left.hitObject.time - songTimeMs) - Math.abs(right.hitObject.time - songTimeMs),
    );

    const selectedCircle = candidates[0];
    const diffMs = songTimeMs - selectedCircle.hitObject.time;
    const judgment = this.scoreManager.judge(diffMs);

    this.resolveObject(selectedCircle.hitObject, judgment, diffMs);
    this.emitHud(songTimeMs, judgment);
  }

  private handlePointerMove(pointer: Phaser.Input.Pointer): void {
    if (!this.isRunning || this.spinningSpinnerId === null) {
      return;
    }

    const spinner = this.activeSpinners.get(this.spinningSpinnerId);
    if (!spinner) {
      this.spinningSpinnerId = null;
      return;
    }

    const worldPoint = this.cameras.main.getWorldPoint(pointer.x, pointer.y);
    spinner.updateSpin(worldPoint.x, worldPoint.y);
  }

  private handlePointerUp(): void {
    if (this.spinningSpinnerId === null) {
      return;
    }

    const spinner = this.activeSpinners.get(this.spinningSpinnerId);
    spinner?.endSpin();
    this.spinningSpinnerId = null;
  }

  private activeSpinnerAtPoint(
    x: number,
    y: number,
    songTimeMs: number,
  ): Spinner | undefined {
    for (const spinner of this.activeSpinners.values()) {
      if (
        songTimeMs >= spinner.hitObject.time &&
        songTimeMs <= spinner.hitObject.endTime &&
        spinner.containsPoint(x, y)
      ) {
        return spinner;
      }
    }
    return undefined;
  }

  private resolveObject(
    hitObject: PositionedBeatmapHitObject,
    forcedJudgment: Judgment,
    diffMs: number,
  ): void {
    if (!this.scoreManager || this.resolvedIds.has(hitObject.id)) {
      return;
    }

    const outcome =
      forcedJudgment === "Miss"
        ? this.scoreManager.registerMiss(diffMs)
        : this.scoreManager.registerHit(diffMs);

    this.resolvedIds.add(hitObject.id);

    const circle = this.activeCircles.get(hitObject.id);

    if (circle) {
      this.showJudgmentBurst(circle.x, circle.y, outcome.judgment);
      circle.destroy();
      this.activeCircles.delete(hitObject.id);
    } else {
      this.showJudgmentBurst(hitObject.x, hitObject.y, outcome.judgment);
    }

    this.showTopJudgment(outcome.judgment);
  }

  private resolveSpinner(
    hitObject: BeatmapSpinnerHitObject,
    completed: boolean,
    diffMs: number,
  ): void {
    if (!this.scoreManager || this.resolvedIds.has(hitObject.id)) {
      return;
    }

    const spinner = this.activeSpinners.get(hitObject.id);
    const bonusScore = spinner?.extraRotations() ?? 0;
    const outcome = this.scoreManager.registerSpinnerResult(completed, bonusScore, diffMs);

    this.resolvedIds.add(hitObject.id);
    this.showJudgmentBurst(
      PLAYFIELD_WIDTH / 2,
      PLAYFIELD_HEIGHT / 2,
      outcome.judgment,
    );
    this.showTopJudgment(outcome.judgment);

    if (spinner) {
      spinner.destroy();
      this.activeSpinners.delete(hitObject.id);
    }
    if (this.spinningSpinnerId === hitObject.id) {
      this.spinningSpinnerId = null;
    }
  }

  private showTopJudgment(judgment: Judgment): void {
    if (!this.judgmentText) {
      return;
    }

    this.tweens.killTweensOf(this.judgmentText);
    this.judgmentText
      .setText(judgment)
      .setColor(JUDGMENT_COLORS[judgment])
      .setAlpha(1)
      .setScale(1);

    this.tweens.add({
      targets: this.judgmentText,
      alpha: 0,
      scale: 1.18,
      duration: 420,
      ease: "Quad.easeOut",
    });
  }

  private showJudgmentBurst(x: number, y: number, judgment: Judgment): void {
    const burst = this.add
      .text(x, y - 12, judgment, {
        color: JUDGMENT_COLORS[judgment],
        fontFamily: "Bahnschrift, 'Trebuchet MS', sans-serif",
        fontSize: "20px",
        fontStyle: "bold",
      })
      .setOrigin(0.5)
      .setDepth(8);

    this.tweens.add({
      targets: burst,
      y: y - 34,
      alpha: 0,
      duration: 460,
      ease: "Sine.easeOut",
      onComplete: () => {
        burst.destroy();
      },
    });
  }

  private finishRun(): void {
    if (!this.beatmap || !this.scoreManager || !this.callbacks) {
      return;
    }

    this.isRunning = false;
    this.spinningSpinnerId = null;
    this.clearActiveObjects();
    this.callbacks.onStateChange?.("finished");
    this.callbacks.onResults(this.scoreManager.buildResults(this.beatmap.title, this.beatmap.artist));
  }

  private emitHud(songTimeMs: number, currentJudgment: string): void {
    if (!this.callbacks || !this.scoreManager) {
      return;
    }

    const clampedProgress =
      this.durationMs > 0 ? Phaser.Math.Clamp(songTimeMs / this.durationMs, 0, 1) : 0;

    this.callbacks.onHudUpdate(
      this.scoreManager.createHudSnapshot(
        currentJudgment,
        clampedProgress,
        Math.max(0, songTimeMs),
        this.durationMs,
      ),
    );
  }

  private getSongTimeMs(): number {
    return this.audio ? this.audio.currentTime * 1000 : 0;
  }

  private clearActiveObjects(): void {
    for (const circle of this.activeCircles.values()) {
      circle.destroy();
    }

    this.activeCircles.clear();

    for (const spinner of this.activeSpinners.values()) {
      spinner.destroy();
    }

    this.activeSpinners.clear();
  }
}
