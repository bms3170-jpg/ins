# 픽데이 자동 체험단 추첨기 (PICKDAY Auto)

인스타그램 **프로페셔널(비즈니스/크리에이터) 계정** 소유자가 직접 관리하는 게시물의 URL을 입력하면, 공식 Meta **Instagram API with Instagram Login**으로 최상위 댓글을 수집하고, 참가자를 집계해 랜덤 추첨/사다리타기를 하는 웹앱입니다. 인스타그램·Meta의 공식 서비스는 아닙니다.

## 기능

- Instagram 공식 OAuth 로그인(계정 비밀번호를 앱에서 직접 입력받지 않음)
- 내 계정이 게시한 피드 게시물과 릴스 URL 판별, 계정 소유 미디어 일치 확인
- 커서 기반 댓글 전체 페이지 수집(최대 50,000개; 그 이상은 **추첨 중단**, 부분 수집으로 추첨하지 않음)
- 동일 계정 중복 제외, 키워드 필터, 운영자 등 제외 계정 지정, 참여자 통계
- 브라우저 암호학적 랜덤 추첨, 랜덤 후보를 이용한 사다리타기(최대 48명 당첨)
- 당첨 결과 텍스트 복사·CSV 내보내기(게시물, 수집 시각, 스냅샷 SHA-256 포함)
- 관리자 비밀번호 보호, 서버측 OAuth 토큰 암호화(SQLite), CSRF 토큰 검증, URL 검증
- Meta 연결 전에도 **예시 데이터**로 추첨 화면을 시험할 수 있습니다.

## 1. 준비

- Python 3.10 이상
- 인스타그램 **비즈니스 또는 크리에이터 계정**, 본인이 올린 게시물
- [Meta for Developers](https://developers.facebook.com/apps/) 에서 만든 앱. **Instagram API with Instagram Login** 설정 후 로그인 권한 `instagram_business_basic`, `instagram_business_manage_comments`를 요청합니다.
- **Instagram Redirect URI**를 Meta 앱 대시보드에 정확히 등록합니다. 예: `https://YOUR-DOMAIN.example/auth/callback`
- 외부 이용자도 연결하는 상용 서비스는 Meta의 **Advanced Access/App Review/Business Verification**이 추가로 필요할 수 있습니다. 내 계정으로 시험하는 개발 모드는 Meta 앱 역할/테스터 설정이 필요할 수 있습니다.

**주의:** 일반 개인 계정이나 다른 사람이 소유한 게시물은 이 구성으로 자동 수집할 수 없습니다. 계정 소유자에게서 적법한 권한을 얻지 않은 댓글을 임의로 스크래핑하지 않습니다. 좋아요·팔로우·태그·공유 여부를 검증하지 않습니다. 대댓글은 제외합니다.

## 2. 서버 실행

```bash
# 폴더 안에서
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env       # Windows: copy .env.example .env
```

`.env`에 값을 채웁니다:

```env
INSTAGRAM_APP_ID=YOUR_INSTAGRAM_APP_ID
INSTAGRAM_APP_SECRET=YOUR_INSTAGRAM_APP_SECRET
INSTAGRAM_REDIRECT_URI=https://YOUR-PUBLIC-HTTPS-DOMAIN/auth/callback
FLASK_SECRET_KEY=PASTE_A_PERSISTENT_RANDOM_32_CHARACTER_SECRET_HERE
ADMIN_PASSWORD=USE_A_DIFFICULT_PRIVATE_PASSWORD_HERE
COOKIE_SECURE=1
GRAPH_API_VERSION=v25.0
```

그런 다음:

```bash
python app.py
```

`http://127.0.0.1:5000`에서 화면을 볼 수 있습니다. 브라우저에서 관리자 비밀번호로 로그인한 뒤 **인스타그램 연결 → 게시물 URL 입력 → 댓글 자동 수집 → 추첨**을 진행합니다.

**HTTPS 필수 안내:** 실제 Meta OAuth 리디렉션을 위해서는 대시보드에 등록한 공개 **HTTPS 주소**로 앱을 띄우는 것이 좋습니다. 로컬 테스트 때도 안전한 HTTPS 터널/도메인과 `INSTAGRAM_REDIRECT_URI`를 일치시키세요. HTTP localhost로 실행해서 UI와 예시 추첨은 시험할 수 있지만 OAuth가 허용된다는 뜻은 아닙니다. localhost HTTP에서 테스트할 때는 `COOKIE_SECURE=0`을 사용합니다.

## 3. 배포

Render, Railway, VPS 등 Python 서버를 실행하는 곳에 이 폴더를 배포할 수 있습니다. 시작 명령 예시:

```bash
gunicorn -w 1 -b 0.0.0.0:$PORT app:app
```

동일한 환경변수를 호스팅 플랫폼의 Secret/Environment에 등록하고 **비밀키와 Meta 앱 시크릿을 코드에 넣거나 공개 저장소에 커밋하지 마세요.** 프로덕션에서는 `COOKIE_SECURE=1` 및 HTTPS 사용이 필수입니다. 토큰 저장용 SQLite DB(`DATABASE_PATH`)는 **영속 디스크**에 둬야 재시작해도 로그인이 유지됩니다. 단일 운영자·단일 인스타 계정 설계이므로 `gunicorn -w 1`로 시작합니다. 다중 운영자/상용 배포 시 인증·DB·암호 키·데이터 보존 정책의 추가 설계가 필요합니다.

## 4. 데이터와 공정성

1. 백엔드는 사용자 URL로 직접 접속하지 않고, URL에서 단축 코드만 검증해 내 계정의 미디어 목록과 비교합니다. 정확히 일치하는 게시물에 한해 공식 API로 댓글을 가져옵니다.
2. **최상위 댓글만** 조회하며 계정 ID 대신 Meta 댓글 응답의 `username` 값으로 사용자 중복을 판단합니다. `username`이 없는 댓글은 집계에서 제외하고 개수를 표시합니다.
3. 모든 페이지를 수집한 시점의 **스냅샷**으로 추첨합니다. 인스타에 댓글이 추가되면 **다시 수집**해야 반영됩니다. 동시 수정 중에는 스냅샷이 달라질 수 있습니다.
4. 암호학적 랜덤 추첨은 `crypto.getRandomValues`의 Fisher–Yates 셔플을 이용합니다. 사다리타기는 전체 신청자에서 동일 확률로 후보를 무작위 선출(최대 48명)한 후 사다리 경로를 그립니다. 시각화 후보 선출도 무작위이므로 전체 대상에 균등한 기회를 제공합니다.
5. 댓글 원본은 API 응답으로 관리자 브라우저에 전달되며, 본 앱은 **댓글 원문을 DB에 영구 저장하지 않습니다**. 계정 토큰만 암호화해 SQLite에 저장합니다. CSV를 내려받으면 사용자 기기에 보관됩니다.
6. 참가자 응모 조건과 제외 계정은 **추첨 전에 확정**하는 것을 권장합니다. 추첨 후 댓글/필터가 바뀌면 브라우저가 이전 결과를 초기화합니다.

## 5. 자주 발생하는 문제

- **계정 연결이 안 돼요** → 인스타 프로 계정인지, 앱 역할/테스터 초대 및 동의가 되었는지, 정확히 같은 Redirect URI를 등록했는지, Meta 앱 권한이 제공되었는지 확인하세요.
- **게시물을 찾지 못했어요** → 연결한 **그 계정이 올린** 게시물인지 확인하세요. 계정의 과거 미디어 10,000개를 넘어서면 탐색 상한에 걸릴 수 있습니다.
- **API 권한 오류가 떠요** → `instagram_business_manage_comments` 승인 상태와 앱 접근 수준을 확인하세요.
- **종종 로그인 해제돼요** → Meta 토큰이 만료되거나 폐기될 수 있어 다시 연결해야 합니다. 앱 실행 키를 바꾸면 저장된 토큰 복호화가 불가능해집니다.
- **다운로드 버튼이 안 보여요** → 추첨을 완료하면 하단 결과에서 `CSV 저장` 또는 `발표문 복사`가 활성화됩니다.

## 6. 테스트

```bash
python -m unittest discover -s tests -v
```

위 자동 테스트는 Meta API 응답을 **모의(mock)한 테스트**입니다. 실제 Instagram 계정과의 연동은 Meta 앱이 준비되어야 검증할 수 있습니다.

## 공식 참고자료

- Meta 공식 Instagram API 문서·컬렉션: https://www.postman.com/meta/instagram/collection/6yqw8pt/instagram-api
- Meta 개발자 대시보드: https://developers.facebook.com/apps/
