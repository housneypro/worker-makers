# 실행 인계 계약 — schema_version 1

`goal.md`가 사람이 읽는 정본 인계이며 같은 WORK_ROOT의 `goal.json`이 실행 도구 입력이다. 해시는 실제 최종 파일 바이트의 SHA-256이다. 완료 표식은 각 문서 마지막의 `<!-- WORKER-MAKERS:COMPLETE -->`다. 아래 값을 실제 조사/합의로 채운다. 임의의 해시·기준 SHA·승인 근거를 만들지 않는다.

```json
{
  "schema_version": 1,
  "status": "frozen",
  "revision": "G-1",
  "agreement": { "reference": "사용자의 실제 요구 합의 및 실행 권한 출처" },
  "documents": [
    { "role": "brief", "path": "brief.md", "sha256": "실제 SHA256" },
    { "role": "plan", "path": "plans/main.md", "sha256": "실제 SHA256" },
    { "role": "spec", "path": "spec/main.md", "sha256": "실제 SHA256" },
    { "role": "impl_plan", "path": "impl_plans/T-001.md", "sha256": "실제 SHA256" },
    { "role": "goal", "path": "goal.md", "sha256": "실제 SHA256" },
    { "role": "pre_work", "path": "pre-work.md", "sha256": "실제 SHA256" }
  ],
  "convergence": {
    "plans": { "critical": 0, "high": 0, "proposals_pending": 0, "contracts_pending": 0, "evidence": "review/plans.md" },
    "spec": { "critical": 0, "high": 0, "proposals_pending": 0, "contracts_pending": 0, "evidence": "review/spec.md" },
    "impl_plans": { "critical": 0, "high": 0, "proposals_pending": 0, "contracts_pending": 0, "evidence": "review/impl_plans.md" }
  },
  "unresolved_questions": [],
  "pending_pre_work": [],
  "repos": { "app": { "path": ".", "base_sha": "실제 제품 Git HEAD SHA" } },
  "tasks": [
    {
      "id": "T-001", "phase": "P1", "repo": "app",
      "owns": ["src/feature.py", "tests/test_feature.py"],
      "deps": [], "requires_gates": [],
      "impl_plan": "impl_plans/T-001.md",
      "acceptance": ["AC-001"], "validation": ["V-T001"]
    }
  ],
  "gates": [ { "id": "P1-pass", "after": ["T-001"], "checks": ["V-P1"] } ],
  "completion": { "checks": ["V-FINAL"] }
}
```

- repo.path는 PROJECT_ROOT 기준 제품 root다. `kind`를 생략하면 git이며 실제 Git root/HEAD가 필요하다. 한 task는 한 repo를 소유한다. 여러 repo 변경은 각각의 task와 repo 간 deps로 분리한다. 원자적 다중 repo 통합을 주장하지 않는다.
- owns는 파일/디렉터리의 구체 상대경로다. glob이나 전체 `.` 소유는 허용하지 않는다. 공유 lockfile·schema·생성물도 실제 소유자를 둔다. `.git`, 실행 상태, 설치/신뢰 설정은 일반 코드 task가 변경하지 않는다.
- deps는 worker 완료가 아닌 **통합된** task를 뜻한다. requires_gates는 phase의 실제 검증까지 통과해야 하는 조건이다. task와 gate를 합친 DAG가 순환하면 안 된다.
- 작은 작업도 spec을 포함한다. 구형 승인 goal은 동등한 내용을 이 계약으로 매핑하고 사용자를 다시 브레인스토밍시키지 않는다. 실제 누락은 담당 단계로 반환한다.
- Git이 없거나 최초 커밋이 없으면 files backend를 사용한다. 기존 사용자 변경을 포함한 파일 기준이 필요한 경우에도 files를 명시할 수 있다. Git 초기화/최초 커밋을 임의로 만들지 않는다.
- `validate-goal`은 기록된 합의의 진실성·리뷰 품질·명령 성공을 증명하지 않는다. goal-maker와 work가 실제 근거를 읽어 판정한다.

## 파일 스냅샷 기준

```json
{
  "app": {
    "kind": "files", "path": ".",
    "exclude": ["worker-makers", "node_modules"],
    "base_sha": "실제 제품 파일 tree SHA-256"
  }
}
```

위 객체는 goal.json의 repos 값이다. 제외할 실제 경로만 기록하고 불필요한 항목을 관습적으로 추가하지 않는다. `exclude`는 제품 root 기준의 구체적인 파일/디렉터리 목록이며 glob·상위 이동·전체 `.`를 허용하지 않는다. excludes와 owns가 겹치면 검증이 실패한다. 제품 tree에는 관리/인증 자산을 포함하지 않으며 worker 사본의 실제 변경은 모두 검사한다.

```text
python <SKILL_ROOT>/scripts/file_snapshot.py --root <제품-root> --project --exclude worker-makers --exclude node_modules
```

출력의 sha256을 base_sha에 넣고 정확히 같은 exclude를 goal에 기록한다. task별 사본에서도 실제 언어의 검증 명령·기대 결과·실패 처리를 명세한다. 파일 backend는 Git 커밋을 요구하지 않으며 결과 head_sha는 worker 사본 전체 지문이다. 허브/worker 사본과 백업을 저장하는 파일 시스템의 hard link 지원이 필요하다. 링크·특수 파일·파일↔디렉터리 전환은 계획에서 명시적으로 분리/조정하고 자동 성공으로 처리하지 않는다.
