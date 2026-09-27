from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DifficultyName = Literal["easy", "normal", "hard"]
JobStatus = Literal["queued", "running", "completed", "failed", "cancelled"]


def _default_candidate_count(difficulty: DifficultyName) -> int:
    if difficulty == "easy":
        return 8
    if difficulty == "normal":
        return 10
    return 12


class AudioMetadataSuggestion(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    title: str | None = None
    title_unicode: str | None = Field(default=None, alias="titleUnicode")
    artist: str | None = None
    artist_unicode: str | None = Field(default=None, alias="artistUnicode")
    duration_ms: int | None = Field(default=None, alias="durationMs")
    sample_rate: int | None = Field(default=None, alias="sampleRate")
    codec: str | None = None
    bitrate_kbps: int | None = Field(default=None, alias="bitrateKbps")


class DifficultySettings(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    candidate_count: int = Field(alias="candidateCount")
    root_seed: int = Field(alias="rootSeed")
    timing_variation: bool = Field(default=False, alias="timingVariation")
    tournament_enabled: bool = Field(default=True, alias="tournamentEnabled")
    hybrid_assembly_enabled: bool = Field(default=True, alias="hybridAssemblyEnabled")
    # Phase 19 mapping control system
    mapping_preset: str = Field(default="balanced", alias="mappingPreset")
    difficulty_target: Literal["auto", "custom"] = Field(default="auto", alias="difficultyTarget")
    custom_target_star: float | None = Field(default=None, alias="customTargetStar")
    custom_min_star: float | None = Field(default=None, alias="customMinStar")
    custom_max_star: float | None = Field(default=None, alias="customMaxStar")
    circle_density: float = Field(default=0.5, alias="circleDensity")
    slider_density: float = Field(default=0.5, alias="sliderDensity")
    spinner_frequency: float = Field(default=0.5, alias="spinnerFrequency")
    jump_intensity: float = Field(default=0.5, alias="jumpIntensity")
    stream_intensity: float = Field(default=0.5, alias="streamIntensity")
    burst_intensity: float = Field(default=0.5, alias="burstIntensity")
    rhythm_complexity: float = Field(default=0.5, alias="rhythmComplexity")
    pattern_variety: float = Field(default=0.5, alias="patternVariety")
    spacing: float = Field(default=0.5, alias="spacing")
    aggression: float = Field(default=0.5, alias="aggression")
    evolution_passes: int = Field(default=2, alias="evolutionPasses")
    seed_mode: Literal["auto", "manual"] = Field(default="auto", alias="seedMode")
    replay_profile: str = Field(default="advanced", alias="replayProfile")
    section_sensitivity: float = Field(default=0.5, alias="sectionSensitivity")

    @field_validator("candidate_count")
    @classmethod
    def validate_candidate_count(cls, value: int) -> int:
        if value < 1 or value > 64:
            raise ValueError("Candidate count must be between 1 and 64.")
        return value

    @field_validator("root_seed")
    @classmethod
    def validate_root_seed(cls, value: int) -> int:
        if value < 0:
            raise ValueError("Root seed must be non-negative.")
        return value

    @field_validator("evolution_passes")
    @classmethod
    def validate_evolution_passes(cls, value: int) -> int:
        if value < 1 or value > 5:
            raise ValueError("Evolution passes must be between 1 and 5.")
        return value

    @field_validator("mapping_preset")
    @classmethod
    def validate_mapping_preset(cls, value: str) -> str:
        allowed = {"balanced", "technical", "aim", "rhythm", "tournament", "custom"}
        if value not in allowed:
            raise ValueError(
                f"Mapping preset must be one of: {', '.join(sorted(allowed))}."
            )
        return value

    @field_validator("replay_profile")
    @classmethod
    def validate_replay_profile(cls, value: str) -> str:
        allowed = {"beginner", "intermediate", "advanced", "tournament", "custom"}
        if value not in allowed:
            raise ValueError(
                f"Replay profile must be one of: {', '.join(sorted(allowed))}."
            )
        return value

    @field_validator(
        "circle_density",
        "slider_density",
        "spinner_frequency",
        "jump_intensity",
        "stream_intensity",
        "burst_intensity",
        "rhythm_complexity",
        "pattern_variety",
        "spacing",
        "aggression",
        "section_sensitivity",
    )
    @classmethod
    def validate_control_value(cls, value: float) -> float:
        if not 0.0 <= value <= 1.0:
            raise ValueError("Control values must stay between 0 and 1.")
        return value

    @model_validator(mode="after")
    def validate_custom_difficulty(self) -> "DifficultySettings":
        if self.difficulty_target != "custom":
            return self
        values = [self.custom_target_star, self.custom_min_star, self.custom_max_star]
        if any(value is None for value in values):
            raise ValueError(
                "Custom difficulty requires target, minimum, and maximum star values."
            )
        target, minimum, maximum = (float(value) for value in values)  # type: ignore[assignment]
        if not (0.5 <= minimum <= target <= maximum <= 12.0):
            raise ValueError(
                "Custom difficulty range is impossible: min <= target <= max "
                "with all values between 0.5 and 12.0 stars."
            )
        return self


class WorkspaceMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    title: str = ""
    title_unicode: str | None = Field(default=None, alias="titleUnicode")
    artist: str = ""
    artist_unicode: str | None = Field(default=None, alias="artistUnicode")
    creator: str = "osu-map-ai"
    source: str = ""
    tags: str = ""
    background_filename: str | None = Field(default=None, alias="backgroundFilename")
    selected_difficulties: list[DifficultyName] = Field(
        default_factory=list,
        alias="selectedDifficulties",
    )
    difficulty_settings: dict[DifficultyName, DifficultySettings] = Field(
        default_factory=dict,
        alias="difficultySettings",
    )


class WorkspaceMetadataUpdateRequest(WorkspaceMetadata):
    @model_validator(mode="after")
    def validate_consistency(self) -> "WorkspaceMetadataUpdateRequest":
        if not self.title.strip():
            raise ValueError("Title is required.")
        if not self.artist.strip():
            raise ValueError("Artist is required.")
        if not self.creator.strip():
            raise ValueError("Creator is required.")
        if not self.selected_difficulties:
            raise ValueError("Select at least one difficulty.")
        for difficulty in self.selected_difficulties:
            if difficulty not in self.difficulty_settings:
                raise ValueError(f"Difficulty settings are missing for {difficulty}.")
            settings = self.difficulty_settings[difficulty]
            if settings.hybrid_assembly_enabled and not settings.tournament_enabled:
                raise ValueError(
                    f"{difficulty.capitalize()} hybrid assembly requires tournament mode."
                )
        return self


class UploadedFileDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    original_filename: str = Field(alias="originalFilename")
    normalized_filename: str = Field(alias="normalizedFilename")
    relative_path: str = Field(alias="relativePath")
    size_bytes: int = Field(alias="sizeBytes")
    content_type: str = Field(alias="contentType")
    sha256: str
    detected_metadata: AudioMetadataSuggestion | None = Field(
        default=None,
        alias="detectedMetadata",
    )


class ArtifactDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str
    workspace_id: str = Field(alias="workspaceId")
    group: str
    kind: str
    label: str
    relative_path: str = Field(alias="relativePath")
    file_name: str = Field(alias="fileName")
    content_type: str = Field(alias="contentType")
    size_bytes: int = Field(alias="sizeBytes")
    difficulty: DifficultyName | None = None
    download_url: str = Field(alias="downloadUrl")


class ArtifactGroup(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    group: str
    items: list[ArtifactDescriptor]


class FinalDifficultyResult(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    difficulty: DifficultyName
    final_map_kind: str = Field(alias="finalMapKind")
    object_count: int | None = Field(default=None, alias="objectCount")
    score: float | None = None
    candidate_winner: int | None = Field(default=None, alias="candidateWinner")
    section_count: int | None = Field(default=None, alias="sectionCount")
    phrase_count: int | None = Field(default=None, alias="phraseCount")
    promoted: bool | None = None
    map_artifact_id: str | None = Field(default=None, alias="mapArtifactId")
    osu_artifact_id: str | None = Field(default=None, alias="osuArtifactId")
    # Phase 22 recovery & map dynamics
    spinner_count: int | None = Field(default=None, alias="spinnerCount")
    avg_spinner_duration_ms: float | None = Field(
        default=None,
        alias="avgSpinnerDurationMs",
    )
    fatigue_peak: float | None = Field(default=None, alias="fatiguePeak")
    recovery_window_count: int | None = Field(
        default=None,
        alias="recoveryWindowCount",
    )


class JobResultSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    title: str
    artist: str
    audio_duration_ms: int | None = Field(default=None, alias="audioDurationMs")
    selected_difficulties: list[DifficultyName] = Field(alias="selectedDifficulties")
    package_artifact_id: str | None = Field(default=None, alias="packageArtifactId")
    package_size_bytes: int | None = Field(default=None, alias="packageSizeBytes")
    section_count: int | None = Field(default=None, alias="sectionCount")
    phrase_count: int | None = Field(default=None, alias="phraseCount")
    difficulties: list[FinalDifficultyResult]


class WorkspaceManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    schema_version: int = Field(default=1, alias="schemaVersion")
    workspace_id: str = Field(alias="workspaceId")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    audio: UploadedFileDescriptor | None = None
    background: UploadedFileDescriptor | None = None
    metadata: WorkspaceMetadata = Field(default_factory=WorkspaceMetadata)
    configuration_signature: str | None = Field(default=None, alias="configurationSignature")
    last_run_signature: str | None = Field(default=None, alias="lastRunSignature")
    job_status: JobStatus | None = Field(default=None, alias="jobStatus")
    available_artifacts: list[ArtifactDescriptor] = Field(
        default_factory=list,
        alias="availableArtifacts",
    )
    last_result: JobResultSummary | None = Field(default=None, alias="lastResult")


class WorkspaceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    workspace: WorkspaceManifest
    artifacts: list[ArtifactGroup]
    ready_for_generation: bool = Field(alias="readyForGeneration")


class AudioUploadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    workspace: WorkspaceManifest
    artifacts: list[ArtifactGroup]
    ready_for_generation: bool = Field(alias="readyForGeneration")
    detected_metadata: AudioMetadataSuggestion = Field(alias="detectedMetadata")


class BackgroundUploadResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    workspace: WorkspaceManifest
    artifacts: list[ArtifactGroup]
    ready_for_generation: bool = Field(alias="readyForGeneration")


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    status: Literal["ok"]
    version: int
    pipeline_available: bool = Field(alias="pipelineAvailable")


class JobEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    index: int
    timestamp: datetime
    level: Literal["info", "warning", "error"]
    message: str


class JobStateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    job_id: str = Field(alias="jobId")
    workspace_id: str = Field(alias="workspaceId")
    status: JobStatus
    current_stage: str | None = Field(default=None, alias="currentStage")
    current_stage_label: str | None = Field(default=None, alias="currentStageLabel")
    completed_stages: int = Field(alias="completedStages")
    total_stages: int = Field(alias="totalStages")
    overall_progress_percent: int = Field(alias="overallProgressPercent")
    current_difficulty: DifficultyName | None = Field(default=None, alias="currentDifficulty")
    current_candidate: int | None = Field(default=None, alias="currentCandidate")
    candidates_completed: int | None = Field(default=None, alias="candidatesCompleted")
    candidates_total: int | None = Field(default=None, alias="candidatesTotal")
    latest_message: str = Field(alias="latestMessage")
    warnings: list[str]
    errors: list[str]
    artifact_ids: list[str] = Field(alias="artifactIds")
    technical_details: str | None = Field(default=None, alias="technicalDetails")
    started_at: datetime = Field(alias="startedAt")
    updated_at: datetime = Field(alias="updatedAt")
    finished_at: datetime | None = Field(default=None, alias="finishedAt")
    events: list[JobEvent] = Field(default_factory=list)
    result: JobResultSummary | None = None


def build_default_workspace_metadata() -> WorkspaceMetadata:
    return WorkspaceMetadata(
        creator="osu-map-ai",
        selectedDifficulties=[],
        difficultySettings={
            "easy": DifficultySettings(
                candidateCount=_default_candidate_count("easy"),
                rootSeed=42,
                timingVariation=False,
                tournamentEnabled=True,
                hybridAssemblyEnabled=True,
            ),
            "normal": DifficultySettings(
                candidateCount=_default_candidate_count("normal"),
                rootSeed=42,
                timingVariation=False,
                tournamentEnabled=True,
                hybridAssemblyEnabled=True,
            ),
            "hard": DifficultySettings(
                candidateCount=_default_candidate_count("hard"),
                rootSeed=42,
                timingVariation=False,
                tournamentEnabled=True,
                hybridAssemblyEnabled=True,
            ),
        },
    )
