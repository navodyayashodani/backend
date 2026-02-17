# tenders/ml_model/predictor.py

import joblib
import os
import shutil
import subprocess
import numpy as np
import pandas as pd
import pytesseract
from PIL import Image, ImageEnhance
import re
import logging

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════
# AUTO-DETECT TESSERACT PATH
# Works on Mac (Homebrew Apple Silicon + Intel), Linux, Windows
# ══════════════════════════════════════════════════════════════
def _find_tesseract():
    candidates = [
        "/opt/homebrew/bin/tesseract",                        # Mac Apple Silicon
        "/usr/local/bin/tesseract",                           # Mac Intel
        "/usr/bin/tesseract",                                 # Linux
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",     # Windows
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]
    for path in candidates:
        if os.path.isfile(path):
            logger.info(f"✅ Tesseract found at: {path}")
            return path

    # Fallback: search system PATH
    found = shutil.which("tesseract")
    if found:
        logger.info(f"✅ Tesseract found via PATH: {found}")
        return found

    logger.error(
        "❌ Tesseract not found!\n"
        "  Mac:   brew install tesseract\n"
        "  Linux: sudo apt install tesseract-ocr\n"
        "  Win:   https://github.com/UB-Mannheim/tesseract/wiki"
    )
    return "tesseract"   # last resort


pytesseract.pytesseract.tesseract_cmd = _find_tesseract()


# ══════════════════════════════════════════════════════════════
# OPTIONAL DEPENDENCIES
# ══════════════════════════════════════════════════════════════
try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    logger.warning("OpenCV not installed. Advanced preprocessing disabled.")

try:
    from pdf2image import convert_from_path
    PDF2IMAGE_AVAILABLE = True
except ImportError:
    PDF2IMAGE_AVAILABLE = False
    logger.warning("pdf2image not installed. PDF support disabled.")


# ══════════════════════════════════════════════════════════════
# PREDICTOR
# ══════════════════════════════════════════════════════════════
class QualityPredictor:
    """
    Cinnamon oil quality predictor.
    Uses calibrated Random Forest (cinnamon_model_enhanced.pkl).
    Falls back to rule-based grading if model or OCR unavailable.
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
        self.load_model()

    # ──────────────────────────────────────────────────────────
    # MODEL LOADING
    # ──────────────────────────────────────────────────────────
    def load_model(self):
        model_dir = os.path.dirname(__file__)

        for filename in ['cinnamon_model_enhanced.pkl', 'cinnamon_model.pkl']:
            path = os.path.join(model_dir, filename)
            if os.path.exists(path):
                try:
                    self.model = joblib.load(path)
                    logger.info(f"✅ Model loaded: {filename} ({type(self.model).__name__})")
                    break
                except Exception as e:
                    logger.error(f"Failed to load {filename}: {e}")

        if self.model is None:
            logger.warning("No model file found. Using rule-based grading.")

        enc_path = os.path.join(model_dir, 'label_encoder.pkl')
        if os.path.exists(enc_path):
            try:
                self.label_encoder = joblib.load(enc_path)
                logger.info(f"✅ Encoder loaded. Classes: {list(self.label_encoder.classes_)}")
            except Exception as e:
                logger.warning(f"Could not load label encoder: {e}")

    # ──────────────────────────────────────────────────────────
    # TESSERACT HEALTH CHECK
    # ──────────────────────────────────────────────────────────
    def _tesseract_ok(self):
        """Return True if tesseract is actually callable."""
        try:
            r = subprocess.run(
                [pytesseract.pytesseract.tesseract_cmd, '--version'],
                capture_output=True, timeout=5
            )
            return r.returncode == 0
        except Exception:
            return False

    # ──────────────────────────────────────────────────────────
    # IMAGE PREPROCESSING
    # ──────────────────────────────────────────────────────────
    def deep_clean_image(self, cv_image):
        if not CV2_AVAILABLE:
            return Image.fromarray(cv_image)
        try:
            h, w   = cv_image.shape[:2]
            cv_image = cv2.resize(cv_image, (w*2, h*2), interpolation=cv2.INTER_LANCZOS4)
            gray   = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY)
            thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]

            for kernel_size in [(50, 1), (1, 50)]:   # horizontal then vertical
                kernel = cv2.getStructuringElement(cv2.MORPH_RECT, kernel_size)
                lines  = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel, iterations=2)
                cnts   = cv2.findContours(lines, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                for c in (cnts[0] if len(cnts) == 2 else cnts[1]):
                    cv2.drawContours(thresh, [c], -1, (0, 0, 0), 3)

            result = cv2.erode(255 - thresh, np.ones((2, 2), np.uint8), iterations=1)
            return Image.fromarray(result)
        except Exception as e:
            logger.error(f"deep_clean_image: {e}")
            return Image.fromarray(cv_image)

    # ──────────────────────────────────────────────────────────
    # OCR EXTRACTION
    # ──────────────────────────────────────────────────────────
    def process_image_content(self, img, source_name):
        """Extract chemical percentages from an image using OCR."""

        # Guard: check tesseract before attempting OCR
        if not self._tesseract_ok():
            logger.error(
                "❌ Tesseract not available. Install it:\n"
                "   Mac:   brew install tesseract\n"
                "   Linux: sudo apt install tesseract-ocr"
            )
            return None

        try:
            if CV2_AVAILABLE:
                cv_img = np.array(img)
                if len(cv_img.shape) == 2:
                    cv_img = cv2.cvtColor(cv_img, cv2.COLOR_GRAY2BGR)
                elif cv_img.shape[2] == 3:
                    cv_img = cv2.cvtColor(cv_img, cv2.COLOR_RGB2BGR)
                cleaned = self.deep_clean_image(cv_img)
            else:
                cleaned = img

            enhanced = ImageEnhance.Contrast(cleaned).enhance(2.5)
            text     = pytesseract.image_to_string(enhanced, config='--oem 3 --psm 6')
            logger.info(f"OCR text ({source_name}):\n{text[:300]}")

            # Extract numbers like 87.42 or 87,42
            numbers  = re.findall(r"(\d{2})[\s.,](\d{2})", text)
            all_nums = [float(f"{n[0]}.{n[1]}") for n in numbers]
            logger.info(f"Parsed numbers: {all_nums}")

            eugenol_candidates = [n for n in all_nums if 60 <= n <= 98]
            if not eugenol_candidates:
                logger.warning(f"No Eugenol value (60–98) found in {source_name}")
                return None

            eugenol = max(eugenol_candidates)
            traces  = [n for n in all_nums if 0.1 <= n <= 5.0]
            logger.info(f"Eugenol={eugenol}%, traces={traces}")

            return {
                'Eugenol_Percentage':         eugenol,
                'Eugenyl_Acetate_Percentage': traces[0] if len(traces) > 0 else 0.54,
                'Linalool_Percentage':        traces[1] if len(traces) > 1 else 1.76,
                'Cinnamaldehyde_Percentage':  traces[2] if len(traces) > 2 else 0.78,
                'Safrole_Percentage':         traces[3] if len(traces) > 3 else 0.76,
            }

        except Exception as e:
            logger.error(f"process_image_content error ({source_name}): {e}")
            return None

    def extract_from_pdf(self, file_path):
        if not PDF2IMAGE_AVAILABLE:
            logger.warning("pdf2image unavailable.")
            return None
        try:
            pages = convert_from_path(file_path, 300)
            for i, page in enumerate(pages):
                result = self.process_image_content(page, f"page_{i+1}")
                if result:
                    return result
            return None
        except Exception as e:
            logger.error(f"extract_from_pdf: {e}")
            return None

    def extract_from_image(self, file_path):
        try:
            img = Image.open(file_path)
            if img.mode != 'RGB':
                img = img.convert('RGB')
            return self.process_image_content(img, file_path)
        except Exception as e:
            logger.error(f"extract_from_image: {e}")
            return None

    # ──────────────────────────────────────────────────────────
    # PUBLIC API
    # ──────────────────────────────────────────────────────────
    def predict_quality(self, file_path):
        """
        Main entry point.
        Returns: { grade, score, confidence, features }
        """
        logger.info(f"predict_quality: {file_path}")
        ext = os.path.splitext(file_path)[1].lower()

        if ext == '.pdf':
            features = self.extract_from_pdf(file_path)
        elif ext in ['.png', '.jpg', '.jpeg']:
            features = self.extract_from_image(file_path)
        else:
            logger.warning(f"Unsupported file type: {ext}")
            return self._default_prediction()

        if not features:
            return self._default_prediction()

        if self.model is not None:
            try:
                return self._ml_prediction(features)
            except Exception as e:
                logger.error(f"ML error: {e}. Falling back to rule-based.")
                return self._rule_based_grading(features)

        return self._rule_based_grading(features)

    # ──────────────────────────────────────────────────────────
    # PREDICTION STRATEGIES
    # ──────────────────────────────────────────────────────────
    def _ml_prediction(self, features):
        input_df = pd.DataFrame([[
            features.get('Eugenol_Percentage',         0),
            features.get('Eugenyl_Acetate_Percentage', 0.54),
            features.get('Linalool_Percentage',        1.76),
            features.get('Cinnamaldehyde_Percentage',  0.78),
            features.get('Safrole_Percentage',         0.76),
        ]], columns=self.feature_names)

        raw_pred = self.model.predict(input_df)[0]

        if self.label_encoder is not None:
            try:
                grade = str(self.label_encoder.inverse_transform([int(raw_pred)])[0])
            except Exception:
                grade = str(raw_pred)
        else:
            grade = str(raw_pred)

        confidence = 0.95
        if hasattr(self.model, 'predict_proba'):
            try:
                confidence = float(np.max(self.model.predict_proba(input_df)[0]))
            except Exception:
                pass

        score = round(float(features.get('Eugenol_Percentage', 0)), 2)
        logger.info(f"✅ ML → Grade={grade}, Score={score}, Conf={confidence:.4f}")
        return {
            'grade':      grade,
            'score':      score,
            'confidence': round(confidence, 4),
            'features':   features,
        }

    def _rule_based_grading(self, features):
        eugenol = features.get('Eugenol_Percentage', 0)
        if   eugenol >= 85: grade = 'A'
        elif eugenol >= 78: grade = 'B'
        elif eugenol >= 70: grade = 'C'
        else:               grade = 'D'
        logger.info(f"✅ Rule-based → Grade={grade}, Eugenol={eugenol}%")
        return {
            'grade':      grade,
            'score':      round(float(eugenol), 2),
            'confidence': 0.85,
            'features':   features,
        }

    def _default_prediction(self):
        return {
            'grade':      'C',
            'score':      75.0,
            'confidence': 0.3,
            'features':   {},
        }


# ══════════════════════════════════════════════════════════════
# SINGLETON
# ══════════════════════════════════════════════════════════════
_predictor = None

def get_predictor():
    global _predictor
    if _predictor is None:
        _predictor = QualityPredictor()
    return _predictor