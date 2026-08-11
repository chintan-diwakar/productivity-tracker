from __future__ import annotations

import io
import json
import unittest
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

from desk_focus_tracker.domain import Status
from desk_focus_tracker.engine_server import EngineService, serve, snapshot_mapping
from desk_focus_tracker.metrics import calculate_daily_metrics


class EngineSnapshotTest(unittest.TestCase):
    def test_serializes_snapshot_for_the_frontend(self) -> None:
        sampled_at = datetime(2026, 8, 10, 12, 30, tzinfo=timezone.utc)
        snapshot = SimpleNamespace(
            status=Status.FOCUSED_SCREEN,
            status_seconds=4.5,
            metrics=calculate_daily_metrics(date(2026, 8, 10), {"FOCUSED_SCREEN": 4.5}),
            session_metrics=None,
            last_sample=sampled_at,
            running=True,
            paused=False,
            error=None,
        )

        result = snapshot_mapping(snapshot)

        self.assertEqual(result["status"], "FOCUSED_SCREEN")
        self.assertEqual(result["last_sample"], sampled_at.isoformat())
        self.assertEqual(result["metrics"]["status_seconds"]["FOCUSED_SCREEN"], 4.5)


class EngineServiceTest(unittest.TestCase):
    def test_serializes_available_cameras(self) -> None:
        controller = Mock()
        controller.available_cameras.return_value = (
            SimpleNamespace(
                to_mapping=lambda: {
                    "index": 0,
                    "name": "Built-in Camera",
                    "path": "/dev/video0",
                }
            ),
        )

        result = EngineService(controller).execute("list_cameras", {})

        self.assertEqual(
            result,
            [{"index": 0, "name": "Built-in Camera", "path": "/dev/video0"}],
        )

    def test_one_request_produces_one_json_response(self) -> None:
        controller = Mock()
        controller.models_ready.return_value = True
        output = io.StringIO()

        status = serve(
            EngineService(controller),
            io.StringIO('{"id":7,"command":"models_ready"}\n'),
            output,
        )

        self.assertEqual(status, 0)
        self.assertEqual(
            json.loads(output.getvalue()),
            {"id": 7, "ok": True, "result": True},
        )
        controller.stop.assert_called_once_with()

    def test_rejects_invalid_arguments_without_stopping_the_protocol(self) -> None:
        controller = Mock()
        output = io.StringIO()

        serve(
            EngineService(controller),
            io.StringIO(
                '{"id":1,"command":"pause_for","arguments":{"seconds":0}}\n'
                '{"id":2,"command":"shutdown"}\n'
            ),
            output,
        )

        responses = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertFalse(responses[0]["ok"])
        self.assertIn("positive", responses[0]["error"])
        self.assertTrue(responses[1]["ok"])
        controller.stop.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
