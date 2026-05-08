# browser.py
import os
import platform
from pathlib import Path
from typing import Optional

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager


def _remove_chrome_singleton_lock(user_data_dir: str):
    """
    이전 Chrome 비정상 종료 시 남는 SingletonLock 파일 삭제.
    이 파일이 남아있으면 Chrome이 '기존 세션에서 여는 중' 메시지 후 종료함.
    """
    for lock_name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        lock_path = Path(user_data_dir) / lock_name
        try:
            if lock_path.exists():
                lock_path.unlink()
                print(f"[브라우저] SingletonLock 삭제됨: {lock_path.name}")
        except Exception as e:
            print(f"[브라우저] SingletonLock 삭제 실패: {lock_path.name} — {e}")


# Windows / macOS / Linux 공용 Selenium 프로필 디렉토리 반환
# hometax_selenium_profile 은 기존 프로젝트가 이미 Chrome 정상 구조를 만들어 둔 디렉토리.
# 같은 user-data-dir을 공유하되 profile-directory만 다르게(JugaProfile) 사용하면
# Chrome이 비어있는 신규 디렉토리를 System Profile로 오인하는 문제가 발생하지 않는다.
def _get_default_user_data_dir() -> str:
    system = platform.system()

    if system == "Windows":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("USERPROFILE") or str(Path.home())
    elif system == "Darwin":  # macOS
        base = str(Path.home() / "Library" / "Application Support")
    else:
        base = str(Path.home() / ".config")

    user_data_path = Path(base) / "hometax_selenium_profile"
    user_data_path.mkdir(parents=True, exist_ok=True)
    return str(user_data_path)


# 프로젝트 내부 공용 다운로드 폴더 (exe/스크립트 위치 기준)
def _get_default_download_dir() -> str:
    import sys
    if getattr(sys, 'frozen', False):
        base = Path(sys.executable).parent
    else:
        base = Path(__file__).resolve().parent.parent
    download_path = base / "downloads"
    download_path.mkdir(parents=True, exist_ok=True)
    return str(download_path.resolve())


# navigator.platform 값을 OS에 맞게 분기
def _get_js_platform_value() -> str:
    system = platform.system()

    if system == "Windows":
        return "Win32"
    elif system == "Darwin":
        return "MacIntel"
    else:
        return "Linux x86_64"


def get_stealth_browser(
    headless: bool = False,
    user_data_dir: Optional[str] = None,
    profile_dir: str = "Default",
    download_dir: Optional[str] = None,
):
    """
    Selenium + webdriver-manager 사용
    - 실제 브라우저(기본, 헤드리스 아님)
    - 간단 스텔스 패치: navigator.webdriver=false 등
    - 다운로드 폴더를 프로젝트 내부 downloads/ 로 통일
    - PDF가 브라우저 탭으로 열리지 않고 바로 다운로드되도록 설정
    - Playwright 인터페이스 호환 반환:
      (browser, context, page) = (driver, None, driver)
    """
    opts = Options()

    # 1) user-data-dir
    if user_data_dir is None:
        user_data_dir = _get_default_user_data_dir()
    else:
        Path(user_data_dir).mkdir(parents=True, exist_ok=True)

    # 2) download-dir
    if download_dir is None:
        download_dir = _get_default_download_dir()
    else:
        Path(download_dir).mkdir(parents=True, exist_ok=True)

    # SingletonLock 제거 (이전 비정상 종료 잔재 → "기존 세션" 오류 방지)
    _remove_chrome_singleton_lock(user_data_dir)

    opts.add_argument(f"--user-data-dir={user_data_dir}")
    opts.add_argument(f"--profile-directory={profile_dir}")

    if headless:
        opts.add_argument("--headless=new")

    # 동작/호환 옵션
    opts.add_argument("--start-maximized")
    opts.add_argument("--disable-popup-blocking")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--ignore-certificate-errors")
    opts.add_argument("--no-first-run")
    opts.add_argument("--no-default-browser-check")
    opts.add_argument("--no-service-autorun")

    # 자동화 배너 제거 & 오토메이션 익스텐션 비활성화
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)

    # 다운로드 / PDF / 비밀번호 저장 관련 설정
    prefs = {
        "download.default_directory": str(Path(download_dir).resolve()),
        "download.prompt_for_download": False,
        "download.directory_upgrade": True,
        "profile.default_content_settings.popups": 0,
        "plugins.always_open_pdf_externally": True,
        "credentials_enable_service": False,
        "profile.password_manager_enabled": False,
    }
    opts.add_experimental_option("prefs", prefs)

    driver = webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=opts,
    )

    # Chrome DevTools Protocol: 다운로드 허용
    try:
        driver.execute_cdp_cmd(
            "Page.setDownloadBehavior",
            {
                "behavior": "allow",
                "downloadPath": str(Path(download_dir).resolve()),
            },
        )
    except Exception:
        # 일부 환경에서 미지원일 수 있으니 방어
        pass

    js_platform = _get_js_platform_value()

    # 간단 스텔스 패치
    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": f"""
                    try {{
                        Object.defineProperty(navigator, 'webdriver', {{
                            get: () => false
                        }});
                    }} catch(e) {{}}

                    try {{
                        Object.defineProperty(navigator, 'languages', {{
                            get: () => ['ko-KR', 'ko']
                        }});
                    }} catch(e) {{}}

                    try {{
                        Object.defineProperty(navigator, 'platform', {{
                            get: () => '{js_platform}'
                        }});
                    }} catch(e) {{}}
                """
            },
        )
    except Exception:
        # 구버전 크롬/드라이버 환경 방어
        pass

    try:
        driver.maximize_window()
    except Exception:
        pass

    print(f"✅ Selenium 브라우저 실행 완료 - browser.py:160")
    print(f"OS: {platform.system()} - browser.py:161")
    print(f"user_data_dir: {user_data_dir} - browser.py:162")
    print(f"download_dir: {download_dir} - browser.py:163")

    browser = driver
    context = None
    page = driver
    return browser, context, page