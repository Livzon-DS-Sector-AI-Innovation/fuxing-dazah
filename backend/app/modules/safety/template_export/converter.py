"""
Excel → PDF converter.

Tries LibreOffice headless first (best quality), falls back to Excel COM
on Windows.  Both are auto-detected; nothing to configure unless you need
a custom soffice path.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

# ── Known LibreOffice install locations ────────────────────────────────────
_SOFFICE_CANDIDATES: list[str] = []
if sys.platform == "win32":
    _SOFFICE_CANDIDATES = [
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ]
else:
    _SOFFICE_CANDIDATES = [
        "/usr/bin/soffice",
        "/usr/local/bin/soffice",
        "/opt/libreoffice/program/soffice",
    ]


# ── Converter class ────────────────────────────────────────────────────────

class ExcelToPdfConverter:
    """Convert a filled .xlsx file to .pdf.

    1. LibreOffice headless (``soffice --headless --convert-to pdf``)
    2. (Windows fallback) Excel COM ``ExportAsFixedFormat``
    """

    def __init__(self, soffice_path: str | Path | None = None) -> None:
        """*soffice_path* overrides auto-detection."""
        self._soffice: Path | None = (
            Path(soffice_path) if soffice_path else None
        )

    # ── Public API ──────────────────────────────────────────────────────

    def convert(self, xlsx_path: str | Path, pdf_path: str | Path) -> Path:
        """Convert *xlsx_path* → *pdf_path*.  Returns the output path.

        Raises ``RuntimeError`` if no converter is available.
        """
        src = Path(xlsx_path).resolve()
        dst = Path(pdf_path).resolve()

        # Remove existing PDF so we can detect a fresh one
        dst.unlink(missing_ok=True)

        if self._try_libreoffice(src, dst):
            return dst

        if sys.platform == "win32" and self._try_excel_com(src, dst):
            return dst

        raise RuntimeError(
            "No Excel→PDF converter available.\n"
            "  Install: winget install TheDocumentFoundation.LibreOffice\n"
            "  Or open the .xlsx in Excel / WPS and Save As PDF manually."
        )

    # ── LibreOffice ─────────────────────────────────────────────────────

    def _find_soffice(self) -> Path | None:
        if self._soffice and self._soffice.exists():
            return self._soffice

        # Check known locations
        for candidate in _SOFFICE_CANDIDATES:
            p = Path(candidate)
            if p.exists():
                self._soffice = p
                return p

        # Try PATH
        for cmd in ("soffice", "libreoffice"):
            found = shutil.which(cmd)
            if found:
                self._soffice = Path(found)
                return self._soffice

        return None

    def _try_libreoffice(self, src: Path, dst: Path) -> bool:
        soffice = self._find_soffice()
        if not soffice:
            return False

        try:
            subprocess.run(
                [
                    str(soffice), "--headless", "--convert-to", "pdf",
                    "--outdir", str(dst.parent), str(src),
                ],
                capture_output=True, text=True, timeout=120,
                # Prevent LibreOffice from inheriting a lock on the input
                env={**os.environ, "SAL_USE_VCLPLUGIN": "gen"},
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False
        except Exception:
            return False

        if dst.exists():
            return True

        # LibreOffice names output as <stem>.pdf — rename if needed
        generated = dst.parent / f"{src.stem}.pdf"
        if generated.exists():
            if generated != dst:
                shutil.move(str(generated), str(dst))
            return True

        # Sometimes it fails silently — check stderr
        # (e.g. missing fonts are non-fatal, but a locked file is)
        return False

    # ── Excel COM fallback (Windows only) ───────────────────────────────

    @staticmethod
    def _try_excel_com(src: Path, dst: Path) -> bool:
        """Fallback: Excel COM Automation (Windows, Excel 2007+)."""
        ps_script = (
            f'$excel = New-Object -ComObject Excel.Application; '
            f'$excel.Visible = $false; '
            f'$excel.DisplayAlerts = $false; '
            f'$wb = $excel.Workbooks.Open("{src}"); '
            f'$wb.ExportAsFixedFormat(0, "{dst}"); '
            f'$wb.Close($false); '
            f'$excel.Quit(); '
            f'[Runtime.InteropServices.Marshal]::ReleaseComObject($wb); '
            f'[Runtime.InteropServices.Marshal]::ReleaseComObject($excel); '
        )
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                capture_output=True, text=True, timeout=120,
            )
        except Exception:
            return False
        return dst.exists()


# ── Convenience ────────────────────────────────────────────────────────────

def convert_xlsx_to_pdf(
    xlsx_path: str | Path,
    pdf_path: str | Path | None = None,
    *,
    soffice_path: str | Path | None = None,
) -> Path:
    """One-shot: convert .xlsx → .pdf.  *pdf_path* auto-derives from stem if omitted."""
    xlsx = Path(xlsx_path)
    pdf = Path(pdf_path) if pdf_path else xlsx.with_suffix(".pdf")
    return ExcelToPdfConverter(soffice_path=soffice_path).convert(xlsx, pdf)
