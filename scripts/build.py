#!/usr/bin/env python3
"""Bundle the canonical runtime into each independently installable skill."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
NAMES = ("breif-maker", "goal-maker", "work", "work-parallel")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="배포 runtime 복사본의 일치 여부만 검사")
    args = parser.parse_args()
    source = (ROOT / "skills/work/scripts/wm.py").read_bytes()
    snapshot = (ROOT / "skills/work/scripts/file_snapshot.py").read_bytes()
    version = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))["version"]
    metadata = (json.dumps({"version": version, "runtime_sha256": hashlib.sha256(source + snapshot).hexdigest()}, indent=2) + "\n").encode()
    problems = []
    for name in NAMES:
        for relative, content in (("scripts/wm.py", source), ("scripts/file_snapshot.py", snapshot), ("bundle.json", metadata)):
            target = ROOT / "skills" / name / relative
            if args.check:
                if not target.exists() or target.read_bytes() != content:
                    problems.append(str(target.relative_to(ROOT)))
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
    if problems:
        print("배포 자산 불일치: " + ", ".join(problems), file=sys.stderr)
        return 1
    print("4개 스킬의 runtime/bundle 일치" if args.check else "4개 스킬의 runtime/bundle 생성")
    return 0


if __name__ == "__main__":
    sys.exit(main())
