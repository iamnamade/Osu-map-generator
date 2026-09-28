#!/usr/bin/env python3
"""P3.4 — bounded job-event log and ``?since=`` tailing tests.

Pins the ring-buffer behavior of the job event log: the in-memory event list
stays capped, indexes stay monotonic across trims, and the ``since`` watermark
returns only newer events so tailing clients never miss an entry.
"""
from __future__ import annotations

import os
import tempfile
import unittest

from fastapi.testclient import TestClient

from tools.local_api import app as local_api_app
from tools.local_api.config import get_local_api_config
from tools.local_api.job_models import MAX_JOB_EVENTS


class BoundedJobEventLogTests(unittest.TestCase):
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
        job_id = f"bounded-log-job-{len(self._registered_jobs) + 1}"
        self.job_manager._jobs[job_id] = JobRecord(
            state=JobRuntimeState(job_id=job_id, workspace_id=workspace_id)
        )
        self._registered_jobs.append(job_id)
        return job_id

    def test_event_log_stays_bounded(self) -> None:
        job_id = self._register_job()
        for number in range(MAX_JOB_EVENTS + 50):
            self.job_manager.log(job_id, "info", f"event {number}")

        state = self.job_manager.get_job(job_id)
        self.assertEqual(len(state.events), MAX_JOB_EVENTS)
        # Oldest entries are evicted; indexes stay monotonic and unique.
        indexes = [event.index for event in state.events]
        self.assertEqual(indexes, sorted(indexes))
        self.assertEqual(len(set(indexes)), len(indexes))
        self.assertEqual(state.events[-1].message, f"event {MAX_JOB_EVENTS + 49}")

    def test_since_returns_only_newer_events(self) -> None:
        job_id = self._register_job()
        for number in range(10):
            self.job_manager.log(job_id, "info", f"event {number}")

        full = self.job_manager.get_job(job_id)
        self.assertEqual(len(full.events), 10)

        watermark = full.events[4].index
        tailed = self.job_manager.get_job(job_id, since=watermark)
        self.assertEqual([event.message for event in tailed.events], [f"event {n}" for n in range(5, 10)])

    def test_since_endpoint_tails_across_ring_buffer_trim(self) -> None:
        job_id = self._register_job()
        for number in range(MAX_JOB_EVENTS + 10):
            self.job_manager.log(job_id, "info", f"event {number}")

        # Client saw only the first event, then the buffer overflowed.
        first = self.job_manager.get_job(job_id).events[0]
        response = self.client.get(f"/api/jobs/{job_id}?since={first.index}").json()
        messages = [event["message"] for event in response["events"]]
        # The evicted range is gone but the tail after the watermark is intact.
        self.assertEqual(response["events"][-1]["message"], f"event {MAX_JOB_EVENTS + 9}")
        self.assertTrue(all(msg != f"event {first.index - 1}" for msg in messages))
        self.assertNotIn(first.message, messages)

    def test_since_zero_returns_whole_buffer(self) -> None:
        job_id = self._register_job()
        for number in range(5):
            self.job_manager.log(job_id, "info", f"event {number}")

        response = self.client.get(f"/api/jobs/{job_id}").json()
        self.assertEqual(len(response["events"]), 5)


if __name__ == "__main__":
    unittest.main()
