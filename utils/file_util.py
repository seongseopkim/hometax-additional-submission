"""
파일/폴더 처리 유틸리티
- find_master_excel : input/ 폴더에서 마스터 엑셀 찾기
- read_master_excel : 마스터 엑셀 행 목록 반환 (A=이름 B=주민번호 C=폴더명 D=파일명)
- parse_rrn         : 주민번호 문자열 → (앞6, 뒤7) 또는 (None, None)
- write_failed_log  : failed_log.txt 에 실패 내역 추가 기록
"""

import re
from pathlib import Path
from datetime import datetime

import openpyxl


# ── 마스터 엑셀 탐색 ─────────────────────────────────────────────────────────

def find_master_excel(input_dir: Path) -> Path | None:
    """input/ 폴더에서 .xlsx/.xls 파일 하나 반환. 여러 개면 첫 번째."""
    excels = list(input_dir.glob("*.xlsx")) + list(input_dir.glob("*.xls"))
    excels = [e for e in excels if not e.name.startswith("~")]  # 임시파일 제외
    if not excels:
        print(f"[파일] ⚠️ 마스터 엑셀 없음: {input_dir}")
        return None
    if len(excels) > 1:
        print(f"[파일] ⚠️ 마스터 엑셀 여러 개: {[e.name for e in excels]} → 첫 번째 사용")
    return excels[0]


# ── 마스터 엑셀 읽기 ─────────────────────────────────────────────────────────

def read_master_excel(excel_path: Path) -> list[dict]:
    """
    마스터 엑셀 2행부터 읽기 (1행은 헤더).
    A열=번호, B열=이름, C열=주민번호, D열=폴더명, E열=파일명(확장자 포함)
    반환: [{"이름": str, "주민번호": str, "폴더명": str, "파일명": str, "행번호": int}, ...]
    """
    rows = []
    try:
        wb = openpyxl.load_workbook(excel_path, data_only=True)
        ws = wb.active
        for i, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
            name   = str(row[1] if len(row) > 1 and row[1] is not None else "").strip()
            rrn    = str(row[2] if len(row) > 2 and row[2] is not None else "").strip()
            folder = str(row[3] if len(row) > 3 and row[3] is not None else "").strip()
            fname  = str(row[4] if len(row) > 4 and row[4] is not None else "").strip()
            if not name and not rrn and not folder and not fname:
                continue
            rows.append({"이름": name, "주민번호": rrn, "폴더명": folder, "파일명": fname, "행번호": i})
        print(f"[엑셀] ✅ 마스터 엑셀 {len(rows)}행 읽음: {excel_path.name}")
    except Exception as e:
        print(f"[엑셀] ❌ 마스터 엑셀 읽기 실패: {excel_path.name} — {e}")
    return rows


# ── 주민번호 파싱 ─────────────────────────────────────────────────────────────

def parse_rrn(rrn_raw: str) -> tuple[str | None, str | None]:
    """
    주민번호 문자열을 (앞6자리, 뒤7자리)로 분리.
    - "123456-1234567" → ("123456", "1234567")
    - "1234561234567"  → ("123456", "1234567")
    - "비대상" 등 숫자 13자리로 변환 불가 → (None, None)
    """
    # 하이픈만 허용, 그 외 비숫자 문자 있으면 실패
    cleaned = re.sub(r'-', '', rrn_raw).strip()
    if not cleaned.isdigit() or len(cleaned) != 13:
        return None, None
    return cleaned[:6], cleaned[6:]


# ── 실패 로그 기록 ────────────────────────────────────────────────────────────

def write_failed_log(log_path: Path, entries: list[dict]):
    """
    실패 내역을 log_path 파일에 추가(append) 기록.
    entries: [{"이름": str, "주민번호": str, "폴더명": str, "파일명": str, "오류": str}, ...]
    """
    if not entries:
        return
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [f"\n[{ts}] 실패 내역 ({len(entries)}건)"]
    for e in entries:
        lines.append(
            f"  이름={e.get('이름', '')} | 주민번호={e.get('주민번호', '')} | "
            f"폴더={e.get('폴더명', '')} | 파일={e.get('파일명', '')} | 오류={e.get('오류', '')}"
        )
    content = "\n".join(lines) + "\n"
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(content)
        print(f"[파일] ✅ failed_log.txt 기록: {len(entries)}건")
    except Exception as e:
        print(f"[파일] ❌ failed_log.txt 기록 실패: {e}")
