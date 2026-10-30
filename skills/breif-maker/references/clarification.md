# goal-maker 질의응답 모드

입력은 question_id, 현재 plans/spec/impl_plans 단계·문서·체크포인트, brief revision, 영향 R/AC/D, 확인한 근거, 답에 따라 바뀔 계획이다. 순수 기술 판단은 goal-maker로 반환한다.

1. 같은 의미·같은 근거 revision의 질문 기록을 재사용한다. 새 정보 없이 같은 질문을 다시 순환시키지 않는다.
2. brief·사용자 대화·지정 정본에서 명시적 합의나 명확한 규칙 적용을 찾는다. 답·출처·참조 revision·적용 논리를 함께 반환한다. 사용자가 위임한 선택 범위 안에서는 스스로 결정할 수 있다.
3. 근거가 없거나 상충하면 필요한 질문·선택지·답이 바꿀 부분을 작성한다. 현재 대화의 허브가 사용자에게 질의한다. 다른 agent가 사용자인 것처럼 답하지 않는다. 허브가 답을 받기 전에는 해당 결정을 확정하지 않는다.
4. 기존 합의 확인은 질문 기록만 보완한다. 새 요구 결정은 brief revision을 올려 기록하며 이전 정본을 보존한다. 기술 계획은 수정하지 않는다.

응답 형식:

```json
{
  "question_id": "Q-001",
  "status": "resolved",
  "brief_revision": "B-2",
  "answer": "기존 합의에서 확인한 답 또는 실제 새 사용자 답",
  "sources": ["brief.md §합의 R-001; 사용자 대화의 해당 선택"],
  "affected": ["R-001", "AC-001"],
  "brief_changed": false,
  "resume_checkpoint": "plans/main.md 결정 D-002"
}
```

`status`는 resolved / needs_user / blocked다. needs_user에는 question/options/impact를, blocked에는 확보할 수 없는 근거·소유자·재개 조건을 포함한다. 질문과 답은 WORK_ROOT/clarifications.md에 남긴다. goal-maker는 응답과 revision을 확인해 영향 계획을 수정·재수렴한 뒤 원래 체크포인트로 돌아간다. 이 모드는 goal-maker를 다시 시작하지 않는다.
