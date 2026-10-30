# 실행·재개와 격리

## CLI 순서

모든 쓰기는 같은 `--hub <id>`로 수행한다. ID는 run 소유권 식별이며 인증 비밀이 아니다. 이벤트+state는 허브 단일 writer다. worker가 CLI를 호출해 중앙 상태를 바꾸지 않는다.

```text
python <SKILL_ROOT>/scripts/wm.py status --work <WORK_ROOT>
python <SKILL_ROOT>/scripts/wm.py ready --work <WORK_ROOT>
python <SKILL_ROOT>/scripts/wm.py prepare --work <WORK_ROOT> --hub <id> --task T-001
```

prepare 반환 packet으로 실제 worker를 기동한 뒤:

```text
python <SKILL_ROOT>/scripts/wm.py dispatch --work <WORK_ROOT> --hub <id> --task T-001 --handle <실제-handle> --resolved-model <실제-설정-ID>
python <SKILL_ROOT>/scripts/wm.py report --work <WORK_ROOT> --hub <id> --task T-001 --file <result.json> --host-evidence evidence/host-T001-a1.json
python <SKILL_ROOT>/scripts/wm.py merge --work <WORK_ROOT> --hub <id> --task T-001
```

Git 경로에서 허브 통합 worktree는 `_integration/<repo-id>/`, 개발 worktree는 `task/T-ID/worktree/`다. task당 branch/worktree, 활성 writer는 하나다. 준비 시 deps가 통합된 최신 integration SHA에서 분기한다. 같은 파일/디렉터리 owns가 겹치면 직렬 실행한다. 통합은 repo당 하나씩이고 run 쓰기 잠금이 동시 merge를 차단한다. 다른 run이 같은 제품에 있어도 branch/worktree/run 상태는 분리한다. 동일 포트·DB·출력 경로 같은 공유 자원은 허브가 별도로 예약한다.

결과 회수는 실제 branch/HEAD·base ancestry·clean 상태·변경 파일 owns·merge commit 없음·attempt ID를 검사한다. Git hook이 commit을 바꿨는지도 실제 diff로 확인한다. task 커밋은 통합 큐에서 순차 cherry-pick한다. 후행 task는 merged 상태와 필요한 phase gate 둘 다 만족해야 ready다.

## 실패와 복구

- command 쓰기 잠금이 남았으면 owner.json의 실제 프로세스를 OS/호스트에서 확인한다. 시간만 보고 지우지 않는다. 실제 종료가 입증되면 잠금 경로를 확인해 해당 lock만 정리하고 같은 hub로 재개한다.
- 이벤트 snapshot이 state보다 앞서면 도구가 journal의 마지막 일관된 state를 읽는다. 손상된 journal은 자동 잘라내지 않는다.
- prepare는 파일/Git 생성 전 preparing intent로 용량·소유·attempt를 예약한다. 중단 시 status와 실제 경로/branch/지문을 확인하고 같은 prepare로 같은 attempt를 이어간다. 알려진 준비 자산이 기준과 다르면 사용자 변경을 보존하고 보류한다. preparing인 repo의 기준은 준비를 마칠 때까지 다른 task 통합으로 앞서가지 않는다.
- merge intent 뒤 중단되면 integration 실제 HEAD·cherry-pick 상태·이미 적용된 commit을 대조한다. 충돌/부분 통합을 자동 재실행하지 않는다. 원 task 소유자에게 해결을 맡기거나, 의도가 명확한 작은 충돌만 허브가 해결하고 별도 리뷰한다.
- host 관찰 timeout은 종료 근거가 아니다. 같은 handle을 다시 조회한다. 이전 writer 종료 근거와 실제 task 상태 없이 새 attempt를 만들지 않는다.
- 무커밋 clean task는 retry로 attempt를 보존하고 재시도한다. 미회수 커밋/dirty 상태는 자동 제거하지 않는다. 실제 결과를 회수하거나 계획/상태를 조정한 뒤 이어간다.
- DB/API 작업은 대상·허용 효과·실행/정리 evidence를 기록한다. 완료 여부 불명확 시 조회·조정 후 재실행하며 exactly-once를 주장하지 않는다.

구현 실패는 실제 handle 종료를 확인한 JSON 근거와 함께 `fail --task <id> --reason <원인> --host-evidence <상대경로>`로 기록한다. 변경 없는 실패/준비 task는 `retry`로 새 attempt를 만든다. 통합된 task의 같은 계약 안의 구현 수정은 `repair --task <id> --reason <지적>`로 다시 준비한다. 이전 attempt/branch와 ignored 파일을 보존하며 영향 phase gate를 무효화한다. 계약 변경은 repair로 숨기지 않는다.

중단된 통합은 실제 상태를 먼저 대조해 `reconcile-merge --task <id> --action accept`로 확인된 결과만 채택한다. Git은 예상 커밋과 공백까지 보존한 patch를 대조한다. 시작 상태로 안전하게 되돌린 경우에만 `--action retry`로 reported 상태를 복원한다. 자동 reset --hard는 수행하지 않는다.

전체 중지/대기는 실제 running writer를 먼저 회수한 후 `set-status --status <paused|waiting_input|blocked|cancelled|running> --reason <근거>`로 기록한다. 상태만 바꿔 worker를 종료했다고 주장하지 않는다. `set-stage --stage <execute|review|verify|report>`로 현재 허브 활동을 기록한다.

후속 요구/계획은 원래 역할에서 재수렴하고 `adopt-goal --authority <기존 후속 요청의 출처>`로 같은 run에 채택한다. 기존 frozen 문서는 revisions에 보존한다. 이미 통합된 task의 의미를 소급 변경하지 말고 새 수정 task ID를 사용한다. 시작한 attempt는 먼저 회수/조정한다. repo/기준 변경은 이력·drift 조정이 선행돼야 한다.

## non-Git / 최초 커밋 없음

`repos.<id>.kind="files"`는 Git 없이 동일한 DAG/모델/상태/리뷰/완료 프로세스를 실행한다. Git을 임의 초기화하거나 기존 작업을 최초 커밋으로 묶지 않는다. `base_sha`와 worker `head_sha`는 파일 내용·mode tree의 SHA-256이다. PROJECT_ROOT의 관리/인증 자산과 계획에 명시한 exclude는 사본에서 제외하고, task/integration 사본의 실제 변경은 전부 owns로 검사한다.

```text
python <SKILL_ROOT>/scripts/file_snapshot.py --root <제품-root> --project --exclude <프로젝트-내-도구-clone-경로>
python <SKILL_ROOT>/scripts/file_snapshot.py --root <worker-cwd>
```

첫 명령은 계획할 제품 지문, 둘째는 실제 worker 결과 지문이다. exclude는 필요할 때 반복한다. clone 소스·의존성·출력 폴더 등 제외할 실제 경로는 goal-maker가 계약에 기록한다. 제외 경로를 owns와 겹치게 정하지 않는다. Git metadata(디렉터리/파일 모두)·호스트(Codex, Claude Code) 신뢰/인증 자산·실제 `.env`는 product 사본으로 옮기지 않는다.

prepare는 staging에서 사본을 완성한 뒤 확정하고 메타데이터/원장 사이의 중단은 preparing intent로 재개한다. files backend의 worktree는 **격리 파일 사본**이며 Git branch가 아니다. 사본 부모의 도구용 Git 차단 metadata로 상위 원본 Git index의 암묵적 탐색을 막는다. worker는 Git 커밋 대신 파일 지문을 result에 기록한다. Python 검증은 `python -B` 등으로 불필요한 bytecode를 만들지 않고, 필요한 생성물은 실제 owns/계획된 검증 출력으로 명시한다. 파일 사본에 생긴 예상 밖 산출물을 조용히 무시하지 않는다.

merge는 기준/결과/현재 파일을 대조하고 옛 파일 백업을 완료한 후 적용한다. 각 파일을 다시 검사하고 교체 대상의 실제 버전을 captured에 보존한다. 새 파일은 기존 경로를 덮어쓰지 않는 hard link 게시를 사용한다. **사본과 백업이 있는 로컬 파일 시스템의 hard link 지원이 필요**하며 미지원이면 원본 코드 적용 전에 보류한다. symlink/junction·특수 파일과 파일↔디렉터리 전환은 자동 처리하지 않는다. 목표 파일을 명시적으로 분리/조정해 계획을 재수렴한다.

파일 사이의 중단은 저장된 intent와 백업을 대조해 reconcile로 이어갈 수 있다. 한 파일의 captured 이동과 새 파일 게시 사이에서 강제 종료돼 경로가 비었다면 `task/<id>/attempts/<n>/merge-before/files/`와 `captured/`의 실제 버전을 먼저 확인해 허브가 원래 파일을 복구한 뒤 재시도한다. 불명확한 사용자 변경을 자동으로 덮어쓰거나 정확히 한 번 적용을 보장하지 않는다. 원 제품 root에는 자동 게시하지 않는다.

## 정리

clean은 먼저 목록만 반환한다. --apply는 완료 task의 clean worktree만 제거하고 branch·문서·로그·evidence는 보존한다. integration은 run branch 외 제품 branch가 최종 commit을 포함해야 제거 후보가 된다. 원 제품 checkout이 dirty이거나 사용자의 다른 변경이 있으면 자동 전환/병합하지 않는다. remote push/PR/배포는 기존 요청/확정 계획에 있을 때만 별도 수행한다.

Git ignored 파일이 있으면 clean에서 보존하고 retry/repair에서는 이전 attempt의 worktree로 옮겨 보존한다. files 사본은 종료 후의 전체 지문을 대조해 변경이 있으면 보존한다. files integration 사본은 원 제품에 같은 결과 지문이 보존돼야 제거 후보가 된다. 정리는 작업 소유의 실제 root 경계 안에서만 수행한다.
