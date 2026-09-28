#!/usr/bin/env python3
"""P2.4 — per-stage timing telemetry tests.

The pipeline records the measured wall-clock duration of every stage; these
tests pin that the durations reach the job response (and the frontend's
``stageTimings`` contract) with the right rounding and status.
"""
from __future__ import annotations

import os
import tempfile
import unittest

from fastapi.testclient import TestClient

from tools.local_api import app as local_api_app
from tools.local_api.config import get_local_api_config


class JobStageTimingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        os.environ["PULSE_LOCAL_API_WORKSPACES_ROOT"] = self._temp_dir.name
        get_local_api_config.cache_clear()
        local_api_app._services.cache_clear()
        self.client = TestClient(local_api_app.create_app())
        services = local_api_app._services()
        self.job_manager = services["job_manager"]
        self._registered_jobs: list[str] = []

    def tearDown(self) -> None:
        for job_id in self._registered_jobs:
            self.job_manager._jobs.pop(job_id, None)
        self.client.close()
        local_api_app._services.cache_clear()
        get_local_api_config.cache_clear()
        os.environ.pop("PULSE_LOCAL_API_WORKSPACES_ROOT", None)
        self._temp_dir.cleanup()

    def _register_job(self) -> str:
        from tools.local_api.job_models import JobRecord, JobRuntimeState

        workspace_id = self.client.post("/api/workspaces").json()["workspace"]["workspaceId"]
        job_id = f"telemetry-job-{len(self._registered_jobs) + 1}"
        self.job_manager._jobs[job_id] = JobRecord(
            state=JobRuntimeState(job_id=job_id, workspace_id=workspace_id)
        )
        self._registered_jobs.append(job_id)
        return job_id

    def test_stage_timing_is_exposed_with_rounding(self) -> None:
        job_id = self._register_job()
        self.job_manager.record_stage_timing(
            job_id,
            index=1,
            stage_code="analyze-audio",
            stage_label="Analyze audio",
            difficulty=None,
            duration_ms=1234.6,
            status="completed",
        )

        response = self.client.get(f"/api/jobs/{job_id}").json()
        timings = response["stageTimings"]
        self.assertEqual(len(timings), 1)
        self.assertEqual(timings[0]["stage"], "analyze-audio")
        self.assertEqual(timings[0]["label"], "Analyze audio")
        self.assertEqual(timings[0]["durationMs"], 1235)
        self.assertEqual(timings[0]["status"], "completed")
        self.assertIsNone(timings[0]["difficulty"])

    def test_timings_accumulate_in_stage_order(self) -> None:
        job_id = self._register_job()
        self.job_manager.record_stage_timing(
            job_id,
            index=1,
            stage_code="analyze",
            stage_label="Analyze",
            difficulty=None,
            duration_ms=500,
            status="completed",
        )
        self.job_manager.record_stage_timing(
            job_id,
            index=2,
            stage_code="generate-easy",
            stage_label="Generate Easy",
            difficulty="easy",
            duration_ms=2500,
            status="completed",
        )

        timings = self.client.get(f"/api/jobs/{job_id}").json()["stageTimings"]
        self.assertEqual([timing["stage"] for timing in timings], ["analyze", "generate-easy"])
        self.assertEqual(timings[1]["difficulty"], "easy")
        self.assertEqual(timings[1]["durationMs"], 2500)

    def test_terminal_stage_statuses_are_preserved(self) -> None:
        job_id = self._register_job()
        self.job_manager.record_stage_timing(
            job_id,
            index=3,
            stage_code="export",
            stage_label="Export",
            difficulty="hard",
            duration_ms=10.4,
            status="failed",
        )
        self.job_manager.record_stage_timing(
            job_id,
            index=4,
            stage_code="package",
            stage_label="Package",
            difficulty=None,
            duration_ms=-5,
            status="cancelled",
        )

        timings = self.client.get(f"/api/jobs/{job_id}").json()["stageTimings"]
        self.assertEqual(timings[0]["status"], "failed")
        self.assertEqual(timings[0]["durationMs"], 10)
        self.assertEqual(timings[1]["status"], "cancelled")
        # Negative durations are clamped rather than surfaced.
        self.assertEqual(timings[1]["durationMs"], 0)


if __name__ == "__main__":
    unittest.main()
