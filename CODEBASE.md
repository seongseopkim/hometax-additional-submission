# 추가_제출 자동화 — 코드베이스 가이드

> **다음 세션을 위한 문서입니다.** 이 파일을 먼저 읽으면 전체 구조를 파악할 수 있습니다.

---

## 한줄 요약

홈택스에서 종합소득세 신고 부속서류(PDF)를 자동으로 제출하는 PyQt5 + Selenium 자동화 프로그램입니다.

---

## 폴더 구조

```
추가_제출/
├── main.py                    # GUI 진입점 (PyQt5)
├── automation/
│   ├── browser.py             # Chrome 드라이버 세팅 (webdriver-manager 사용)
│   ├── login.py               # 홈택스 로그인 (공인인증서)
│   └── tasks.py               # 핵심 자동화 로직
├── utils/
│   ├── file_util.py           # 엑셀 읽기, 주민번호 파싱
│   ├── popup_util.py          # DOM 팝업 / alert 처리
│   └── selenium_safe.py       # safe_click, fill_input, safe_select
├── input/
│   ├── 마스터엑셀.xlsx          # 처리할 사람 목록 (이름 무관, .xlsx/.xls)
│   └── pdf/
│       └── 폴더명/             # 엑셀 D열 폴더명과 일치해야 함
│           └── 파일명.pdf       # 엑셀 E열 파일명과 일치해야 함
└── dist/
    └── 추가제출자동화.exe        # 배포용 실행파일
```

---

## 엑셀 형식 (input/ 안의 .xlsx)

| A열 | B열 | C열 | D열 | E열 |
|-----|-----|-----|-----|-----|
| 번호 | 이름 | 주민번호 | 폴더명 | 파일명 |
| 1 | 홍길동 | 1234561234567 | RDP011_홍길동_123456_789012 | 홍길동_2024.pdf |

- 1행은 헤더, 2행부터 읽음
- 주민번호: 하이픈 있어도 없어도 됨 (13자리 숫자로 파싱)

---

## 핵심 로직 흐름 (`tasks.py`)

```
process_row() 호출
  ├─ navigate=True  → _navigate_and_load()  : SUBMIT_URL 이동 → 버튼 클릭 → 필드 대기
  └─ navigate=False → 기존 폼 재사용 (RRN 필드 살아있는지 확인)
       ↓
  _fill_date_and_rrn()  : 신고일자 + 주민번호 입력 → JS 검증
       ↓
  세목 선택 (종합소득세) → _do_search() → 팝업 처리
       ↓
  버튼 텍스트 확인:
    "첨부하기"     → 정상 진행
    "제출내역보기" → (False, "제출내역존재") 반환
       ↓
  _click_attach_and_switch()  : 첨부하기 클릭 → 새 창 전환 대기
       ↓
  _upload_pdf()               : pyautogui OS 클릭 → 파일탐색기 → 경로 붙여넣기
       ↓
  파일명 검증 (그리드 셀 innerText vs pdf_path.name)
       ↓
  부속서류 제출하기 버튼 클릭 → alert 대기(최대 40초) → 창 종료 대기
       ↓
  return (True, "")
```

---

## 실패 처리

실패 시 **폴더명 자체를 변경**합니다 (`_rename_folder_on_failure`):

```
RDP011_홍길동_123456_789012  →  RDP011_홍길동_123456_789012_주민번호_입력_실패
```

| 실패 사유 | 발생 조건 |
|-----------|-----------|
| `주민번호_형식_이상` | 13자리 숫자로 파싱 불가 |
| `pdf파일_없음` | 파일 경로 미존재 |
| `pdf파일이_아님` | 확장자가 .pdf 아님 |
| `페이지_로드_실패` | 홈택스 URL 진입 후 필드 15초 내 미감지 |
| `주민번호_입력_실패` | 입력 후 JS 검증 불일치 |
| `조회된_데이터_없음` | 해당 연도 신고내역 없음 |
| `제출내역존재` | 버튼이 이미 "제출내역보기"로 표시됨 |
| `첨부하기_창_열기_실패` | 새 창 25초 내 미오픈 |
| `파일_업로드_실패` | 그리드에 파일명 10초 내 미반영 |
| `파일명_불일치` | 그리드 파일명 ≠ PDF 파일명 |
| `제출버튼_클릭_실패` | 제출 버튼 10초 내 미감지 |
| `예외_<Type>` | 예상치 못한 Python 예외 |

---

## GUI (`main.py`)

- **PyQt5** QMainWindow, 왼쪽(입력+목록) / 오른쪽(버튼) HBoxLayout
- 로그는 터미널 `print()`에만 출력 (GUI에 로그창 없음)
- 버튼 3개: 📂 파일 불러오기 / 🔐 홈택스 로그인 / 📤 추가서류 제출
- `신고일자` 입력란: 기본값 `20260501`, YYYYMMDD 8자리, 로그인 전 변경 가능
- 로그인 → submit 버튼 활성화 → 제출 실행 → 완료 후 자동 로그아웃

### navigate 플래그

- 첫 번째 사람: `navigate=True` (URL 진입)
- 성공 후 다음 사람: `navigate=False` (폼 재사용, 빠름)
- 실패 후 다음 사람: `navigate=True` (안전하게 재진입)

---

## 주의사항

### 파일선택 버튼 (`w2trigger`)
JS `.click()`으로는 파일 다이얼로그가 열리지 않음 → `pyautogui`로 **OS 레벨 마우스 클릭** 필요.  
화면 좌표 계산: `driver.get_window_position()` + 크롬 UI 높이 + `getBoundingClientRect()`

### 팝업 구분 (`popup_util.py`)
홈택스 알림 팝업의 확인 버튼: `aria-hidden="false"` 속성 있음  
결과 테이블 확인 버튼(trigger44): `aria-hidden` 속성 자체 없음  
→ `getAttribute('aria-hidden') === 'false'`로 팝업 버튼만 정확히 타겟팅

### exe 배포 시 폴더 구조
exe 파일 옆에 `input/` 폴더 구조가 반드시 있어야 함.  
exe 빌드: `추가_제출/.venv/Scripts/python.exe` → PyInstaller `--onefile --noconsole`

### ChromeDriver
`webdriver_manager` 사용으로 자동 다운로드. 첫 실행 또는 Chrome 업데이트 후 인터넷 필요.

---

## 주요 CSS 셀렉터

```python
CSS_RRN_FRONT    = "#mf_txppWframe_UTERNAAZ0Z41_wframe_inputResno_1"
CSS_RRN_BACK     = "#mf_txppWframe_UTERNAAZ0Z41_wframe_inputResno_2"
CSS_SEMOK_SEL    = "#mf_txppWframe_UTERNAAZ0Z41_wframe_selectbox2_UTERNAAZ41"
CSS_SEARCH_BTN   = "#mf_txppWframe_UTERNAAZ0Z41_wframe_trigger45_UTERNAAZ41"
CSS_DATE_START   = "#mf_txppWframe_UTERNAAZ0Z41_wframe_rtnDtSrt_UTERNAAZ41_input"
CSS_ATTACH_BTN   = 'td[data-col_id="column53"] button'   # 첨부하기 / 제출내역보기
CSS_FILE_BTN     = '#mf_pf_UTECMGAA06_UTECMGAA06_trigger1'
CSS_CLOSE_FORM   = '#mf_txppWframe_UTERNAAZ0Z41_wframe_trigger41_Z12'
CSS_SUBMIT_BTN   = '#mf_trigger2_'
```

---

## 의존 패키지 (`.venv` 기준)

- `selenium`, `webdriver-manager`
- `PyQt5`
- `pyautogui`, `pyperclip`
- `openpyxl`
- `pyinstaller` (빌드용)
