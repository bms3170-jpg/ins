"""Creates a local-only .env with randomized admin password and session key."""
from pathlib import Path
from secrets import token_urlsafe

p = Path(__file__).resolve().parent / '.env'
if p.exists():
    raise SystemExit('.env가 이미 있습니다. 덮어쓰지 않았습니다.')
password = token_urlsafe(18)
key = token_urlsafe(40)
p.write_text(f'''# Local trial settings. Add Meta values + HTTPS redirect to activate auto-import.\nINSTAGRAM_APP_ID=\nINSTAGRAM_APP_SECRET=\nINSTAGRAM_REDIRECT_URI=\nFLASK_SECRET_KEY={key}\nADMIN_PASSWORD={password}\nGRAPH_API_VERSION=v25.0\nCOOKIE_SECURE=0\nDATABASE_PATH=./pickday.sqlite3\n''')
print('.env 파일을 생성했습니다!')
print('관리자 비밀번호:', password)
print('이 비밀번호는 안전한 곳에 보관하세요. 실제 배포에서는 HTTPS 및 COOKIE_SECURE=1 설정이 필요합니다.')
