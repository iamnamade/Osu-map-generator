import type { EditorRootState } from "../EditorState";
import { formatTimeMs } from "../../shared/format";
import { renderBeatTrack, renderOnsetTrack } from "./BeatGridRenderer";
import { renderObjectTrack, type TimelineIssueMarker, type TimelineObjectMarker } from "./ObjectTrackRenderer";
import { renderPhraseTrack, type TimelinePhraseMarker } from "./PhraseTrackRenderer";
import { renderPlayhead } from "./PlayheadRenderer";
import { renderRecoveryTrack, type TimelineRecoveryMarker } from "./RecoveryTrackRenderer";
import { renderSectionTrack, type TimelineSectionMarker } from "./SectionTrackRenderer";
import { renderWaveformTrack, type TimelineFrame } from "./WaveformRenderer";

export interface TimelineRenderResult {
  objectMarkers: TimelineObjectMarker[];
  issueMarkers: TimelineIssueMarker[];
  sectionMarkers: TimelineSectionMarker[];
  phraseMarkers: TimelinePhraseMarker[];
  recoveryMarkers: TimelineRecoveryMarker[];
  chartFrame: TimelineFrame;
}

export class TimelineRenderer {
  render(
    canvas: HTMLCanvasElement,
    state: EditorRootState,
  ): TimelineRenderResult {
    const context = canvas.getContext("2d");
    if (!context) {
      return {
        objectMarkers: [],
        issueMarkers: [],
        sectionMarkers: [],
        phraseMarkers: [],
        recoveryMarkers: [],
        chartFrame: {
          x: 0,
          y: 0,
          width: 0,
          height: 0,
          visibleStartMs: 0,
          visibleEndMs: 1,
        },
      };
    }

    const ratio = window.devicePixelRatio || 1;
    const width = canvas.clientWidth || 1200;
    const height = canvas.clientHeight || 300;
    canvas.width = Math.floor(width * ratio);
    canvas.height = Math.floor(height * ratio);
    context.setTransform(ratio, 0, 0, ratio, 0, 0);

    context.clearRect(0, 0, width, height);
    context.fillStyle = "#0b1018";
    context.fillRect(0, 0, width, height);

    const trackLabelWidth = 94;
    const chartPadding = 12;
    const chartFrame: TimelineFrame = {
      x: trackLabelWidth,
      y: 26,
      width: width - trackLabelWidth - chartPadding,
      height: height - 38,
      visibleStartMs: state.ui.timeline.visibleStartMs,
      visibleEndMs:
        state.ui.timeline.visibleStartMs + state.ui.timeline.visibleDurationMs,
    };

    const waveformFrame = subFrame(chartFrame, 0, 46);
    const energyFrame = subFrame(chartFrame, 52, 34);
    const beatFrame = subFrame(chartFrame, 92, 26);
    const onsetFrame = subFrame(chartFrame, 124, 26);
    const sectionFrame = subFrame(chartFrame, 156, 42);
    const phraseFrame = subFrame(chartFrame, 204, 42);
    const recoveryFrame = subFrame(chartFrame, 252, 42);
    const objectFrame = subFrame(chartFrame, 300, 54);
    const issueFrame = subFrame(chartFrame, 360, 22);

    drawTrackBackground(context, width, trackLabelWidth, [
      ["Waveform", waveformFrame],
      ["Energy", energyFrame],
      ["Beats", beatFrame],
      ["Onsets", onsetFrame],
      ["Sections", sectionFrame],
      ["Phrases", phraseFrame],
      ["Recovery", recoveryFrame],
      ["Hit Objects", objectFrame],
      ["Issues", issueFrame],
    ]);

    renderWaveformTrack(context, state, waveformFrame);
    renderEnergyTrack(context, state, energyFrame);
    renderBeatTrack(context, state, beatFrame);
    renderOnsetTrack(context, state, onsetFrame);
    const sections = renderSectionTrack(context, state, sectionFrame);
    const phrases = renderPhraseTrack(context, state, phraseFrame);
    const recovery = renderRecoveryTrack(context, state, recoveryFrame);
    const objects = renderObjectTrack(context, state, objectFrame);
    renderPlayhead(
      context,
      {
        ...chartFrame,
        y: waveformFrame.y,
        height: issueFrame.y + issueFrame.height - waveformFrame.y,
      },
      state.session.playheadMs,
      formatTimeMs(state.session.playheadMs),
    );
    drawAxisLabels(context, chartFrame);

    return {
      objectMarkers: objects.objectMarkers,
      issueMarkers: objects.issueMarkers,
      sectionMarkers: sections,
      phraseMarkers: phrases,
      recoveryMarkers: recovery,
      chartFrame,
    };
  }
}

function drawTrackBackground(
  context: CanvasRenderingContext2D,
  width: number,
  labelWidth: number,
  tracks: Array<[string, TimelineFrame]>,
): void {
  context.fillStyle = "#0f1622";
  context.fillRect(0, 0, width, 26);
  context.font = "12px Bahnschrift, 'Segoe UI', sans-serif";
  context.textAlign = "left";
  context.textBaseline = "middle";

  for (const [label, frame] of tracks) {
    context.fillStyle = "#101826";
    context.fillRect(0, frame.y, width, frame.height);
    context.strokeStyle = "rgba(96, 113, 144, 0.35)";
    context.lineWidth = 1;
    context.beginPath();
    context.moveTo(labelWidth, frame.y + frame.height + 0.5);
    context.lineTo(width, frame.y + frame.height + 0.5);
    context.stroke();

    context.fillStyle = "#ced7ea";
    context.fillText(label, 18, frame.y + frame.height / 2);
  }
}

function renderEnergyTrack(
  context: CanvasRenderingContext2D,
  state: EditorRootState,
  frame: TimelineFrame,
): void {
  const frames = state.session.analysis?.energyFrames ?? [];
  if (frames.length === 0) {
    return;
  }

  context.beginPath();
  context.moveTo(frame.x, frame.y + frame.height);

  for (const sample of frames) {
    if (sample.timeMs < frame.visibleStartMs || sample.timeMs > frame.visibleEndMs) {
      continue;
    }

    const x =
      frame.x +
      ((sample.timeMs - frame.visibleStartMs) /
        (frame.visibleEndMs - frame.visibleStartMs)) *
        frame.width;
    const y = frame.y + frame.height - sample.value * (frame.height - 4);
    context.lineTo(x, y);
  }

  context.lineTo(frame.x + frame.width, frame.y + frame.height);
  context.closePath();
  context.fillStyle = "rgba(96, 164, 255, 0.26)";
  context.fill();
}

function drawAxisLabels(
  context: CanvasRenderingContext2D,
  chartFrame: TimelineFrame,
): void {
  const stepCount = 10;
  context.fillStyle = "#8da0be";
  context.font = "11px Bahnschrift, 'Segoe UI', sans-serif";
  context.textAlign = "center";
  context.textBaseline = "top";

  for (let index = 0; index <= stepCount; index += 1) {
    const ratio = index / stepCount;
    const timeMs =
      chartFrame.visibleStartMs +
      ratio * (chartFrame.visibleEndMs - chartFrame.visibleStartMs);
    const x = chartFrame.x + ratio * chartFrame.width;
    context.fillText(formatTimeMs(timeMs).slice(0, 5), x, 6);
  }

  context.textAlign = "right";
  context.fillText(
    `${formatTimeMs(chartFrame.visibleStartMs)} - ${formatTimeMs(chartFrame.visibleEndMs)} (${(
      (chartFrame.visibleEndMs - chartFrame.visibleStartMs) /
      1000
    ).toFixed(3)}s)`,
    chartFrame.x + chartFrame.width,
    6,
  );
}

function subFrame(
  chartFrame: TimelineFrame,
  offsetY: number,
  height: number,
): TimelineFrame {
  return {
    ...chartFrame,
    y: chartFrame.y + offsetY,
    height,
  };
}
