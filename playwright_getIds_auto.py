import os
import time
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
import random
import re
import csv


def random_sleep(min_seconds, max_seconds):
    sleep_time = random.uniform(min_seconds, max_seconds)
    print(f"{sleep_time:.2f}초 동안 대기")
    time.sleep(sleep_time)


def human_click(page, locator):
    """
    탐지에 걸리지 않기 위해
    사람처럼 마우스를 이동하여 클릭하는 함수
    """
    try:
        # 해당 요소가 보이도록 스크롤
        random_sleep(0.3, 0.7)

        box = locator.bounding_box()
        if box:
            target_x = box["x"] + box["width"] * random.uniform(0.2, 0.8)
            target_y = box["y"] + box["height"] * random.uniform(0.2, 0.8)

            page.mouse.move(target_x, target_y, steps=random.randint(20, 60))
            random_sleep(0.1, 0.3)
            page.mouse.down()
            random_sleep(0.05, 0.15)
            page.mouse.up()
        else:
            locator.click()
    except Exception as e:
        print(f"  [Human Click] 실패: {e}")
        locator.click()


TARGET_URL = "https://www.naver.com"
AUTH_FILE = "auth.json"
TARGET_CAFE_MENU_URL = "https://m.cafe.naver.com/ca-fe/web/cafes/21771803?tab=popular"

# 환경변수로 범위 설정 (기본값: 0-100)
START_INDEX = int(os.environ.get("START", 0))
END_INDEX = int(os.environ.get("END", 100))
WORKER_ID = os.environ.get("WORKER", "0")

BATCH_SIZE = 100
MIN_BATCH_WAIT = 0
MAX_BATCH_WAIT = 5
# URL에서 카페 ID 추출 (cafes/ 뒤의 숫자)
MENU_ID = TARGET_CAFE_MENU_URL.split("cafes/")[1].split("?")[0]
CSV_FILENAME = f"collected_data_menu{MENU_ID}_worker{WORKER_ID}.csv"

print(f"[Worker {WORKER_ID}] 범위: {START_INDEX} ~ {END_INDEX}, 저장: {CSV_FILENAME}")


def extract_naver_id(html_content):
    """
    HTML 소스에서 네이버 ID 정보를 추출하는 함수
    """
    try:
        # onload 패턴에서 JSON 형식 데이터로 되어있는 두 번째 인자 추출
        pattern = re.compile(r"onload\('([^']+)',\s*'([^']+)'\);")
        matches = pattern.findall(html_content)

        if matches:
            nickname = matches[0][0]
            print(f"추출된 닉네임: {nickname}")
            return nickname
    except Exception as e:
        print(f"  [Error] ID 추출 중 오류 발생: {e}")
        return None


def extract_level(page):
    try:
        if "탈퇴" in page.locator(".nickname").inner_text():
            return ""
        grade = page.locator(".member_grade").inner_text()
        # "등급\n성실맘" 형식에서 두 번째 줄만 추출
        return grade.strip().split("\n")[-1].strip()
    except Exception as e:
        print(f"  레벨 추출 실패: {e}")
        return ""


def extract_post_info(page):
    """
    게시글 페이지에서 제목, 작성자 닉네임, 작성 시간, 조회수 추출하는 함수
    제목 추출 실패 시 None 반환 (다음 게시글로 넘어가기 위함)
    """
    post_info = {
        "title": "",
        "nickname": "",
        "write_time": "",
        "view_count": "",
    }

    try:
        title_elem = page.locator(".tit").first
        post_info["title"] = title_elem.inner_text().strip() if title_elem else ""
        if not post_info["title"]:
            print("  제목 추출 실패: 제목이 비어있음")
            return None
    except Exception as e:
        print(f"  제목 추출 실패: {e}")
        return None

    try:
        nick_elem = page.locator(".nick .end_user_nick").first
        post_info["nickname"] = nick_elem.inner_text().strip() if nick_elem else ""
    except Exception as e:
        print(f"  닉네임 추출 실패: {e}")

    try:
        time_elem = page.locator(".date").first
        post_info["write_time"] = time_elem.inner_text().strip().split("\n")[-1].strip() if time_elem else ""
    except Exception as e:
        print(f"  작성 시간 추출 실패: {e}")

    try:
        view_elem = page.locator(".no").first
        post_info["view_count"] = view_elem.inner_text().strip() if view_elem else ""
    except Exception as e:
        print(f"  조회수 추출 실패: {e}")

    return post_info


def process_post(page, index, is_first_post=True):
    """
    is_first_post: True면 목록에서 스크롤하여 찾기,
                   False면 siblingContent에서 다음 게시글로 이동
    """
    print(f"\n[{index + 1}번째 게시글 처리 중]")

    # 2. i번째 게시글에서 정보 추출
    post_item = None
    post_info = {
        "title": "",
        "nickname": "",
        "write_time": "",
        "view_count": "",
        "naver_id": "",
        "level": "",
    }

    try:
        if is_first_post:
            # 첫번째 게시물: 목록에서 스크롤하여 찾기
            # 게시글 목록 로딩 대기
            try:
                page.wait_for_selector(".PopularArticleList .ListItem", timeout=5000)
            except Exception:
                print("게시글 목록을 찾을 수 없습니다.")
                return None

            # 리스트 요소 다시 찾기 (광고 게시글 제외)
            post_selector = ".PopularArticleList .ListItem:not(.adtype_infinity)"

            # 해당 인덱스의 게시글이 로드될 때까지 스크롤
            prev_count = 0
            no_change_count = 0
            max_no_change = 20  # 20회 연속 변화 없으면 종료

            while True:
                current_count = page.locator(post_selector).count()
                print(f"현재 로드된 게시글 수: {current_count}, 필요한 인덱스: {index}")

                if current_count > index:
                    # 원하는 게시글이 로드됨
                    break

                # 게시글 수 변화 체크
                if current_count == prev_count:
                    no_change_count += 1
                    if no_change_count >= max_no_change:
                        print(f"[ERROR] 게시글 수가 {current_count}개에서 더 이상 증가하지 않음. 인덱스 {index}는 존재하지 않습니다.")
                        return None
                else:
                    no_change_count = 0
                prev_count = current_count

                # 아직 로드 안됨 -> 페이지 끝까지 스크롤
                for _ in range(4):  # 3번 스크롤
                    page.mouse.wheel(0, 1000)
                    page.wait_for_timeout(200)

                # 스크롤 후 잠시 대기
                page.wait_for_timeout(300)

                # "더보기" 버튼 찾아서 클릭
                more_btn = page.locator(".btn_list_more button.CdsButton").first
                if more_btn.is_visible():
                    print("더보기 버튼 클릭")
                    human_click(page, more_btn)
                    page.wait_for_timeout(800)
                else:
                    # 더보기 버튼이 없으면 추가 스크롤 시도
                    page.mouse.wheel(0, 1000)
                    page.wait_for_timeout(300)

            post_item = page.locator(post_selector).nth(index)
            post_item.scroll_into_view_if_needed()
            random_sleep(0.3, 0.5)

            print("스크롤 완료")

            # 클릭 전 현재 URL 저장
            url_before_click = page.url

            target_link = post_item.locator("a").first
            human_click(page, target_link)

            page.wait_for_load_state("domcontentloaded")
            random_sleep(0.5, 1)

            # URL 변경 확인 및 게시글 페이지 검증
            current_url = page.url
            retry_count = 0
            max_retries = 3

            while current_url == url_before_click or "tab=popular" in current_url:
                retry_count += 1
                if retry_count > max_retries:
                    print(f"  [WARNING] {max_retries}회 재시도 후에도 게시글 이동 실패")
                    break

                print(f"  [WARNING] URL 변경 안됨, 재시도 {retry_count}/{max_retries}...")

                # 게시글 다시 찾아서 클릭
                post_item = page.locator(post_selector).nth(index)
                post_item.scroll_into_view_if_needed()
                random_sleep(0.3, 0.5)

                target_link = post_item.locator("a").first
                try:
                    # expect_navigation으로 명시적 네비게이션 대기
                    with page.expect_navigation(timeout=10000):
                        target_link.click()
                except Exception as nav_err:
                    print(f"  [WARNING] 네비게이션 대기 실패: {nav_err}")

                page.wait_for_load_state("domcontentloaded")
                random_sleep(0.5, 1)
                current_url = page.url

            # 게시글 페이지 제목 요소 로딩 대기
            try:
                page.wait_for_selector(".tit", timeout=5000)
                print("게시글로 이동했습니다.")
            except Exception:
                print("  [WARNING] 게시글 제목 요소를 찾을 수 없음")

            print(f"  [DEBUG] 최종 URL: {current_url}")
        else:
            # 두번째 게시물부터: siblingContent에서 다음 게시글 클릭
            print("siblingContent에서 다음 게시글 찾는 중...")
            post_selector = ".SiblingArticleFlicker .PREV_NEXT .BasicArticleList"

            basic_list = page.locator(post_selector)

            # .now의 인덱스를 찾아서 그 다음 항목 선택
            all_items = basic_list.first.locator(".ListItem")
            now_index = -1
            for i in range(all_items.count()):
                if "now" in (all_items.nth(i).get_attribute("class") or ""):
                    now_index = i
                    break

            next_post = None
            if now_index >= 0 and now_index + 1 < all_items.count():
                # next_post의 a 태그
                next_post = all_items.nth(now_index + 1).locator("a").first

            if next_post and next_post.is_visible():
                url_before_click = page.url

                # 클릭과 동시에 네비게이션 대기
                try:
                    with page.expect_navigation(timeout=10000):
                        next_post.click()
                except Exception as nav_err:
                    print(f"  [WARNING] 네비게이션 대기 실패: {nav_err}")

                page.wait_for_load_state("domcontentloaded")
                random_sleep(0.5, 1)
                current_url = page.url

                # URL 변경 및 유효성 검증
                retry_count = 0
                max_retries = 2

                while current_url == url_before_click or "tab=popular" in current_url:
                    retry_count += 1
                    if retry_count > max_retries:
                        print(f"  [WARNING] 다음 게시글 이동 실패, 목록에서 재시도")
                        page.goto(TARGET_CAFE_MENU_URL)
                        page.wait_for_load_state("domcontentloaded")
                        random_sleep(1, 2)
                        return process_post(page, index, is_first_post=True)

                    print(f"  [WARNING] URL 변경 안됨, 재시도 {retry_count}/{max_retries}...")
                    next_post.click()
                    page.wait_for_timeout(1500)
                    current_url = page.url

                # 게시글 페이지 제목 요소 로딩 대기
                try:
                    page.wait_for_selector(".tit", timeout=5000)
                    print("다음 게시글로 이동했습니다.")
                except Exception:
                    print("  [WARNING] 게시글 제목 요소를 찾을 수 없음")

                print(f"  [DEBUG] 최종 URL: {current_url}")
            else:
                print("다음 게시글을 찾을 수 없음, 목록으로 복귀하여 재시도")
                page.goto(TARGET_CAFE_MENU_URL)
                page.wait_for_load_state("domcontentloaded")
                random_sleep(1, 2)
                # 재귀 호출로 목록에서 찾기
                return process_post(page, index, is_first_post=True)

        # 게시글 URL 저장 (나중에 복귀용)
        post_url = page.url
        print(f"  게시글 URL 저장: {post_url}")

        # URL 유효성 검사 - 목록 URL이면 스킵
        if "tab=popular" in post_url or post_url == TARGET_CAFE_MENU_URL:
            print("  [ERROR] 게시글 페이지가 아닌 목록 페이지임 -> 스킵")
            return None

        # 게시글 상세 페이지에서 정보 추출
        extracted_info = extract_post_info(page)
        if extracted_info is None:
            print("  제목 추출 실패 -> 다음 게시글로 넘어갑니다.")
            return None
        post_info.update(extracted_info)
        print(f"  제목: {post_info['title']}")
        print(f"  닉네임: {post_info['nickname']}")
        print(f"  작성시간: {post_info['write_time']}")
        print(f"  조회수: {post_info['view_count']}")

        # 사람이 스크롤한 척
        page.mouse.wheel(0, random.randint(-20, 20))
        random_sleep(0.2, 0.5)
    except Exception as e:
        print(f"게시글 클릭 실패: {e}")
        return post_info

    # 작성자 프로필 클릭
    try:
        profile_link = page.locator(".user_wrap .info").locator("a").first
        human_click(page, profile_link)

        page.wait_for_load_state("domcontentloaded")
        print("작성자 프로필을 클릭했습니다.")
        random_sleep(1, 2)

        # 등급 요소 로딩 대기
        try:
            page.wait_for_selector(".member_grade", timeout=3000)
        except Exception:
            print("  [DEBUG] .member_grade 로딩 대기 실패")

        # 작성자 레벨 추출
        level = extract_level(page)
        post_info["level"] = level
        print(f"  작성자 레벨: {level}")
    except Exception as e:
        print(f"프로필 클릭 실패: {e}")
        return post_info

    # 쪽지 보내기 버튼 클릭 및 ID 추출
    try:
        if "탈퇴" in page.locator(".nickname").inner_text():
            post_info["naver_id"] = "탈퇴한 멤버"
            # 그리고 넘어가기 (ID 추출 건너뛰고 다음단계)
        else:
            menu_btn = page.locator(".HeaderGnbRight").get_by_role("button").nth(2)
            human_click(page, menu_btn)
            random_sleep(0.3, 0.6)

            message_btn = page.locator(".CdsButtonGroup").locator("button").nth(0)
            human_click(page, message_btn)
            print("쪽지 보내기 페이지로 이동합니다.")

            page.wait_for_load_state("networkidle")
            random_sleep(0.5, 1)
            # HTML에서 ID 추출
            html_content = page.content()
            real_id = extract_naver_id(html_content)

            if real_id:
                print(f"추출 성공! ID: {real_id}")
                post_info["naver_id"] = real_id
            else:
                print("ID 추출 실패")

    except Exception:
        print("쪽지 보내기/ID 추출 과정 실패")

    # 게시글 페이지로 복귀 (다음 게시글 이동을 위해)
    try:
        print(f"  게시글로 복귀: {post_url}")
        page.goto(post_url)
        page.wait_for_load_state("domcontentloaded")
        random_sleep(0.5, 1)
        print("  게시글 복귀 완료!")
    except Exception as e:
        print(f"  게시글 복귀 실패: {e}")

    return post_info


def save_batch_to_csv(collected_data, batch_start, batch_end):
    """배치 데이터를 CSV 파일에 저장 (같은 번호는 덮어씌움)"""
    fieldnames = ["번호", "제목", "작성자_닉네임", "작성시간", "조회수", "네이버_ID", "등급"]

    # 기존 데이터 읽기 (번호를 키로 하는 dict)
    existing_data = {}
    if os.path.exists(CSV_FILENAME):
        with open(CSV_FILENAME, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                existing_data[int(row["번호"])] = row

    # 새 데이터로 업데이트 (같은 번호면 덮어씌움)
    for idx, data in enumerate(collected_data):
        row_num = batch_start + idx
        existing_data[row_num] = {
            "번호": row_num,
            "제목": data.get("title", ""),
            "작성자_닉네임": data.get("nickname", ""),
            "작성시간": data.get("write_time", ""),
            "조회수": data.get("view_count", ""),
            "네이버_ID": data.get("naver_id", ""),
            "등급": data.get("level", ""),
        }

    # 번호 순으로 정렬하여 전체 다시 쓰기
    with open(CSV_FILENAME, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row_num in sorted(existing_data.keys()):
            writer.writerow(existing_data[row_num])

    print(f" {CSV_FILENAME} 파일에 {len(collected_data)}개 저장 (덮어씌움)되었습니다.")
    return CSV_FILENAME


def run_automation():
    # auth.json 파일 확인
    if not os.path.exists(AUTH_FILE):
        print(f"❌ '{AUTH_FILE}' 파일이 없습니다. 'make_auth.py'를 먼저 실행해 주세요.")
        return

    total_batches = (END_INDEX - START_INDEX + BATCH_SIZE - 1) // BATCH_SIZE

    current_index = START_INDEX
    batch_num = 0

    while current_index < END_INDEX:
        batch_num += 1
        batch_start = current_index
        batch_end = min(current_index + BATCH_SIZE, END_INDEX)

        print(f"\n{'=' * 50}")
        print(f"📦 배치 {batch_num}/{total_batches} 시작")
        print(f"   처리 범위: {batch_start} ~ {batch_end - 1}")
        print(f"{'=' * 50}")

        batch_start_time = time.time()
        collected_data = []

        with sync_playwright() as p:
            print("저장된 로그인 정보를 불러와 브라우저를 실행합니다...")

            iphone = p.devices["iPhone 14 Pro Max"]

            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-infobars",
                ],
            )
            context = browser.new_context(
                **iphone,
                storage_state=AUTH_FILE,
                locale="ko-KR",
                timezone_id="Asia/Seoul",
            )

            page = context.new_page()
            page.route("**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2}", lambda route: route.abort())
            # playwright-stealth 적용 (탐지 회피)
            Stealth().apply_stealth_sync(page)

            # 네이버 접속
            page.goto(TARGET_URL)
            page.wait_for_load_state("domcontentloaded")
            print(f"✅ {TARGET_URL} 접속 성공! (로그인된 상태)")
            time.sleep(2)

            # 카페 사이트 이동
            page.goto(TARGET_CAFE_MENU_URL)
            page.wait_for_load_state("domcontentloaded")
            random_sleep(2, 3)

            # 게시글 처리
            for i in range(batch_start, batch_end):
                try:
                    is_first = i == batch_start  # 배치의 첫 게시글인지
                    post_info = process_post(page, i, is_first_post=is_first)
                    if post_info:
                        collected_data.append(post_info)
                    else:
                        collected_data.append(
                            {
                                "title": "FAILED",
                                "nickname": "",
                                "write_time": "",
                                "view_count": "",
                                "naver_id": "",
                                "level": "",
                            }
                        )
                except Exception:
                    print(f"[{i + 1}번째] 오류 발생")
                    collected_data.append(
                        {
                            "title": "ERROR",
                            "nickname": "",
                            "write_time": "",
                            "view_count": "",
                            "naver_id": "",
                            "level": "",
                        }
                    )

                    # 오류 발생 시 목록으로 복귀
                    try:
                        page.goto(TARGET_CAFE_MENU_URL)
                        time.sleep(3)
                    except Exception:
                        pass

                print("-" * 30)

                # 각 게시글 처리 후 랜덤 대기 (배치 내 마지막 게시글 제외)
                if i < batch_end - 1:
                    wait_time = random.uniform(1, 3)
                    print(f"⏳ 다음 게시글까지 {wait_time:.1f}초 대기...")
                    time.sleep(wait_time)

            browser.close()

        # 데이터 저장
        save_batch_to_csv(collected_data, batch_start, batch_end)

        batch_elapsed = time.time() - batch_start_time
        batch_minutes = int(batch_elapsed // 60)
        batch_seconds = batch_elapsed % 60
        avg_per_post = batch_elapsed / len(collected_data) if collected_data else 0

        print(f"\n{'=' * 50}")
        print(f"✅ 배치 {batch_num} 완료! (수집: {len(collected_data)}개)")
        print(f"   소요 시간: {batch_minutes}분 {batch_seconds:.1f}초")
        print(f"   게시글당 평균: {avg_per_post:.1f}초")
        print(f"{'=' * 50}")

        # 다음 배치로 이동
        current_index = batch_end

        # 다음 배치가 있으면 대기
        if current_index < END_INDEX:
            wait_minutes = random.uniform(MIN_BATCH_WAIT, MAX_BATCH_WAIT)
            print(f"\n{'=' * 50}")
            print(f"다음 배치까지 {wait_minutes:.1f}분 대기")
            print(f"   다음 배치: {current_index} ~ {min(current_index + BATCH_SIZE, END_INDEX) - 1}")
            print(f"{'=' * 50}")
            time.sleep(wait_minutes * 60)  # 분 -> 초 변환

    print(f"\n{'=' * 50}")
    print("🎉 모든 작업 완료!")
    print(f"   처리 범위: {START_INDEX} ~ {END_INDEX - 1}")
    print(f"   총 배치: {batch_num}개")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    run_automation()
