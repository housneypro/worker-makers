#!/usr/bin/env python3
"""Worker Makers: local, hub-driven orchestration. Python 3.11+, no dependencies."""
from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone

VERSION = "0.1.1"
SCHEMA = 1
SKILLS = ("breif-maker", "goal-maker", "work", "work-parallel")
TERMINAL = {"merged", "cancelled"}


class Error(Exception):
    pass


def require(condition, message):
    if not condition:
        raise Error(message)


def now():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".wm-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            content = value if isinstance(value, (str, bytes)) else json.dumps(value, ensure_ascii=False, indent=2) + "\n"
            stream.write(content if isinstance(content, bytes) else content.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def inside(root, relative):
    require(isinstance(relative, str) and relative and "\\" not in relative, "경로는 비어 있지 않은 / 상대경로여야 합니다")
    require(not Path(relative).is_absolute() and not re.match(r"^[A-Za-z]:", relative), "절대경로는 허용되지 않습니다")
    require(".." not in Path(relative).parts, "상위 경로 이동은 허용되지 않습니다")
    require(":" not in relative and "\0" not in relative, "경로에 드라이브/스트림 구문을 사용할 수 없습니다")
    target = (Path(root) / relative).resolve()
    require(target.is_relative_to(Path(root).resolve()), "허용된 root 밖의 경로입니다")
    return target


def identifier(value):
    require(isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", value), "ID는 영문/숫자/_/- 1~80자여야 합니다")
    return value


def work_name(value):
    require(value and len(value) <= 100 and value == value.strip() and not value.endswith("."), "유효하지 않은 작업명입니다")
    require(not re.search(r'[<>:"/\\|?*\x00-\x1f]', value) and value not in {".", "..", "project.json"}, "유효하지 않은 작업명입니다")
    require(value.split(".")[0].upper() not in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}, "예약 작업명입니다")
    return value


def git(repo, *args, check=True):
    result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    if check and result.returncode:
        raise Error(result.stderr.decode("utf-8", "replace").strip() or "Git 명령 실패")
    return result


def gtext(repo, *args):
    return git(repo, *args).stdout.decode("utf-8", "replace").strip()


def head(repo):
    return gtext(repo, "rev-parse", "HEAD")


def clean(repo):
    return not git(repo, "status", "--porcelain=v1", "--untracked-files=all").stdout


def ignored_files(repo):
    return bool(git(repo, "ls-files", "--others", "--ignored", "--exclude-standard", "-z").stdout)


def ancestor(repo, base, tip):
    return git(repo, "merge-base", "--is-ancestor", base, tip, check=False).returncode == 0


def common_dir(repo):
    path = Path(gtext(repo, "rev-parse", "--git-common-dir"))
    return (path if path.is_absolute() else Path(repo) / path).resolve()


def dirty_owned(repo, owns):
    raw = git(repo, "diff", "--no-renames", "--name-only", "-z", "HEAD", "--").stdout
    raw += git(repo, "ls-files", "--others", "--exclude-standard", "-z").stdout
    raw += git(repo, "ls-files", "--others", "--ignored", "--exclude-standard", "-z", "--", *owns).stdout
    paths = [p.decode("utf-8", "surrogateescape") for p in raw.split(b"\0") if p]
    return [p for p in paths if any(overlaps(p, own) for own in owns)]


def bundle():
    return {"version": VERSION, "runtime_sha256": runtime_digest(Path(__file__).parent)}


def runtime_digest(folder):
    return hashlib.sha256(b"".join((Path(folder) / name).read_bytes() for name in ("wm.py", "file_snapshot.py"))).hexdigest()


def files_api():
    spec = importlib.util.spec_from_file_location("wm_file_snapshot", Path(__file__).with_name("file_snapshot.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def product_tree(path, info):
    return files_api().scan(path, project=True, excluded=info.get("exclude", []))


def product_head(path, info):
    return files_api().fingerprint(product_tree(path, info)) if info.get("kind") == "files" else head(path)


def git_barrier(parent):
    """Stop ordinary Git discovery from reaching the product above a file snapshot."""
    parent = Path(parent)
    parent.mkdir(parents=True, exist_ok=True)
    marker = parent / ".git"
    expected = "gitdir: .wm-no-git\n"
    require(not (parent / ".wm-no-git").exists(), "files 사본의 Git 차단 대상이 생겼습니다")
    if marker.exists():
        require(marker.is_file() and marker.read_text(encoding="utf-8") == expected, "files 사본 부모에 다른 Git metadata가 있습니다")
    else:
        atomic(marker, expected)


def snapshot_goal(work, goal):
    work = Path(work)
    revision = inside(work, "revisions/" + digest(work / "goal.json"))
    if revision.exists():
        require(load(revision / "goal.json") == goal and all(digest(inside(revision, d["path"])) == d["sha256"] for d in goal["documents"]), "보존된 frozen snapshot이 불완전합니다")
        return
    revision.mkdir(parents=True)
    for doc in goal["documents"]:
        atomic(inside(revision, doc["path"]), inside(work, doc["path"]).read_bytes())
    for record in goal["convergence"].values():
        atomic(inside(revision, record["evidence"]), inside(work, record["evidence"]).read_bytes())
    atomic(revision / "goal.json", goal)


def init_workspace(project, name):
    project = Path(project).resolve()
    require(project.is_dir(), "대상 프로젝트가 없습니다")
    workspace = inside(project, ".worker-makers")
    workspace.mkdir(exist_ok=True)
    connection = workspace / "project.json"
    if connection.exists():
        require(load(connection)["project_root"] == str(project), "기존 프로젝트 연결이 다릅니다")
    else:
        atomic(connection, {"schema_version": SCHEMA, "project_root": str(project), "created_at": now()})
    target = inside(workspace, work_name(name))
    require(not target.exists(), "같은 작업명이 이미 있습니다. 기존 작업 경로를 사용하세요")
    target.mkdir()
    atomic(target / "workspace.json", {"schema_version": SCHEMA, "project_root": str(project), "work_root": str(target), "work_id": uuid.uuid4().hex, "bundle": bundle()})
    # Git local exclude, never alter the product's tracked .gitignore.
    probe = git(project, "rev-parse", "--git-path", "info/exclude", check=False) if shutil.which("git") else None
    if probe is not None and probe.returncode == 0 and Path(gtext(project, "rev-parse", "--show-toplevel")).resolve() == project:
        exclude = Path(probe.stdout.decode().strip())
        if not exclude.is_absolute():
            exclude = project / exclude
        previous = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
        if "/.worker-makers/" not in previous.splitlines():
            atomic(exclude, previous.rstrip("\n") + "\n/.worker-makers/\n")
    return {"work_root": str(target)}


def validate_goal(work):
    work = Path(work).resolve()
    workspace = load(work / "workspace.json")
    require(workspace["work_root"] == str(work), "작업 경로가 변경됐습니다. 기존 연결을 확인하세요")
    goal = load(work / "goal.json")
    require(goal.get("schema_version") == SCHEMA and goal.get("status") == "frozen", "frozen schema_version=1 goal이 필요합니다")
    require(goal.get("agreement", {}).get("reference"), "기존 합의/실행 권한의 출처를 기록하세요. 새 승인 토큰은 필요하지 않습니다")
    require(goal.get("documents"), "계획 문서 목록이 필요합니다")
    roles = set()
    for document in goal["documents"]:
        path = inside(work, document["path"])
        require(path.is_file() and digest(path) == document["sha256"], f"문서 누락/변경: {document['path']}")
        content = path.read_text(encoding="utf-8")
        require(content.rstrip().endswith("<!-- WORKER-MAKERS:COMPLETE -->"), f"완료 표식 누락: {document['path']}")
        require(len(content.splitlines()) <= 2000, "문서는 2,000행 이하로 분할하세요")
        roles.add(document["role"])
    require({"brief", "plan", "spec", "impl_plan", "goal", "pre_work"} <= roles, "brief/plan/spec/impl_plan/goal/pre_work 문서가 필요합니다")
    convergence = goal.get("convergence", {})
    for stage in ("plans", "spec", "impl_plans"):
        record = convergence.get(stage, {})
        require(record.get("critical") == 0 and record.get("high") == 0 and record.get("proposals_pending") == 0 and record.get("contracts_pending") == 0 and record.get("evidence"), f"{stage} 수렴 근거가 필요합니다")
        require(inside(work, record["evidence"]).is_file(), f"{stage} 리뷰 근거 파일이 없습니다")
    require(not goal.get("unresolved_questions") and not goal.get("pending_pre_work"), "미해결 질문/선행작업이 있습니다")
    tasks = goal.get("tasks", [])
    require(tasks, "실행 task가 없습니다")
    by_id = {}
    repos = goal.get("repos", {})
    project = Path(workspace["project_root"])
    registered_repos, registered_roots = set(), set()
    for repo_id, info in repos.items():
        identifier(repo_id)
        path = inside(project, info["path"]) if info["path"] != "." else project
        require(path.is_dir(), f"대상 repo가 없습니다: {repo_id}")
        require(info.get("kind", "git") in {"git", "files"}, "repo kind는 git/files입니다")
        root_key = str(path.resolve()).casefold()
        require(root_key not in registered_roots, "동일 제품 root를 중복 등록할 수 없습니다")
        registered_roots.add(root_key)
        if info.get("kind") != "files":
            require(gtext(path, "rev-parse", "--show-toplevel").replace("\\", "/").lower() == str(path).replace("\\", "/").lower(), "repo.path는 제품 Git root여야 합니다")
            common = str(common_dir(path)).casefold()
            require(common not in registered_repos, "동일 Git common directory를 여러 repo ID로 등록할 수 없습니다")
            registered_repos.add(common)
        require(product_head(path, info) == info["base_sha"], f"제품 기준 SHA drift: {repo_id}")
    for task in tasks:
        tid = identifier(task["id"])
        require(tid not in by_id, "중복 task ID")
        by_id[tid] = task
        require(task.get("repo") in repos, "task repo가 없습니다")
        require(task.get("owns") and task.get("acceptance") and task.get("validation"), "task owns/acceptance/validation은 필수입니다")
        for own in task["owns"]:
            require(own not in {".", "./"} and not re.search(r"[*?\[]", own), "owns는 구체적인 파일/디렉터리 상대경로입니다")
            inside(project, own.rstrip("/"))
            normalized = Path(own.rstrip("/")).as_posix().casefold()
            require(normalized.split("/")[0] not in {".git", ".worker-makers", ".codex", ".agents"}, "보호 자산은 일반 owns가 될 수 없습니다")
            repo_path = project / repos[task["repo"]]["path"]
            owned_path = inside(repo_path, own.rstrip("/"))
            if repos[task["repo"]].get("kind") == "files":
                exclusions = files_api().validate_excludes(repos[task["repo"]].get("exclude", []))
                require(not any(overlaps(normalized, excluded) for excluded in exclusions), "snapshot 제외 경로는 owns에 포함할 수 없습니다")
            for other_id, other in repos.items():
                other_root = (project / other["path"]).resolve()
                if other_id != task["repo"] and other_root.is_relative_to(repo_path.resolve()):
                    require(not (owned_path.is_relative_to(other_root) or other_root.is_relative_to(owned_path)), "상위 repo owns가 등록된 중첩 repo 경계를 침범합니다")
        plan = inside(work, task["impl_plan"])
        require(plan.is_file() and any(d["path"] == task["impl_plan"] and d["role"] == "impl_plan" for d in goal["documents"]), "task impl_plan이 frozen 문서가 아닙니다")
        if repos[task["repo"]].get("kind") != "files":
            require(not dirty_owned(project / repos[task["repo"]]["path"], task["owns"]), f"사용자 owns 변경이 있습니다: {tid}. 임의 덮어쓰기/커밋 없이 계획 기준을 조정하세요")
    visiting, visited = set(), set()
    def visit(tid):
        require(tid in by_id, f"누락된 의존 task: {tid}")
        require(tid not in visiting, "task DAG 순환")
        if tid in visited:
            return
        visiting.add(tid)
        for dep in by_id[tid].get("deps", []):
            visit(dep)
        visiting.remove(tid)
        visited.add(tid)
    for tid in by_id:
        visit(tid)
    gates = goal.get("gates", [])
    gate_ids = [identifier(g["id"]) for g in gates]
    require(len(gate_ids) == len(set(gate_ids)), "중복 gate")
    for gate in gates:
        require(gate.get("after") and set(gate["after"]) <= by_id.keys(), "gate after task가 없습니다")
        require(gate.get("checks"), "gate 검증 기준이 없습니다")
    for task in tasks:
        require(set(task.get("requires_gates", [])) <= set(gate_ids), "누락된 gate")
        # A gate cannot depend on the very task that waits for it (directly or transitively).
        waiting = set(task.get("requires_gates", []))
        for gate in gates:
            if gate["id"] in waiting:
                def depends_on(candidate, target):
                    return candidate == target or any(depends_on(d, target) for d in by_id[candidate].get("deps", []))
                require(not any(depends_on(t, task["id"]) for t in gate["after"]), "gate/task 의존 순환")
    graph = {"t:" + tid: ["t:" + d for d in t.get("deps", [])] + ["g:" + g for g in t.get("requires_gates", [])] for tid, t in by_id.items()}
    graph.update({"g:" + g["id"]: ["t:" + t for t in g["after"]] for g in gates})
    visiting.clear(); visited.clear()
    def visit_node(node):
        require(node not in visiting, "task/gate 결합 DAG 순환")
        if node in visited:
            return
        visiting.add(node)
        for dependency in graph[node]:
            visit_node(dependency)
        visiting.remove(node); visited.add(node)
    for node in graph:
        visit_node(node)
    require(goal.get("completion", {}).get("checks"), "전체 완료 검증 기준이 필요합니다")
    return workspace, goal


class Store:
    def __init__(self, work, hub=None):
        self.work = Path(work).resolve()
        self.hub = hub
        self.lock = self.work / ".hub-write-lock"

    def read(self):
        state = load(self.work / "state.json")
        journal = self.work / "events.jsonl"
        if journal.exists():
            events = [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]
            require(all(e["seq"] == i + 1 for i, e in enumerate(events)), "이벤트 순번이 손상됐습니다")
            require(all(e["state"]["seq"] == e["seq"] for e in events), "이벤트 snapshot 순번이 손상됐습니다")
            if events:
                require(events[-1]["state"]["run_id"] == state["run_id"], "run 원장이 충돌합니다")
                require(state["seq"] <= events[-1]["seq"], "state가 journal보다 앞서 있습니다")
                if events[-1]["seq"] > state["seq"]:
                    state = events[-1]["state"]
                else:
                    require(state == events[-1]["state"], "state와 journal snapshot이 다릅니다")
        return state

    @contextlib.contextmanager
    def write(self):
        try:
            self.lock.mkdir()
        except FileExistsError:
            raise Error("허브 쓰기 잠금이 있습니다. 실제 소유 프로세스 종료 확인 없이 제거하지 마세요")
        atomic(self.lock / "owner.json", {"pid": os.getpid(), "hub": self.hub, "time": now()})
        try:
            state = self.read()
            require(self.hub and state["hub"] == self.hub, "다른 허브가 소유한 run입니다")
            require(state["bundle"] == bundle(), "실행 도구 버전/내용이 달라졌습니다. 활성 run bundle을 보존하세요")
            yield state
        finally:
            (self.lock / "owner.json").unlink(missing_ok=True)
            self.lock.rmdir()

    def save(self, state, kind, details=None):
        state["seq"] += 1
        state["updated_at"] = now()
        event = {"seq": state["seq"], "event_id": uuid.uuid4().hex, "kind": kind, "details": details or {}, "state": copy.deepcopy(state)}
        journal = self.work / "events.jsonl"
        previous = journal.read_text(encoding="utf-8") if journal.exists() else ""
        # Journal is committed before the snapshot; read() recovers the interrupted second write.
        atomic(journal, previous + json.dumps(event, ensure_ascii=False) + "\n")
        atomic(self.work / "state.json", state)


def start(work, hub, model, reasoning=None, mode="auto", capacity=2, cr=False, policy_source="explicit"):
    require(model and hub and capacity > 0 and mode in {"auto", "serial", "parallel"}, "명시적 worker 모델/허브/용량/실행 방식이 필요합니다")
    work = Path(work).resolve()
    require(not (work / "state.json").exists(), "run이 이미 있습니다. status와 실제 host/Git를 확인해 재개하세요")
    workspace, goal = validate_goal(work)
    require(policy_source in {"explicit", "resume", "project-default", "selection"}, "모델 정책 선택 출처가 유효하지 않습니다")
    state = {"schema_version": SCHEMA, "run_id": uuid.uuid4().hex, "seq": 0, "hub": hub, "bundle": bundle(), "project_root": workspace["project_root"], "work_root": str(work), "goal_sha256": digest(work / "goal.json"), "goal": goal, "status": "running", "stage": "execute", "worker_policy": {"model": model, "reasoning": reasoning, "source": policy_source}, "mode": mode, "capacity": capacity, "cross_review": cr, "repos": {}, "tasks": {}, "gates": {}, "evidence": [], "created_at": now()}
    for repo_id, info in goal["repos"].items():
        repo = Path(workspace["project_root"]) / info["path"]
        state["repos"][repo_id] = {"path": str(repo.resolve()), "kind": info.get("kind", "git"), "exclude": info.get("exclude", []), "base_sha": info["base_sha"], "integration_sha": info["base_sha"], "integration_path": str(work / "_integration" / repo_id), "integration_branch": f"wm/{state['run_id'][:12]}/integration/{repo_id}" if info.get("kind") != "files" else None}
    for task in goal["tasks"]:
        state["tasks"][task["id"]] = {"plan": task, "status": "queued", "attempt": 0}
    store = Store(work, hub)
    # Reserve the new run before any Git mutation, including the first snapshot.
    try:
        store.lock.mkdir()
    except FileExistsError:
        raise Error("다른 허브가 run을 시작/변경 중입니다")
    try:
        require(not (work / "state.json").exists() and not (work / "events.jsonl").exists(), "run이 이미 있습니다")
        atomic(store.lock / "owner.json", {"pid": os.getpid(), "hub": hub, "time": now()})
        snapshot_goal(work, goal)
        atomic(work / "state.json", state)
        store.save(state, "started")
    finally:
        (store.lock / "owner.json").unlink(missing_ok=True)
        store.lock.rmdir()
    return state


def overlaps(left, right):
    a, b = left.rstrip("/").casefold(), right.rstrip("/").casefold()
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


def ready(state):
    active = [t for t in state["tasks"].values() if t["status"] in {"preparing", "prepared", "running", "reported"}]
    capacity = (1 if state["mode"] == "serial" else state["capacity"]) - len(active)
    selected = []
    for tid, task in state["tasks"].items():
        plan = task["plan"]
        if task["status"] != "queued" or not all(state["tasks"][d]["status"] == "merged" for d in plan.get("deps", [])):
            continue
        if not all(g in state["gates"] for g in plan.get("requires_gates", [])):
            continue
        conflict = any(t["plan"]["repo"] == plan["repo"] and any(overlaps(a, b) for a in plan["owns"] for b in t["plan"]["owns"]) for t in active + selected)
        conflict = conflict or any(set(plan.get("resources", [])) & set(t["plan"].get("resources", [])) for t in active + selected)
        if capacity > 0 and not conflict:
            selected.append(task)
            capacity -= 1
    return [t["plan"]["id"] for t in selected]


def verify_frozen(work, state):
    require(digest(Path(work) / "goal.json") == state["goal_sha256"], "goal 계약이 변경됐습니다. 영향 task를 중단하고 goal-maker에서 개정하세요")
    for doc in state["goal"]["documents"]:
        require(digest(inside(work, doc["path"])) == doc["sha256"], f"frozen 문서 변경: {doc['path']}")
    for rid, repo in state["repos"].items():
        require(product_head(repo["path"], repo) == repo["base_sha"], f"실행 중 제품 기준 drift: {rid}")
        owns = [p for t in state["tasks"].values() if t["plan"]["repo"] == rid for p in t["plan"]["owns"]]
        if repo["kind"] != "files":
            require(not dirty_owned(repo["path"], owns), f"실행 중 제품 owns에 사용자 변경이 있습니다: {rid}")


def ensure_integration(repo):
    target = Path(repo["integration_path"])
    if repo["kind"] == "files":
        api = files_api()
        git_barrier(target.parent)
        if not target.exists():
            tree = product_tree(repo["path"], repo)
            require(api.fingerprint(tree) == repo["integration_sha"], "통합 snapshot이 유실됐습니다. 보존된 결과/백업을 먼저 조정하세요")
            api.snapshot(repo["path"], target, tree)
        require(api.fingerprint(api.scan(target)) == repo["integration_sha"], "통합 snapshot이 원장과 다릅니다. 실제 지문을 조정하세요")
        return
    if target.exists():
        require(gtext(target, "symbolic-ref", "--short", "HEAD") == repo["integration_branch"], "통합 worktree 소유 branch 불일치")
        require(head(target) == repo["integration_sha"] and clean(target), "통합 worktree 상태가 원장과 다릅니다. 실제 Git를 조정하세요")
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    existing = git(repo["path"], "rev-parse", "--verify", "refs/heads/" + repo["integration_branch"], check=False)
    if existing.returncode == 0:
        require(existing.stdout.decode().strip() == repo["integration_sha"], "통합 준비 branch가 기준과 다릅니다")
        git(repo["path"], "worktree", "add", str(target), repo["integration_branch"])
    else:
        git(repo["path"], "worktree", "add", "-b", repo["integration_branch"], str(target), repo["integration_sha"])


def prepare(store, state, tid):
    verify_frozen(store.work, state)
    task = state["tasks"][tid]
    repo = state["repos"][task["plan"]["repo"]]
    target = store.work / "task" / tid / "worktree"
    require(state["status"] == "running", "실행 중인 run에서만 준비합니다")
    policy = task.get("worker_policy", state["worker_policy"])
    if task["status"] != "preparing":
        require(tid in ready(state), "지금 실행 가능한 task가 아닙니다")
        require(not target.exists(), "소유 기록 없는 task worktree가 있습니다. 실제 상태를 먼저 확인하세요")
        task["attempt"] += 1
        branch = f"wm/{state['run_id'][:12]}/{tid}/a{task['attempt']}"
        task.update(status="preparing", kind=repo["kind"], attempt_id=uuid.uuid4().hex, branch=branch if repo["kind"] == "git" else None, worktree=str(target), base_sha=repo["integration_sha"], requested_model=policy["model"], resolved_model=None, confirmed_model=None, handle=None)
        store.save(state, "prepare_intent", {"task": tid})
    require(not task.get("handle") and repo["integration_sha"] == task["base_sha"], "준비 중 기준/host가 변경됐습니다")
    ensure_integration(repo)
    target.parent.mkdir(parents=True, exist_ok=True)
    if repo["kind"] == "files":
        api = files_api()
        git_barrier(target.parent)
        tree = api.scan(repo["integration_path"])
        atomic(target.parent / "base-tree.json", tree)
        if target.exists():
            require(api.fingerprint(api.scan(target)) == task["base_sha"], "준비 중인 snapshot에 사용자 변경이 있습니다")
        else:
            api.snapshot(repo["integration_path"], target, tree)
    else:
        if target.exists():
            require(gtext(target, "symbolic-ref", "--short", "HEAD") == task["branch"] and head(target) == task["base_sha"] and clean(target), "준비 중인 Git worktree가 기준과 다릅니다")
        else:
            existing = git(repo["path"], "rev-parse", "--verify", "refs/heads/" + task["branch"], check=False)
            if existing.returncode == 0:
                require(existing.stdout.decode().strip() == task["base_sha"], "task 준비 branch가 기준과 다릅니다")
                git(repo["path"], "worktree", "add", str(target), task["branch"])
            else:
                git(repo["path"], "worktree", "add", "-b", task["branch"], str(target), task["base_sha"])
    packet = {"run_id": state["run_id"], "task_id": tid, "attempt_id": task["attempt_id"], "backend": repo["kind"], "work_root": str(store.work), "cwd": str(target), "base_sha": task["base_sha"], "plan": task["plan"], "worker_policy": policy, "result_path": str(store.work / "task" / tid / "result.json"), "instruction": "지정 impl_plan을 읽고 owns만 구현한다. files backend는 Git 커밋 대신 파일 지문을 반환한다. 상위 스킬을 호출하지 않는다. 질문은 허브에 반환한다."}
    atomic(store.work / "task" / tid / "task.json", packet)
    task["status"] = "prepared"
    store.save(state, "prepared", {"task": tid})
    return packet


def dispatch(store, state, tid, handle, resolved, confirmed=None):
    require(state["status"] == "running", "중지/대기 중인 run에서 worker를 기동하지 않습니다")
    verify_frozen(store.work, state)
    task = state["tasks"][tid]
    require(task["status"] == "prepared" and handle and resolved == task["requested_model"], "prepared task와 실제 모델 지정 근거가 필요합니다")
    require(confirmed is None or confirmed == resolved, "호스트가 확인한 모델이 선택 모델과 다릅니다. writer를 중지하고 모델/alias 근거를 조정하세요")
    task.update(status="running", handle=handle, resolved_model=resolved, confirmed_model=confirmed)
    store.save(state, "dispatched", {"task": tid, "handle": handle})


def changed(repo, base, tip):
    return [s.decode("utf-8", "surrogateescape") for s in git(repo, "diff", "--no-renames", "--name-only", "-z", base, tip, "--").stdout.split(b"\0") if s]


def report(store, state, tid, result_path, host_evidence):
    task = state["tasks"][tid]
    require(task["status"] == "running", "running task만 회수할 수 있습니다. 중복 결과는 허용하지 않습니다")
    result = load(result_path)
    require((result.get("run_id"), result.get("task_id"), result.get("attempt_id"), result.get("base_sha")) == (state["run_id"], tid, task["attempt_id"], task["base_sha"]), "오래되거나 다른 attempt의 결과입니다")
    require(result.get("status") == "completed" and result.get("validation") and host_evidence, "완료·검증·host 종료 확인 근거가 필요합니다")
    require(inside(store.work, host_evidence).is_file(), "host 종료 확인 근거 파일이 없습니다")
    stopped = load(inside(store.work, host_evidence))
    require(stopped.get("status") == "stopped" and stopped.get("handle") == task["handle"] and stopped.get("source"), "해당 host handle의 실제 종료 근거가 필요합니다")
    checks = result["validation"]
    require(all(v.get("status") == "pass" and v.get("exit_code") == 0 and v.get("command") and v.get("summary") for v in checks), "실패/미실행 worker 검증은 완료로 수락하지 않습니다")
    require(set(task["plan"]["validation"]) <= {v.get("id") for v in checks}, "계획된 worker 검증이 누락됐습니다")
    repo = task["worktree"]
    tip = result.get("head_sha")
    if task["kind"] == "files":
        api = files_api()
        tree = api.scan(repo)
        require(api.fingerprint(tree) == tip, "worker snapshot 지문 불일치")
        base_tree = load(Path(repo).parent / "base-tree.json")
        require(api.fingerprint(base_tree) == task["base_sha"], "기준 snapshot 손상")
        files = api.delta(base_tree, tree)
        task["result_tree"] = tree
    else:
        require(gtext(repo, "symbolic-ref", "--short", "HEAD") == task["branch"], "task branch 불일치")
        require(clean(repo) and head(repo) == tip and ancestor(repo, task["base_sha"], tip), "dirty task 또는 커밋 기준/HEAD 불일치")
        require(not gtext(repo, "rev-list", "--merges", f"{task['base_sha']}..{tip}"), "task 결과에 merge commit을 포함할 수 없습니다")
        commits = gtext(repo, "rev-list", "--reverse", f"{task['base_sha']}..{tip}").splitlines()
        files = sorted({p for commit in commits for p in changed(repo, commit + "^", commit)})
    for path in files:
        require(any(path == own.rstrip("/") or path.startswith(own.rstrip("/") + "/") for own in task["plan"]["owns"]), f"owns 밖 변경: {path}")
    require(files or result.get("no_change_reason"), "무변경 결과의 근거가 필요합니다")
    task.update(status="reported", result=result, result_sha256=digest(result_path), host_evidence=host_evidence, tip_sha=tip)
    store.save(state, "reported", {"task": tid, "files": files})


def merge(store, state, tid):
    verify_frozen(store.work, state)
    task = state["tasks"][tid]
    require(task["status"] == "reported", "검사된 reported task만 통합할 수 있습니다")
    require(not task.get("merge_intent"), "중단된 merge intent가 있습니다. 실제 Git를 확인하고 reconcile-merge를 사용하세요")
    repo = state["repos"][task["plan"]["repo"]]
    require(not any(t["status"] == "preparing" and t["plan"]["repo"] == task["plan"]["repo"] for t in state["tasks"].values()), "이 repo에 준비를 마쳐야 할 task가 있습니다")
    require(not any(t.get("merge_intent") and t["plan"]["repo"] == task["plan"]["repo"] for t in state["tasks"].values()), "이 repo에 조정해야 할 통합 intent가 있습니다")
    ensure_integration(repo)
    if task["kind"] == "files":
        api = files_api()
        base = load(Path(task["worktree"]).parent / "base-tree.json")
        require(api.fingerprint(base) == task["base_sha"], "기준 snapshot 손상")
        expected = api.expected_tree(api.scan(repo["integration_path"]), base, task["result_tree"], task["plan"]["owns"])
        backup = str((store.work / "task" / tid / "attempts" / str(task["attempt"]) / "merge-before").relative_to(store.work)).replace("\\", "/")
        task["merge_intent"] = {"from": repo["integration_sha"], "expected": api.fingerprint(expected), "backup": backup}
        store.save(state, "merge_intent", {"task": tid})
        merged = api.apply(repo["integration_path"], task["worktree"], base, task["result_tree"], task["plan"]["owns"], inside(store.work, backup))
        repo["integration_sha"] = merged
        task.update(status="merged", merged_sha=merged)
        task.pop("merge_intent", None)
        store.save(state, "merged", {"task": tid, "sha": merged})
        return
    require(clean(task["worktree"]) and head(task["worktree"]) == task["tip_sha"], "회수 이후 worker 결과가 변경됐습니다")
    commits = gtext(task["worktree"], "rev-list", "--reverse", f"{task['base_sha']}..{task['tip_sha']}").splitlines()
    # Record intent first. A crash after cherry-pick must be reconciled, never replayed blindly.
    task["merge_intent"] = {"from": repo["integration_sha"], "commits": commits}
    store.save(state, "merge_intent", {"task": tid})
    for commit in commits:
        result = git(repo["integration_path"], "cherry-pick", commit, check=False)
        if result.returncode:
            task["status"] = "blocked"
            task["failure"] = "통합 충돌: 원 소유자에게 반환하고 실제 cherry-pick 상태를 조정하세요"
            store.save(state, "merge_conflict", {"task": tid})
            raise Error(task["failure"])
    repo["integration_sha"] = head(repo["integration_path"])
    task.update(status="merged", merged_sha=repo["integration_sha"])
    task.pop("merge_intent", None)
    store.save(state, "merged", {"task": tid, "sha": task["merged_sha"]})


def revisions(state):
    return {rid: repo["integration_sha"] for rid, repo in state["repos"].items()}


def add_evidence(store, state, path):
    evidence = load(path)
    identifier(evidence["id"])
    require(evidence.get("kind") in {"code_review", "security_review", "verification", "gap", "cross_review", "phase"}, "알 수 없는 evidence 종류")
    require(evidence.get("revisions") == revisions(state), "현재 통합 revision과 다른 검증입니다")
    require(evidence.get("status") in {"pass", "not_applicable"} and evidence.get("summary") and evidence.get("checks"), "실제 검증 결과/범위가 필요합니다")
    require(evidence.get("critical", 0) == 0 and evidence.get("high", 0) == 0, "차단급 지적이 남아 있습니다")
    if evidence["kind"] in {"phase", "verification", "gap", "cross_review"}:
        require(evidence["status"] == "pass", "필수 실행/갭 검증은 비적용으로 우회할 수 없습니다")
    if evidence["kind"] in {"verification", "phase"}:
        commands = evidence.get("commands", [])
        require(commands and all(c.get("argv") and c.get("cwd") and c.get("exit_code") == 0 and c.get("observed") for c in commands), "실제로 성공한 명령/cwd/관찰 근거가 필요합니다")
    if evidence["kind"] in {"code_review", "security_review", "gap", "cross_review"}:
        require(evidence.get("reviewer") and evidence.get("context"), "독립 리뷰의 수행자/컨텍스트 근거가 필요합니다")
    require(not any(e["id"] == evidence["id"] for e in state["evidence"]), "중복 evidence ID")
    target = store.work / "evidence" / f"{evidence['id']}.json"
    require(not target.exists(), "기존 evidence 파일을 덮어쓰지 않습니다")
    atomic(target, evidence)
    evidence["file"] = str(target.relative_to(store.work)).replace("\\", "/")
    evidence["sha256"] = digest(target)
    evidence["goal_sha256"] = state["goal_sha256"]
    state["evidence"].append(evidence)
    store.save(state, "evidence", {"id": evidence["id"]})


def gate(store, state, gid, eid):
    spec = next((g for g in state["goal"].get("gates", []) if g["id"] == gid), None)
    require(spec and all(state["tasks"][t]["status"] == "merged" for t in spec["after"]), "gate의 선행 task가 통합되지 않았습니다")
    evidence = next((e for e in state["evidence"] if e["id"] == eid), None)
    require(evidence and evidence["kind"] == "phase" and evidence["status"] == "pass" and evidence["revisions"] == revisions(state), "현재 revision의 phase 검증이 필요합니다")
    require(set(spec["checks"]) <= set(evidence["checks"]), "phase 필수 검증이 누락됐습니다")
    state["gates"][gid] = eid
    store.save(state, "gate", {"gate": gid})


def complete(store, state):
    require(state["status"] == "running", "중지/취소 상태를 먼저 명시적으로 재개하세요")
    verify_frozen(store.work, state)
    require(all(t["status"] == "merged" for t in state["tasks"].values()), "미통합 task가 있습니다")
    require(set(g["id"] for g in state["goal"].get("gates", [])) <= state["gates"].keys(), "미검증 gate가 있습니다")
    for repo in state["repos"].values():
        ensure_integration(repo)
    current = [e for e in state["evidence"] if e["revisions"] == revisions(state) and e.get("goal_sha256") == state["goal_sha256"]]
    for evidence in state["evidence"]:
        require(digest(inside(store.work, evidence["file"])) == evidence["sha256"], "기록한 검증 근거가 변경됐습니다")
    for kind in ("code_review", "security_review", "verification") + (("cross_review",) if state["cross_review"] else ()):
        require(any(e["kind"] == kind and e["status"] in {"pass", "not_applicable"} for e in current), f"현재 revision의 {kind}가 필요합니다")
    require(any(a["context"] != b["context"] for a in current if a["kind"] == "code_review" for b in current if b["kind"] == "security_review"), "코드/보안 리뷰는 별도 독립 컨텍스트 근거가 필요합니다")
    checks = state["goal"]["completion"]["checks"]
    require(set(checks) <= {c for e in current if e["kind"] == "verification" and e["status"] == "pass" for c in e["checks"]}, "전체 완료 검증이 누락됐습니다")
    gaps = [e for e in current if e["kind"] == "gap"]
    require(len(gaps) >= 2 and all(e["status"] == "pass" for e in gaps[-2:]) and gaps[-1]["context"] != gaps[-2]["context"], "현재 revision에서 연속 두 번의 독립 잔여 갭 확인이 필요합니다")
    state.update(status="completed", stage="report")
    store.save(state, "completed")


def retry(store, state, tid, host_evidence):
    task = state["tasks"][tid]
    require(task["status"] in {"failed", "blocked", "running", "prepared", "preparing"}, "재시도할 상태가 아닙니다")
    require(inside(store.work, host_evidence).is_file(), "이전 writer 종료의 실제 host 근거가 필요합니다")
    stopped = load(inside(store.work, host_evidence))
    require(stopped.get("status") == "stopped" and stopped.get("handle") == task.get("handle") and stopped.get("source"), "이전 handle의 종료 근거가 필요합니다")
    require(not task.get("merge_intent"), "중단된 통합은 먼저 reconcile-merge로 조정하세요")
    repo = state["repos"][task["plan"]["repo"]]
    archive = store.work / "task" / tid / "attempts" / str(task["attempt"])
    if task.get("worktree") and Path(task["worktree"]).exists():
        if task["kind"] == "files":
            require(files_api().fingerprint(files_api().scan(task["worktree"])) == task["base_sha"], "미회수 파일 변경을 먼저 보존/조정하세요")
        else:
            require(clean(task["worktree"]), "dirty task를 자동 정리하지 않습니다")
            require(head(task["worktree"]) == task["base_sha"], "미회수 커밋이 있습니다. 결과/계획을 먼저 조정하세요")
        archive_or_remove(store, task, repo, archive)
    atomic(archive / "state.json", task)
    task.update(status="queued", handle=None)
    store.save(state, "retry", {"task": tid, "host_evidence": host_evidence})


def cleanup(store, state, apply=False):
    require(state["status"] == "completed", "완료 run만 정리할 수 있습니다")
    targets, preserved_paths = [], []
    for tid, task in state["tasks"].items():
        target = Path(task["worktree"]).resolve()
        require(target.is_relative_to(store.work / "task" / tid), "허용된 task root 밖 정리 대상")
        if target.exists():
            if task["kind"] == "files":
                require(files_api().fingerprint(files_api().scan(target)) == task["tip_sha"], "변경된 snapshot은 보존합니다")
                targets.append((None, str(target)))
                continue
            require(task["status"] == "merged" and clean(target) and head(target) == task["tip_sha"], "dirty/변경된 task는 보존합니다")
            require(gtext(target, "symbolic-ref", "--short", "HEAD") == task["branch"], "다른 branch로 전환된 task는 보존합니다")
            if ignored_files(target):
                preserved_paths.append({"path": str(target), "reason": "ignored 파일 보존"})
            else:
                targets.append((state["repos"][task["plan"]["repo"]]["path"], str(target)))
    # Integration commits must first be preserved by a product branch before its worktree is removed.
    for repo in state["repos"].values():
        target = Path(repo["integration_path"])
        require(target.resolve().is_relative_to(store.work / "_integration"), "허용된 integration root 밖 정리 대상")
        if target.exists():
            if repo["kind"] == "files":
                require(files_api().fingerprint(files_api().scan(target)) == repo["integration_sha"], "변경된 통합 snapshot은 보존합니다")
                if product_head(repo["path"], repo) == repo["integration_sha"]:
                    targets.append((None, str(target)))
                else:
                    preserved_paths.append({"path": str(target), "reason": "제품 원본에 파일 결과가 아직 보존되지 않음"})
                continue
            require(clean(target) and head(target) == repo["integration_sha"], "통합 worktree 변경을 보존합니다")
            require(gtext(target, "symbolic-ref", "--short", "HEAD") == repo["integration_branch"], "다른 branch로 전환된 통합 worktree는 보존합니다")
            branches = gtext(repo["path"], "for-each-ref", "--format=%(refname:short)", "--contains", repo["integration_sha"], "refs/heads").splitlines()
            commit_preserved = any(not b.startswith(f"wm/{state['run_id'][:12]}/") for b in branches)
            if commit_preserved and not ignored_files(target):
                targets.append((repo["path"], str(target)))
            else:
                preserved_paths.append({"path": str(target), "reason": "제품 branch에 커밋 미보존 또는 ignored 파일 존재"})
    if apply:
        for repo, target in targets:
            if repo is None:
                absolute = Path(target).resolve()
                require(absolute.is_relative_to(store.work / "task") or absolute.is_relative_to(store.work / "_integration"), "snapshot 정리 경계 오류")
                shutil.rmtree(absolute)
            else:
                git(repo, "worktree", "remove", target)
        store.save(state, "cleaned", {"paths": [p for _, p in targets]})
    return {"apply": apply, "paths": [p for _, p in targets], "preserved": preserved_paths, "branches_preserved": True, "integration_preserved_until_product_branch_contains_commits": True}


def archive_or_remove(store, task, repo, archive):
    source = Path(task["worktree"]).resolve()
    require(source == store.work / "task" / task["plan"]["id"] / "worktree", "다른 task 경로는 정리하지 않습니다")
    if task["kind"] == "files":
        target = (archive / "worktree").resolve()
        require(target.is_relative_to(store.work / "task" / task["plan"]["id"] / "attempts"), "snapshot 보존 경계 오류")
        target.parent.mkdir(parents=True, exist_ok=True)
        os.rename(source, target)
        task["archived_worktree"] = str(target)
        return
    require(gtext(source, "symbolic-ref", "--short", "HEAD") == task["branch"], "다른 branch의 worktree는 정리하지 않습니다")
    if ignored_files(source):
        target = (archive / "worktree").resolve()
        require(target.is_relative_to(store.work / "task" / task["plan"]["id"] / "attempts"), "보존 worktree 경계 오류")
        target.parent.mkdir(parents=True, exist_ok=True)
        git(repo["path"], "worktree", "move", str(source), str(target))
        task["archived_worktree"] = str(target)
    else:
        git(repo["path"], "worktree", "remove", str(source))


def repair(store, state, tid, reason):
    """Reopen an integrated task without rewriting its frozen meaning/owns/deps."""
    task = state["tasks"][tid]
    require(task["status"] == "merged" and reason, "통합된 task의 구체적인 구현 수정 사유가 필요합니다")
    require(not any(t["status"] in {"preparing", "prepared", "running", "reported"} for t in state["tasks"].values()), "활성/미통합 작업을 먼저 회수하세요")
    if task["kind"] == "files":
        require(files_api().fingerprint(files_api().scan(task["worktree"])) == task["tip_sha"], "이전 task snapshot이 변경됐습니다")
    else:
        require(clean(task["worktree"]) and head(task["worktree"]) == task["tip_sha"], "이전 task 결과가 변경됐습니다")
    archive = store.work / "task" / tid / "attempts" / str(task["attempt"])
    archive_or_remove(store, task, state["repos"][task["plan"]["repo"]], archive)
    atomic(archive / "state.json", task)
    task.update(status="queued", repair_reason=reason, handle=None)
    # A correction invalidates dependent phase evidence, including transitively.
    affected = {tid}
    invalid_gates = set()
    while True:
        previous = (len(affected), len(invalid_gates))
        invalid_gates.update(g["id"] for g in state["goal"].get("gates", []) if set(g["after"]) & affected)
        affected.update(tid2 for tid2, t in state["tasks"].items() if set(t["plan"].get("deps", [])) & affected or set(t["plan"].get("requires_gates", [])) & invalid_gates)
        if previous == (len(affected), len(invalid_gates)):
            break
    for gid in invalid_gates:
        state["gates"].pop(gid, None)
    store.save(state, "repair", {"task": tid, "reason": reason, "affected": sorted(affected)})


def patch_id(repo, commit):
    patch = git(repo, "show", "--format=", "--no-ext-diff", "--binary", commit).stdout
    result = subprocess.run(["git", "-C", str(repo), "patch-id", "--verbatim"], input=patch, capture_output=True, check=True)
    return result.stdout.split()[0] if result.stdout.split() else b"empty"


def reconcile_merge(store, state, tid, action):
    task = state["tasks"][tid]
    intent = task.get("merge_intent")
    require(intent, "복구할 merge intent가 없습니다")
    repo = state["repos"][task["plan"]["repo"]]
    target = repo["integration_path"]
    if repo["kind"] == "files":
        api = files_api()
        if action == "retry":
            require(api.fingerprint(api.scan(target)) == intent["from"], "통합 snapshot을 intent 시작 지문으로 먼저 조정하세요")
            task["status"] = "reported"
        else:
            base = load(Path(task["worktree"]).parent / "base-tree.json")
            require(api.fingerprint(base) == task["base_sha"], "기준 snapshot 손상")
            projected = api.expected_tree(api.scan(target), base, task["result_tree"], task["plan"]["owns"])
            require(api.fingerprint(projected) == intent["expected"], "복구할 통합 snapshot에 예상 밖 변경이 있습니다")
            merged = api.apply(target, task["worktree"], base, task["result_tree"], task["plan"]["owns"], inside(store.work, intent["backup"]))
            require(merged == intent["expected"], "복구된 snapshot에 예상 밖 변경이 있습니다")
            task.update(status="merged", merged_sha=merged)
            repo["integration_sha"] = merged
        task.pop("merge_intent", None)
        store.save(state, "merge_reconciled", {"task": tid, "action": action})
        return
    require(gtext(target, "symbolic-ref", "--short", "HEAD") == repo["integration_branch"] and clean(target), "실제 통합 branch/clean 상태를 먼저 조정하세요")
    require(git(target, "rev-parse", "--verify", "CHERRY_PICK_HEAD", check=False).returncode != 0, "진행 중인 cherry-pick을 먼저 해결/중단하세요")
    actual = head(target)
    if action == "retry":
        require(actual == intent["from"], "재시도하려면 실제 통합 HEAD가 intent 시작 SHA여야 합니다. 미보존 커밋을 지우지 마세요")
        task.update(status="reported")
    else:
        require(ancestor(target, intent["from"], actual), "통합 이력 연결이 달라졌습니다")
        applied = gtext(target, "rev-list", "--reverse", f"{intent['from']}..{actual}").splitlines()
        require(len(applied) == len(intent["commits"]), "부분 통합/예상 밖 커밋입니다")
        require(all(patch_id(target, a) == patch_id(task["worktree"], b) for a, b in zip(applied, intent["commits"])), "실제 통합 patch가 보고된 결과와 다릅니다. 원 소유자의 수정/재회수가 필요합니다")
        task.update(status="merged", merged_sha=actual)
        repo["integration_sha"] = actual
    task.pop("merge_intent", None)
    store.save(state, "merge_reconciled", {"task": tid, "action": action, "sha": actual})


def fail_task(store, state, tid, reason, host_evidence):
    task = state["tasks"][tid]
    require(task["status"] in {"prepared", "running"} and reason, "실행 중 task의 실패 사유가 필요합니다")
    evidence = load(inside(store.work, host_evidence))
    require(evidence.get("status") == "stopped" and evidence.get("handle") == task.get("handle") and evidence.get("source"), "실제 writer 종료 근거가 필요합니다")
    task.update(status="failed", failure=reason, host_evidence=host_evidence)
    store.save(state, "failed", {"task": tid, "reason": reason})


def set_status(store, state, status, reason):
    require(reason and status in {"running", "waiting_input", "blocked", "paused", "cancelled"}, "실행 상태와 사유가 필요합니다")
    require(not any(t["status"] == "running" for t in state["tasks"].values()), "실제 running writer를 먼저 회수/종료해야 합니다")
    state.update(status=status, status_reason=reason)
    store.save(state, "run_status", {"status": status, "reason": reason})


def task_policy(store, state, tid, model, reasoning, authority):
    task = state["tasks"][tid]
    require(task["status"] == "queued" and model and authority, "queued task와 기존 모델 선택/승격 권한의 출처가 필요합니다")
    task["worker_policy"] = {"model": model, "reasoning": reasoning, "source": "task-authorized", "authority": authority}
    store.save(state, "task_policy", {"task": tid, "policy": task["worker_policy"]})


def set_stage(store, state, stage):
    require(stage in {"handoff", "worker_policy", "execute", "review", "verify", "report"}, "유효하지 않은 실행 단계")
    state["stage"] = stage
    store.save(state, "stage", {"stage": stage})


def adopt_goal(store, state, authority):
    require(authority, "실제 후속 요청/계획 개정 권한의 출처가 필요합니다")
    require(all(t["status"] == "merged" or (t["status"] == "queued" and t["attempt"] == 0) for t in state["tasks"].values()), "기존 시도의 writer/결과/실패를 먼저 회수하고 조정하세요")
    _, goal = validate_goal(store.work)
    new_hash = digest(store.work / "goal.json")
    require(new_hash != state["goal_sha256"], "새 goal revision이 아닙니다")
    new_tasks = {t["id"]: t for t in goal["tasks"]}
    require(goal["repos"] == state["goal"]["repos"], "repo/기준 변경은 통합 이력과 drift를 먼저 조정해야 합니다")
    for tid, task in state["tasks"].items():
        if task["status"] == "merged":
            require(new_tasks.get(tid) == task["plan"], "통합된 task 의미를 소급 변경하지 마세요. 수정 task를 새 ID로 계획하세요")
    previous = state["goal_sha256"]
    snapshot_goal(store.work, goal)
    tasks = {}
    for tid, plan in new_tasks.items():
        old = state["tasks"].get(tid)
        tasks[tid] = old if old and old["plan"] == plan else {"plan": plan, "status": "queued", "attempt": 0}
    old_gate_specs = {g["id"]: g for g in state["goal"].get("gates", [])}
    state["gates"] = {g["id"]: state["gates"][g["id"]] for g in goal.get("gates", []) if g["id"] in state["gates"] and old_gate_specs.get(g["id"]) == g}
    state.update(goal=goal, goal_sha256=new_hash, tasks=tasks, status="running", stage="execute")
    store.save(state, "goal_adopted", {"previous": previous, "current": new_hash, "authority": authority})


def main(argv=None):
    parser = argparse.ArgumentParser(description="Worker Makers 허브용 로컬 실행 도구 (agent spawn은 Codex 호스트가 수행)")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("init"); p.add_argument("--project", required=True); p.add_argument("--name", required=True)
    for command in ("validate-goal", "status", "ready", "start", "prepare", "dispatch", "report", "merge", "evidence", "gate", "complete", "retry", "clean", "repair", "reconcile-merge", "fail", "set-status", "adopt-goal", "task-policy", "set-stage"):
        p = sub.add_parser(command); p.add_argument("--work", required=True)
        if command not in {"validate-goal", "status", "ready"}: p.add_argument("--hub", required=True)
        if command in {"prepare", "dispatch", "report", "merge", "retry", "repair", "reconcile-merge", "fail", "task-policy"}: p.add_argument("--task", required=True)
        if command == "start":
            p.add_argument("--worker-model", required=True); p.add_argument("--worker-reasoning"); p.add_argument("--mode", choices=("auto", "serial", "parallel"), default="auto"); p.add_argument("--capacity", type=int, default=2); p.add_argument("--cr", action="store_true")
            p.add_argument("--policy-source", choices=("explicit", "resume", "project-default", "selection"), default="explicit")
        if command == "dispatch":
            p.add_argument("--handle", required=True); p.add_argument("--resolved-model", required=True); p.add_argument("--confirmed-model")
        if command in {"report", "retry", "fail"}: p.add_argument("--host-evidence", required=True)
        if command in {"report", "evidence"}: p.add_argument("--file", required=True)
        if command == "gate": p.add_argument("--id", required=True); p.add_argument("--evidence", required=True)
        if command == "clean": p.add_argument("--apply", action="store_true")
        if command in {"repair", "fail", "set-status"}: p.add_argument("--reason", required=True)
        if command == "set-status": p.add_argument("--status", required=True)
        if command == "reconcile-merge": p.add_argument("--action", choices=("accept", "retry"), required=True)
        if command == "adopt-goal": p.add_argument("--authority", required=True)
        if command == "task-policy":
            p.add_argument("--worker-model", required=True); p.add_argument("--worker-reasoning"); p.add_argument("--authority", required=True)
        if command == "set-stage": p.add_argument("--stage", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            result = init_workspace(args.project, args.name)
        elif args.command == "validate-goal":
            _, goal = validate_goal(args.work); result = {"valid": True, "tasks": len(goal["tasks"])}
        elif args.command == "start":
            result = start(args.work, args.hub, args.worker_model, args.worker_reasoning, args.mode, args.capacity, args.cr, args.policy_source)
        else:
            store = Store(args.work, getattr(args, "hub", None))
            if args.command in {"status", "ready"}:
                state = store.read(); result = state if args.command == "status" else {"ready": ready(state)}
            else:
                with store.write() as state:
                    require(state["status"] != "completed" or args.command in {"clean", "adopt-goal"}, "완료 run은 수정할 수 없습니다")
                    if args.command == "prepare": result = prepare(store, state, args.task)
                    elif args.command == "dispatch": result = dispatch(store, state, args.task, args.handle, args.resolved_model, args.confirmed_model)
                    elif args.command == "report": result = report(store, state, args.task, args.file, args.host_evidence)
                    elif args.command == "merge": result = merge(store, state, args.task)
                    elif args.command == "evidence": result = add_evidence(store, state, args.file)
                    elif args.command == "gate": result = gate(store, state, args.id, args.evidence)
                    elif args.command == "complete": result = complete(store, state)
                    elif args.command == "retry": result = retry(store, state, args.task, args.host_evidence)
                    elif args.command == "clean": result = cleanup(store, state, args.apply)
                    elif args.command == "repair": result = repair(store, state, args.task, args.reason)
                    elif args.command == "reconcile-merge": result = reconcile_merge(store, state, args.task, args.action)
                    elif args.command == "fail": result = fail_task(store, state, args.task, args.reason, args.host_evidence)
                    elif args.command == "set-status": result = set_status(store, state, args.status, args.reason)
                    elif args.command == "adopt-goal": result = adopt_goal(store, state, args.authority)
                    elif args.command == "task-policy": result = task_policy(store, state, args.task, args.worker_model, args.worker_reasoning, args.authority)
                    elif args.command == "set-stage": result = set_stage(store, state, args.stage)
                    if result is None: result = {"status": state["status"], "seq": state["seq"]}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (Error, OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
