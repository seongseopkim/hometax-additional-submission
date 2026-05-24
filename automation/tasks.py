"""
메인 자동화 태스크.

process_row  : 실제 제출 처리 (신고일자 20250508 → 주민번호 → 조회 → 팝업 처리)
query_popup  : 주민번호 조회 후 DOM팝업 텍스트만 캡처 (결과 txt 저장용)
"""

import time
from pathlib import Path


from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

from utils.selenium_safe import safe_click, fill_input, safe_select
from utils.popup_util import (
    accept_alert_if_any, wait_loading_modal,
    handle_dom_popup,
)

SUBMIT_URL = (
    "https://hometax.go.kr/websquare/websquare.html"
    "?w2xPath=/ui/pp/index_pp.xml&tmIdx=41&tm2lIdx=4103000000&tm3lIdx=4103150000"
)

CSS_RRN_FRONT  = "#mf_txppWframe_UTERNAAZ0Z41_wframe_inputResno_1"
CSS_RRN_BACK   = "#mf_txppWframe_UTERNAAZ0Z41_wframe_inputResno_2"
CSS_SEMOK_SEL  = "#mf_txppWframe_UTERNAAZ0Z41_wframe_selectbox2_UTERNAAZ41"
CSS_SEARCH_BTN = "#mf_txppWframe_UTERNAAZ0Z41_wframe_trigger45_UTERNAAZ41"
CSS_DATE_START  = "#mf_txppWframe_UTERNAAZ0Z41_wframe_rtnDtSrt_UTERNAAZ41_input"
CSS_ATTACH_BTN  = 'td[data-col_id="column53"] button'
CSS_FILE_BTN    = '#mf_pf_UTECMGAA06_UTECMGAA06_trigger1'
CSS_FILE_INPUT  = 'input[type="file"]'
CSS_CLOSE_BTN       = '#mf_trigger1'
CSS_SUBMIT_BTN      = '#mf_trigger2_'
CSS_CLOSE_FORM_BTN  = '#mf_txppWframe_UTERNAAZ0Z41_wframe_trigger41_Z12'
CSS_SUBMIT_DONE_BTN = 'td[data-col_id="column53"] button'   # 제출내역보기 (같은 셀, 텍스트 변경)

FIXED_DATE = "20260501"

_JS_ATTACH_CLICK = (
    "var btns = document.querySelectorAll('button');"
    "for(var i=0;i<btns.length;i++){"
    "  if(btns[i].innerText.trim()==='첨부하기'){"
    "    btns[i].click(); return true;"
    "  }"
    "}"
    "return false;"
)


# ── 내부 헬퍼 ────────────────────────────────────────────────────────────────

def _wait_present(driver, css: str, timeout: int = 15):
    return WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, css))
    )


def _js_value(driver, css: str) -> str:
    return driver.execute_script(
        f"var el = document.querySelector({css!r}); return el ? (el.value || '') : ''; "
    )


def _wm(driver, _s, note: str = "") -> str:
    alert_text = wait_loading_modal(driver)
    if alert_text:
        where = f" [{note}]" if note else ""
        _s(f"🚨 로딩 중 alert 발생{where}: {alert_text!r}")
    return alert_text


def _do_search(driver, _s) -> tuple[str, bool]:
    _s("🔍 조회 버튼 클릭 중...")
    safe_click(driver, CSS_SEARCH_BTN, "조회")
    time.sleep(1)

    _s("📋 팝업 대기 중...")
    popup_text, clicked = handle_dom_popup(driver, timeout=2)
    if popup_text:
        _s(f"📋 팝업: {popup_text!r}")
        if clicked:
            time.sleep(1)
        return popup_text, clicked

    # 2초 내 팝업 미감지 → 로딩 모달 대기 후 재확인 → 그래도 없으면 버튼 재클릭
    _s("⚠️ 팝업 미감지 → 로딩 대기 후 재확인")
    _wm(driver, _s, "조회 후 로딩")
    popup_text, clicked = handle_dom_popup(driver, timeout=5)
    if popup_text:
        _s(f"📋 팝업 (재확인): {popup_text!r}")
        if clicked:
            time.sleep(1)
        return popup_text, clicked

    _s("⚠️ 재확인도 미감지 → 조회 버튼 재클릭")
    safe_click(driver, CSS_SEARCH_BTN, "조회 재클릭")
    time.sleep(1)
    _wm(driver, _s, "재클릭 후 로딩")
    popup_text, clicked = handle_dom_popup(driver, timeout=10)
    if popup_text:
        _s(f"📋 팝업 (재클릭 후): {popup_text!r}")
        if clicked:
            time.sleep(1)
    else:
        _s("⚠️ 팝업 미감지 (handle_dom_popup 결과 없음)")
    return popup_text, clicked


def _click_attach_and_switch(driver, _s) -> str:
    """
    첨부하기 버튼 클릭 → 새 창 대기 → 새 창으로 포커스 전환.
    반환: 메인 창 handle (실패 시 "")
    """
    main_handle = driver.current_window_handle
    original_handles = set(driver.window_handles)

    _s("📎 첨부하기 버튼 클릭 중...")

    clicked = False
    try:
        btn = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, CSS_ATTACH_BTN))
        )
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", btn)
        time.sleep(0.3)
        driver.execute_script("arguments[0].click();", btn)
        clicked = True
        _s("✅ 첨부하기 버튼 클릭 완료 (CSS)")
    except TimeoutException:
        _s("⚠️ CSS 탐색 실패 → JS 텍스트 탐색 시도")

    if not clicked:
        try:
            result = driver.execute_script(_JS_ATTACH_CLICK)
            if result:
                clicked = True
                _s("✅ 첨부하기 버튼 클릭 완료 (JS)")
            else:
                _s("❌ 첨부하기 버튼을 찾지 못했습니다")
                return ""
        except Exception as e:
            _s(f"❌ JS 클릭 실패: {e}")
            return ""

    # 새 창 열릴 때까지 대기
    _s("🔎 새 창 대기 중...")
    try:
        WebDriverWait(driver, 25).until(
            lambda d: len(set(d.window_handles) - original_handles) > 0
        )
    except TimeoutException:
        _s("❌ 새 창이 열리지 않았습니다 (25초 초과)")
        return ""

    new_handle = (set(driver.window_handles) - original_handles).pop()
    driver.switch_to.window(new_handle)
    _s(f"✅ 새 창 전환 완료 (handle: {new_handle[:8]}...)")

    # readyState 대기
    _s("⏳ 새 창 페이지 로딩 대기 중...")
    try:
        WebDriverWait(driver, 25).until(
            lambda d: d.execute_script("return document.readyState") == "complete"
        )
        _s("✅ readyState 완료")
    except TimeoutException:
        _s("⚠️ 페이지 로드 타임아웃 — 계속 진행")

    # 홈택스 로딩 모달 대기 (readyState 후에도 모달이 뒤늦게 뜰 수 있음)
    time.sleep(1)

    # WebSquare 비동기 렌더링 대기 — 파일선택 버튼이 실제로 나타날 때까지 대기
    _s("⏳ WebSquare 초기화 대기 중 (파일선택 버튼 출현까지)...")
    try:
        WebDriverWait(driver, 25).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, CSS_FILE_BTN))
        )
        _s("✅ 파일선택 버튼 확인 — 새 창 준비 완료")
    except TimeoutException:
        _s("⚠️ 파일선택 버튼 미감지 (25초) — 계속 시도")

    return main_handle



CSS_GRID_FILE_NAME = '#mf_pf_UTECMGAA06_grdAddDocTery_cell_0_3 > nobr'

def _verify_file_selected(driver, _s, expected_name: str = "", timeout: float = 10) -> bool:
    """파일 선택 후 그리드 첫 번째 행 파일명 셀이 채워졌는지 검증. expected_name 전달 시 일치 여부도 확인."""
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: bool(d.execute_script(
                f"var el = document.querySelector('{CSS_GRID_FILE_NAME}');"
                "return el ? el.innerText.trim() : '';"
            ))
        )
        actual = (driver.execute_script(
            f"var el = document.querySelector('{CSS_GRID_FILE_NAME}');"
            "return el ? el.innerText.trim() : '';"
        ) or "").strip()
        if expected_name and actual != expected_name:
            _s(f"⚠️ 파일명 불일치: 그리드={actual!r}, 기대={expected_name!r}")
            return False
        _s(f"✅ 파일 선택 그리드 반영 확인: {actual!r}")
        return True
    except TimeoutException:
        _s("❌ 파일 선택 미확인 (그리드에 파일명 없음)")
        return False


def _close_popup_and_return(driver, main_handle: str, _s) -> None:
    """닫기 버튼 클릭 → 팝업 닫기 → 메인 창 복귀."""
    try:
        btn = WebDriverWait(driver, 5).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, CSS_CLOSE_BTN))
        )
        driver.execute_script("arguments[0].click();", btn)
        _s("✅ 닫기 버튼 클릭 — 팝업 종료")
        time.sleep(1.0)
    except Exception as e:
        _s(f"⚠️ 닫기 버튼 클릭 실패: {e} → 창 강제 종료")
        try:
            driver.close()
        except Exception:
            pass

    try:
        driver.switch_to.window(main_handle)
        _s("✅ 메인 창 복귀 완료")
    except Exception as e:
        _s(f"⚠️ 메인 창 복귀 실패: {e}")


def _find_and_send_file(driver, abs_path: str) -> bool:
    """
    top-level 및 iframe 탐색하며 input[type="file"] 에 send_keys.
    visibility 조작 없이 시도 → Chrome 보안 우회.
    """
    contexts = [None]  # None = default_content
    try:
        contexts += list(driver.find_elements(By.TAG_NAME, "iframe"))
    except Exception:
        pass

    for ctx in contexts:
        try:
            if ctx is None:
                driver.switch_to.default_content()
            else:
                driver.switch_to.default_content()
                driver.switch_to.frame(ctx)

            inputs = driver.find_elements(By.CSS_SELECTOR, CSS_FILE_INPUT)
            if not inputs:
                continue

            inputs[0].send_keys(abs_path)
            driver.switch_to.default_content()
            return True
        except Exception:
            try:
                driver.switch_to.default_content()
            except Exception:
                pass

    return False


def _upload_pdf(driver, _s, pdf_path: Path) -> bool:
    """
    input[type="file"]에 직접 경로 주입 → 그리드 반영 검증.
    top-level 및 iframe 양쪽에서 탐색, visibility 조작 없이 send_keys.
    """
    _s(f"📁 파일 선택 시작: {pdf_path.name}")
    abs_path = str(pdf_path.resolve())

    if not _find_and_send_file(driver, abs_path):
        _s("❌ 파일 입력 실패: input[type=file] 탐색 또는 send_keys 불가")
        return False

    _s(f"✅ 파일 경로 직접 입력: {pdf_path.name}")
    return _verify_file_selected(driver, _s, expected_name=pdf_path.name, timeout=10)


def _navigate_and_load(driver, _s) -> bool:
    """페이지 이동 → 버튼 클릭 → 입력 영역 대기. 실패 시 False 반환."""
    _s("🌐 신고 부속·증빙서류 제출 페이지 이동 중...")
    driver.get(SUBMIT_URL)
    time.sleep(1)
    time.sleep(2)
    accept_alert_if_any(driver)

    _s("🖱 [신고 부속·증빙서류 제출] 버튼 클릭 중...")
    safe_click(driver, "#mf_txppWframe_btnelc", "[신고 부속·증빙서류 제출]")
    time.sleep(1)
    time.sleep(1)

    _s("🔎 입력 영역 대기 중...")
    try:
        _wait_present(driver, CSS_RRN_FRONT, timeout=15)
        time.sleep(1)
        _s("✅ 페이지 로드 확인")
        return True
    except TimeoutException:
        _s("❌ 주민번호 입력 필드를 찾지 못함")
        return False


def _fill_date_and_rrn(driver, _s, rrn_front: str, rrn_back: str, fixed_date: str = FIXED_DATE) -> bool:
    """신고일자 → 주민번호 앞/뒷자리 입력 → JS 검증. 실패 시 False 반환."""
    _s(f"📅 신고일자 입력: {fixed_date}")
    try:
        fill_input(driver, CSS_DATE_START, fixed_date, "신고일자")
        time.sleep(1)
        time.sleep(0.3)
    except Exception as e:
        _s(f"⚠️ 신고일자 입력 실패 (무시): {e}")

    # 주민번호 앞자리
    _s(f"✏️ 주민번호 앞자리 입력: {rrn_front}")
    fill_input(driver, CSS_RRN_FRONT, rrn_front, "주민번호 앞자리")
    time.sleep(1)
    time.sleep(0.3)

    # 주민번호 뒷자리
    _s("✏️ 주민번호 뒷자리 입력")
    fill_input(driver, CSS_RRN_BACK, rrn_back, "주민번호 뒷자리")
    time.sleep(1)
    time.sleep(0.3)

    # JS 검증
    val_f = _js_value(driver, CSS_RRN_FRONT)
    val_b = _js_value(driver, CSS_RRN_BACK)
    if val_f != rrn_front or val_b != rrn_back:
        _s(f"⚠️ 입력값 불일치 — 앞:{val_f!r}≠{rrn_front!r} / 뒤:{val_b!r}≠{rrn_back!r}")
        return False
    _s(f"✅ 입력 검증 완료: {rrn_front}-{rrn_back[0]}******")
    return True


# ── 실제 제출 처리 ────────────────────────────────────────────────────────────

def process_row(
    driver,
    rrn_front: str,
    rrn_back: str,
    pdf_path: Path,
    name: str = "",
    status_cb=None,
    navigate: bool = True,
    fixed_date: str = FIXED_DATE,
) -> tuple[bool, str]:
    """
    마스터 엑셀 한 행을 처리.
    navigate=True : URL로 페이지 새 진입 (첫 번째 또는 실패 후 복구)
    navigate=False: 기존 폼에서 주민번호만 재입력 (제출 성공 후 연속 처리)
    반환: (성공여부, 실패사유 또는 "")
    """
    def _s(msg):
        print(msg)
        if status_cb:
            try: status_cb(msg)
            except Exception: pass

    label = name if name else f"{rrn_front}-{rrn_back[0]}******"
    _s(f"📂 처리 시작: {label}")

    try:
        if navigate:
            if not _navigate_and_load(driver, _s):
                return False, "페이지_로드_실패"
        else:
            # 기존 폼 재사용 — RRN 입력 필드가 살아있는지 확인, 없으면 재진입
            _s("🔄 기존 폼 재사용 (URL 재진입 생략)")
            try:
                _wait_present(driver, CSS_RRN_FRONT, timeout=5)
            except TimeoutException:
                _s("⚠️ 폼 필드 소실 → URL 재진입")
                if not _navigate_and_load(driver, _s):
                    return False, "페이지_로드_실패"

        if not _fill_date_and_rrn(driver, _s, rrn_front, rrn_back, fixed_date):
            _s("⚠️ 주민번호 입력 검증 실패 → URL 재진입 후 1회 재시도")
            if not _navigate_and_load(driver, _s):
                return False, "페이지_로드_실패"
            if not _fill_date_and_rrn(driver, _s, rrn_front, rrn_back, fixed_date):
                return False, "주민번호_입력_실패"

        # 세목 선택
        _s("📋 세목 선택 중: 종합소득세")
        safe_select(driver, CSS_SEMOK_SEL, label="종합소득세", desc="세목")
        time.sleep(1)
        time.sleep(0.3)

        # 조회 + 팝업 처리
        popup_text, clicked = _do_search(driver, _s)

        # 세목 관련 팝업 → 종합소득세 재선택 후 재조회
        # "레이어팝업시작" 포함 시 서비스 안내 레이어이므로 제외
        if "세목" in popup_text and "레이어팝업시작" not in popup_text:
            _s("⚠️ 세목 관련 팝업 감지 → 종합소득세 재선택 후 재조회")
            safe_select(driver, CSS_SEMOK_SEL, label="종합소득세", desc="세목 재선택")
            time.sleep(1)
            time.sleep(0.3)
            popup_text, clicked = _do_search(driver, _s)

        if "조회된 데이터가 없습니다" in popup_text:
            _s("⚠️ 조회된 데이터 없음 → 다음 항목으로")
            return False, "조회된_데이터_없음"
        elif "조회가 완료되었습니다" in popup_text or "조회 완료" in popup_text:
            _s("✅ 조회 완료")
        elif not popup_text:
            _s("⚠️ 팝업 미감지 — 계속 진행")
        else:
            _s(f"ℹ️ 팝업: {popup_text!r}")

        # 버튼 텍스트 확인 — 이미 제출된 경우 스킵
        btn_text = (driver.execute_script(
            "var b = document.querySelector('td[data-col_id=\"column53\"] button');"
            "return b ? b.innerText.trim() : '';"
        ) or "").strip()
        _s(f"🔎 버튼 텍스트 확인: {btn_text!r}")
        if btn_text == "제출내역보기":
            _s("⚠️ 이미 제출내역 존재 → 스킵")
            return False, "제출내역존재"
        elif btn_text != "첨부하기":
            _s(f"⚠️ 예상치 못한 버튼 텍스트: {btn_text!r} → 계속 시도")

        # 첨부하기 버튼 클릭 → 새 창 전환
        main_handle = _click_attach_and_switch(driver, _s)
        if not main_handle:
            return False, "첨부하기_창_열기_실패"

        # 파일 업로드
        if not _upload_pdf(driver, _s, pdf_path):
            _close_popup_and_return(driver, main_handle, _s)
            return False, "파일_업로드_실패"

        # 첨부 파일명 검증 (그리드 첫 번째 행 apndFleNm 셀 innerText)
        _s("🔍 첨부 파일명 검증 중...")
        try:
            grid_name = (driver.execute_script(
                "var el = document.querySelector("
                "  '#mf_pf_UTECMGAA06_grdAddDocTery_cell_0_3 > nobr');"
                "return el ? el.innerText.trim() : '';"
            ) or "").strip()
            if grid_name == pdf_path.name:
                _s(f"✅ 파일명 일치: {grid_name!r}")
            else:
                _s(f"❌ 파일명 불일치: 그리드={grid_name!r}, 기대={pdf_path.name!r}")
                _close_popup_and_return(driver, main_handle, _s)
                return False, "파일명_불일치"
        except Exception as e:
            _s(f"⚠️ 파일명 검증 예외 (계속 진행): {e}")

        # 부속서류 제출하기 버튼 클릭
        _s("📤 부속서류 제출하기 버튼 클릭 중...")
        try:
            submit_btn = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, CSS_SUBMIT_BTN))
            )
            driver.execute_script("arguments[0].click();", submit_btn)
            _s("✅ 부속서류 제출하기 클릭 완료")
        except Exception as e:
            _s(f"❌ 부속서류 제출하기 버튼 클릭 실패: {e}")
            _close_popup_and_return(driver, main_handle, _s)
            return False, "제출버튼_클릭_실패"

        # 제출 완료 alert 처리 — 서버 처리 시간 고려해 최대 40초 대기
        _s("⏳ 제출 완료 alert 대기 중 (최대 40초)...")
        alerted, alert_text = accept_alert_if_any(driver, timeout=40)
        if alerted:
            _s(f"✅ 제출 완료 alert 확인: {alert_text!r}")
        else:
            _s("⚠️ 40초 내 alert 미감지 — DOM 팝업 확인")
            time.sleep(1)
            popup_text, _ = handle_dom_popup(driver, timeout=5)
            if popup_text:
                _s(f"📋 제출 후 팝업: {popup_text!r}")

        # alert 확인 후 팝업 창이 자동 종료될 때까지 대기 (최대 10초)
        _s("⏳ 팝업 창 자동 종료 대기 중...")
        try:
            WebDriverWait(driver, 10).until(
                lambda d: main_handle in d.window_handles
                and len(d.window_handles) == 1
            )
            _s("✅ 팝업 창 자동 종료 확인")
        except TimeoutException:
            _s("⚠️ 팝업 창 미종료 — 닫기 버튼으로 강제 종료")
            _close_popup_and_return(driver, main_handle, _s)

        # 메인 창으로 포커스 확정
        try:
            driver.switch_to.window(main_handle)
            _s("✅ 메인 창 포커스 완료")
        except Exception as e:
            _s(f"⚠️ 메인 창 전환 실패: {e}")

        # 제출내역보기 버튼 출현으로 최종 성공 확인
        _s("🔎 제출내역보기 버튼 확인 중...")
        try:
            WebDriverWait(driver, 10).until(
                lambda d: any(
                    btn.text.strip() == "제출내역보기"
                    for btn in d.find_elements(By.CSS_SELECTOR, CSS_SUBMIT_DONE_BTN)
                    if btn.is_displayed()
                )
            )
            _s("✅ 제출내역보기 버튼 확인 — 제출 완료")
        except TimeoutException:
            _s("⚠️ 제출내역보기 버튼 미감지 — 결과 불확실")

        return True, ""

    except Exception as e:
        _s(f"❌ {label} 처리 중 예외: {e}")
        return False, f"예외_{type(e).__name__}"


def do_close_and_logout(driver, status_cb=None) -> None:
    """
    전체 처리 완료 후 폼 닫기 버튼 클릭 → 로그아웃.
    """
    def _s(msg):
        print(msg)
        if status_cb:
            try: status_cb(msg)
            except Exception: pass

    # 닫기 버튼 클릭
    _s("🔒 닫기 버튼 클릭 중...")
    try:
        btn = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, CSS_CLOSE_FORM_BTN))
        )
        driver.execute_script("arguments[0].click();", btn)
        _s("✅ 닫기 버튼 클릭 완료")
        time.sleep(1.5)
        accept_alert_if_any(driver, timeout=3)
    except Exception as e:
        _s(f"⚠️ 닫기 버튼 실패: {e}")

    # 로그아웃: #mf_wfHeader_group1503 클릭 → "로그아웃" 텍스트 요소 JS 탐색
    _s("🚪 로그아웃 중...")
    try:
        # 1차: 헤더 그룹 클릭 (드롭다운 열기)
        driver.execute_script(
            "var el = document.querySelector('#mf_wfHeader_group1503');"
            "if(el) el.click();"
        )
        time.sleep(0.8)
        # 2차: "로그아웃" 텍스트 있는 요소 클릭
        found = driver.execute_script(
            "var all = document.querySelectorAll('a, button, input[type=button], li, span');"
            "for(var i=0;i<all.length;i++){"
            "  if((all[i].innerText||'').trim()==='로그아웃'){"
            "    all[i].click(); return true;"
            "  }"
            "}"
            "return false;"
        )
        if found:
            _s("✅ 로그아웃 클릭 완료")
            time.sleep(1)
            accept_alert_if_any(driver, timeout=3)
            # "로그아웃 하시겠습니까?" DOM 팝업 처리
            popup_text, clicked = handle_dom_popup(driver, timeout=5)
            if clicked:
                _s(f"✅ 로그아웃 확인 팝업 클릭: {popup_text!r}")
            elif popup_text:
                _s(f"⚠️ 로그아웃 팝업 감지되었으나 클릭 실패: {popup_text!r}")
        else:
            _s("⚠️ 로그아웃 버튼을 찾지 못했습니다")
    except Exception as e:
        _s(f"⚠️ 로그아웃 실패: {e}")


# ── 팝업 텍스트 캡처 (조회 결과 수집용) ──────────────────────────────────────

def query_popup(
    driver,
    rrn_front: str,
    rrn_back: str,
    name: str = "",
    status_cb=None,
) -> tuple[bool, str]:
    """
    신고일자 20250508 → 주민번호 입력 → 조회 → DOM팝업 텍스트 캡처.
    반환: (성공여부, 팝업텍스트 또는 오류사유)
    """
    def _s(msg):
        print(msg)
        if status_cb:
            try: status_cb(msg)
            except Exception: pass

    label = name if name else f"{rrn_front}-***"
    _s(f"🔍 팝업 조회: {label}")

    try:
        if not _navigate_and_load(driver, _s):
            return False, "페이지_로드_실패"

        if not _fill_date_and_rrn(driver, _s, rrn_front, rrn_back):
            return False, "주민번호_입력_실패"

        # 세목 선택
        safe_select(driver, CSS_SEMOK_SEL, label="종합소득세", desc="세목")
        time.sleep(1)
        time.sleep(0.3)

        # 조회 → 팝업 텍스트 그대로 반환
        popup_text, _ = _do_search(driver, _s)
        _s(f"📋 결과: {label} → {popup_text!r}")
        return True, popup_text

    except Exception as e:
        _s(f"❌ {label} 예외: {e}")
        return False, f"예외_{type(e).__name__}"
