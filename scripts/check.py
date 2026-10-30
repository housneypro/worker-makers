#!/usr/bin/env python3
"""Validate distributable skills and relative resources using only stdlib."""
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
NAMES = ("breif-maker", "goal-maker", "work", "work-parallel")


def main():
    errors = []
    package = json.loads((ROOT / "distribution.json").read_text(encoding="utf-8"))["files"]
    if len(package) != len(set(package)): errors.append("중복 배포 경로")
    for relative in package:
        path = (ROOT / relative).resolve()
        if not path.is_relative_to(ROOT) or not path.is_file(): errors.append("배포 파일 누락/경계: " + relative)
    for name in NAMES:
        folder = ROOT / "skills" / name
        skill = (folder / "SKILL.md").read_text(encoding="utf-8")
        if not skill.startswith("---\n"): errors.append(name + ": frontmatter 누락")
        header = skill.split("---", 2)[1]
        if not re.search(r"^name: " + re.escape(name) + r"$", header, re.M): errors.append(name + ": 이름 불일치")
        if not re.search(r"^description: .+", header, re.M): errors.append(name + ": description 누락")
        for path in folder.rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts: continue
            if path.relative_to(ROOT).as_posix() not in package: errors.append("배포 목록 누락: " + str(path.relative_to(ROOT)))
            if path.suffix != ".md": continue
            text = path.read_text(encoding="utf-8")
            for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", text):
                if target.startswith(("https://", "http://", "#")): continue
                target = target.split("#")[0]
                resolved = (path.parent / target).resolve()
                if not resolved.is_relative_to(folder) or not resolved.is_file(): errors.append("독립 스킬 참조 오류: " + str(path.relative_to(ROOT)) + " → " + target)
            if re.search(r"\bTODO\b|\[TODO", text): errors.append("미완료 scaffold: " + str(path.relative_to(ROOT)))
    codex_manifest = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))
    claude_manifest = json.loads((ROOT / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
    marketplace = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text(encoding="utf-8"))
    if claude_manifest["version"] != codex_manifest["version"]: errors.append("Codex·Claude 플러그인 버전 불일치")
    if claude_manifest["name"] != codex_manifest["name"]: errors.append("Codex·Claude 플러그인 이름 불일치")
    if not any(p["name"] == claude_manifest["name"] and p["source"] == "./" for p in marketplace["plugins"]): errors.append("Claude marketplace 항목 불일치")
    result = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts/build.py"), "--check"], capture_output=True, text=True, encoding="utf-8")
    if result.returncode: errors.append(result.stderr.strip())
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"4개 스킬 · {len(package)}개 배포 파일 · 참조/bundle 검사 통과")
    return 0


if __name__ == "__main__":
    sys.exit(main())
