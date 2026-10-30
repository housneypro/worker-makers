#!/usr/bin/env python3
"""Content-checked file snapshots for projects without a Git baseline."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import uuid

PROJECT_EXCLUDES = {".git", ".worker-makers", ".codex", ".agents", ".claude", ".ssh"}


def is_link(path):
    try:
        entry = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISLNK(entry.st_mode) or bool(getattr(entry, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def safe(root, relative):
    if not isinstance(relative, str) or not relative or relative == "." or "\0" in relative or "\\" in relative or ":" in relative or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise ValueError("유효하지 않은 snapshot 상대경로")
    root = Path(root).resolve()
    path = root / relative
    cursor = root
    # Reject links even if their current target happens to be inside the root.
    for part in path.relative_to(root).parts:
        cursor = cursor / part
        if is_link(cursor):
            raise ValueError("snapshot 경로의 symlink는 명시적 대조 없이 사용하지 않습니다")
    if not path.resolve().is_relative_to(root):
        raise ValueError("snapshot 경로 경계 오류")
    return path


def validate_excludes(excluded):
    if not isinstance(excluded, (list, tuple)):
        raise ValueError("exclude는 구체적인 상대경로의 목록이어야 합니다")
    result = []
    for value in excluded:
        if not isinstance(value, str) or not value or value == "." or "\0" in value or "\\" in value or ":" in value or Path(value).is_absolute() or ".." in Path(value).parts:
            raise ValueError("유효하지 않은 exclude 경로")
        normalized = Path(value).as_posix().rstrip("/")
        if normalized == "." or any(c in normalized for c in "*?["):
            raise ValueError("exclude는 glob이 아닌 구체 경로여야 합니다")
        result.append(normalized)
    return set(result)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def scan(root, project=False, excluded=()):
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError("snapshot root 디렉터리가 없습니다")
    result = {}
    excluded = {p.casefold() for p in validate_excludes(excluded)}
    def failed(error):
        raise error
    for directory, folders, files in os.walk(root, followlinks=False, onerror=failed):
        base = Path(directory)
        for name in list(folders):
            path = base / name
            rel = path.relative_to(root).as_posix()
            if (project and name.casefold() in PROJECT_EXCLUDES) or rel.casefold() in excluded:
                folders.remove(name)
            elif is_link(path):
                raise ValueError("snapshot의 symlink 디렉터리는 별도 계획이 필요합니다: " + rel)
        for name in files:
            path = base / name
            rel = path.relative_to(root).as_posix()
            lower = name.casefold()
            if rel.casefold() in excluded or (project and (lower in PROJECT_EXCLUDES or lower == ".env" or (lower.startswith(".env.") and lower != ".env.example"))):
                continue
            if is_link(path) or not stat.S_ISREG(path.stat().st_mode):
                raise ValueError("일반 파일만 snapshot할 수 있습니다: " + rel)
            result[rel] = {"sha256": sha(path), "mode": stat.S_IMODE(path.stat().st_mode)}
    return result


def fingerprint(tree):
    return hashlib.sha256(json.dumps(tree, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def atomic_bytes(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".wm-file-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary): os.unlink(temporary)


def snapshot(source, destination, tree):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if destination.exists():
        raise ValueError("기존 snapshot을 덮어쓰지 않습니다")
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".wm-snapshot-", dir=destination.parent)).resolve()
    try:
        for relative, entry in tree.items():
            original, target = safe(source, relative), safe(stage, relative)
            if sha(original) != entry["sha256"]:
                raise ValueError("복사 중 원본 파일이 변경됐습니다")
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, target)
        if scan(stage) != tree:
            raise ValueError("snapshot 복사 결과가 기준과 다릅니다")
        if destination.exists():
            raise ValueError("준비 중 snapshot 목적지가 생겼습니다")
        os.rename(stage, destination)
    finally:
        if stage.exists():
            if stage.parent != destination.parent.resolve() or not stage.name.startswith(".wm-snapshot-"):
                raise ValueError("snapshot staging 정리 경계 오류")
            shutil.rmtree(stage)


def delta(base, result):
    return sorted(p for p in base.keys() | result.keys() if base.get(p) != result.get(p))


def owned(paths, owns):
    for path in paths:
        if not any(path == own.rstrip("/") or path.startswith(own.rstrip("/") + "/") for own in owns):
            raise ValueError("owns 밖 snapshot 변경: " + path)


def expected_tree(current, base, result, owns):
    paths = delta(base, result)
    owned(paths, owns)
    for path in base.keys() | result.keys():
        other = result if path in base else base
        if any(parent.as_posix() in other for parent in Path(path).parents if str(parent) != "."):
            raise ValueError("파일/디렉터리 전환은 별도 복구 계획이 필요합니다")
    output = dict(current)
    for path in paths:
        # New values are accepted on replay, allowing interruption recovery without a blind repeat.
        if current.get(path) not in (base.get(path), result.get(path)):
            raise ValueError("snapshot 통합 충돌: " + path)
        if path in result: output[path] = result[path]
        else: output.pop(path, None)
    # A file replacing a directory or vice versa cannot be applied as independent files.
    for path in output:
        parents = Path(path).parents
        if any(p.as_posix() in output for p in parents if str(p) != "."):
            raise ValueError("파일/디렉터리 경로 충돌")
    return output


def entry(path):
    if not path.exists() and not is_link(path):
        return None
    if is_link(path) or not path.is_file():
        raise ValueError("통합 대상이 일반 파일이 아닙니다")
    return {"sha256": sha(path), "mode": stat.S_IMODE(path.stat().st_mode)}


def require_link_support(backup):
    probe = backup / (".probe-" + uuid.uuid4().hex)
    linked = probe.with_suffix(".link")
    try:
        atomic_bytes(probe, b"")
        os.link(probe, linked)
    finally:
        probe.unlink(missing_ok=True); linked.unlink(missing_ok=True)


def checked_change(target, relative, before, after, source, backup):
    destination = safe(target, relative)
    if entry(destination) != before:
        raise ValueError("통합 직전 대상 사용자 변경: " + relative)
    captured = None
    temporary = None
    try:
        if before is not None:
            captured = safe(backup, "captured/" + uuid.uuid4().hex + "/" + relative)
            captured.parent.mkdir(parents=True, exist_ok=True)
            os.rename(destination, captured)
            if entry(captured) != before:
                raise ValueError("통합 도중 변경된 파일을 백업에 보존했습니다: " + relative)
        if after is not None:
            data = safe(source, relative).read_bytes()
            if hashlib.sha256(data).hexdigest() != after["sha256"]:
                raise ValueError("적용 중 worker 파일 변경")
            temporary = backup / (".publish-" + uuid.uuid4().hex)
            atomic_bytes(temporary, data)
            os.chmod(temporary, after["mode"])
            destination.parent.mkdir(parents=True, exist_ok=True)
            # Unlike replace(), linking refuses a concurrently-created destination.
            os.link(temporary, destination)
    except BaseException:
        if captured is not None and captured.exists():
            try:
                os.link(captured, destination, follow_symlinks=False)
            except FileExistsError:
                pass  # Preserve both the concurrent destination and captured version.
        raise
    finally:
        if temporary is not None: temporary.unlink(missing_ok=True)


def apply(target, source, base, result, owns, backup):
    target, source, backup = Path(target).resolve(), Path(source).resolve(), Path(backup).resolve()
    roots = (target, source, backup)
    if any(a.is_relative_to(b) or b.is_relative_to(a) for i, a in enumerate(roots) for b in roots[i + 1:]):
        raise ValueError("통합·worker·백업 root는 서로 겹칠 수 없습니다")
    if scan(source) != result:
        raise ValueError("회수 후 worker snapshot이 변경됐습니다")
    current = scan(target)
    expected = expected_tree(current, base, result, owns)
    backup.mkdir(parents=True, exist_ok=True)
    marker = backup / "before.json"
    if not marker.exists():
        for relative in delta(base, result):
            if relative in current:
                atomic_bytes(safe(backup / "files", relative), safe(target, relative).read_bytes())
        # This marker means every backup finished; interruption before it never mutates target.
        atomic_bytes(marker, json.dumps({"tree": current, "base": fingerprint(base), "result": fingerprint(result)}, ensure_ascii=False, indent=2).encode())
    saved = json.loads(marker.read_text(encoding="utf-8"))
    if saved.get("base") != fingerprint(base) or saved.get("result") != fingerprint(result):
        raise ValueError("다른 통합 시도의 백업입니다")
    for relative in delta(base, result):
        before = saved["tree"].get(relative)
        if before is not None and sha(safe(backup / "files", relative)) != before["sha256"]:
            raise ValueError("통합 백업이 누락/변경됐습니다")
    require_link_support(backup)
    if scan(target) != current:
        raise ValueError("백업 도중 통합 대상에 사용자 변경이 있습니다")
    for relative in delta(base, result):
        if current.get(relative) != result.get(relative):
            checked_change(target, relative, current.get(relative), result.get(relative), source, backup)
    if scan(target) != expected:
        raise ValueError("snapshot 통합 결과가 예상 지문과 다릅니다")
    return fingerprint(expected)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--project", action="store_true", help="프로젝트 관리/인증 자산을 제외한 제품 지문")
    parser.add_argument("--exclude", action="append", default=[])
    args = parser.parse_args()
    tree = scan(args.root, args.project, args.exclude)
    print(json.dumps({"sha256": fingerprint(tree), "files": len(tree)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
