"""
클릭 / 입력 / 선택 유틸리티 (검증 강화 버전)

기존 프로그램 대비 개선 사항:
- fill_input  : 입력 후 값 readback 검증 → 불일치 시 재입력
- safe_click  : JS fallback + 클릭 전 scrollIntoView
- safe_select : 선택 후 실제 선택된 option 검증
- upload_file : PDF 등 파일 업로드 (input[type=file] send_keys)
"""

import time
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    UnexpectedAlertPresentException,
    ElementClickInterceptedException,
)


# ── 클릭 ─────────────────────────────────────────────────────────────────────

def safe_click(driver, css: str, desc: str = "") -> bool:
    """
    CSS 셀렉터로 요소를 찾아 클릭.
    1) 일반 click()
    2) 실패 시 JS click()
    클릭 전 scrollIntoView 수행.
    """
    label = desc or css
    try:
        el = WebDriverWait(driver, 8).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, css))
        )
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        time.sleep(0.2)
        try:
            el.click()
        except Exception:
            driver.execute_script("arguments[0].click();", el)
        print(f"[클릭] ✅ {label}")
        return True
    except TimeoutException:
        print(f"[클릭] ⚠️ 요소 없음(timeout): {label}")
        return False
    except Exception as e:
        print(f"[클릭] ❌ 실패: {label} — {e.__class__.__name__}")
        # 마지막 수단: find_elements + JS
        try:
            els = driver.find_elements(By.CSS_SELECTOR, css)
            if els:
                driver.execute_script("arguments[0].click();", els[0])
                print(f"[클릭] ✅ JS 강제클릭: {label}")
                return True
        except Exception:
            pass
        return False


def safe_click_and_verify(
    driver, css: str, desc: str = "",
    verify_css: str = "", verify_text: str = "",
    verify_timeout: float = 3,
) -> bool:
    """
    클릭 후 verify_css 요소가 나타나거나, 특정 텍스트가 페이지에 등장하는지 검증.
    verify_css / verify_text 중 하나만 지정해도 됨. 둘 다 없으면 safe_click과 동일.
    """
    ok = safe_click(driver, css, desc)
    if not ok:
        return False
    if not verify_css and not verify_text:
        return True

    try:
        if verify_css:
            WebDriverWait(driver, verify_timeout).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, verify_css))
            )
            print(f"[클릭검증] ✅ {desc} → {verify_css} 나타남")
        elif verify_text:
            WebDriverWait(driver, verify_timeout).until(
                lambda d: verify_text in d.page_source
            )
            print(f"[클릭검증] ✅ {desc} → '{verify_text}' 페이지 출현")
        return True
    except TimeoutException:
        print(f"[클릭검증] ⚠️ {desc} → 검증 실패 (timeout)")
        return False


# ── 입력 ─────────────────────────────────────────────────────────────────────

def fill_input(
    driver, css: str, value, desc: str = "",
    verify: bool = True, max_retry: int = 2,
) -> bool:
    """
    input 필드에 값 입력.
    1) 기존값 clear → send_keys
    2) JS value 설정 + change 이벤트 dispatch
    verify=True : 입력 후 element.value 읽어서 일치 확인 → 불일치 시 max_retry회 재시도.
    """
    label = desc or css
    str_val = str(value) if value is not None else ""

    def _dismiss_alert() -> str:
        """alert가 있으면 accept하고 텍스트 반환. 없으면 빈 문자열."""
        try:
            al = driver.switch_to.alert
            text = (al.text or "").strip()
            al.accept()
            print(f"[입력] ⚠️ alert accept: {text!r}")
            return text
        except Exception:
            return ""

    def _do_fill(el):
        driver.execute_script("arguments[0].value = '';", el)
        try:
            el.click()
        except (ElementClickInterceptedException, Exception):
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
            driver.execute_script("arguments[0].click();", el)
        el.send_keys(Keys.CONTROL + 'a')
        el.send_keys(str_val)
        driver.execute_script(
            "arguments[0].dispatchEvent(new Event('input', {bubbles:true}));"
            "arguments[0].dispatchEvent(new Event('change', {bubbles:true}));",
            el
        )

    def _read_back(el) -> str:
        raw = driver.execute_script("return arguments[0].value;", el) or ""
        return raw.replace(",", "").strip()

    for attempt in range(1, max_retry + 2):
        try:
            el = WebDriverWait(driver, 8).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, css))
            )
            _do_fill(el)
            time.sleep(0.3)

            if verify:
                actual = _read_back(el)
                expected = str_val.replace(",", "").strip()
                if actual == expected:
                    print(f"[입력] ✅ {label} = {str_val!r} (검증 OK)")
                    return True
                else:
                    print(f"[입력] ⚠️ {label} 검증 불일치: 기대={expected!r}, 실제={actual!r} (시도 {attempt})")
                    if attempt <= max_retry:
                        time.sleep(0.5)
                        continue
                    print(f"[입력] ❌ {label} {max_retry}회 재시도 후 포기")
                    return False
            else:
                print(f"[입력] ✅ {label} = {str_val!r}")
                return True

        except UnexpectedAlertPresentException:
            # alert 자동 accept 후 재시도
            _dismiss_alert()
            time.sleep(0.5)
            if attempt <= max_retry:
                continue
            print(f"[입력] ❌ {label} alert 반복 발생으로 포기")
            return False
        except TimeoutException:
            print(f"[입력] ⚠️ 요소 없음: {label}")
            return False
        except Exception as e:
            print(f"[입력] ❌ 예외: {label} — {e.__class__.__name__}: {e}")
            return False

    return False


# ── 선택 ─────────────────────────────────────────────────────────────────────

def safe_select(
    driver, css: str,
    value: str = None, label: str = None, index: int = None,
    desc: str = "",
    verify: bool = True,
) -> bool:
    """
    <select> 요소에서 value / label(텍스트) / index 중 하나로 옵션 선택.
    verify=True : 선택 후 실제 selected option 텍스트 또는 value 검증.
    """
    desc_label = desc or css
    try:
        el = WebDriverWait(driver, 8).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, css))
        )
        sel = Select(el)

        if index is not None:
            sel.select_by_index(index)
            selected_text = sel.first_selected_option.text.strip()
            print(f"[선택] ✅ {desc_label} index={index} → '{selected_text}'")
            return True

        if value is not None:
            # value 직접 시도 → 실패 시 텍스트 끝 매칭
            try:
                sel.select_by_value(str(value))
            except Exception:
                opts = sel.options
                matched = [o for o in opts if o.get_attribute("value") == str(value)
                           or o.text.strip().endswith(str(value))]
                if matched:
                    sel.select_by_visible_text(matched[0].text.strip())
                else:
                    print(f"[선택] ❌ {desc_label} value={value!r} 매칭 옵션 없음")
                    return False

        elif label is not None:
            # 텍스트 포함 매칭
            opts = sel.options
            matched = [o for o in opts if label in o.text]
            if matched:
                sel.select_by_visible_text(matched[0].text.strip())
            else:
                print(f"[선택] ❌ {desc_label} label={label!r} 매칭 옵션 없음")
                return False

        selected = sel.first_selected_option
        selected_text = selected.text.strip()
        selected_val  = selected.get_attribute("value") or ""

        if verify:
            target = str(value or label or "")
            if target and (target not in selected_text and target not in selected_val):
                print(f"[선택] ⚠️ {desc_label} 검증 불일치: 기대={target!r}, 실제={selected_text!r}")
            else:
                print(f"[선택] ✅ {desc_label} → '{selected_text}'")
        else:
            print(f"[선택] ✅ {desc_label} → '{selected_text}'")

        return True

    except TimeoutException:
        print(f"[선택] ⚠️ 요소 없음: {desc_label}")
        return False
    except Exception as e:
        print(f"[선택] ❌ 예외: {desc_label} — {e.__class__.__name__}: {e}")
        return False


# ── 파일 업로드 ───────────────────────────────────────────────────────────────

def upload_file(driver, css: str, file_path: str, desc: str = "") -> bool:
    """
    input[type=file] 요소에 파일 경로 전달 (홈택스 파일 업로드).
    숨겨진 input도 처리 가능하도록 visibility 해제 후 send_keys.
    """
    label = desc or css
    try:
        el = WebDriverWait(driver, 8).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, css))
        )
        # 숨겨진 input도 send_keys 가능하게
        driver.execute_script(
            "arguments[0].style.display='block';"
            "arguments[0].style.visibility='visible';",
            el
        )
        el.send_keys(file_path)
        print(f"[업로드] ✅ {label} → {file_path}")
        return True
    except TimeoutException:
        print(f"[업로드] ⚠️ 요소 없음: {label}")
        return False
    except Exception as e:
        print(f"[업로드] ❌ 실패: {label} — {e}")
        return False
