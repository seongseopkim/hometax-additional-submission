from __future__ import annotations

import sys
import os
import io
import time
import threading
from pathlib import Path

# Windows cp949 환경에서 이모지 출력 시 인코딩 오류 방지
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
if hasattr(sys.stderr, 'buffer'):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)

def _patch_sys_path():
    if getattr(sys, 'frozen', False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    if base not in sys.path:
        sys.path.insert(0, base)
_patch_sys_path()

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLineEdit, QPushButton, QListWidget, QRadioButton, QButtonGroup
)
from PyQt5.QtCore import pyqtSignal, QObject
from PyQt5.QtGui import QFont

from automation.login import login_and_save_session
from automation.tasks import process_row, do_close_and_logout
from utils.file_util import (
    find_master_excel, read_master_excel,
    find_pdf_for_row, write_bigo_to_excel,
)

if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys.executable).parent
else:
    BASE_DIR = Path(__file__).parent

INPUT_DIR = BASE_DIR / "input"
PDF_DIR   = BASE_DIR / "input" / "pdf"


# ── 실패 사유 → 비고 텍스트 매핑 ─────────────────────────────────────────────

def _reason_to_bigo(ok: bool, reason: str) -> str:
    if ok:
        return "완료"
    if reason == "조회된_데이터_없음":
        return "조회된 데이터 없음"
    if reason == "제출내역존재":
        return "제출내역존재"
    return "첨부 실패"


# ── 시그널 브릿지 ─────────────────────────────────────────────────────────────
class _Sig(QObject):
    done       = pyqtSignal(bool)
    login_done = pyqtSignal(bool)


# ── 메인 윈도우 ───────────────────────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("추가 제출 자동화")
        self.setGeometry(100, 100, 1200, 600)
        self.statusBar().hide()
        self._sig = _Sig()
        self._sig.done.connect(self._on_done)
        self._sig.login_done.connect(self._on_login_done)
        self._driver = None
        self._stop_flag = False
        self._build_ui()

    # ── UI 빌드 ──────────────────────────────────────────────────────────────
    def _build_ui(self):
        container = QWidget(self)
        self.setCentralWidget(container)

        mainLayout = QHBoxLayout(container)

        # ── 왼쪽 영역 ────────────────────────────────────────────────────────
        leftLayout = QVBoxLayout()

        # 로그인 방식 선택
        methodLayout = QHBoxLayout()
        self.radio_cert = QRadioButton("공인인증서 로그인")
        self.radio_idpw = QRadioButton("아이디+인증서 로그인")
        self.radio_cert.setChecked(True)
        self._login_method_group = QButtonGroup()
        self._login_method_group.addButton(self.radio_cert)
        self._login_method_group.addButton(self.radio_idpw)
        methodLayout.addWidget(self.radio_cert)
        methodLayout.addWidget(self.radio_idpw)
        methodLayout.addStretch()
        leftLayout.addLayout(methodLayout)

        loginLayout = QHBoxLayout()

        self.id_input = QLineEdit()
        self.id_input.setPlaceholderText("아이디")
        self.id_input.setText("seobtax01")
        loginLayout.addWidget(self.id_input)

        self.pw_input = QLineEdit()
        self.pw_input.setPlaceholderText("비밀번호")
        self.pw_input.setText("slakdak960*")
        self.pw_input.setEchoMode(QLineEdit.Password)
        loginLayout.addWidget(self.pw_input)

        self.cert_input = QLineEdit()
        self.cert_input.setPlaceholderText("인증서 명")
        self.cert_input.setText("세무법인 서월(seowol)008168020240326181001322")
        loginLayout.addWidget(self.cert_input)

        self.cpw_input = QLineEdit()
        self.cpw_input.setPlaceholderText("인증서 비번")
        self.cpw_input.setText("rladudfks2469@@")
        self.cpw_input.setEchoMode(QLineEdit.Password)
        loginLayout.addWidget(self.cpw_input)

        self.date_input = QLineEdit()
        self.date_input.setPlaceholderText("신고일자 (YYYYMMDD)")
        self.date_input.setText("20260501")
        self.date_input.setMaximumWidth(130)
        loginLayout.addWidget(self.date_input)

        leftLayout.addLayout(loginLayout)

        self.nameList = QListWidget()
        leftLayout.addWidget(self.nameList)

        # ── 오른쪽 영역 ──────────────────────────────────────────────────────
        rightLayout = QVBoxLayout()

        self.load_btn = QPushButton("📂 파일 불러오기")
        self.load_btn.setMinimumHeight(60)
        self.load_btn.setFixedWidth(250)
        self.load_btn.clicked.connect(self._load_excel)
        rightLayout.addWidget(self.load_btn)

        self.login_btn = QPushButton("🔐 홈택스 로그인")
        self.login_btn.setMinimumHeight(60)
        self.login_btn.setFixedWidth(250)
        self.login_btn.clicked.connect(self._login)
        rightLayout.addWidget(self.login_btn)

        self.submit_btn = QPushButton("📤 추가서류 제출")
        self.submit_btn.setMinimumHeight(60)
        self.submit_btn.setFixedWidth(250)
        self.submit_btn.setEnabled(False)
        self.submit_btn.clicked.connect(self._submit)
        rightLayout.addWidget(self.submit_btn)

        mainLayout.addLayout(leftLayout)
        mainLayout.addLayout(rightLayout)

    # ── 파일 불러오기 ────────────────────────────────────────────────────────
    def _load_excel(self):
        self.nameList.clear()
        excel_path = find_master_excel(INPUT_DIR)
        if excel_path is None:
            self.nameList.addItem("⚠️ input/ 폴더에 엑셀 파일이 없습니다.")
            return

        rows = read_master_excel(excel_path)
        if not rows:
            self.nameList.addItem("⚠️ 엑셀에 데이터가 없습니다.")
            return

        self.nameList.addItem(f"📁 {excel_path.name}  —  총 {len(rows)}명")
        self.nameList.addItem("")
        for i, row in enumerate(rows, 1):
            pdf_stem = f"{row['이름']}_{row['유저번호1']}_{row['유저번호2']}"
            self.nameList.addItem(f"  {i}.  {row['이름']}  ({pdf_stem}.pdf)")

    # ── 슬롯 ────────────────────────────────────────────────────────────────
    def _on_login_done(self, success: bool):
        self.login_btn.setEnabled(True)
        if success:
            self.submit_btn.setEnabled(True)
        else:
            self.submit_btn.setEnabled(False)
            self._driver = None

    def _on_done(self, _: bool):
        self.login_btn.setEnabled(True)
        self.submit_btn.setEnabled(self._driver is not None)

    # ── 로그인 / 제출 ────────────────────────────────────────────────────────
    def _login(self):
        self._stop_flag = False
        self.login_btn.setEnabled(False)
        self.submit_btn.setEnabled(False)
        t = threading.Thread(target=self._run_login, daemon=True)
        t.start()

    def _submit(self):
        if not self._driver:
            print("❌ 로그인 먼저 해주세요.")
            return
        self._stop_flag = False
        self.login_btn.setEnabled(False)
        self.submit_btn.setEnabled(False)
        t = threading.Thread(target=self._run_submit, daemon=True)
        t.start()

    # ── 로그인 스레드 ────────────────────────────────────────────────────────
    def _run_login(self):
        def _log(msg): print(msg)

        if self._driver:
            try: self._driver.quit()
            except Exception: pass
            self._driver = None

        try:
            method = "idpw" if self.radio_idpw.isChecked() else "cert"
            _log(f"🚀 브라우저 시작 및 로그인 중... (방식: {'아이디+인증서' if method == 'idpw' else '공인인증서'})")
            _, _, driver = login_and_save_session(
                user_id      = self.id_input.text().strip(),
                user_pw      = self.pw_input.text().strip(),
                cert_name    = self.cert_input.text().strip(),
                cert_pw      = self.cpw_input.text().strip(),
                status_callback = _log,
                login_method    = method,
            )
            self._driver = driver
            _log("✅ 로그인 완료 — 이제 [추가서류 제출] 버튼을 눌러주세요")
            self._sig.login_done.emit(True)

        except Exception as e:
            _log(f"❌ 로그인 오류: {e}")
            if self._driver:
                try: self._driver.quit()
                except Exception: pass
                self._driver = None
            self._sig.login_done.emit(False)

    # ── 제출 스레드 ──────────────────────────────────────────────────────────
    def _run_submit(self):
        def _log(msg): print(msg)

        fixed_date = self.date_input.text().strip()
        if not fixed_date.isdigit() or len(fixed_date) != 8:
            print(f"❌ 신고일자 형식 오류: {fixed_date!r} (YYYYMMDD 8자리 숫자)")
            self._sig.done.emit(False)
            return
        _log(f"📅 신고일자: {fixed_date}")

        driver = self._driver

        try:
            excel_path = find_master_excel(INPUT_DIR)
            if excel_path is None:
                _log("❌ input/ 폴더에 마스터 엑셀(.xlsx/.xls)이 없습니다.")
                self._sig.done.emit(False)
                return

            _log(f"📋 마스터 엑셀: {excel_path.name}")
            rows = read_master_excel(excel_path)
            if not rows:
                _log("⚠️ 마스터 엑셀에 처리할 행이 없습니다.")
                self._sig.done.emit(True)
                return

            total = len(rows)
            skip_count = sum(1 for r in rows if r.get("비고", ""))
            _log(f"📂 처리 대상: {total}명 (비고 기록됨 {skip_count}명 건너뜀, 미처리 {total - skip_count}명)")

            navigate = True

            for i, row in enumerate(rows, 1):
                if self._stop_flag:
                    _log("⚠️ 사용자 중지 요청으로 종료")
                    break

                name      = row["이름"]
                rrn_front = row["주민번호앞"]
                rrn_back  = row["주민번호뒤"]
                user_num1 = row["유저번호1"]
                user_num2 = row["유저번호2"]
                row_no    = row["행번호"]
                label     = f"{name}({row_no}행)"

                if row.get("비고", ""):
                    _log(f"⏭️  [{i}/{total}] {label} — 비고 '{row['비고']}' 이미 있음, 건너뜀")
                    continue

                _log(f"📂 [{i}/{total}] {label}")

                try:
                    _ = driver.current_url
                except Exception:
                    _log("❌ Chrome이 응답하지 않습니다. 재로그인 후 다시 시도하세요.")
                    self._driver = None
                    self._sig.done.emit(False)
                    return

                # 주민번호 앞자리 검증
                if len(rrn_front) != 6 or not rrn_front.isdigit():
                    _log(f"⚠️ [{label}] 주민번호 앞자리 형식 이상: {rrn_front!r}")
                    write_bigo_to_excel(excel_path, row_no, "첨부 실패")
                    navigate = True
                    continue

                # 주민번호 뒷자리 검증
                if len(rrn_back) != 7 or not rrn_back.isdigit():
                    _log(f"⚠️ [{label}] 주민번호 뒷자리 형식 이상: {rrn_back!r}")
                    write_bigo_to_excel(excel_path, row_no, "첨부 실패")
                    navigate = True
                    continue

                # PDF 파일 탐색 (pdf/ 폴더 flat 구조)
                pdf_path = find_pdf_for_row(PDF_DIR, name, user_num1, user_num2)
                if pdf_path is None:
                    _log(f"⚠️ [{label}] PDF 없음: {name}_{user_num1}_{user_num2}.pdf")
                    write_bigo_to_excel(excel_path, row_no, "PDF 없음")
                    navigate = True
                    continue

                ok, reason = process_row(
                    driver, rrn_front, rrn_back, pdf_path,
                    name=name, status_cb=_log, navigate=navigate,
                    fixed_date=fixed_date,
                )

                bigo = _reason_to_bigo(ok, reason)
                write_bigo_to_excel(excel_path, row_no, bigo)

                if ok:
                    _log(f"✅ 완료: {label}")
                    navigate = False
                elif reason in ("조회된_데이터_없음", "제출내역존재"):
                    _log(f"❌ 실패: {label}  ({reason})")
                    navigate = False  # 폼 그대로 — 주민번호만 재입력
                else:
                    _log(f"❌ 실패: {label}  ({reason})")
                    navigate = True

                time.sleep(1)

            _log("🔒 처리 완료 — 닫기 및 로그아웃")
            do_close_and_logout(driver, status_cb=_log)

            _log("🎉 전체 처리 완료")
            self._sig.done.emit(True)

        except Exception as e:
            _log(f"❌ 오류: {e}")
            self._sig.done.emit(False)


# ── 진입점 ────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = QApplication(sys.argv)
    font = QFont("맑은 고딕", 10)
    app.setFont(font)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())
