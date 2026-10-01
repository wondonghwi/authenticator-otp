# Contributing

작은 수정과 오류 제보를 환영합니다. 기능 추가 전에 이슈에서 목적과 변경 범위를 설명해 주세요. 보안 문제는 [SECURITY.md](SECURITY.md)의 제보 방법을 따릅니다.

## 개발 환경

macOS, Python 3.9 이상, Git이 필요합니다. Python 표준 라이브러리만 사용하므로 별도 의존성 설치나 lock 파일은 없습니다.

```sh
python3 -m unittest discover -s tests -v
python3 scripts/check-publication.py
bash -n scripts/install-app.sh
./scripts/install-app.sh --name "auth-otp Dev" --destination "$HOME/Applications"
```

기본 테스트는 키체인과 클립보드를 모의 처리합니다. 실사용 비밀키를 테스트에 넣지 마세요. OTP 로직에는 RFC 6238 공개 벡터를, macOS 연동에는 임시 키체인의 합성 데이터를 사용합니다.

## Pull request

- 목적에 필요한 최소 변경으로 구성합니다.
- 동작 변경에는 실패 조건을 포함한 테스트를 추가합니다.
- 코드·테스트·문서 커밋은 역할이 드러나게 작성합니다.
- 비밀키, 개인 메일·경로, 조직의 계정·인증 설정, `.env`, 키체인 파일과 앱 번들은 올리지 않습니다.
- README의 실제 실행 예시와 변경된 동작을 함께 갱신합니다.
- 아이콘에는 개인 메타데이터를 포함하지 않습니다.

Python 코드는 표준 라이브러리만 사용하고, CI 권한은 읽기 전용으로 유지합니다. 외부 의존성이나 네트워크 전송을 추가하는 변경은 보안 모델을 함께 검토해야 합니다.
