# login.py (Selenium 버전)
# ⚠️ 코드 내 공개된 계정/비번은 실제 배포 전 반드시 환경변수/설정파일로 분리하세요.

import time
import random
import platform
from typing import Callable, Optional, Tuple

from automation.browser import get_stealth_browser  # Selenium용 browser.py (driver 반환)

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver import ActionChains
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    NoAlertPresentException,
    ElementClickInterceptedException,
    ElementNotInteractableException,
    StaleElementReferenceException,
    JavascriptException,
)

StatusCB = Callable[[str], None]
NOTICE_URL_PAT = "websquare/popup.html"


# -----------------------------
# 기본 유틸
# -----------------------------
def _get_select_all_key():
    return Keys.COMMAND if platform.system() == "Darwin" else Keys.CONTROL


def random_delay(a=0.6, b=1.6):
    """VPN/해외 환경 고려: 기본 딜레이를 조금 넉넉하게"""
    time.sleep(random.uniform(a, b))


def _wait_ready(driver: WebDriver, timeout=20):
    """문서 기본 로딩 완료 대기"""
    WebDriverWait(driver, timeout).until(
        lambda d: d.execute_script("return document.readyState") in ("interactive", "complete")
    )


def _sleep_retry(base=0.6, jitter=0.5):
    time.sleep(base + random.uniform(0, jitter))


def _safe_status(status: StatusCB, msg: str):
    try:
        status(msg)
    except Exception:
        pass


# -----------------------------
# 요소 대기/탐색/조작 유틸
# -----------------------------
def _find_present(driver: WebDriver, css: str, timeout=15) -> WebElement:
    return WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, css))
    )


def _find_visible(driver: WebDriver, css: str, timeout=15) -> WebElement:
    return WebDriverWait(driver, timeout).until(
        EC.visibility_of_element_located((By.CSS_SELECTOR, css))
    )


def _scroll_into_view(driver: WebDriver, el: WebElement):
    try:
        driver.execute_script(
            "arguments[0].scrollIntoView({block:'center', inline:'center'});", el
        )
        time.sleep(0.2)
    except Exception:
        pass


def _js_click(driver: WebDriver, el: WebElement):
    driver.execute_script("arguments[0].click();", el)


def _safe_click(
    driver: WebDriver,
    css: str,
    timeout=15,
    retries=4,
    status: Optional[StatusCB] = None,
) -> WebElement:
    """
    클릭 가능한 상태를 기다리되,
    홈택스/VPN 환경에서 click 실패 시 JS click까지 시도
    """
    last_err = None

    for attempt in range(1, retries + 1):
        try:
            el = WebDriverWait(driver, timeout).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, css))
            )
            _scroll_into_view(driver, el)

            try:
                WebDriverWait(driver, 3).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, css))
                )
            except Exception:
                pass

            try:
                el.click()
                return el
            except (ElementClickInterceptedException, ElementNotInteractableException, StaleElementReferenceException) as e:
                last_err = e
                _safe_status(status, f"⚠️ 일반 클릭 실패({attempt}/{retries}) → JS 클릭 시도: {css}")
                el = driver.find_element(By.CSS_SELECTOR, css)
                _scroll_into_view(driver, el)
                _js_click(driver, el)
                return el

        except Exception as e:
            last_err = e
            _safe_status(status, f"⚠️ 클릭 재시도({attempt}/{retries}): {css} / {e}")
            _sleep_retry(0.8, 0.6)

    raise last_err


def _safe_fill(
    driver: WebDriver,
    css: str,
    value: str,
    clear=True,
    timeout=15,
    retries=4,
    status: Optional[StatusCB] = None,
) -> WebElement:
    """
    일반 send_keys 우선, 실패하면 JS value 주입 fallback
    """
    last_err = None

    for attempt in range(1, retries + 1):
        try:
            el = WebDriverWait(driver, timeout).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, css))
            )
            _scroll_into_view(driver, el)

            try:
                WebDriverWait(driver, 3).until(
                    EC.visibility_of_element_located((By.CSS_SELECTOR, css))
                )
            except Exception:
                pass

            try:
                if clear:
                    try:
                        el.clear()
                    except Exception:
                        el.send_keys(_get_select_all_key(), "a")
                        el.send_keys(Keys.BACKSPACE)

                el.click()
                time.sleep(0.1)
                el.send_keys(value)
                return el

            except (ElementNotInteractableException, StaleElementReferenceException) as e:
                last_err = e
                _safe_status(status, f"⚠️ send_keys 실패({attempt}/{retries}) → JS 입력 시도: {css}")

                el = driver.find_element(By.CSS_SELECTOR, css)
                driver.execute_script(
                    """
                    const el = arguments[0];
                    const val = arguments[1];

                    if (!el) return;

                    el.removeAttribute('readonly');
                    el.removeAttribute('disabled');
                    el.focus();
                    el.value = val;
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    """,
                    el,
                    value,
                )
                return el

        except Exception as e:
            last_err = e
            _safe_status(status, f"⚠️ 입력 재시도({attempt}/{retries}): {css} / {e}")
            _sleep_retry(0.8, 0.6)

    raise last_err


def _wait_css(driver: WebDriver, css: str, timeout=15):
    return WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, css))
    )


def _handle_intermediate_page(driver: WebDriver, status: StatusCB) -> bool:
    """
    로그인 후 '홈택스 신고안내 임시페이지'가 뜰 수 있음.
    3번째 카드(홈택스 바로가기, #TH4BOX a)가 있으면 클릭하고 True 반환.
    없으면 False 반환(정상 홈택스 메인으로 바로 진입한 경우).
    """
    try:
        WebDriverWait(driver, 4).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "#TH4BOX a"))
        )
        _safe_status(status, "🔎 홈택스 신고안내 임시페이지 감지 → 홈택스 바로가기 클릭")
        el = driver.find_element(By.CSS_SELECTOR, "#TH4BOX a")
        _js_click(driver, el)
        random_delay(2.0, 3.0)
        _safe_status(status, "✅ 홈택스 바로가기 클릭 완료")
        return True
    except TimeoutException:
        return False


def _verify_login_success(driver: WebDriver, status: StatusCB, timeout: int = 20) -> bool:
    """
    로그아웃 버튼(#mf_wfHeader_group1503) 존재 여부로 로그인 성공을 판단.
    True 반환 = 로그인 성공 / False = 실패
    """
    try:
        _wait_css(driver, "#mf_wfHeader_group1503", timeout=timeout)
        _safe_status(status, "✅ 로그인 성공 확인 (로그아웃 버튼 감지)")
        return True
    except TimeoutException:
        _safe_status(status, "❌ 로그인 실패: 로그아웃 버튼(#mf_wfHeader_group1503) 미감지")
        return False


def _accept_alert_if_present(driver: WebDriver, status: StatusCB, timeout=2.0):
    try:
        WebDriverWait(driver, timeout).until(EC.alert_is_present())
        alert = driver.switch_to.alert
        msg = alert.text
        try:
            alert.accept()
        finally:
            status(f"⚠️ dialog: {msg}")
    except (TimeoutException, NoAlertPresentException):
        pass


def _close_unwanted_windows(driver: WebDriver, status: StatusCB):
    """about:blank, 공지팝업 등 불필요 창 닫고 메인 복귀"""
    try:
        main = driver.current_window_handle
    except Exception:
        main = None

    handles = driver.window_handles[:]
    for h in handles:
        if h == main:  # 메인 창은 절대 닫지 않음
            continue
        try:
            driver.switch_to.window(h)
            url = driver.current_url or ""
        except Exception:
            url = ""

        if (not url) or url.startswith("about:blank") or (NOTICE_URL_PAT in url):
            try:
                status("🧹 팝업 창 닫기")
                driver.close()
            except Exception:
                pass

    # 복귀
    try:
        if main and main in driver.window_handles:
            driver.switch_to.window(main)
        elif driver.window_handles:
            driver.switch_to.window(driver.window_handles[0])
    except Exception:
        pass


def _switch_to_frame_containing(driver: WebDriver, css: str, timeout_each=3) -> bool:
    """
    기본 문서 + 1차 iframe들 중에서 특정 css가 존재하는 프레임으로 이동
    성공하면 그 프레임에 머무름
    """
    driver.switch_to.default_content()

    # 1) 먼저 기본 문서 확인
    try:
        WebDriverWait(driver, timeout_each).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, css))
        )
        return True
    except Exception:
        pass

    # 2) 1차 iframe 순회
    frames = driver.find_elements(By.TAG_NAME, "iframe")
    for frame in frames:
        try:
            driver.switch_to.default_content()
            driver.switch_to.frame(frame)
            WebDriverWait(driver, timeout_each).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, css))
            )
            return True
        except Exception:
            continue

    driver.switch_to.default_content()
    return False


def _click_dynamic_confirm_button(driver, status: StatusCB, timeout=6):
    """
    mf_txppWframe_confirmXXXX_wframe 안에 있는 '확인' 버튼을
    동적으로 찾아 클릭
    """
    wait = WebDriverWait(driver, timeout)

    try:
        driver.switch_to.default_content()
        wait.until(
            EC.frame_to_be_available_and_switch_to_it(
                (By.CSS_SELECTOR, 'iframe[id^="mf_txppWframe_confirm"][id$="_wframe"]')
            )
        )
        status("🔎 confirm 팝업 iframe 진입")
    except TimeoutException:
        status("ℹ️ confirm iframe 없음 → 페이지 레벨 버튼 시도")
        driver.switch_to.default_content()
        try:
            _safe_click(
                driver,
                'input[id$="_btn_confirm"][type="button"]',
                timeout=4,
                retries=3,
                status=status,
            )
            status("✅ 페이지 레벨 '확인' 버튼 클릭 성공")
            return
        except Exception as e:
            status(f"⚠️ 페이지 레벨 '확인' 버튼 없음/클릭 실패: {e}")
            return

    try:
        _safe_click(
            driver,
            'input[id$="_btn_confirm"][type="button"]',
            timeout=4,
            retries=3,
            status=status,
        )
        status("✅ confirm 팝업 '확인' 버튼 클릭")
    except Exception as e:
        status(f"⚠️ confirm 팝업 버튼 클릭 실패: {e}")
    finally:
        try:
            driver.switch_to.default_content()
        except Exception:
            pass


# -----------------------------
# 인증서 iframe 처리
# -----------------------------
def _try_in_cert_iframe(driver: WebDriver, cert_name: str, cert_pw: str, status: StatusCB) -> bool:
    """
    인증서 선택/비번 입력 UI를 iframe들에서 탐색
    """
    driver.switch_to.default_content()
    frames = driver.find_elements(By.TAG_NAME, "iframe")

    for idx, f in enumerate(frames):
        try:
            driver.switch_to.default_content()
            driver.switch_to.frame(f)

            spans = driver.find_elements(By.CSS_SELECTOR, f"span[title*='{cert_name}']")
            if not spans:
                continue

            status(f"🔎 인증서 iframe 탐지: index={idx}")

            # 인증서 선택
            try:
                _scroll_into_view(driver, spans[0])
                try:
                    spans[0].click()
                except Exception:
                    _js_click(driver, spans[0])
            except Exception as e:
                status(f"⚠️ 인증서 항목 클릭 실패: {e}")
                continue

            random_delay(0.5, 1.0)

            # 비번 입력 필드 탐색
            pw_field = None
            try:
                pw_field = driver.find_element(By.CSS_SELECTOR, "#input_cert_pw")
            except NoSuchElementException:
                cands = driver.find_elements(By.CSS_SELECTOR, "input[type='password']")
                pw_field = cands[0] if cands else None

            if pw_field:
                try:
                    _scroll_into_view(driver, pw_field)
                    try:
                        pw_field.clear()
                    except Exception:
                        pass
                    try:
                        pw_field.click()
                        pw_field.send_keys(cert_pw)
                    except Exception:
                        driver.execute_script(
                            """
                            const el = arguments[0];
                            const val = arguments[1];
                            if (!el) return;
                            el.focus();
                            el.value = val;
                            el.dispatchEvent(new Event('input', { bubbles: true }));
                            el.dispatchEvent(new Event('change', { bubbles: true }));
                            """,
                            pw_field,
                            cert_pw,
                        )
                except Exception as e:
                    status(f"⚠️ 인증서 비번 입력 실패: {e}")
                    continue

            random_delay(0.3, 0.8)

            # 확인 버튼 탐색
            btn = None
            try:
                btn = driver.find_element(By.CSS_SELECTOR, "#btn_confirm_iframe")
            except NoSuchElementException:
                btns = driver.find_elements(By.CSS_SELECTOR, "button, input[type='button'], a")
                btn = btns[0] if btns else None

            if btn:
                try:
                    _scroll_into_view(driver, btn)
                    try:
                        btn.click()
                    except Exception:
                        _js_click(driver, btn)
                    status("✅ 인증서 로그인 시도")
                    driver.switch_to.default_content()
                    return True
                except Exception as e:
                    status(f"⚠️ 인증서 확인 버튼 클릭 실패: {e}")

        except Exception:
            pass
        finally:
            try:
                driver.switch_to.default_content()
            except Exception:
                pass

    return False


# -----------------------------
# 메인 로그인 함수
# -----------------------------
def login_and_save_session(
    user_id: str,
    user_pw: str,
    cert_name: str,
    cert_pw: str,
    status_callback: StatusCB = print,
):
    """
    반환: (browser, context, page) Playwright 호환 형태
    - browser == page == Selenium WebDriver
    - context == None
    """
    driver: Optional[WebDriver] = None

    try:
        driver, context, page = get_stealth_browser()
        driver.set_page_load_timeout(90)
        try:
            driver.implicitly_wait(1)
        except Exception:
            pass
    except Exception as e:
        status_callback(f"❌ get_stealth_browser 오류: {e}")
        raise

    try:
        status_callback("🌐 홈택스 접속 중...")
        driver.get(
            "https://hometax.go.kr/websquare/websquare.html?w2xPath=/ui/pp/index_pp.xml&menuCd=index3"
        )

        _wait_ready(driver, timeout=30)
        random_delay(2.0, 3.5)

        # 혹시 초기 팝업/alert
        _close_unwanted_windows(driver, status_callback)
        _accept_alert_if_present(driver, status_callback, timeout=2.0)

        # 헤더 로그인 버튼
        status_callback("🔐 로그인 버튼 진입 시도")
        _safe_click(
            driver,
            "#mf_wfHeader_group1503",
            timeout=25,
            retries=5,
            status=status_callback,
        )
        random_delay(1.0, 2.0)

        # 공동·금융인증서 탭 선택
        status_callback("🔎 공동·금융인증서 탭 탐색")
        found_cert_tab = _switch_to_frame_containing(driver, "#mf_txppWframe_anchor13", timeout_each=5)
        if not found_cert_tab:
            raise TimeoutException("공동·금융인증서 탭(#mf_txppWframe_anchor13)을 찾지 못했습니다.")

        _safe_click(
            driver,
            "#mf_txppWframe_anchor13",
            timeout=15,
            retries=5,
            status=status_callback,
        )
        random_delay(1.2, 2.0)

        # 공동·금융인증서 버튼 클릭
        status_callback("🖱 공동·금융인증서 버튼 클릭")
        found_cert_btn = _switch_to_frame_containing(driver, "#mf_txppWframe_anchor22", timeout_each=5)
        if not found_cert_btn:
            raise TimeoutException("공동·금융인증서 버튼(#mf_txppWframe_anchor22)을 찾지 못했습니다.")

        _safe_click(
            driver,
            "#mf_txppWframe_anchor22",
            timeout=15,
            retries=5,
            status=status_callback,
        )
        random_delay(2.0, 3.0)

        driver.switch_to.default_content()

        # 팝업/빈창/알럿 정리
        _close_unwanted_windows(driver, status_callback)
        _accept_alert_if_present(driver, status_callback, timeout=2.0)

        # 인증서 처리 시도 (느린 환경이므로 넉넉하게)
        success_cert = False
        for attempt in range(1, 7):
            status_callback(f"🔎 인증서 iframe 탐색 시도 {attempt}/6")
            if _try_in_cert_iframe(driver, cert_name, cert_pw, status_callback):
                success_cert = True
                break
            random_delay(1.0, 2.0)

        if not success_cert:
            status_callback("⚠️ 인증서 선택 UI를 찾지 못했습니다(환경/팝업 구조 상이).")
        else:
            status_callback("✅ 인증서 로그인 성공(추정)")

        random_delay(1.5, 2.5)

        # 불필요 팝업/알럿 정리
        _close_unwanted_windows(driver, status_callback)
        _accept_alert_if_present(driver, status_callback, timeout=2.5)

        # confirm 팝업 처리
        try:
            _click_dynamic_confirm_button(driver, status_callback, timeout=6)
        except Exception as e:
            status_callback(f"⚠️ confirm 팝업 처리 중 예외(무시 가능): {e}")

        random_delay(1.0, 2.0)

        # 세무대리인 로그인(있을 때만)
        try:
            status_callback("🔎 세무대리인 로그인 화면 탐색")
            if _switch_to_frame_containing(driver, "#mf_txppWframe_input1", timeout_each=4):
                _safe_fill(
                    driver,
                    "#mf_txppWframe_input1",
                    "P95818",
                    timeout=10,
                    retries=4,
                    status=status_callback,
                )
                _safe_fill(
                    driver,
                    "#mf_txppWframe_input2",
                    "rladudfks2469@@",
                    timeout=10,
                    retries=4,
                    status=status_callback,
                )
                _safe_click(
                    driver,
                    "#mf_txppWframe_trigger41",
                    timeout=10,
                    retries=4,
                    status=status_callback,
                )
                status_callback("🎉 세무대리인 로그인 성공")
            else:
                status_callback("ℹ️ 세무대리인 로그인 화면 미노출(환경에 따라 생략됨)")
        except TimeoutException:
            status_callback("ℹ️ 세무대리인 로그인 화면 미노출(환경에 따라 생략됨)")
        finally:
            try:
                driver.switch_to.default_content()
            except Exception:
                pass

        _close_unwanted_windows(driver, status_callback)

        # 로그인 후 임시 안내 페이지가 뜰 수 있음 → 홈택스 바로가기 클릭
        _handle_intermediate_page(driver, status_callback)

        _close_unwanted_windows(driver, status_callback)

        # 로그인 성공 확인: 로그아웃 버튼이 있어야 진짜 로그인된 것
        if not _verify_login_success(driver, status_callback, timeout=20):
            raise TimeoutException("로그인 성공 확인 실패: 로그아웃 버튼(#mf_wfHeader_group1503) 미감지")

        browser = driver
        context = None
        page = driver
        return browser, context, page

    except Exception as e:
        status_callback(f"❌ 로그인 오류: {e}")
        try:
            if driver:
                driver.quit()
        except Exception:
            pass
        raise