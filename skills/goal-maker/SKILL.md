---
name: goal-maker
description: 합의된 brief나 확정 요구를 조사해 plans, spec, 매우 상세한 impl_plans, goal 패키지로 순차 수렴시킨다. 저비용 개발 worker가 설계를 추측하지 않고 실행할 작업 계획을 만든다.
---

# goal-maker

요구 합의는 breif-maker, 기술 조사·계획·명세·task 분해는 이 스킬, 개발 실행은 work가 소유한다. work의 허브가 높은 모델을 사용해도 불충분한 계획을 즉석 설계로 메우게 만들지 않는다.

입력은 `--from-brief <brief.md>` 또는 동일하게 확정된 요구와 합의 출처다. 기존 요구를 R/AC로 대응시킬 수 있으면 다시 브레인스토밍시키지 않는다. 프로젝트 root와 WORK_ROOT는 원래 연결을 유지한다. 새 작업 공간만 `python <SKILL_ROOT>/scripts/wm.py init --project <root> --name <이름>`으로 만든다.

## 계획 파이프라인

[계획·수렴 규약](references/planning.md)과 [상세 impl-plan 템플릿](assets/impl-plan.md)을 읽는다. 실행 인계에는 [goal.json 계약](references/goal-contract.md)을 적용한다.

1. 입력의 목적·R/AC·합의·비목표·권한 범위를 확인한다. AGENTS.md와 실제 코드·테스트·CI·명령·환경을 조사하고 파일/심볼/설정 근거를 확보한다. 기술 선택은 확인한 프로젝트 자산과 제약에 근거한다.
2. 작업을 bounded/architectural로 분류한다. 작은 작업도 필요한 spec을 짧게 남긴다. 준비도는 READY/DEFERRED/NOT_APPLICABLE/BLOCKED로 판정한다. 확보하지 못한 필수 사실은 실행 가능한 정본으로 만들지 않는다.
3. `plans/`를 작성·리뷰·수정해 수렴시킨다. 문제·근거·대안·D-ID 결정·R/AC 범위 계약·검증 매트릭스·리스크·환경 준비도를 담는다.
4. plans 수렴 후 `spec/`를 작성·수렴시킨다. 정확한 인터페이스·타입·동작·실패·호환성·데이터/보안 계약과 검증 사례를 S-ID로 명세한다. architectural은 공유 계약을 먼저 고정하고 독립 영역 문서만 병렬 작성한다.
5. spec 수렴 후 `impl_plans/`를 작성·수렴시킨다. T-ID별 repo·phase·owns·deps·선행 검증 gate·수정 경로/심볼·정확한 변경 절차·허용 명령/기대 결과·실패 처리·롤백·완료 체크리스트를 구체화한다. 낮은 모델의 worker가 새 제품/기술 결정을 내리지 않고 수행 가능한지 별도로 검토한다.
6. `goal.md`, `pre-work.md`, 실행용 `goal.json`을 만든다. 확장 제안은 필요할 때만 `backlog.md`에 격리한다. brief→R/AC→D→S→T→검증을 연결하고 source revision·수렴 evidence·합의 출처·권한 경계·필수 환경을 기록한다. 계획된 로컬 커밋과 원격 발행/배포 권한을 구분한다.
7. 모든 인계 문서에 실제 완료 확인 후 `<!-- WORKER-MAKERS:COMPLETE -->`를 넣고 해시를 goal.json에 기록한다. `python <SKILL_ROOT>/scripts/wm.py validate-goal --work <WORK_ROOT>`로 구조·지문·DAG·선행조건을 검증한다. 이 검사는 내용의 타당성이나 실제 사용자 합의를 대신하지 않는다.

단계 사이의 수렴 배리어를 건너뛰지 않는다. 한 단계 안의 독립 문서/관점 리뷰만 병렬화한다. 사용자에게 새 계획 승인을 강요하는 토큰/파일을 만들지 않는다. 기존 승인/계획 작성 요청을 보존하고 실제로 새로운 요구·권한만 필요한 결정을 받는다.

## 계획 중 질문

요구 의문이면 Q-ID·단계·문서/체크포인트·brief revision·영향 R/AC/D·확인 근거·답의 영향을 clarifications.md에 기록한다. 같은 설치 bundle의 breif-maker를 찾아 **질의응답 모드**를 같은 허브 대화에서 적용한다. 기술 사실/선택은 이 스킬이 조사·판단한다.

breif-maker의 답을 근거와 revision에 대조한다. 기존 합의로 풀리지 않으면 허브가 사용자에게 질문하고 의존 결정은 보류한다. 독립 조사와 같은 단계의 무관한 초안은 계속할 수 있다. 답을 받으면 영향 문서만 수정·재수렴하고 같은 체크포인트로 돌아간다. 새 정보 없이 반복 질의하지 않는다. breif-maker가 없으면 같은 역할 경계로 요구 출처를 확인하고 필요한 사용자 질문을 직접 전달하되 외부 패키지 설치를 선결 조건으로 만들지 않는다.

## 인계

수렴된 패키지 경로·revision·합의/미확인 사실·선행작업·권장 작업 배치를 보고한다. work의 허브 모델이나 worker 모델을 여기서 선택하지 않는다. `work --from-goal <goal.md>`가 개발 진입점이며, 사용자 실행 요청이 이미 있으면 같은 세션에서 이어갈 수 있다.
