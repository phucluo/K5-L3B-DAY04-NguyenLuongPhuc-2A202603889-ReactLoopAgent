"""Hỗ trợ checkpoint/resume; không gọi API."""
import hashlib
import json
from pathlib import Path
import os
from grading import summarize, bonus_points

ROOT = Path(__file__).resolve().parents[1]


def load_cases(dataset):
    if dataset not in ("core", "bonus"):
        raise ValueError("dataset phải là core hoặc bonus")

    relative = (
        "evals/cases.json" if dataset == "core"
        else "bonus/cases.json"
    )
    return json.loads(
        (ROOT / relative).read_text(encoding="utf-8")
    )


def build_manifest(config):
    dataset = config["dataset"]
    load_cases(dataset)  # Kiểm tra dataset hợp lệ.

    files = [
        ROOT / "agent.py",
        ROOT / "providers.py",
        ROOT / "status_tools.py",
        ROOT / "bonus/__init__.py",
        ROOT / "bonus/tools.py",
    ]
    files.extend((ROOT / "evals").glob("*.py"))
    files.extend((ROOT / "fixtures").glob("*.json"))

    if dataset == "bonus":
        files.append(ROOT / "bonus/cases.json")
        files.extend((ROOT / "bonus/fixtures").glob("*.json"))
    else:
        files.append(ROOT / "evals/cases.json")

    hashes = {
        str(path.relative_to(ROOT)): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(set(files))
    }
    return {
        "config": dict(config),
        "sha256": hashes,
    }


def check_manifest(saved, current):
    if saved != current:
        raise ValueError(
            "Không resume: cấu hình hoặc code/dữ liệu đã đổi. "
            "Hãy dùng đúng phiên bản ban đầu của lượt eval."
        )

def new_checkpoint(config):
    identity = {
        key: config[key]
        for key in (
            "provider", "model", "judge_provider", "judge_model"
        )
    }
    items = [
        {
            **case,
            **identity,
            "result": None,
            "grade": {
                "score": None,
                "status": "unscored",
                "reason": "Chưa chạy.",
            },
        }
        for case in load_cases(config["dataset"])
    ]
    return {
        "config": dict(config),
        "manifest": build_manifest(config),
        "cases": items,
    }


def validate_checkpoint(report, config):
    if report["config"] != config:
        raise ValueError("Cấu hình checkpoint không khớp.")

    check_manifest(report["manifest"], build_manifest(config))
    original = load_cases(config["dataset"])

    if [x["id"] for x in report["cases"]] != [
        x["id"] for x in original
    ]:
        raise ValueError("Danh sách hoặc thứ tự case không khớp.")

    for item, case in zip(report["cases"], original):
        for key in ("question", "expected"):
            if item[key] != case[key]:
                raise ValueError(
                    f"Nội dung case {case['id']} không khớp."
                )


def load_checkpoint(path, config):
    path = Path(path)
    if not path.exists():
        return new_checkpoint(config)

    report = json.loads(path.read_text(encoding="utf-8"))
    validate_checkpoint(report, config)
    return report


def save_checkpoint(path, report):
    validate_checkpoint(report, report["config"])
    report["summary"] = summarize(report["cases"])

    if report["config"]["dataset"] == "bonus":
        report["summary"]["bonus_points_0_15"] = bonus_points(
            report["summary"]["score_0_100"],
            full_run=True,
        )

    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def next_stage(item):
    # Dùng "is not None" để giữ cả điểm 0.
    if item["grade"].get("score") is not None:
        return "done"

    result = item.get("result") or {}
    if result.get("status") in ("completed", "max_steps"):
        return "judge"

    return "agent"