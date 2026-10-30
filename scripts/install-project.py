#!/usr/bin/env python3
"""Register this local plugin for one project; preserve unrelated JSON/TOML."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib

SOURCE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("wm", SOURCE / "skills/work/scripts/wm.py")
wm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wm)


def enabled_config(text, key):
    parsed = tomllib.loads(text)
    current = parsed.get("plugins", {}).get(key)
    quoted = json.dumps(key)
    if current is None:
        result = text.rstrip() + f"\n\n[plugins.{quoted}]\nenabled = true\n"
    elif current.get("enabled") is True:
        return text
    else:
        lines = text.splitlines(keepends=True)
        headers = [i for i, line in enumerate(lines) if re.fullmatch(r'\s*\[plugins\.(?:"' + re.escape(key) + r'"|\x27' + re.escape(key) + r'\x27)\]\s*(?:#.*)?\r?\n?', line)]
        wm.require(len(headers) == 1, "기존 plugin TOML은 복합 표현입니다. 해당 항목의 enabled=true를 직접 설정하세요")
        start = headers[0]
        end = next((i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("[")), len(lines))
        matches = [i for i in range(start + 1, end) if re.match(r"\s*enabled\s*=", lines[i])]
        if matches:
            wm.require(len(matches) == 1 and re.fullmatch(r"\s*enabled\s*=\s*(?:true|false)\s*(?:#.*)?\r?\n?", lines[matches[0]]), "enabled 항목을 안전하게 변경할 수 없습니다")
            lines[matches[0]] = re.sub(r"(=\s*)(true|false)", r"\g<1>true", lines[matches[0]], count=1)
        else:
            lines.insert(start + 1, "enabled = true\n")
        result = "".join(lines)
    wm.require(tomllib.loads(result)["plugins"][key]["enabled"] is True, "활성화 설정 검증 실패")
    return result.lstrip("\n")


def marketplace_config(text, name, project):
    """CLI 0.164 needs an explicit project-scoped marketplace source."""
    parsed = tomllib.loads(text)
    current = parsed.get("marketplaces", {}).get(name)
    if current is not None:
        wm.require(current.get("source_type") == "local" and Path(current.get("source", "")).resolve() == project, "동일 이름의 marketplace 설정이 다른 소스를 가리킵니다")
        return text
    return text.rstrip() + f'\n\n[marketplaces.{json.dumps(name)}]\nsource_type = "local"\nsource = {json.dumps(str(project), ensure_ascii=False)}\n'


def tree_hashes(root):
    return {p.relative_to(root).as_posix(): wm.digest(p) for p in Path(root).rglob("*") if p.is_file() and "__pycache__" not in p.parts}


def install_cache(project, marketplace, codex_home=None):
    """Let Codex build a cache in an isolated home, then publish only cache files.

    Never run `plugin add` against the user's config: it enables the plugin globally.
    """
    codex = shutil.which("codex")
    wm.require(codex, "Codex CLI가 필요합니다. 설정 등록만 하려면 --register-only를 사용하세요")
    home = Path(codex_home or os.environ.get("CODEX_HOME") or (Path.home() / ".codex")).resolve()
    catalog = wm.load(Path(project) / ".agents/plugins/marketplace.json")
    entry = next(p for p in catalog["plugins"] if p["name"] == "worker-makers")
    source_path = entry["source"] if isinstance(entry["source"], str) else entry["source"]["path"]
    source_root = wm.inside(project, source_path)
    with tempfile.TemporaryDirectory(prefix="wm-plugin-stage-") as temporary:
        staged_home = Path(temporary) / "codex-home"
        staged_home.mkdir()
        stage_root = Path(temporary) / "marketplace"
        staged_plugin = stage_root / "worker-makers"
        staged_plugin.mkdir(parents=True)
        allowed = wm.load(source_root / "distribution.json")["files"]
        wm.require(len(allowed) == len(set(allowed)) and "plugin.json" in allowed, "배포 파일 목록 오류")
        for relative in allowed:
            original = wm.inside(source_root, relative)
            target = wm.inside(staged_plugin, relative)
            wm.require(original.is_file(), f"배포 파일 누락: {relative}")
            wm.atomic(target, original.read_bytes())
        wm.atomic(stage_root / ".agents/plugins/marketplace.json", {"name": marketplace, "plugins": [{"name": "worker-makers", "source": {"source": "local", "path": "./worker-makers"}, "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"}, "category": "Productivity"}]})
        wm.atomic(staged_home / "config.toml", f'[marketplaces.{json.dumps(marketplace)}]\nsource_type = "local"\nsource = {json.dumps(str(stage_root), ensure_ascii=False)}\n')
        result = subprocess.run([codex, "plugin", "add", "worker-makers@" + marketplace, "--json"], cwd=stage_root, env=dict(os.environ, CODEX_HOME=str(staged_home)), capture_output=True, timeout=60)
        wm.require(result.returncode == 0, "Codex cache 설치 실패: " + result.stderr.decode("utf-8", "replace"))
        installed = Path(json.loads(result.stdout)["installedPath"]).resolve()
        wm.require(installed.is_relative_to(staged_home / "plugins" / "cache"), "호스트가 예상 밖 cache 경로를 반환했습니다")
        relative = installed.relative_to(staged_home).as_posix()
        destination = wm.inside(home, relative)
        if destination.exists():
            wm.require(tree_hashes(destination) == tree_hashes(installed), "동일 버전 cache의 내용이 다릅니다. 활성 run을 보존하고 새 버전으로 배포하세요")
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            stage = Path(tempfile.mkdtemp(prefix=".wm-cache-", dir=destination.parent))
            try:
                shutil.copytree(installed, stage, dirs_exist_ok=True)
                os.rename(stage, destination)
            finally:
                # Only our freshly-created staging folder, never an existing plugin tree.
                if stage.exists():
                    wm.require(stage.resolve().is_relative_to(destination.parent.resolve()) and stage.name.startswith(".wm-cache-"), "cache staging 정리 경계 오류")
                    shutil.rmtree(stage)
    return str(destination)


def install(project, source=SOURCE, dry_run=False):
    project, source = Path(project).resolve(), Path(source).resolve()
    wm.require(project.is_dir() and source.is_relative_to(project), "플러그인 소스를 대상 프로젝트 내부에 clone한 뒤 --project를 지정하세요")
    manifest = wm.load(source / "plugin.json")
    wm.require(manifest["name"] == "worker-makers", "플러그인 식별자 불일치")
    for name in wm.SKILLS:
        folder = source / "skills" / name
        wm.require((folder / "SKILL.md").is_file() and (folder / "scripts/wm.py").is_file(), f"불완전 스킬: {name}")
        wm.require(wm.load(folder / "bundle.json")["runtime_sha256"] == wm.runtime_digest(folder / "scripts"), "runtime bundle 지문 불일치")
    marketplace_path = wm.inside(project, ".agents/plugins/marketplace.json")
    config_path = wm.inside(project, ".codex/config.toml")
    old_marketplace = marketplace_path.read_text(encoding="utf-8") if marketplace_path.exists() else None
    old_config = config_path.read_text(encoding="utf-8") if config_path.exists() else None
    marketplace = json.loads(old_marketplace) if old_marketplace is not None else {"name": "worker-makers-local", "interface": {"displayName": "Worker Makers"}, "plugins": []}
    wm.require(isinstance(marketplace.get("name"), str) and marketplace["name"], "기존 marketplace name이 없습니다")
    wm.require(isinstance(marketplace.get("plugins"), list), "기존 marketplace plugins는 목록이어야 합니다")
    relative = "./" + source.relative_to(project).as_posix()
    if relative == "./.":
        relative = "./"
    existing = [p for p in marketplace["plugins"] if p.get("name") == "worker-makers"]
    wm.require(len(existing) <= 1, "중복 worker-makers marketplace 항목")
    entry = {"name": "worker-makers", "source": {"source": "local", "path": relative}, "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"}, "category": "Productivity"}
    if existing:
        wm.require(existing[0].get("source") in (relative, entry["source"]), "기존 worker-makers가 다른 소스를 가리킵니다. 자동 교체하지 않습니다")
    else:
        marketplace["plugins"].append(entry)
    config = enabled_config(old_config or "", "worker-makers@" + marketplace["name"])
    config = marketplace_config(config, marketplace["name"], project)
    new_marketplace = json.dumps(marketplace, ensure_ascii=False, indent=2) + "\n"
    if not dry_run:
        lock = wm.inside(project, ".agents/plugins/.worker-makers-setup-lock")
        lock.parent.mkdir(parents=True, exist_ok=True)
        try:
            lock.mkdir()
        except FileExistsError:
            raise wm.Error("다른 프로젝트 설치가 진행 중입니다")
        try:
            # Preflight again under lock so another edit is not silently overwritten.
            wm.require((marketplace_path.read_text(encoding="utf-8") if marketplace_path.exists() else None) == old_marketplace, "marketplace가 동시에 변경됐습니다")
            wm.require((config_path.read_text(encoding="utf-8") if config_path.exists() else None) == old_config, "config가 동시에 변경됐습니다")
            wm.atomic(marketplace_path, new_marketplace)
            try:
                wm.atomic(config_path, config)
            except OSError:
                if old_marketplace is None:
                    marketplace_path.unlink()
                else:
                    wm.atomic(marketplace_path, old_marketplace)
                raise
        finally:
            lock.rmdir()
    return {"dry_run": dry_run, "project": str(project), "source": str(source), "marketplace": marketplace["name"], "files": [str(marketplace_path), str(config_path)], "registered": not dry_run, "host_discovery_verified": False, "next": "신뢰한 프로젝트를 지원 클라이언트에서 열고 로컬 marketplace의 Worker Makers 설치/탐색을 확인하세요"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, help="실제 대상 프로젝트 root")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--register-only", action="store_true", help="호스트 cache 설치 없이 프로젝트 설정만 등록")
    args = parser.parse_args()
    try:
        result = install(args.project, dry_run=args.dry_run)
        if not args.dry_run and not args.register_only:
            result["cache_path"] = install_cache(Path(args.project).resolve(), result["marketplace"])
            result["cache_installed"] = True
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (wm.Error, OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
