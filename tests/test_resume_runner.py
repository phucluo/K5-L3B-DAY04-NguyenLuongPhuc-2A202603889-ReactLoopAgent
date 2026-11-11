"""Kiểm tra runner bằng model giả; không gọi API."""
import contextlib
import fcntl
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "evals"))

import run_evals_resume as runner
from request_control import RequestGate
from resume_support import load_cases, load_checkpoint
from test_lab import tool_call, final


def offline_gate():
    now = [0.0]

    def advance(seconds):
        now[0] += seconds

    return RequestGate(
        9, clock=lambda: now[0], sleeper=advance
    )


class ResumeRunnerTests(unittest.TestCase):
    def test_agent_tool_judge_and_keep_zero_on_resume(self):
        case = load_cases("core")[0]
        config = runner.make_config()

        agent = Mock(key="offline-test")
        agent.complete.side_effect = [
            tool_call(
                "offline-call", "get_status",
                '{"provider":"github","component":"Actions"}',
            ),
            final("OFFLINE TEST"),
        ]

        judge = Mock(key="offline-test")
        judge.complete.return_value = final(json.dumps({
            "factuality": 0,
            "completeness": 0,
            "evidence": 0,
            "boundaries": 0,
            "reason": "offline test",
            "improvement": "offline test",
        }))
        factory = Mock(side_effect=[agent, judge])

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "offline_test.json"

            for _ in range(2):
                report = load_checkpoint(path, config)
                with contextlib.redirect_stdout(io.StringIO()):
                    runner.process_cases(
                        report, path, offline_gate(),
                        provider_factory=factory,
                        only_case=case["id"],
                    )

            self.assertEqual(factory.call_count, 2)
            self.assertEqual(agent.complete.call_count, 2)
            self.assertEqual(judge.complete.call_count, 1)

            item = report["cases"][0]
            self.assertEqual(item["result"]["status"], "completed")
            self.assertEqual(item["grade"]["score"], 0)
            self.assertIsNone(report["summary"]["score_0_100"])

            messages = agent.complete.call_args_list[1].args[0]
            self.assertEqual(messages[1]["content"], case["question"])
            tool_messages = [
                m for m in messages if m["role"] == "tool"
            ]
            self.assertEqual(
                tool_messages[0]["tool_call_id"], "offline-call"
            )
            self.assertEqual(
                json.loads(tool_messages[0]["content"])["provider"],
                "github",
            )

            judge_input = json.loads(
                judge.complete.call_args.args[0][-1]["content"]
            )
            self.assertEqual(judge_input["expected"], case["expected"])

            sessions = report["request_sessions"]
            self.assertEqual(
                [e["stage"] for e in sessions[0]["events"]],
                ["agent", "agent", "judge"],
            )
            self.assertEqual(sessions[1]["events"], [])

    def test_cli_refuses_when_repo_lock_is_held(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "offline_test.json"
            with (ROOT / ".eval_resume.lock").open("a") as lock:
                fcntl.flock(
                    lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB
                )
                with (
                    patch.object(sys, "argv", [
                        "run_evals_resume.py",
                        "--output", str(path),
                        "--max-requests", "9",
                    ]),
                    patch.object(
                        runner, "process_cases",
                        side_effect=AssertionError(
                            "Không được chạy khi đang bị khóa!"
                        ),
                    ) as process,
                    contextlib.redirect_stderr(
                        io.StringIO()
                    ) as errors,
                ):
                    self.assertEqual(runner.main(), 2)
                    process.assert_not_called()
                    self.assertIn(
                        "phiên resume khác", errors.getvalue()
                    )
                    self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()