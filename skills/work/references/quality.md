# 코드·보안 리뷰와 검증

## 검토와 수정

통합 diff에 독립 fresh 읽기 컨텍스트의 코드 리뷰와 보안 리뷰를 적용한다. 가능하면 두 리뷰를 병렬로 수행하되 같은 파일을 동시에 수정하지 않는다. 허브가 지적을 코드·정본·실패 시나리오에 대조해 유효/기각/중복으로 처리한다. 수정은 원래 owns의 한 개발 worker가 수행한다. 리팩토링은 단순화/유지보수 두 관점으로 검토하되 합의 목표에 필요한 범위만 반영한다.

코드 리뷰는 AC/spec 일치, 오류/경계, 회귀, 테스트의 검증력, 호환성, 경쟁·자원 수명, 불필요한 복잡성을 확인한다. 보안 리뷰는 실제 변경에 해당하는 아래 항목을 검토하고 비적용이면 이유를 남긴다.

- 인증·인가·테넌트 경계, 업무 흐름 악용.
- 입력/출력 검증·인젝션·역직렬화, 파일/경로·SSRF.
- 비밀·암호·개인정보·오류/로그 노출.
- 의존성·기본 설정·권한·공급망, 경쟁/데이터 무결성.

웹 변경에는 OWASP ASVS와 Secure Code Review 관점을 연결한다. 정확한 ASVS ID를 인용하면 버전과 실제 확인 근거를 함께 쓴다. 오프라인 실행은 이 내장 점검 기준만으로 가능하고 OWASP 문서 다운로드는 필수가 아니다. ASVS 전체 준수/인증을 선언하지 않는다.

지적은 severity·위치/식별자·공격/실패 시나리오·영향·근거·권고를 남긴다. 불확실한 CRITICAL/HIGH를 임의 하향해 수렴시키지 않는다. 수정 후 영향받은 리뷰·검증만 무효화한다. 테스트/수정 3회, 선택 --cr 5회 상한 이후는 근본 원인·잔여·재개 선택을 보고한다.

## 실제 검증

AGENTS/CI/프로젝트 설정에서 실제 명령을 확인한다. 임의의 테스트/부팅 명령 성공을 가정하지 않는다. 단순 문서 변경에 부팅·DB 실행을 강요하지 않는다. 테스트는 의미 있는 동작/불변식에 집중한다. migration은 DB별 DDL/트랜잭션 특성에 맞는 격리 환경/dry-run을 사용하며 BEGIN/ROLLBACK이 항상 안전하다고 가정하지 않는다.

각 evidence는 revision·실제 명령 argv/cwd·시각·종료 코드·관찰·커버 범위를 담는다. 필수 FAIL·미실행을 not_applicable로 바꾸지 않는다. 외부 효과와 비밀값은 계획/로그에 노출하지 않고 대상 식별과 안전한 근거만 남긴다.

## CLI evidence 계약

검증 결과 JSON을 임시 파일에 실제 내용으로 쓰고 `evidence --work ... --hub ... --file ...`로 보관한다. 다음은 형태 예시다.

```json
{
  "id": "verify-P1-1", "kind": "verification", "status": "pass",
  "revisions": { "app": "실제 통합 SHA" },
  "checks": ["V-FINAL"], "critical": 0, "high": 0,
  "summary": "실제 명령과 관찰 결과 요약",
  "commands": [{ "argv": ["python", "-m", "unittest", "discover"], "cwd": "실제 통합 경로", "exit_code": 0, "observed": "실제 출력 참조" }]
}
```

kind: code_review / security_review / verification / gap / cross_review / phase. 리뷰/gap에는 reviewer와 context(실제 독립 컨텍스트/도구 근거)를 추가한다. not_applicable은 실제 비적용 이유와 범위를 summary에 남기는 경우만 사용한다. CLI는 형식/지문/revision을 검사하며 결과의 진실성을 대신 보증하지 않는다.

phase의 checks가 gate 기준을 만족하면 `gate --id <gate-id> --evidence <phase-evidence-id>`로 후행 작업을 푼다. completion.checks는 pass verification으로 모두 덮여야 한다. 마지막 전체 검토는 현재 revision에서 CRITICAL/HIGH=0인 독립 gap 두 번을 남긴다. 두 번째는 첫 번째 이후 잔여/누락을 다시 판정하는 것이며 동일 빌드를 반복하는 뜻이 아니다.

전체 task 통합, phase gate, 현재 코드/보안 리뷰, 전체 검증, 선택 --cr, 두 번의 잔여 갭 확인을 실제 근거로 갖춘 뒤 complete한다. 계획과 결과를 AC별로 대응해 로컬 완료와 제품 branch 반영·원격 발행 상태를 분리해서 보고한다.
