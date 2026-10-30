# 배치·병렬성 판단

기본 auto는 ready task가 여럿이어도 계약 공유·충돌·시작 비용·실제 용량을 고려한다. 같은 파일, 상위/하위 디렉터리 owns, lockfile, schema, 코드 생성 산출물은 소유가 분리되지 않으면 직렬로 처리한다. task 의미/owns/deps를 바꾸려면 goal-maker에서 계획을 개정한다. batch ID만 새로 부여하고 run ID는 유지한다.

task A의 worker 완료와 A의 integration merge는 다르다. B.deps=[A]라면 A merged 후의 기준에서 B를 준비한다. B.requires_gates가 있으면 그 phase 검증까지 통과해야 한다. worker 완료 메시지를 계기로 B를 먼저 띄우지 않는다.

실제 가용 host API에 spawn/send/wait/inspect/stop을 대응한다. fork 모델 override 제약은 fresh/no-history worker로 해결할 수 있는지 확인한다. 모든 개발자에게 명시적 모델을 적용하고 요청/설정/런타임 확인값을 구분한다. 종료 확인이 불가능하면 안전하게 단일 writer를 보장할 수 있는 범위만 실행한다.

허브만 중앙 state/events를 쓴다. worker는 task 결과와 task 코드만 쓴다. 같은 task 재시도는 실제 writer 종료·Git 상태·이전 커밋 보존을 먼저 확인한다. 미통합 결과를 지우거나 오래됐다는 이유로 lock을 탈취하지 않는다. 통합 중 중단은 실제 cherry-pick/HEAD와 intent를 조정한 후 재개한다.

work에서 수정 배치를 받으면 같은 owns/모델/결과 프로토콜을 적용한다. 전체 코드/보안 리뷰·전체 부팅·최종 gap 검증을 각 worker에서 중복 실행하지 않는다. 요구/계획 결함은 허브에 원인·근거와 반환하고 worker가 상위 스킬을 호출하지 않는다.

Git이 없는 프로젝트는 work의 files backend로 동일한 DAG·격리 사본·지문 대조·회수 규약을 따른다. 파일 사본과 백업의 hard link 지원 등 격리 조건이 없으면 쓰기 기동을 보류하고 사유를 보고한다. 여기서 Git 초기화나 최초 커밋을 임의로 하지 않는다.
