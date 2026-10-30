---
name: work-parallel
description: work 허브가 계획된 독립 task를 병렬 개발 worker에게 배치하고 결과를 회수·직렬 통합하는 내부 실행 전략이다. 별도 목표·허브·실행을 만들지 않는다.
---

# work-parallel

work가 소유한 같은 run·허브·모델 정책·frozen 계획을 사용한다. 사용자가 직접 이 스킬을 호출했어도 goal/run 입력이 없으면 work의 인계 단계로 연결하고 독자적인 개발 목표를 만들지 않는다. 이 스킬·work·goal-maker를 worker가 재귀 호출하지 않는다.

입력은 WORK_ROOT, hub ID, batch ID, ready task, 실제 가용 용량, 개발 모델/effort, 적용 spec/impl-plan이다. [병렬 실행 규약](references/parallel.md)을 읽는다. 기계적 처리는 이 패키지의 동일 버전 `scripts/wm.py`를 사용한다. 다른 설치 bundle의 원장/스킬을 혼용하지 않는다.

1. status/ready로 DAG·merged deps·phase gate·owns·용량을 검사한다. 독립 task 2개 이상일 때만 병렬 이득을 판단한다. --parallel도 의존/공유 계약을 무시하는 강제 병렬이 아니다.
2. 각 task를 prepare하고 packet을 만든다. deps가 통합된 최신 기준에서 Git branch/worktree 또는 files 격리 사본을 만든다. preparing intent는 owns와 용량을 예약하고 중단 시 같은 attempt로 재개한다. 한 task worktree에는 활성 writer 하나만 둔다.
3. 호스트 native spawn에 실제 개발 모델과 task cwd를 명시하고 handle/모델 설정을 dispatch에 기록한다. 호스트 override 불가/모델 불가면 보류한다. 슬롯만 부족하면 같은 정책으로 직렬화한다. work의 높은 허브 모델 상속으로 숨기지 않는다.
4. worker에 새 설계를 시키지 않는다. owns의 상세 절차·좁은 검증·계획된 로컬 커밋·result 반환만 맡긴다. 공유 포트/DB/출력 자원은 허브가 예약하고 외부 효과 권한은 기존 범위대로 적용한다.
5. 실제 host 종료와 result ID/base/HEAD/clean/owns/검증을 검사해 report한다. 종료 timeout만으로 재기동하지 않는다. 오래된 attempt·중복 결과·회수 뒤 변경을 거부한다.
6. repo별 단일 통합 큐에서 merge한다. 결과 reported는 후행 task를 풀지 않으며 merged SHA와 phase 검증까지 기록해야 한다. 충돌은 원 소유자에게 반환한다. 다른 독립 task는 계속한다.
7. 배치별 task/attempt·requested/resolved/confirmed model·커밋/통합 SHA·검증·충돌·잔여를 work 허브에 반환한다. 최종 리뷰/전체 완료/사용자 결정은 work가 소유한다.

자체 오케스트레이션은 scheduler·소유권·상태·증거·통합 큐다. 에이전트 실행/메시지/대기는 실제 호스트를 사용하며 세션 밖 daemon이나 OS process manager를 제공한다고 주장하지 않는다.
