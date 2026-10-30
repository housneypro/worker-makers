# Codex 호스트와 모델 정책

## 도구 대응

호스트에서 실제 제공하는 spawn / send / wait / inspect / stop 기능을 확인한다. 이름은 환경마다 다르다. 도구가 없는데 있다고 가정하거나 고정 API를 실행하지 않는다. native subagent API가 있으면 사용하고, 별도 CLI worker는 사용자가 허용하고 모델/cwd/종료를 검증할 수 있는 경우에만 사용한다. 세션 종료 후 계속 동작하는 daemon은 제공하지 않는다.

모든 개발 worker spawn에 선택 모델을 **실제 API 인자/실제 적용되는 custom agent 설정**으로 지정한다. 프롬프트에 모델 이름을 쓰는 것은 설정이 아니다. 호스트가 full-history fork의 모델 override를 금지하면 최소 task packet을 담은 fresh/no-history fork를 사용한다. custom agent 고정 모델과 충돌하는지도 확인한다. 설정할 수 없으면 해당 개발 기동을 보류하고 지원되는 대안을 제시한다. 비싼 허브 상속이나 허브 직접 구현으로 조용히 전환하지 않는다.

동시성은 실제 남은 agent slot·공유 자원 상한 이하로 제한한다. 슬롯이 부족하면 동일 모델 정책으로 직렬 실행한다. reasoning은 별도 선택이며 저비용 모델을 low effort로 강제하지 않는다. 모델 실패와 계획 불충분을 구분한다. 사용자에게 허용받은 범위의 개별 task 승격만 적용한다. 전역 Codex 설정은 바꾸지 않는다.

## 모델 기록

- requested_model: 사용자가 선택한 ID.
- resolved_model: spawn 설정이 실제로 받아들인 모델 ID/설정 근거.
- confirmed_model: 호스트가 런타임 정보를 노출한 경우의 확인값. 미노출이면 null.
- handle: 실제 agent/process/session ID. 임의 ID를 만들어 생존처럼 기록하지 않는다.

독립 코드/보안/교차 리뷰의 모델은 개발 worker 선택과 별개로 역량에 맞게 정한다. 실제 다른 모델을 썼을 때만 모델 간 교차 검증이라고 부른다. 같은 모델의 새 컨텍스트는 독립 검증이다.

start의 `--policy-source <explicit|resume|project-default|selection>`에 실제 선택 출처를 기록한다. 사용자가 기본값 저장을 요청했다면 프로젝트 `.worker-makers/project.json`의 `worker_defaults`에 model/reasoning을 보존할 수 있다. run 선택을 사용자 전역 Codex 설정 변경으로 확대하지 않는다.

사용자가 허용한 개별 task 승격/모델 선택은 아직 queued인 task에만 `task-policy --task <id> --worker-model <id> [--worker-reasoning <effort>] --authority <기존 선택/승격 권한의 출처>`로 적용한다. 다른 task와 허브 모델은 바뀌지 않는다. 실행 중인 worker의 모델을 상태 기록만으로 변경하지 않는다. 종료·결과 확인 후 다음 attempt에서 적용한다.

## worker packet

prepare가 만든 task.json과 task의 impl_plan·필요한 brief/spec 참조만 전달한다. 원래 사용자 의도, 적용 지침, PROJECT_ROOT/WORK_ROOT·cwd·base SHA·run/task/attempt ID·owns/deps·허용 검증·중지 조건·결과 경로를 포함한다. worker는 task worktree에서만 코드 수정하고 중앙 원장이나 상위 스킬을 호출하지 않는다.

spawn 후 dispatch 기록이 실패하면 worker를 계속 방치하지 말고 실제 종료/대기시킨 후 원장을 조정한다. 종료 API가 없다면 동시 writer를 안전하게 관리할 수 있는 범위만 실행한다.

## 결과와 종료

worker는 WORK_ROOT/task/T-ID/result.json을 반환한다.

```json
{
  "run_id": "전달받은 ID", "task_id": "T-001", "attempt_id": "전달받은 ID",
  "base_sha": "전달받은 SHA", "status": "completed", "head_sha": "실제 task HEAD",
  "validation": [{ "id": "V-T001", "status": "pass", "command": ["실제 실행 파일", "인자"], "cwd": "실제 경로", "exit_code": 0, "summary": "관찰 결과" }],
  "summary": "구현 결과와 잔여", "no_change_reason": null
}
```

허브는 host handle을 실제 inspect/wait해 writer가 종료됐는지 확인하고 evidence/host-T-ID-attempt.json에 handle·상태·도구 호출/출력 참조를 기록한다. 완료 메시지만으로 종료·커밋·검증을 인정하지 않는다. CLI report에 이 파일의 WORK_ROOT 상대경로를 전달한다. CLI는 Git/ID/owns를 검사하지만 실제 host 종료 여부는 허브가 확인하는 책임이다.

host 근거 JSON에는 `{"handle":"실제 handle","status":"stopped","source":"실제 inspect/wait 결과의 출처"}`를 기록한다. files backend는 head_sha에 `file_snapshot.py --root <worker-cwd>`의 sha256을 넣고 Git commit을 만들지 않는다. requested/resolved와 호스트 confirmed 값이 다르면 기동을 보류해 alias/설정 근거를 조정한다. 런타임 확인값을 노출하지 않으면 null을 유지한다.
