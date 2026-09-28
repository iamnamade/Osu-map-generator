#!/usr/bin/env python3
"""P0 hardening tests (Phase 6 roadmap).

Covers:
- P0.2 — stage watchdog, orphaned-running reconciliation, cancel polling
  inside evolution progress callbacks.
- P0.4 — magic-byte upload verification, canonical Content-Type serving,
  rejection of spoofed declarations.
"""
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
from tools.local_api.config import get_local_api_config
from tools.local_api.security import detect_content_kind, verify_upload_content
from tools.local_api.errors import LocalApiUnsupportedMediaTypeError

# Real magic headers.
MP3_ID3 = b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\x00" * 64
MP3_SYNC = b"\xff\xfb\x90\x44" + b"\x00" * 64
WAV_RIFF = b"RIFF\x24\x00\x00\x00WAVEfmt " + b"\x00" * 48
OGG = b"OggS\x00\x02" + b"\x00" * 62
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 56
JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 57
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 48
TXT = b"just some text, definitely not audio or an image" + b"\x00" * 32


class ContentSniffingTests(unittest.TestCase):
    """P0.4 unit tests for header detection."""

    def test_detects_audio_kinds(self) -> None:
        self.assertEqual(detect_content_kind(MP3_ID3), "mp3")
        self.assertEqual(detect_content_kind(MP3_SYNC), "mp3")
        self.assertEqual(detect_content_kind(WAV_RIFF), "wav")
        self.assertEqual(detect_content_kind(OGG), "ogg")

    def test_detects_image_kinds(self) -> None:
        self.assertEqual(detect_content_kind(PNG), "png")
        self.assertEqual(detect_content_kind(JPEG), "jpeg")
        self.assertEqual(detect_content_kind(WEBP), "webp")

    def test_rejects_plain_text(self) -> None:
        self.assertIsNone(detect_content_kind(TXT))

    def test_verify_returns_canonical_content_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "song.mp3"
            path.write_bytes(MP3_ID3)
            self.assertEqual(verify_upload_content(path, ".mp3"), "audio/mpeg")

    def test_verify_rejects_spoofed_extension(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "evil.mp3"
            path.write_bytes(TXT)
            with self.assertRaises(LocalApiUnsupportedMediaTypeError):
                verify_upload_content(path, ".mp3")

    def test_verify_rejects_wrong_kind_for_extension(self) -> None:
        """A PNG renamed to .webp must NOT pass (exact extension-kind match)."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "image.webp"
            path.write_bytes(PNG)
            with self.assertRaises(LocalApiUnsupportedMediaTypeError):
                verify_upload_content(path, ".webp")


class P0UploadRouteTests(unittest.TestCase):
    """P0.4 end-to-end upload rejection through the API."""

    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        os.environ["PULSE_LOCAL_API_WORKSPACES_ROOT"] = self._temp_dir.name
        get_local_api_config.cache_clear()
        local_api_app._services.cache_clear()
        self.client = TestClient(local_api_app.create_app())
        services = local_api_app._services()
        self.metadata_service = services["metadata_service"]

    def tearDown(self) -> None:
        self.client.close()
        local_api_app._services.cache_clear()
        get_local_api_config.cache_clear()
        os.environ.pop("PULSE_LOCAL_API_WORKSPACES_ROOT", None)
        self._temp_dir.cleanup()

    def _create_workspace(self) -> str:
        return self.client.post("/api/workspaces").json()["workspace"]["workspaceId"]

    def test_renamed_text_file_is_rejected_with_415(self) -> None:
        workspace_id = self._create_workspace()
        response = self.client.post(
            f"/api/workspaces/{workspace_id}/audio",
            files={"file": ("song.mp3", io.BytesIO(TXT), "audio/mpeg")},
        )
        self.assertEqual(response.status_code, 415)
        manifest = local_api_app._services()["workspace_manager"].load_manifest(workspace_id)
        self.assertIsNone(manifest.audio)

    def test_valid_mp3_upload_stores_canonical_content_type(self) -> None:
        workspace_id = self._create_workspace()
        from tools.local_api.models import AudioMetadataSuggestion

        with patch.object(
            self.metadata_service,
            "extract_audio_metadata",
            return_value=AudioMetadataSuggestion(durationMs=120000),
        ):
            response = self.client.post(
                f"/api/workspaces/{workspace_id}/audio",
                files={"file": ("song.mp3", io.BytesIO(MP3_ID3), "application/x-fake")},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["workspace"]["audio"]["contentType"],
            "audio/mpeg",
            "P0.4: spoofed client content type must be replaced by the sniffed canonical type",
        )

    def test_spoofed_background_is_rejected(self) -> None:
        workspace_id = self._create_workspace()
        response = self.client.post(
            f"/api/workspaces/{workspace_id}/background",
            files={"file": ("bg.png", io.BytesIO(TXT), "image/png")},
        )
        self.assertEqual(response.status_code, 415)


class P0WatchdogTests(unittest.TestCase):
    """P0.2 watchdog + reconciliation units.

    These tests register job records white-box (without spawning pipeline
    threads) so Windows temp-dir cleanup never races a live worker.
    """

    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        os.environ["PULSE_LOCAL_API_WORKSPACES_ROOT"] = self._temp_dir.name
        get_local_api_config.cache_clear()
        local_api_app._services.cache_clear()
        self.client = TestClient(local_api_app.create_app())
        services = local_api_app._services()
        self.job_manager = services["job_manager"]
        self.workspace_manager = services["workspace_manager"]
        self._registered_jobs: list[str] = []
        self._registered_workspaces: list[str] = []

    def tearDown(self) -> None:
        for job_id in self._registered_jobs:
            self.job_manager._jobs.pop(job_id, None)
            # _active_by_workspace cleanup is best-effort here.
        self.client.close()
        local_api_app._services.cache_clear()
        get_local_api_config.cache_clear()
        os.environ.pop("PULSE_LOCAL_API_WORKSPACES_ROOT", None)
        self._temp_dir.cleanup()

    def _register_job(self, workspace_id: str) -> str:
        """Create a queued JobRecord without launching a pipeline thread."""
        from tools.local_api.job_models import JobRecord, JobRuntimeState

        job_id = f"test-job-{len(self._registered_jobs) + 1}"
        state = JobRuntimeState(job_id=job_id, workspace_id=workspace_id)
        self.job_manager._jobs[job_id] = JobRecord(state=state)
        self.job_manager._active_by_workspace[workspace_id] = job_id
        self._registered_jobs.append(job_id)
        self._registered_workspaces.append(workspace_id)
        return job_id

    def test_stage_timeout_fails_job(self) -> None:
        from tools.local_api.job_manager import LocalApiStageTimeoutError

        workspace_id = self.client.post("/api/workspaces").json()["workspace"]["workspaceId"]
        job_id = self._register_job(workspace_id)

        def _hang() -> None:
            import time

            time.sleep(5)

        with patch.dict(os.environ, {"PULSE_LOCAL_API_STAGE_TIMEOUT_SECONDS": "0.2"}):
            with self.assertRaises(LocalApiStageTimeoutError):
                self.job_manager.run_stage_with_watchdog(job_id, "hang stage", _hang)

    def test_watchdog_passes_through_normal_stages(self) -> None:
        workspace_id = self.client.post("/api/workspaces").json()["workspace"]["workspaceId"]
        job_id = self._register_job(workspace_id)
        results: list[str] = []
        self.job_manager.run_stage_with_watchdog(
            job_id, "quick stage", lambda: results.append("ran")
        )
        self.assertEqual(results, ["ran"])

    def test_reconcile_orphaned_running_workspaces(self) -> None:
        workspace_id = self.client.post("/api/workspaces").json()["workspace"]["workspaceId"]
        # Simulate a crash: manifest claims running, no job exists.
        manifest = self.workspace_manager.load_manifest(workspace_id)
        self.workspace_manager.save_manifest(
            manifest.model_copy(update={"job_status": "running"}, deep=True)
        )
        reconciled = self.job_manager.reconcile_orphaned_running_jobs([workspace_id])
        self.assertEqual(reconciled, [workspace_id])
        self.assertEqual(
            self.workspace_manager.load_manifest(workspace_id).job_status,
            "failed",
        )

    def test_reconcile_skips_live_jobs(self) -> None:
        workspace_id = self.client.post("/api/workspaces").json()["workspace"]["workspaceId"]
        manifest = self.workspace_manager.load_manifest(workspace_id)
        self.workspace_manager.save_manifest(
            manifest.model_copy(update={"job_status": "running"}, deep=True)
        )
        self._register_job(workspace_id)  # live in-memory record exists now
        reconciled = self.job_manager.reconcile_orphaned_running_jobs([workspace_id])
        self.assertEqual(reconciled, [])

    def test_recover_orphaned_workspaces_from_cleanup_service(self) -> None:
        services = local_api_app._services()
        workspace_id = self.client.post("/api/workspaces").json()["workspace"]["workspaceId"]
        manifest = self.workspace_manager.load_manifest(workspace_id)
        self.workspace_manager.save_manifest(
            manifest.model_copy(update={"job_status": "running"}, deep=True)
        )
        recovered = services["cleanup_service"].recover_orphaned_workspaces()
        self.assertIn(workspace_id, recovered)

    def test_cancel_requested_polled_in_progress_callback(self) -> None:
        """Cancellation must be detectable from the evolution callback path.

        The P0.2 change makes the evolution ``progress_callback`` invoke
        ``_check_cancellation`` before every candidate; this pins that the
        check raises once a cancel request is registered.
        """
        from tools.local_api.errors import LocalApiCancellationRequested

        services = local_api_app._services()
        workspace_id = self.client.post("/api/workspaces").json()["workspace"]["workspaceId"]
        job_id = self._register_job(workspace_id)
        runner = services["pipeline_runner"]
        # Before the cancel request: no raise.
        runner._check_cancellation(services["job_manager"], job_id)
        services["job_manager"].request_cancel(job_id)
        # After the cancel request: the callback's poll raises.
        with self.assertRaises(LocalApiCancellationRequested):
            runner._check_cancellation(services["job_manager"], job_id)


if __name__ == "__main__":
    unittest.main()
