"""Eval có checkpoint theo giai đoạn agent/judge."""
import json
from pathlib import Path
import sys
import time
import argparse
import fcntl

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent import run_agent
from providers import Provider
from scenarios import ScenarioTools
from bonus.tools import BonusTools
from grading import grade_case, summarize
from request_control import RequestGate
from controlled_provider import ControlledProvider, error_details
from resume_support import (
    load_cases, validate_checkpoint, save_checkpoint,
    load_checkpoint, next_stage,
)


def process_cases(
    report, path, gate, provider_factory=Provider, only_case=None,
):
    config = report["config"]
    validate_checkpoint(report, config)
    original = {
        case["id"]: case for case in load_cases(config["dataset"])
    }
    only_case = only_case.upper() if only_case else None
    if only_case and only_case not in original:
        raise ValueError("Không tìm thấy case.")

    session = {
        "started_at_unix": time.time(),
        "max_requests": gate.max_requests,
        "events": [],
    }
    report.setdefault("request_sessions", []).append(session)

    def persist():
        session["requests_reserved"] = gate.used
        session["stop_reason"] = gate.stop_reason
        save_checkpoint(path, report)

    def make_provider(case_id, stage):
        prefix = "judge_" if stage == "judge" else ""
        base = provider_factory(
            config[prefix + "provider"],
            config[prefix + "model"],
        )
        return ControlledProvider(
            base, gate, session["events"], case_id, stage,
            on_update=persist,
            output_limit=config["max_tokens"],
        )

    persist()
    try:
        for item in report["cases"]:
            if only_case and item["id"] != only_case:
                continue

            stage = next_stage(item)
            if stage == "done":
                continue

            case = original[item["id"]]
            result = item.get("result")
            required = (
                config["max_steps"] + 1
                if stage == "agent"
                else int(result["status"] == "completed")
            )
            if gate.max_requests - gate.used < required:
                gate.stop_reason = (
                    "Không đủ ngân sách để bắt đầu giai đoạn tiếp."
                )
                break

            print(f"{item['id']}: {stage}", flush=True)

            if stage == "agent":
                try:
                    tools = (
                        BonusTools(
                            "snapshot",
                            scenario=case.get("scenario", "normal"),
                        )
                        if config["dataset"] == "bonus"
                        else ScenarioTools(
                            case.get("scenario", "normal"),
                            case.get("fail", False),
                        )
                    )
                    result = run_agent(
                        case["question"],
                        make_provider(item["id"], "agent"),
                        tools,
                        max_steps=config["max_steps"],
                    )
                    if (
                        not isinstance(result, dict)
                        or not isinstance(result.get("trace"), list)
                    ):
                        raise ValueError("Agent trả kết quả sai contract.")
                except Exception as exc:
                    result = {
                        "status": "error", "answer": "",
                        "trace": [], "usage": [],
                        "error": json.dumps(
                            error_details(exc), ensure_ascii=False
                        ),
                    }

                if item.get("result") is not None:
                    item.setdefault("previous_agent_errors", []).append(
                        item["result"]
                    )
                item["result"] = result
                persist()

                if result.get("status") not in ("completed", "max_steps"):
                    item["grade"] = grade_case(case, result, None)
                    gate.stop_reason = gate.stop_reason or (
                        "Agent chưa hoàn tất; cần kiểm tra trace."
                    )
                    persist()
                    break

            try:
                judge = (
                    None if result["status"] == "max_steps"
                    else make_provider(item["id"], "judge")
                )
                grade = grade_case(case, result, judge)
            except Exception as exc:
                grade = {
                    "score": None, "status": "unscored",
                    "reason": json.dumps(
                        error_details(exc), ensure_ascii=False
                    ),
                    "judge_usage": {},
                }

            item["grade"] = grade
            item.setdefault("grading_attempts", []).append(grade)
            if grade.get("score") is None:
                gate.stop_reason = gate.stop_reason or (
                    "Judge chưa chấm được; dừng để kiểm tra."
                )

            persist()
            print(
                f"{item['id']}: {grade.get('score')} "
                f"({grade['status']})",
                flush=True,
            )
            if gate.stop_reason:
                break
    finally:
        session["finished_at_unix"] = time.time()
        persist()

    return report["summary"]

def make_config(bonus=False, max_steps=None):
    return {
        "provider": "gemini",
        "model": "gemini-3.8-flash",
        "judge_provider": "gemini",
        "judge_model": "gemini-3.5-flash-lite",
        "max_steps": (
            max_steps if max_steps is not None
            else (16 if bonus else 8)
        ),
        "dataset": "bonus" if bonus else "core",
        "mode": "snapshot",
        "reasoning_effort": "low",
        "max_tokens": 4096,
        "workers": 1,
        "min_interval_seconds": 7.0,
        "token_budget_per_minute": 400_000,
        "python_version": sys.version.split()[0],
    }


def show_status(report):
    counts = {"agent": 0, "judge": 0, "done": 0}
    for item in report["cases"]:
        counts[next_stage(item)] += 1

    summary = summarize(report["cases"])
    print("Config:", json.dumps(
        report["config"], ensure_ascii=False, sort_keys=True
    ))
    print("Stages:", counts)
    print(
        f"Đã chấm: {summary['scored_cases']}/"
        f"{summary['total_cases']}"
    )
    print("Điểm toàn bộ:", summary["score_0_100"])


def main():
    parser = argparse.ArgumentParser(
            description="Eval snapshot có checkpoint, dùng Gemini."
    )
    parser.add_argument("--output", required=True)
    parser.add_argument("--bonus", action="store_true")
    parser.add_argument("--case")
    parser.add_argument("--max-steps", type=int)
    parser.add_argument(
        "--max-requests", type=int,
        help="Ngân sách phiên; tự đối chiếu quota ngày còn lại.",
    )
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()

    config = make_config(args.bonus, args.max_steps)
    if config["max_steps"] < 1:
        parser.error("--max-steps phải >= 1")
    if args.max_requests is not None:
        if not 1 <= args.max_requests <= 600:
            parser.error("--max-requests phải từ 1 đến 600")
    if not args.check_only and args.max_requests is None:
        parser.error("Cần chỉ định --max-requests khi chạy thật")
    if args.case:
        args.case = args.case.upper()
        ids = {c["id"] for c in load_cases(config["dataset"])}
        if args.case not in ids:
            parser.error("Không tìm thấy case")

    path = Path(args.output).resolve()
    try:
        if args.check_only:
            report = load_checkpoint(path, config)
            show_status(report)
            print("CHECK_ONLY_OK — không ghi checkpoint, không gọi API.")
            return 0

        with (ROOT / ".eval_resume.lock").open("a") as lock:
            try:
                fcntl.flock(
                    lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB
                )
            except BlockingIOError:
                raise RuntimeError(
                    "Đang có một phiên resume khác trong repo."
                ) from None

            report = load_checkpoint(path, config)
            gate = RequestGate(
                args.max_requests,
                min_interval=config["min_interval_seconds"],
                token_budget=config["token_budget_per_minute"],
            )
            summary = process_cases(
                report, path, gate, only_case=args.case
            )
            show_status(report)
            print("Request phiên này:", gate.used)
            print("Lý do dừng:", gate.stop_reason)
            print("Checkpoint:", path)
            return 0 if summary["score_0_100"] is not None else 1

    except KeyboardInterrupt:
        print("\nĐã ngắt; kiểm tra checkpoint trước khi tiếp tục.")
        return 130
    except (ValueError, RuntimeError, OSError, KeyError) as exc:
        print(f"Lỗi: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())