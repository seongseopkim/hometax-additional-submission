"""
팝업/alert/modal 처리 유틸리티
- accept_alert_if_any   : native alert 감지 + accept
- wait_loading_modal    : 홈택스 로딩 모달 대기
- click_yes_button      : 예/확인 버튼 클릭
- click_button_by_value : value 속성으로 버튼 클릭
- handle_dom_popup      : DOM 팝업 텍스트 감지 + 확인 클릭
"""

import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, UnexpectedAlertPresentException


# ── native alert ─────────────────────────────────────────────────────────────

def accept_alert_if_any(driver, timeout: float = 1.5) -> tuple[bool, str]:
    """
    native alert가 있으면 accept하고 (True, 텍스트) 반환.
    없으면 (False, "") 반환.
    """
    try:
        WebDriverWait(driver, timeout).until(EC.alert_is_present())
        al = driver.switch_to.alert
        text = (al.text or "").strip()
        al.accept()
        print(f"[alert] ✅ accept: {text!r}")
        return True, text
    except TimeoutException:
        return False, ""
    except Exception as e:
        print(f"[alert] ⚠️ 예외: {e}")
        return False, ""


def dismiss_alert_if_any(driver, timeout: float = 1.5) -> tuple[bool, str]:
    """native alert가 있으면 dismiss(취소)하고 (True, 텍스트) 반환."""
    try:
        WebDriverWait(driver, timeout).until(EC.alert_is_present())
        al = driver.switch_to.alert
        text = (al.text or "").strip()
        al.dismiss()
        print(f"[alert] ✅ dismiss: {text!r}")
        return True, text
    except TimeoutException:
        return False, ""
    except Exception as e:
        print(f"[alert] ⚠️ 예외: {e}")
        return False, ""


# ── 로딩 모달 ─────────────────────────────────────────────────────────────────

def wait_loading_modal(driver, timeout: int = 15) -> str:
    """
    홈택스 로딩 모달(.w2_proc_modal[aria-hidden="false"])이 사라질 때까지 대기.
    UnexpectedAlertPresentException 발생 시 alert accept 후 재시도.
    반환: 감지된 alert 텍스트 (없으면 "").
    """
    def _do_wait():
        print("[로딩대기] 시작...")
        try:
            WebDriverWait(driver, timeout).until(
                EC.invisibility_of_element_located(
                    (By.CSS_SELECTOR, '.w2_proc_modal[aria-hidden="false"]')
                )
            )
            print("[로딩대기] 완료 ✅")
        except TimeoutException:
            print(f"[로딩대기] {timeout}초 후에도 모달 존재 → 계속 진행")

    alert_text = ""
    try:
        _do_wait()
    except UnexpectedAlertPresentException as e:
        alert_text = (getattr(e, 'alert_text', None) or str(e)).strip()
        print(f"[로딩대기] 🚨 로딩 중 alert 발생: {alert_text!r} → accept 후 재시도")
        accept_alert_if_any(driver)
        _do_wait()
    return alert_text


# ── DOM 버튼 클릭 ─────────────────────────────────────────────────────────────

def click_yes_button(driver) -> bool:
    """
    화면에 보이는 '예' 버튼 클릭. 없으면 '확인' 버튼 시도.
    반환: 클릭 성공 여부
    """
    for val in ["예", "확인"]:
        els = driver.find_elements(By.CSS_SELECTOR, f'input[type="button"][value="{val}"], button[value="{val}"]')
        for el in els:
            try:
                if el.is_displayed() and el.is_enabled():
                    driver.execute_script("arguments[0].click();", el)
                    print(f"[클릭] ✅ '{val}' 버튼")
                    return True
            except Exception:
                continue
    print("[클릭] ℹ️ 예/확인 버튼 없음")
    return False


def click_button_by_value(driver, value: str) -> bool:
    """value 속성이 일치하는 input[type=button] 또는 button 클릭."""
    els = driver.find_elements(
        By.CSS_SELECTOR,
        f'input[type="button"][value="{value}"], button[value="{value}"]'
    )
    for el in els:
        try:
            if el.is_displayed() and el.is_enabled():
                driver.execute_script("arguments[0].click();", el)
                print(f"[클릭] ✅ value='{value}' 버튼")
                return True
        except Exception:
            continue
    print(f"[클릭] ℹ️ value='{value}' 버튼 없음")
    return False


# ── DOM 팝업 처리 ─────────────────────────────────────────────────────────────

# ── 핵심 구분자 ──────────────────────────────────────────────────────────────
# 홈택스 알림 팝업의 확인 버튼:  aria-hidden="false" 가 명시적으로 설정됨
# 결과 테이블의 확인 버튼(trigger44): aria-hidden 속성 자체가 없음
# → getAttribute('aria-hidden') === 'false' 로 팝업 버튼만 정확히 타겟
#
# 메시지 위치: .pop_cbox > p[id*="_tbx_message"]   (pop_box 아님!)
# ─────────────────────────────────────────────────────────────────────────────

# 팝업 메시지 텍스트 반환
_JS_POPUP_TEXT = (
    # aria-hidden=false 인 확인 버튼을 찾고, 그 팝업 컨테이너에서 메시지 추출
    "var btns=document.querySelectorAll('input[type=\"button\"][value=\"확인\"]');"
    "for(var i=0;i<btns.length;i++){"
    "  var b=btns[i];"
    "  if(b.getAttribute('aria-hidden')!=='false') continue;"
    "  var cs=getComputedStyle(b);"
    "  if(cs.display==='none'||cs.visibility==='hidden') continue;"
    "  var pop=b.closest('.w2popup-window,.w2popup_window');"
    "  if(!pop) continue;"
    # 1차: p[id*="_tbx_message"] (실제 메시지 요소)
    "  var el=pop.querySelector('p[id*=\"_tbx_message\"]');"
    "  if(el&&getComputedStyle(el).display!=='none'){"
    "    var t=el.innerText.trim();if(t) return t;"
    "  }"
    # 2차: .pop_cbox 또는 .pop_box 에서 screen_hide 제거 후 추출
    "  var cx=pop.querySelector('.pop_cbox,.pop_box');"
    "  if(cx){"
    "    var cl=cx.cloneNode(true);"
    "    var hs=cl.querySelectorAll('.screen_hide');for(var j=0;j<hs.length;j++)hs[j].remove();"
    "    var t=cl.innerText.trim();if(t) return t;"
    "  }"
    "  return '알림';"
    "}"
    "return '';"
)

# aria-hidden=false + 팝업 내부 확인 버튼만 클릭
_JS_CLICK_CONFIRM = (
    "var btns=document.querySelectorAll('input[type=\"button\"][value=\"확인\"]');"
    "for(var i=0;i<btns.length;i++){"
    "  var b=btns[i];"
    "  if(b.getAttribute('aria-hidden')!=='false') continue;"
    "  var cs=getComputedStyle(b);"
    "  if(cs.display==='none'||cs.visibility==='hidden') continue;"
    "  if(!b.closest('.w2popup-window,.w2popup_window')) continue;"
    "  b.click(); return true;"
    "}"
    "return false;"
)

# 팝업 확인 버튼(aria-hidden=false)이 아직 visible한지 확인
_JS_POPUP_VISIBLE = (
    "var btns=document.querySelectorAll('input[type=\"button\"][value=\"확인\"]');"
    "for(var i=0;i<btns.length;i++){"
    "  var b=btns[i];"
    "  if(b.getAttribute('aria-hidden')!=='false') continue;"
    "  var cs=getComputedStyle(b);"
    "  if(cs.display==='none'||cs.visibility==='hidden') continue;"
    "  if(b.closest('.w2popup-window,.w2popup_window')) return true;"
    "}"
    "return false;"
)


def handle_dom_popup(
    driver,
    message_selector: str = "",   # 현재 미사용 (JS 방식으로 대체)
    confirm_value: str = "확인",
    timeout: float = 10,
    expect_contains: str = "",
) -> tuple[str, bool]:
    """
    알림 팝업 감지 + 확인 버튼 클릭 + 소거 검증.
    구분 방법: 확인 버튼의 aria-hidden="false" 속성 (테이블 확인 버튼과의 핵심 차이)
    메시지: p[id*="_tbx_message"] 또는 .pop_cbox에서 추출
    소거 검증: 클릭 후 최대 3초간 aria-hidden=false 버튼 사라질 때까지 대기
    반환: (팝업 텍스트, 확인버튼 클릭 여부)
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            text = (driver.execute_script(_JS_POPUP_TEXT) or "").strip()

            if text:
                if expect_contains and expect_contains not in text:
                    return text, False

                print(f"[DOM팝업] 감지: {text!r}")

                # 확인 버튼 클릭 (aria-hidden=false + .closest(popup) 로 정확히 타겟)
                clicked = False
                try:
                    clicked = bool(driver.execute_script(_JS_CLICK_CONFIRM))
                    if clicked:
                        print("[DOM팝업] ✅ 확인 버튼 클릭")
                    else:
                        print("[DOM팝업] ⚠️ 확인 버튼 탐색 실패")
                except Exception as e:
                    print(f"[DOM팝업] ⚠️ 클릭 예외: {e}")

                # 소거 검증: 최대 3초간 0.5초 간격으로 팝업 잔존 여부 확인
                if clicked:
                    for attempt in range(6):
                        time.sleep(0.5)
                        try:
                            still_visible = bool(driver.execute_script(_JS_POPUP_VISIBLE))
                        except Exception:
                            still_visible = False
                        if not still_visible:
                            print(f"[DOM팝업] ✅ 팝업 소거 확인 ({(attempt+1)*0.5:.1f}s)")
                            break
                    else:
                        # 3초 후에도 잔존 → 재클릭 1회
                        print("[DOM팝업] ⚠️ 3초 후에도 팝업 잔존 → 재클릭")
                        try:
                            driver.execute_script(_JS_CLICK_CONFIRM)
                            time.sleep(0.5)
                        except Exception:
                            pass

                return text, clicked

        except Exception as e:
            print(f"[DOM팝업] 예외: {e}")

        time.sleep(0.5)

    return "", False
