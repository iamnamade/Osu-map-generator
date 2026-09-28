from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from tools.local_api import app as local_api_app
from tools.local_api.artifact_service import ArtifactService
from tools.local_api.config import get_local_api_config
from tools.local_api.errors import LocalApiValidationError
from tools.local_api.models import (
    AudioMetadataSuggestion,
    DifficultySettings,
    UploadedFileDescriptor,
    WorkspaceMetadata,
    build_default_workspace_metadata,
)
from tools.local_api.workspace_manager import WorkspaceManager

# P0.4: uploads are magic-byte verified, so fixtures carry a real ID3v2
# header (identity/decoding of the payload is mocked where needed).
VALID_MP3_HEADER = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\x00" * 64
# P1.1: background uploads are magic-byte verified too (P0.4), so the preview
# route fixture needs a real PNG header.
VALID_PNG_HEADER = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


class LocalApiRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        os.environ["PULSE_LOCAL_API_WORKSPACES_ROOT"] = self._temp_dir.name
        get_local_api_config.cache_clear()
        local_api_app._services.cache_clear()
        self.client = TestClient(local_api_app.create_app())
        services = local_api_app._services()
        self.metadata_service = services["metadata_service"]
        self.job_manager = services["job_manager"]
        self.workspace_manager = services["workspace_manager"]

    def tearDown(self) -> None:
        self.client.close()
        local_api_app._services.cache_clear()
        get_local_api_config.cache_clear()
        os.environ.pop("PULSE_LOCAL_API_WORKSPACES_ROOT", None)
        self._temp_dir.cleanup()

    def test_health_and_workspace_lifecycle(self) -> None:
        health = self.client.get("/api/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["status"], "ok")

        created = self.client.post("/api/workspaces")
        self.assertEqual(created.status_code, 200)
        payload = created.json()
        workspace_id = payload["workspace"]["workspaceId"]

        workspace_dir = Path(self._temp_dir.name, workspace_id)
        self.assertTrue(workspace_dir.exists())
        self.assertFalse(payload["readyForGeneration"])

        loaded = self.client.get(f"/api/workspaces/{workspace_id}")
        self.assertEqual(loaded.status_code, 200)
        self.assertEqual(loaded.json()["workspace"]["workspaceId"], workspace_id)

        deleted = self.client.delete(f"/api/workspaces/{workspace_id}")
        self.assertEqual(deleted.status_code, 200)
        self.assertFalse(workspace_dir.exists())

    def test_metadata_update_succeeds_before_audio_and_stays_not_ready(self) -> None:
        workspace_id = self._create_workspace_id()

        response = self.client.put(
            f"/api/workspaces/{workspace_id}/metadata",
            json=build_metadata_payload(title="Route Test", artist="Unit Test"),
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["workspace"]["metadata"]["title"], "Route Test")
        self.assertFalse(payload["readyForGeneration"])

    def test_audio_upload_succeeds_with_empty_metadata_and_detected_suggestions(self) -> None:
        workspace_id = self._create_workspace_id()

        with patch.object(
            self.metadata_service,
            "extract_audio_metadata",
            return_value=AudioMetadataSuggestion(
                title="Detected Song",
                artist="Detected Artist",
                durationMs=180000,
                sampleRate=44100,
                codec="mp3",
            ),
        ):
            response = self._upload_audio(workspace_id)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertFalse(payload["readyForGeneration"])
        self.assertEqual(payload["detectedMetadata"]["title"], "Detected Song")
        self.assertEqual(payload["detectedMetadata"]["artist"], "Detected Artist")
        self.assertEqual(payload["workspace"]["audio"]["normalizedFilename"], "source-audio.mp3")
        self.assertEqual(payload["workspace"]["audio"]["detectedMetadata"]["durationMs"], 180000)
        self.assertEqual(payload["workspace"]["metadata"]["title"], "")

    def test_audio_upload_without_tags_succeeds_and_preserves_existing_metadata(self) -> None:
        workspace_id = self._create_workspace_id()
        save_metadata = self.client.put(
            f"/api/workspaces/{workspace_id}/metadata",
            json=build_metadata_payload(title="Manual Title", artist="Manual Artist"),
        )
        self.assertEqual(save_metadata.status_code, 200)

        with patch.object(
            self.metadata_service,
            "extract_audio_metadata",
            return_value=AudioMetadataSuggestion(
                durationMs=95000,
                sampleRate=44100,
                codec="mp3",
            ),
        ):
            response = self._upload_audio(workspace_id)

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["workspace"]["metadata"]["title"], "Manual Title")
        self.assertEqual(payload["workspace"]["metadata"]["artist"], "Manual Artist")
        self.assertTrue(payload["readyForGeneration"])
        self.assertIsNone(payload["detectedMetadata"]["title"])

    def test_audio_upload_does_not_call_generation_readiness_validation(self) -> None:
        workspace_id = self._create_workspace_id()

        with patch.object(
            self.metadata_service,
            "extract_audio_metadata",
            return_value=AudioMetadataSuggestion(durationMs=120000),
        ), patch.object(
            self.metadata_service,
            "validate_generation_ready",
            side_effect=AssertionError("upload route should not run generation readiness"),
        ):
            response = self._upload_audio(workspace_id)

        self.assertEqual(response.status_code, 200)

    def test_failed_audio_upload_does_not_leave_incomplete_manifest_state(self) -> None:
        workspace_id = self._create_workspace_id()

        with patch.object(
            self.metadata_service,
            "extract_audio_metadata",
            side_effect=LocalApiValidationError("Uploaded audio file could not be decoded."),
        ):
            response = self._upload_audio(workspace_id)

        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json()["detail"],
            "Uploaded audio file could not be decoded.",
        )

        manifest = self.workspace_manager.load_manifest(workspace_id)
        paths = self.workspace_manager.get_workspace_paths(workspace_id)
        self.assertIsNone(manifest.audio)
        self.assertEqual(list(paths.source_dir.iterdir()), [])

    def test_background_preview_route_serves_uploaded_image(self) -> None:
        workspace_id = self._create_workspace_id()
        upload = self.client.post(
            f"/api/workspaces/{workspace_id}/background",
            files={"file": ("cover.png", io.BytesIO(VALID_PNG_HEADER), "image/png")},
        )
        self.assertEqual(upload.status_code, 200)
        background = upload.json()["workspace"]["background"]
        self.assertIsNotNone(background)
        self.assertEqual(background["normalizedFilename"], "background.png")

        preview = self.client.get(
            f"/api/workspaces/{workspace_id}/preview-background/"
            f"{background['normalizedFilename']}"
        )
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.content, VALID_PNG_HEADER)
        self.assertEqual(preview.headers["content-type"], "image/png")

    def test_background_preview_route_rejects_unknown_filename(self) -> None:
        workspace_id = self._create_workspace_id()
        response = self.client.get(
            f"/api/workspaces/{workspace_id}/preview-background/background.png"
        )
        self.assertEqual(response.status_code, 404)

    def test_invalid_metadata_returns_controlled_422(self) -> None:
        workspace_id = self._create_workspace_id()

        response = self.client.put(
            f"/api/workspaces/{workspace_id}/metadata",
            json=build_metadata_payload(title="", artist="Unit Test"),
        )

        self.assertEqual(response.status_code, 422)
        payload = response.json()["detail"]
        self.assertEqual(payload["code"], "INVALID_METADATA")
        self.assertEqual(payload["message"], "Song title is required before generation.")
        self.assertEqual(payload["fields"]["title"], "Title is required.")

    def test_generate_fails_with_422_and_does_not_create_job_when_metadata_is_incomplete(self) -> None:
        workspace_id = self._create_workspace_id()

        with patch.object(
            self.metadata_service,
            "extract_audio_metadata",
            return_value=AudioMetadataSuggestion(durationMs=120000),
        ), patch.object(
            self.job_manager,
            "create_job",
            side_effect=AssertionError("generation job should not start"),
        ) as create_job:
            upload = self._upload_audio(workspace_id)
            self.assertEqual(upload.status_code, 200)
            response = self.client.post(f"/api/workspaces/{workspace_id}/generate")

        self.assertEqual(response.status_code, 422)
        payload = response.json()["detail"]
        self.assertEqual(payload["code"], "INVALID_METADATA")
        self.assertEqual(payload["fields"]["title"], "Title is required.")
        create_job.assert_not_called()

    def test_generate_succeeds_after_valid_metadata_is_saved(self) -> None:
        workspace_id = self._create_workspace_id()
        job_payload = {
            "jobId": "job-123",
            "workspaceId": workspace_id,
            "status": "queued",
            "completedStages": 0,
            "totalStages": 0,
            "overallProgressPercent": 0,
            "latestMessage": "Queued",
            "warnings": [],
            "errors": [],
            "artifactIds": [],
            "startedAt": "2026-07-17T00:00:00Z",
            "updatedAt": "2026-07-17T00:00:00Z",
            "events": [],
        }

        with patch.object(
            self.metadata_service,
            "extract_audio_metadata",
            return_value=AudioMetadataSuggestion(durationMs=120000),
        ):
            upload = self._upload_audio(workspace_id)
            self.assertEqual(upload.status_code, 200)

        metadata = self.client.put(
            f"/api/workspaces/{workspace_id}/metadata",
            json=build_metadata_payload(title="Ready Song", artist="Unit Test"),
        )
        self.assertEqual(metadata.status_code, 200)
        self.assertTrue(metadata.json()["readyForGeneration"])

        with patch.object(self.job_manager, "create_job", return_value=job_payload) as create_job:
            response = self.client.post(f"/api/workspaces/{workspace_id}/generate")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["jobId"], "job-123")
        create_job.assert_called_once_with(workspace_id)

    def _create_workspace_id(self) -> str:
        return self.client.post("/api/workspaces").json()["workspace"]["workspaceId"]

    def _upload_audio(self, workspace_id: str, content: bytes = VALID_MP3_HEADER):
        return self.client.post(
            f"/api/workspaces/{workspace_id}/audio",
            files={
                "file": ("song.mp3", io.BytesIO(content), "audio/mpeg"),
            },
        )


class DifficultySettingsModelTests(unittest.TestCase):
    def test_old_payload_loads_safe_defaults(self) -> None:
        settings = DifficultySettings.model_validate(
            {
                "candidateCount": 8,
                "rootSeed": 42,
                "timingVariation": False,
                "tournamentEnabled": True,
                "hybridAssemblyEnabled": True,
            }
        )
        self.assertEqual(settings.mapping_preset, "balanced")
        self.assertEqual(settings.difficulty_target, "auto")
        self.assertEqual(settings.circle_density, 0.5)
        self.assertEqual(settings.jump_intensity, 0.5)
        self.assertEqual(settings.aggression, 0.5)
        self.assertEqual(settings.evolution_passes, 2)
        self.assertEqual(settings.seed_mode, "auto")
        self.assertEqual(settings.replay_profile, "advanced")
        self.assertEqual(settings.section_sensitivity, 0.5)

    def test_full_payload_round_trips(self) -> None:
        payload = {
            "candidateCount": 5,
            "rootSeed": 1234,
            "timingVariation": False,
            "tournamentEnabled": True,
            "hybridAssemblyEnabled": True,
            "mappingPreset": "technical",
            "difficultyTarget": "custom",
            "customTargetStar": 5.0,
            "customMinStar": 4.0,
            "customMaxStar": 6.0,
            "circleDensity": 0.7,
            "sliderDensity": 0.3,
            "spinnerFrequency": 0.2,
            "jumpIntensity": 0.6,
            "streamIntensity": 0.8,
            "burstIntensity": 0.7,
            "rhythmComplexity": 0.65,
            "patternVariety": 0.75,
            "spacing": 0.55,
            "aggression": 0.6,
            "evolutionPasses": 3,
            "seedMode": "manual",
            "replayProfile": "tournament",
            "sectionSensitivity": 0.4,
        }
        settings = DifficultySettings.model_validate(payload)
        dumped = settings.model_dump(by_alias=True)
        for key, value in payload.items():
            self.assertEqual(dumped[key], value, key)

    def test_custom_difficulty_requires_valid_range(self) -> None:
        with self.assertRaises(ValueError):
            DifficultySettings.model_validate(
                {
                    "candidateCount": 5,
                    "rootSeed": 42,
                    "difficultyTarget": "custom",
                    "customTargetStar": 8.0,
                    "customMinStar": 9.0,
                    "customMaxStar": 7.0,
                }
            )
        with self.assertRaises(ValueError):
            DifficultySettings.model_validate(
                {
                    "candidateCount": 5,
                    "rootSeed": 42,
                    "difficultyTarget": "custom",
                    "customTargetStar": 5.0,
                    "customMinStar": None,
                    "customMaxStar": None,
                }
            )

    def test_evolution_passes_and_control_ranges_validated(self) -> None:
        with self.assertRaises(ValueError):
            DifficultySettings.model_validate(
                {"candidateCount": 5, "rootSeed": 42, "evolutionPasses": 9}
            )
        with self.assertRaises(ValueError):
            DifficultySettings.model_validate(
                {"candidateCount": 5, "rootSeed": 42, "circleDensity": 1.5}
            )
        with self.assertRaises(ValueError):
            DifficultySettings.model_validate(
                {"candidateCount": 5, "rootSeed": 42, "mappingPreset": "weird"}
            )

    def test_default_workspace_metadata_carries_new_fields(self) -> None:
        metadata = build_default_workspace_metadata()
        for difficulty in ("easy", "normal", "hard"):
            settings = metadata.difficulty_settings[difficulty]
            self.assertEqual(settings.mapping_preset, "balanced")
            self.assertEqual(settings.evolution_passes, 2)
            self.assertEqual(settings.replay_profile, "advanced")

    def test_metadata_payload_with_new_fields_parses(self) -> None:
        metadata = WorkspaceMetadata.model_validate(
            build_metadata_payload(title="Config Test", artist="Unit Test")
        )
        settings = metadata.difficulty_settings["easy"]
        self.assertEqual(settings.circle_density, 0.5)
        self.assertEqual(settings.mapping_preset, "balanced")


class ArtifactServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        os.environ["PULSE_LOCAL_API_WORKSPACES_ROOT"] = self._temp_dir.name
        get_local_api_config.cache_clear()

        self.config = get_local_api_config()
        self.workspace_manager = WorkspaceManager(self.config)
        self.artifact_service = ArtifactService(self.config, self.workspace_manager)

    def tearDown(self) -> None:
        get_local_api_config.cache_clear()
        os.environ.pop("PULSE_LOCAL_API_WORKSPACES_ROOT", None)
        self._temp_dir.cleanup()

    def test_result_summary_prefers_hybrid_outputs_and_resolves_artifacts(self) -> None:
        manifest = self.workspace_manager.create_workspace()
        workspace_id = manifest.workspace_id
        paths = self.workspace_manager.get_workspace_paths(workspace_id)

        audio_path = paths.source_dir / "source-audio.mp3"
        audio_path.write_bytes(b"fake mp3")
        manifest = manifest.model_copy(
            update={
                "audio": UploadedFileDescriptor(
                    originalFilename="song.mp3",
                    normalizedFilename="source-audio.mp3",
                    relativePath="source/source-audio.mp3",
                    sizeBytes=audio_path.stat().st_size,
                    contentType="audio/mpeg",
                    sha256="abc123",
                    detectedMetadata=AudioMetadataSuggestion(durationMs=123456),
                ),
                "metadata": manifest.metadata.model_copy(
                    update={
                        "title": "Summary Song",
                        "artist": "Unit Test",
                        "selected_difficulties": ["easy"],
                    },
                    deep=True,
                ),
            },
            deep=True,
        )
        manifest = self.workspace_manager.save_manifest(manifest)

        write_json(paths.generated_maps_dir / "easy.json", {"objects": [{"id": 1}]})
        write_json(paths.improved_maps_dir / "easy.json", {"objects": [{"id": 1}, {"id": 2}]})
        write_json(
            paths.hybrid_maps_dir / "easy.json",
            {"objects": [{"id": 1}, {"id": 2}, {"id": 3}]},
        )
        write_json(paths.generated_reports_dir / "easy-report.json", {"scores": {"overall": 80.0}})
        write_json(paths.hybrid_reports_dir / "easy-report.json", {"scores": {"overall": 92.5}})
        write_json(
            paths.tournaments_dir / "easy-tournament.json",
            {"champion": {"candidateIndex": 4}},
        )
        write_json(
            paths.sections_dir / "sections.json",
            {"sections": [{"id": 1}, {"id": 2}, {"id": 3}]},
        )
        write_json(
            paths.hybrid_details_dir / "easy-assembly.json",
            {"promotion": {"promoted": True}},
        )
        (paths.hybrid_details_dir / "easy-transitions.json").write_text(
            json.dumps({"transitions": []}),
            encoding="utf-8",
        )
        (paths.exports_osu_dir / "Unit Test - Summary Song (osu-map-ai) [Hybrid Easy].osu").write_text(
            "osu file format v14\n",
            encoding="utf-8",
        )
        (paths.exports_mapsets_dir / "Unit Test - Summary Song.osz").write_bytes(b"osz")

        manifest = self.artifact_service.refresh_workspace_artifacts(manifest)
        summary = self.artifact_service.build_result_summary(manifest)

        self.assertIsNotNone(summary)
        self.assertEqual(summary.title, "Summary Song")
        self.assertEqual(summary.package_size_bytes, 3)
        self.assertEqual(len(summary.difficulties), 1)

        difficulty = summary.difficulties[0]
        self.assertEqual(difficulty.final_map_kind, "hybrid")
        self.assertEqual(difficulty.object_count, 3)
        self.assertEqual(difficulty.score, 92.5)
        self.assertEqual(difficulty.candidate_winner, 4)
        self.assertEqual(difficulty.section_count, 3)
        self.assertTrue(difficulty.promoted)
        self.assertIsNotNone(difficulty.map_artifact_id)
        self.assertIsNotNone(difficulty.osu_artifact_id)

        package_artifact_id = summary.package_artifact_id
        self.assertIsNotNone(package_artifact_id)
        _, artifact, resolved_path = self.artifact_service.resolve_artifact(package_artifact_id)
        self.assertEqual(artifact.group, ".osz package")
        self.assertTrue(resolved_path.exists())


class WorkspaceManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        os.environ["PULSE_LOCAL_API_WORKSPACES_ROOT"] = self._temp_dir.name
        get_local_api_config.cache_clear()
        self.config = get_local_api_config()
        self.workspace_manager = WorkspaceManager(self.config)

    def tearDown(self) -> None:
        get_local_api_config.cache_clear()
        os.environ.pop("PULSE_LOCAL_API_WORKSPACES_ROOT", None)
        self._temp_dir.cleanup()

    def test_resolve_audio_source_path_accepts_registered_workspace_file(self) -> None:
        manifest = self.workspace_manager.create_workspace()
        paths = self.workspace_manager.get_workspace_paths(manifest.workspace_id)
        audio_path = paths.source_dir / "source-audio.mp3"
        audio_path.write_bytes(b"fake mp3")
        manifest = self.workspace_manager.save_manifest(
            manifest.model_copy(
                update={
                    "audio": UploadedFileDescriptor(
                        originalFilename="song.mp3",
                        normalizedFilename="source-audio.mp3",
                        relativePath="source/source-audio.mp3",
                        sizeBytes=audio_path.stat().st_size,
                        contentType="audio/mpeg",
                        sha256="abc123",
                        detectedMetadata=None,
                    )
                },
                deep=True,
            )
        )

        resolved = self.workspace_manager.resolve_audio_source_path(manifest)

        self.assertEqual(resolved, audio_path.resolve())

    def test_resolve_audio_source_path_rejects_workspace_escape(self) -> None:
        manifest = self.workspace_manager.create_workspace()
        outside_audio = Path(self._temp_dir.name) / "outside.mp3"
        outside_audio.write_bytes(b"fake mp3")
        manifest = self.workspace_manager.save_manifest(
            manifest.model_copy(
                update={
                    "audio": UploadedFileDescriptor(
                        originalFilename="song.mp3",
                        normalizedFilename="source-audio.mp3",
                        relativePath="../outside.mp3",
                        sizeBytes=outside_audio.stat().st_size,
                        contentType="audio/mpeg",
                        sha256="abc123",
                        detectedMetadata=None,
                    )
                },
                deep=True,
            )
        )

        with self.assertRaisesRegex(
            LocalApiValidationError,
            "Relative path traversal is not allowed.",
        ):
            self.workspace_manager.resolve_audio_source_path(manifest)


def build_metadata_payload(*, title: str, artist: str) -> dict[str, object]:
    return {
        "title": title,
        "artist": artist,
        "titleUnicode": "",
        "artistUnicode": "",
        "creator": "osu-map-ai",
        "source": "",
        "tags": "",
        "selectedDifficulties": ["easy"],
        "difficultySettings": {
            "easy": {
                "candidateCount": 8,
                "rootSeed": 42,
                "timingVariation": False,
                "tournamentEnabled": True,
                "hybridAssemblyEnabled": True,
            },
            "normal": {
                "candidateCount": 10,
                "rootSeed": 42,
                "timingVariation": False,
                "tournamentEnabled": True,
                "hybridAssemblyEnabled": True,
            },
            "hard": {
                "candidateCount": 12,
                "rootSeed": 42,
                "timingVariation": False,
                "tournamentEnabled": True,
                "hybridAssemblyEnabled": True,
            },
        },
    }


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
