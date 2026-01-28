import time
from playwright.sync_api import sync_playwright

LOGIN_URL = "https://nid.naver.com/nidlogin.login"
AUTH_FILE = "auth.json"


def save_login_state():
    with sync_playwright() as p:
        print("🚀 브라우저를 실행합니다...")
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        # 로그인 페이지로 이동
        page.goto(LOGIN_URL)

        # 2. 사용자 대기
        print(f"'{LOGIN_URL}'에 접속했습니다.")
        print("브라우저에서 아이디/비밀번호를 입력하고 로그인을 완료하세요.")
        print("로그인이 완료되면, 이 터미널에서 [Enter] 키를 누르세요...")

        input()  # 사용자가 엔터 칠 때까지 무한 대기

        # 3. 로그인 상태 저장
        context.storage_state(path=AUTH_FILE)
        print(f"✅ 로그인 정보(쿠키/세션)가 '{AUTH_FILE}' 파일로 저장되었습니다!")

        browser.close()


if __name__ == "__main__":
    save_login_state()
