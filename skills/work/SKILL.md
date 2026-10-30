---
name: work
description: 합의된 goal.md의 개발을 단일 허브에서 실행·리뷰·검증한다. 개발 worker 모델을 명시적으로 정하고 상세 계획의 task를 직렬 또는 work-parallel로 수행하며 상태 조회·재개·정리를 지원한다.
---

# work

이 세션이 유일한 허브다. 사용자가 세션에 선택한 허브 모델을 유지한다. 구현은 별도 개발 worker에게 위임하며 단일 작업도 같은 원칙이다. 요구/기술 계획을 여기서 새로 만들지 않는다. 이 패키지의 실행 규약과 실제 호스트 도구를 사용한다.

## 호출

- `work --from-goal <goal.md> [--parallel | --serial] [--worker-model <id>] [--worker-reasoning <effort>] [--cr]`
- `work`: 현재 프로젝트에 연결된 활성 run을 재개하거나 합의된 goal이 정확히 하나면 실행한다. 최신 수정 시각으로 임의 선택하지 않는다.
- `--status`, `--resume`, `--extend <후속>`, `--clean`은 관리 모드다. 신규 일반 요구는 breif-maker/goal-maker로 안내하고 연결 goal을 확인한다.

위 표기는 호스트의 스킬 입력이다. 셸 실행 파일 `work`를 설치하지 않는다. 기계적 조작은 `python <SKILL_ROOT>/scripts/wm.py --help`의 실제 CLI를 사용한다.

## 시작 전

1. WORK_ROOT·최초 PROJECT_ROOT·제품 repo를 원래 연결로 확인한다. 적용 지침, brief/goal/pre-work/plans/spec/impl_plans·수렴 evidence·기존 합의/권한·환경 준비도를 읽는다. backlog는 실행 범위가 아니다.
2. goal.json이 있으면 `validate-goal`을 실행한다. 구형 goal은 실제 동등한 승인 내용을 매핑한다. D-ID별 재사용 판정·신규 도입 근거와 phase/검증의 완료 기준 대응도 확인한다. 실제 누락·계약 결함은 goal-maker, 요구 의문은 breif-maker 역할로 반환한다. 사용자가 이미 맡긴 범위의 교정에 수동 스킬 재호출이나 새 승인 파일을 강요하지 않는다.
3. 모델 정책은 [호스트·모델 규약](references/host-model.md)을 적용한다. 첫 개발 worker 전에 `--worker-model` > 동일 run의 기존 선택 > 사용자가 저장한 프로젝트 기본값 > 한 번 질문 순서로 결정한다. 실제 가용 후보의 저비용 개발 모델을 추천하되 가격/가용성을 추정으로 단정하지 않는다. reasoning·동시성·승격·독립 리뷰 모델은 별개다.
4. Python CLI의 Git/files 경로에서 `start --work <WORK_ROOT> --hub <안정적인-hub-id> --worker-model <id> [--worker-reasoning ...] --mode <auto|serial|parallel> --capacity <상한> [--cr]`로 run을 만든다. `--policy-source`에 실제 선택 출처를 기록한다. 기존 run에는 start를 반복하지 않는다. files는 Git 커밋 대신 격리 사본과 파일 지문을 사용한다.

## 개발 실행

[실행·복구 규약](references/execution.md)을 읽는다. `ready`로 통합된 deps·phase gate·owns·용량 조건을 만족한 task를 얻는다. auto 기본, --parallel은 독립 task 병렬 우선, --serial은 항상 한 개발 worker다. 병렬은 동일 bundle의 work-parallel을 적용한다. 별도 허브/run을 만들지 않는다.

각 task에 prepare → 실제 host spawn(명시적 모델/cwd/packet) → dispatch 기록 → 결과/종료 검사 → report → merge를 수행한다. 준비 intent는 preparing 상태로 먼저 기록한다. 중단된 preparing은 같은 prepare로 실제 사본/기준을 확인해 같은 attempt를 이어간다. 상세 impl-plan의 의미·owns·deps를 바꾸지 않는다. worker는 필요한 좁은 테스트와 Git 로컬 커밋 또는 files 지문을 수행한다. 공유 자원·전체 부팅/빌드·DB/API 외부 효과는 허브가 기존 권한/계획에 따라 관리한다.

구현 중 떠오른 일반화·인접 정리·추가 하네스를 상세 계획에 몰래 끼워 넣지 않는다. 필수 결함이면 담당 단계로 반환하고 없어도 목표가 성립하면 backlog로 격리한다.

실패는 구현 오류→원 소유 worker, 계획/계약 누락→goal-maker, 요구 선택→breif-maker, 환경/권한/모델→허브로 분류한다. 허브가 계획을 즉석으로 메우거나 같은 파일에 여러 writer를 만들지 않는다. phase 검증이 필요한 후행 task는 merge만으로 시작하지 않는다.

## 품질·완료

[리뷰·검증 규약](references/quality.md)을 적용한다. 통합 결과에 독립 읽기 코드 리뷰와 보안 리뷰를 수행하고 지적의 타당성을 허브가 판정한다. 수정은 한 소유자에게 반환한다. 두 관점의 리팩토링 제안도 읽기 검토 후 같은 소유자가 필요한 범위만 반영한다.

수정 영향 리뷰·검증만 다시 수행한다. 테스트/수정 루프 최대 3회, 선택적 --cr 독립 검증 최대 5회 이후에도 실패하면 원인·잔여·선택지를 보고한다. 이 상한을 goal-maker의 문서 수렴 루프에 적용하지 않는다.

필수 phase gate를 기록하고 다음 phase를 계속한다. 마지막에 현재 통합 revision의 코드/보안 리뷰·필수 전체 검증과 연속 두 번 차단급 없는 잔여 갭 확인을 evidence로 남긴 후 `complete`한다. 같은 코드에서 빌드를 두 번 실행할 필요는 없다. 실제 증거 없이 status만 완료로 만들지 않는다.

완료 보고는 AC/goal 대비 결과, 통합 branch/SHA, 실제 검증, 잔여/미실행, 사용자 checkout에 반영 여부, 원격 발행 여부를 구분한다. 도구는 사용자 원래 branch를 자동 변경하거나 push하지 않는다. 계획/요청에 원래 branch 반영이 포함되면 dirty 상태를 보존하며 명시된 통합을 별도 수행하고 증거를 남긴다.

## 관리

- status: CLI status + 실제 host/Git 상태를 대조한다.
- resume: 원장→실제 Git/diff→기존 host handle→외부 효과→미완료 task 순으로 조사한다. 관찰 timeout은 종료가 아니다. 살아 있는 writer 확인/종료 없이 새 attempt를 만들지 않는다.
- extend: 같은 목표의 후속만 받는다. 요구/계획 변경은 담당 스킬에서 증분 수렴하고 이전 frozen 자료를 보존한다. 다른 목표는 새 WORK_ROOT다.
- clean: `clean`으로 대상 목록을 보고 `clean --apply`로 소유·clean·보존 확인된 worktree만 제거한다. 계획/로그/evidence·branch·설치 자산은 보존한다. 원격 삭제는 포함하지 않는다.
