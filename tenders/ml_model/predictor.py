# tenders/ml_model/predictor.py
"""
CinnaTend — Cinnamon Oil Quality Predictor
==========================================
Model  : XGBoost (cinnamon_model_enhanced.pkl)
Grades : A (premium), B (standard), C (substandard) — no other grades
Inputs : PDF, PNG, JPG/JPEG, TIFF, BMP, WEBP, TXT, CSV

Key behaviours
--------------
* Loads cinnamon_model_enhanced.pkl (falls back to cinnamon_model.pkl).
* Grades are strictly A / B / C.  Any raw numeric prediction is mapped to
  A/B/C via the label encoder; unknown values default to C safely.
* Accepts ANY common document/image format and routes it correctly.
* Validates that the uploaded file is a cinnamon oil GC-MS report:
    - Must contain at least Eugenol + one other recognised chemical.
    - If none of the five chemicals are detected  →  raises InvalidReportError
      so the caller can show a clear "wrong file" error message.
* Confidence threshold  : 0.80  (flags low-confidence predictions).
* Rule-based fallback   : used only when the ML model is unavailable.
"""

import joblib
import os
import shutil
import subprocess
import re
import logging

from typing import Optional

import numpy as np
import pandas as pd
import pytesseract
from PIL import Image, ImageEnhance

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# CUSTOM EXCEPTION — raised when the uploaded file is not a cinnamon oil report
# ══════════════════════════════════════════════════════════════════════════════
class InvalidReportError(Exception):
    """
    Raised when the uploaded file does not appear to be a valid
    cinnamon oil GC-MS laboratory report.
    """
    pass


# ══════════════════════════════════════════════════════════════════════════════
# SUPPORTED FILE EXTENSIONS
# ══════════════════════════════════════════════════════════════════════════════
IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.tiff', '.tif', '.bmp', '.webp'}
PDF_EXTS   = {'.pdf'}
TEXT_EXTS  = {'.txt', '.csv'}
ALL_EXTS   = IMAGE_EXTS | PDF_EXTS | TEXT_EXTS


# ══════════════════════════════════════════════════════════════════════════════
# GRADE CONSTANTS — strictly A, B, C only
# ══════════════════════════════════════════════════════════════════════════════
VALID_GRADES = {'A', 'B', 'C'}
CONFIDENCE_THRESHOLD = 0.80   # below this → flagged as low-confidence


# ══════════════════════════════════════════════════════════════════════════════
# CHEMICAL DETECTION — fuzzy patterns that survive common OCR errors
# ══════════════════════════════════════════════════════════════════════════════
# Each entry: (feature_key, [regex_patterns], (min_valid, max_valid))
CHEMICAL_PATTERNS = [
    (
        'Eugenol_Percentage',
        [
            # Must NOT be followed by "yl" — avoids matching "Eugenyl Acetate"
            r'[Ee][Uu][Gg][Ee3][Nn][Oo0][Ll1](?!\s*[Yy][Ll1])(?:\s*[Pp]ercentage|\s*\(%\)|\s*%)?',
            r'[Ee]ug[e3]n[o0]l(?![yY])',
        ],
        (55.0, 98.0),
    ),
    (
        'Eugenyl_Acetate_Percentage',
        [
            r'[Ee][Uu][Gg][Ee3][Nn][Yy][Ll1]\s*[Aa][Cc][Ee3][Tt][Aa][Tt][Ee3]',
            r'[Ee]ug[e3]ny[l1]\s*[Aa]c[e3]tat[e3]',
        ],
        # Wide range: covers trace amounts AND reports where Eugenyl Acetate
        # is listed as the dominant compound (e.g. 88.75%) in place of Eugenol
        (0.1, 98.0),
    ),
    (
        'Linalool_Percentage',
        [
            r'[Ll][Ii1][Nn][Aa][Ll][Oo0][Oo0][Ll1]',
            r'[Ll]ina[l1][o0]{2}[l1]',
        ],
        (0.1, 15.0),
    ),
    (
        'Cinnamaldehyde_Percentage',
        [
            r'[Cc][Ii1][Nn][Nn][Aa][Mm][Aa][Ll][Dd][Ee3][Hh][Yy][Dd][Ee3]',
            r'[Cc]innam[a4]ld[e3]hyd[e3]',
        ],
        (0.1, 15.0),
    ),
    (
        'Safrole_Percentage',
        [
            r'[Ss][Aa][Ff][Rr][Oo0][Ll1][Ee3]',
            r'[Ss]afr[o0][l1][e3]',
        ],
        (0.0, 5.0),
    ),
]

# Minimum number of chemicals that must be detected to accept the file as valid
MIN_CHEMICALS_REQUIRED = 2   # Eugenol + at least one other


# ══════════════════════════════════════════════════════════════════════════════
# TESSERACT AUTO-DETECT
# ══════════════════════════════════════════════════════════════════════════════
def _find_tesseract():
    candidates = [
        "/opt/homebrew/bin/tesseract",                          # Mac Apple Silicon
        "/usr/local/bin/tesseract",                             # Mac Intel
        "/usr/bin/tesseract",                                   # Linux
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",       # Windows 64-bit
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe", # Windows 32-bit
    ]
    for path in candidates:
        if os.path.isfile(path):
            logger.info(f"Tesseract found: {path}")
            return path
    found = shutil.which("tesseract")
    if found:
        logger.info(f"Tesseract found via PATH: {found}")
        return found
    logger.error(
        "Tesseract not found!\n"
        "  Mac:   brew install tesseract\n"
        "  Linux: sudo apt install tesseract-ocr\n"
        "  Win:   https://github.com/UB-Mannheim/tesseract/wiki"
    )
    return "tesseract"


pytesseract.pytesseract.tesseract_cmd = _find_tesseract()


# ══════════════════════════════════════════════════════════════════════════════
# OPTIONAL HEAVY DEPENDENCIES
# ══════════════════════════════════════════════════════════════════════════════
try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    logger.warning("OpenCV not installed — advanced image preprocessing disabled.")

try:
    from pdf2image import convert_from_path
    PDF2IMAGE_AVAILABLE = True
except ImportError:
    PDF2IMAGE_AVAILABLE = False
    logger.warning("pdf2image not installed — PDF support disabled.")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN PREDICTOR CLASS
# ══════════════════════════════════════════════════════════════════════════════
class QualityPredictor:
    """
    Cinnamon oil quality predictor using XGBoost.

    Grades are strictly A, B, or C.

    Raises InvalidReportError when the uploaded file does not contain
    recognisable cinnamon oil GC-MS data (e.g. a bill, invoice, or
    unrelated document).
    """

    def __init__(self):
        self.model         = None
        self.label_encoder = None
        self.feature_names = [
            'Eugenol_Percentage',
            'Eugenyl_Acetate_Percentage',
            'Linalool_Percentage',
            'Cinnamaldehyde_Percentage',
            'Safrole_Percentage',
        ]
        # Fallback feature defaults (median values from training data)
        self._feature_defaults = {
            'Eugenol_Percentage':         85.0,
            'Eugenyl_Acetate_Percentage':  0.54,
            'Linalool_Percentage':         1.76,
            'Cinnamaldehyde_Percentage':   0.78,
            'Safrole_Percentage':          0.76,
        }
        self.load_model()

    # ──────────────────────────────────────────────────────────────────────────
    # MODEL LOADING
    # ──────────────────────────────────────────────────────────────────────────
    def load_model(self):
        model_dir = os.path.dirname(__file__)

        # Prefer the XGBoost model; fall back to legacy pkl if absent
        for filename in ['cinnamon_model_enhanced.pkl', 'cinnamon_model.pkl']:
            path = os.path.join(model_dir, filename)
            if os.path.exists(path):
                try:
                    self.model = joblib.load(path)
                    logger.info(
                        f"Model loaded: {filename}  "
                        f"(type={type(self.model).__name__})"
                    )
                    break
                except Exception as e:
                    logger.error(f"Failed to load {filename}: {e}")

        if self.model is None:
            logger.warning("No model file found. Rule-based grading will be used.")

        enc_path = os.path.join(model_dir, 'label_encoder.pkl')
        if os.path.exists(enc_path):
            try:
                self.label_encoder = joblib.load(enc_path)
                logger.info(
                    f"Label encoder loaded. "
                    f"Classes: {list(self.label_encoder.classes_)}"
                )
            except Exception as e:
                logger.warning(f"Could not load label encoder: {e}")

    # ──────────────────────────────────────────────────────────────────────────
    # TESSERACT HEALTH CHECK
    # ──────────────────────────────────────────────────────────────────────────
    def _tesseract_ok(self) -> bool:
        try:
            r = subprocess.run(
                [pytesseract.pytesseract.tesseract_cmd, '--version'],
                capture_output=True, timeout=5
            )
            return r.returncode == 0
        except Exception:
            return False

    # ──────────────────────────────────────────────────────────────────────────
    # IMAGE PREPROCESSING  (OpenCV pipeline)
    # ──────────────────────────────────────────────────────────────────────────
    def _preprocess_image(self, cv_image):
        """
        Enhance a CV2 image for OCR:
        upscale → greyscale → Otsu threshold → remove grid lines → erode.
        Falls back to PIL grayscale if OpenCV is unavailable.
        """
        if not CV2_AVAILABLE:
            return Image.fromarray(cv_image)
        try:
            h, w    = cv_image.shape[:2]
            cv_image = cv2.resize(cv_image, (w * 2, h * 2),
                                  interpolation=cv2.INTER_LANCZOS4)
            gray    = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY)
            thresh  = cv2.threshold(
                gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU
            )[1]

            # Remove horizontal and vertical grid lines
            for kernel_size in [(50, 1), (1, 50)]:
                kernel = cv2.getStructuringElement(cv2.MORPH_RECT, kernel_size)
                lines  = cv2.morphologyEx(
                    thresh, cv2.MORPH_OPEN, kernel, iterations=2
                )
                cnts   = cv2.findContours(
                    lines, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
                )
                for c in (cnts[0] if len(cnts) == 2 else cnts[1]):
                    cv2.drawContours(thresh, [c], -1, (0, 0, 0), 3)

            result = cv2.erode(255 - thresh, np.ones((2, 2), np.uint8), iterations=1)
            return Image.fromarray(result)
        except Exception as e:
            logger.error(f"_preprocess_image: {e}")
            return Image.fromarray(cv_image)

    # ──────────────────────────────────────────────────────────────────────────
    # CHEMICAL VALUE EXTRACTION  (from OCR text string)
    # ──────────────────────────────────────────────────────────────────────────
    @staticmethod
    def _extract_number_near(text: str, pattern: str, valid_range: tuple) -> Optional[float]:
        """
        Search for `pattern` in `text`, then try to read a float on the same
        line or the immediately following line.  Validates against valid_range.

        Handles OCR variants:
          87.42  |  87,42  |  87 42  |  87.4  |  87
          1,80 (European decimal comma normalised to 1.80)
          Numbers adjacent to letters or symbols (no word boundary required)
        """
        # Normalise OCR artifacts:
        #   comma-as-decimal: "1,80" -> "1.80"
        #   space-as-decimal: "78 45" -> handled by two-integer fallback below
        clean = text.replace(',', '.')

        lines = clean.splitlines()
        for i, line in enumerate(lines):
            if re.search(pattern, line, re.IGNORECASE):
                # Search current line first, then the next line (value on own row)
                search_lines = [line]
                if i + 1 < len(lines):
                    search_lines.append(lines[i + 1])

                for sline in search_lines:
                    # Primary: grab all decimal numbers (no strict word boundary
                    # so values adjacent to symbols like "78.45|" still match)
                    # CORRECT — no space: (\d
                    nums = re.findall(r'(?<![\d.])(\d{1,3}\.\d{1,4})(?![\d])', sline)
                    # Fallback: integers only (e.g. "Eugenol 78")
                    if not nums:
                        nums = re.findall(r'\b(\d{1,3})\b', sline)
                    for n in nums:
                        try:
                            val = float(n)
                            if valid_range[0] <= val <= valid_range[1]:
                                return val
                        except ValueError:
                            continue
        return None

    def _parse_chemicals(self, text: str) -> dict:
        """
        Run fuzzy pattern matching on OCR text to extract all five
        chemical percentages.  Returns a dict with only the found values;
        absent keys will be filled with defaults later.

        Special case — Eugenyl Acetate as primary compound:
        Some lab reports list "Eugenyl Acetate" as the dominant row at 55-98%
        with no separate "Eugenol" row.  When this happens the high-% Eugenyl
        Acetate value is promoted to Eugenol_Percentage so the model receives
        a meaningful primary feature.
        """
        found = {}
        for feature_key, patterns, valid_range in CHEMICAL_PATTERNS:
            for pat in patterns:
                val = self._extract_number_near(text, pat, valid_range)
                if val is not None:
                    found[feature_key] = val
                    break   # stop trying patterns for this chemical

        # ── Eugenyl Acetate → Eugenol promotion ─────────────────────────────
        # Some lab reports (e.g. Cinnamon Analytics Labs) list "Eugenyl Acetate"
        # as the dominant compound row (55–98%) with no separate "Eugenol" row.
        # Promote it to fill Eugenol_Percentage so the model has its primary feature.
        if (
            'Eugenol_Percentage' not in found
            and 'Eugenyl_Acetate_Percentage' in found
            and found['Eugenyl_Acetate_Percentage'] >= 55.0
        ):
            found['Eugenol_Percentage'] = found['Eugenyl_Acetate_Percentage']
            logger.info(
                "Eugenyl Acetate (%.2f%%) promoted to Eugenol_Percentage "
                "— no explicit Eugenol row found in report.",
                found['Eugenyl_Acetate_Percentage']
            )

        # ── Last-resort scan ─────────────────────────────────────────────────
        # If Eugenol is STILL missing after promotion, scan all lines for any
        # number in the primary Eugenol range (55–98). Handles unusual layouts
        # where the chemical name and value are on non-adjacent lines.
        if 'Eugenol_Percentage' not in found:
            clean = text.replace(',', '.')
            for line in clean.splitlines():
                for m in re.finditer(r'(?<!\d)(\d{2,3}\.\d{1,4})(?!\d)', line):
                    try:
                        val = float(m.group(1))
                        if 55.0 <= val <= 98.0:
                            found['Eugenol_Percentage'] = val
                            logger.info(
                                "Last-resort scan found primary-range value "
                                "%.2f%% for Eugenol_Percentage.", val
                            )
                            break
                    except ValueError:
                        continue
                if 'Eugenol_Percentage' in found:
                    break

        return found

    # ──────────────────────────────────────────────────────────────────────────
    # VALIDATION — is this actually a cinnamon oil GC-MS report?
    # ──────────────────────────────────────────────────────────────────────────
    def _validate_report(self, found: dict, raw_text: str):
        """
        Raises InvalidReportError when the file is not a valid GC-MS report.

        Rules:
          1. At least MIN_CHEMICALS_REQUIRED chemicals must be detected
             (after Eugenyl Acetate promotion, so Eugenol_Percentage is
             always present in a valid report by this point).
          2. If the text contains financial/non-report keywords AND lacks
             chemical data → give a specific "wrong file" error message.

        Note: Eugenol_Percentage may have been populated by Eugenyl Acetate
        promotion in _parse_chemicals(), so we do NOT require the word
        "Eugenol" to appear literally in the text.
        """
        non_report_kws = [
            'invoice', 'receipt', 'purchase order', 'bill to', 'ship to',
            'total amount', 'subtotal', 'tax invoice', 'payment due',
            'unit price', 'grand total', 'order number',
            'customer id', 'account number',
        ]
        text_lower = raw_text.lower()
        has_non_report_kw = any(kw in text_lower for kw in non_report_kws)

        chemicals_found = len(found)
        # After promotion, Eugenol_Percentage is set whenever any primary-range
        # compound (Eugenol or high-% Eugenyl Acetate) is found.
        has_primary = 'Eugenol_Percentage' in found

        if chemicals_found < MIN_CHEMICALS_REQUIRED or not has_primary:
            if has_non_report_kw:
                raise InvalidReportError(
                    "The uploaded file appears to be a financial document "
                    "(invoice, bill, or receipt), not a cinnamon oil GC-MS "
                    "laboratory report. Please upload a valid lab report "
                    "showing chemical composition percentages."
                )
            elif chemicals_found == 0:
                raise InvalidReportError(
                    "No cinnamon oil chemical composition data was found in "
                    "the uploaded file. Please ensure the file is a GC-MS "
                    "laboratory report containing Eugenol (or Eugenyl Acetate), "
                    "Linalool, Cinnamaldehyde, and Safrole percentages."
                )
            else:
                raise InvalidReportError(
                    f"Only {chemicals_found} chemical value(s) could be "
                    "extracted from the uploaded file. "
                    "A valid cinnamon oil GC-MS report must include at least "
                    f"{MIN_CHEMICALS_REQUIRED} recognised chemical compounds "
                    "including a primary Eugenol or Eugenyl Acetate percentage."
                )

    # ──────────────────────────────────────────────────────────────────────────
    # OCR ON A PIL IMAGE
    # ──────────────────────────────────────────────────────────────────────────
    def _ocr_image(self, pil_img: Image.Image, source_name: str) -> str:
        """
        Run OCR on a PIL image using adaptive multi-pass preprocessing.

        Strategy: try several enhancement combinations and pick the result
        that yields the most recognised chemical compound names.  This handles
        both dark-on-white reports (needs contrast boost) and light-background
        reports with coloured tables (where high contrast destroys table rows).

        Pass order:
          1. Brightness 1.5  — best for light-background / coloured-table reports
          2. Brightness 1.2  — mild lift, preserves subtle colours
          3. No enhancement  — raw PIL image
          4. Contrast 1.5    — moderate contrast for standard white-bg reports
          5. CV2 pipeline + contrast 1.5  — heavy preprocessing for noisy scans
        """
        CHEM_KEYWORDS = [
            'eugenol', 'linalool', 'cinnamaldehyde', 'safrole',
            'acetate', 'caryophyllene', 'benzoate', 'constituent',
            'percentage', 'value', 'compound',
        ]

        def _count_keywords(t):
            tl = t.lower()
            return sum(1 for kw in CHEM_KEYWORDS if kw in tl)

        def _ocr(img_pil):
            return pytesseract.image_to_string(img_pil, config='--oem 3 --psm 6')

        # Build candidate passes
        passes = [
            ("brightness_1.5",  ImageEnhance.Brightness(pil_img).enhance(1.5)),
            ("brightness_1.2",  ImageEnhance.Brightness(pil_img).enhance(1.2)),
            ("raw",             pil_img),
            ("contrast_1.5",    ImageEnhance.Contrast(pil_img).enhance(1.5)),
        ]

        # Add CV2 pass if available
        if CV2_AVAILABLE:
            try:
                cv_img = np.array(pil_img)
                if len(cv_img.shape) == 2:
                    cv_img = cv2.cvtColor(cv_img, cv2.COLOR_GRAY2BGR)
                elif cv_img.shape[2] == 4:
                    cv_img = cv2.cvtColor(cv_img, cv2.COLOR_RGBA2BGR)
                elif cv_img.shape[2] == 3:
                    cv_img = cv2.cvtColor(cv_img, cv2.COLOR_RGB2BGR)
                cv2_clean = self._preprocess_image(cv_img)
                passes.append(
                    ("cv2+contrast_1.5",
                     ImageEnhance.Contrast(cv2_clean).enhance(1.5))
                )
            except Exception as e:
                logger.warning(f"CV2 pass skipped: {e}")

        best_text  = ""
        best_score = -1

        for pass_name, img_variant in passes:
            try:
                t = _ocr(img_variant)
                score = _count_keywords(t)
                logger.debug(
                    f"OCR pass [{pass_name}] score={score} "
                    f"chars={len(t)} src={source_name}"
                )
                if score > best_score:
                    best_score = best_score if score <= best_score else score
                    best_score = score
                    best_text  = t
            except Exception as e:
                logger.warning(f"OCR pass [{pass_name}] failed: {e}")

        logger.debug(f"Best OCR [{source_name}] score={best_score}:\n{best_text[:400]}")
        return best_text

    # ──────────────────────────────────────────────────────────────────────────
    # FILE-TYPE ROUTERS
    # ──────────────────────────────────────────────────────────────────────────
    def _text_from_pdf(self, file_path: str) -> str:
        """Convert each PDF page to an image and run OCR."""
        if not PDF2IMAGE_AVAILABLE:
            raise InvalidReportError(
                "PDF support is not available on this server. "
                "Please install the 'pdf2image' library and Poppler utilities, "
                "or upload the report as a PNG or JPG image."
            )
        pages = convert_from_path(file_path, dpi=300)
        collected = []
        for i, page in enumerate(pages):
            try:
                collected.append(self._ocr_image(page, f"pdf_page_{i+1}"))
            except Exception as e:
                logger.warning(f"PDF page {i+1} OCR failed: {e}")
        if not collected:
            raise InvalidReportError(
                "Could not extract any text from the PDF. "
                "The file may be corrupted or contain only scanned images "
                "with insufficient quality."
            )
        return "\n".join(collected)

    def _text_from_image(self, file_path: str) -> str:
        """Open any supported image format and run OCR."""
        try:
            img = Image.open(file_path)
        except Exception as e:
            raise InvalidReportError(
                f"Could not open the image file: {e}. "
                "Please upload a valid PNG, JPG, TIFF, BMP, or WEBP file."
            )
        if img.mode not in ('RGB', 'L'):
            img = img.convert('RGB')
        return self._ocr_image(img, os.path.basename(file_path))

    def _text_from_text_file(self, file_path: str) -> str:
        """Read a plain-text or CSV file directly — no OCR needed."""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                return f.read()
        except Exception as e:
            raise InvalidReportError(
                f"Could not read the text file: {e}."
            )

    # ──────────────────────────────────────────────────────────────────────────
    # GRADE MAPPER  — ensures only A, B, C are ever returned
    # ──────────────────────────────────────────────────────────────────────────
    def _map_to_grade(self, raw_pred) -> str:
        """
        Convert a raw model prediction to a valid grade (A / B / C).
        Uses the label encoder when available; otherwise attempts direct
        string coercion.  Anything unrecognised defaults to 'C' safely.
        """
        if self.label_encoder is not None:
            try:
                decoded = str(
                    self.label_encoder.inverse_transform([int(raw_pred)])[0]
                ).strip().upper()
                if decoded in VALID_GRADES:
                    return decoded
            except Exception:
                pass

        # Direct string match
        grade = str(raw_pred).strip().upper()
        if grade in VALID_GRADES:
            return grade

        # Numeric fallback (0→A, 1→B, 2→C as per label encoding)
        try:
            idx = int(float(raw_pred))
            mapping = {0: 'A', 1: 'B', 2: 'C'}
            if idx in mapping:
                return mapping[idx]
        except (ValueError, TypeError):
            pass

        logger.warning(
            f"Unrecognised prediction '{raw_pred}'. Defaulting to Grade C."
        )
        return 'C'

    # ──────────────────────────────────────────────────────────────────────────
    # ML PREDICTION
    # ──────────────────────────────────────────────────────────────────────────
    def _ml_prediction(self, features: dict) -> dict:
        """Run the XGBoost model and return a structured result."""
        row = [
            features.get(f, self._feature_defaults[f])
            for f in self.feature_names
        ]
        input_df = pd.DataFrame([row], columns=self.feature_names)

        raw_pred = self.model.predict(input_df)[0]
        grade    = self._map_to_grade(raw_pred)

        # Confidence from predict_proba (XGBoost always supports this)
        confidence = 0.95
        if hasattr(self.model, 'predict_proba'):
            try:
                proba      = self.model.predict_proba(input_df)[0]
                confidence = float(np.max(proba))
            except Exception as e:
                logger.warning(f"predict_proba failed: {e}")

        low_confidence = confidence < CONFIDENCE_THRESHOLD

        logger.info(
            f"XGBoost prediction → Grade={grade}, "
            f"Confidence={confidence:.4f}, "
            f"LowConf={low_confidence}"
        )
        return {
            'grade':          grade,
            'score':          round(float(features.get('Eugenol_Percentage', 0)), 2),
            'confidence':     round(confidence, 4),
            'low_confidence': low_confidence,
            'features':       features,
            'method':         'xgboost',
        }

    # ──────────────────────────────────────────────────────────────────────────
    # RULE-BASED FALLBACK  (only used when model file is missing)
    # ──────────────────────────────────────────────────────────────────────────
    def _rule_based_grading(self, features: dict) -> dict:
        """
        Simple Eugenol-threshold grading used when the XGBoost model
        is unavailable.  Strictly returns A, B, or C.
        """
        eugenol = features.get('Eugenol_Percentage', 0.0)

        if   eugenol >= 85.0: grade = 'A'
        elif eugenol >= 78.0: grade = 'B'
        else:                 grade = 'C'

        logger.info(
            f"Rule-based prediction → Grade={grade}, Eugenol={eugenol}%"
        )
        return {
            'grade':          grade,
            'score':          round(float(eugenol), 2),
            'confidence':     0.75,
            'low_confidence': True,   # always flag rule-based as low-confidence
            'features':       features,
            'method':         'rule_based',
        }

    # ──────────────────────────────────────────────────────────────────────────
    # PUBLIC API
    # ──────────────────────────────────────────────────────────────────────────
    def predict_quality(self, file_path: str) -> dict:
        """
        Main entry point.

        Parameters
        ----------
        file_path : str
            Absolute path to the uploaded file.

        Returns
        -------
        dict with keys:
            grade          : 'A', 'B', or 'C'
            score          : float  (Eugenol %)
            confidence     : float  (0.0 – 1.0)
            low_confidence : bool   (True if confidence < 0.80)
            features       : dict   (extracted chemical values)
            method         : str    ('xgboost' | 'rule_based')

        Raises
        ------
        InvalidReportError
            When the file is not a valid cinnamon oil GC-MS report,
            an unsupported file type, or a non-oil document such as
            an invoice or bill.
        """
        logger.info(f"predict_quality called: {file_path}")

        ext = os.path.splitext(file_path)[1].lower()

        # ── 1. Reject unsupported file types immediately ──────────────────────
        if ext not in ALL_EXTS:
            raise InvalidReportError(
                f"Unsupported file type '{ext}'. "
                "Please upload a PDF, PNG, JPG, JPEG, TIFF, BMP, WEBP, "
                "TXT, or CSV file."
            )

        # ── 2. Check Tesseract for OCR-dependent formats ──────────────────────
        if ext not in TEXT_EXTS and not self._tesseract_ok():
            raise InvalidReportError(
                "OCR engine (Tesseract) is not available on this server. "
                "Please contact the system administrator, or upload the "
                "report as a plain-text (.txt) or CSV (.csv) file."
            )

        # ── 3. Extract raw text from the file ────────────────────────────────
        if ext in PDF_EXTS:
            raw_text = self._text_from_pdf(file_path)
        elif ext in IMAGE_EXTS:
            raw_text = self._text_from_image(file_path)
        else:  # .txt / .csv
            raw_text = self._text_from_text_file(file_path)

        # ── 4. Parse chemical values ──────────────────────────────────────────
        found = self._parse_chemicals(raw_text)
        logger.info(f"Chemicals extracted: {found}")

        # ── 5. Validate: raises InvalidReportError for wrong files ───────────
        self._validate_report(found, raw_text)

        # ── 6. Fill missing features with training-data defaults ─────────────
        features = {**self._feature_defaults, **found}

        # ── 7. Predict ────────────────────────────────────────────────────────
        if self.model is not None:
            try:
                return self._ml_prediction(features)
            except InvalidReportError:
                raise
            except Exception as e:
                logger.error(f"XGBoost inference failed: {e}. Falling back.")
                return self._rule_based_grading(features)

        return self._rule_based_grading(features)


# ══════════════════════════════════════════════════════════════════════════════
# SINGLETON
# ══════════════════════════════════════════════════════════════════════════════
_predictor: Optional[QualityPredictor] = None


def get_predictor() -> QualityPredictor:
    global _predictor
    if _predictor is None:
        _predictor = QualityPredictor()
    return _predictor