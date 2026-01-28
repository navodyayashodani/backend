# tenders/ml_model/predictor.py

import joblib
import os
import numpy as np
import pandas as pd
from django.conf import settings
import pytesseract
from PIL import Image, ImageEnhance
import re
import logging

# Configure logging
logger = logging.getLogger(__name__)

# Configure tesseract path (adjust based on your system)
# For Mac with Homebrew

pytesseract.pytesseract.tesseract_cmd = "/opt/homebrew/bin/tesseract"
# For Ubuntu/Linux
# pytesseract.pytesseract.tesseract_cmd = "/usr/bin/tesseract"
# For Windows
# pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# Try to import cv2 (OpenCV) - optional but recommended
try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    logger.warning("OpenCV (cv2) not installed. Advanced image preprocessing disabled.")

# Try to import pdf2image
try:
    from pdf2image import convert_from_path
    PDF2IMAGE_AVAILABLE = True
except ImportError:
    PDF2IMAGE_AVAILABLE = False
    logger.warning("pdf2image not installed. PDF processing will be limited.")


class QualityPredictor:
    """
    ML Model for predicting cinnamon oil quality grade based on Eugenol content
    
    Features used:
    - Eugenol_Percentage (60-95%)
    - Eugenyl_Acetate_Percentage (0.1-2.5%)
    - Linalool_Percentage (1.0-5.0%)
    - Cinnamaldehyde_Percentage (0.5-3.5%)
    - Safrole_Percentage (0.1-2.5%)
    
    Grading System:
    - A: Eugenol >= 85%
    - B: Eugenol 78-85%
    - C: Eugenol 70-78%
    - D: Eugenol < 70%
    """
    
    def __init__(self):
        self.model = None
        self.feature_names = [
            'Eugenol_Percentage',
            'Eugenyl_Acetate_Percentage',
            'Linalool_Percentage',
            'Cinnamaldehyde_Percentage',
            'Safrole_Percentage'
        ]
        self.load_model()
    
    def load_model(self):
        """Load the trained ML model (joblib format)"""
        model_path = os.path.join(
            os.path.dirname(__file__),
            'cinnamon_model.pkl'
        )
        
        try:
            if os.path.exists(model_path):
                # Try joblib first (your model uses this)
                try:
                    self.model = joblib.load(model_path)
                    logger.info("✅ ML Model loaded successfully with joblib")
                except Exception as e1:
                    logger.warning(f"joblib load failed: {e1}, trying pickle...")
                    # Fallback to pickle
                    import pickle
                    with open(model_path, 'rb') as f:
                        self.model = pickle.load(f)
                    logger.info("✅ ML Model loaded successfully with pickle")
                
                logger.info(f"Model type: {type(self.model).__name__}")
            else:
                logger.warning(f"❌ Model file not found at {model_path}")
                self.model = None
        except Exception as e:
            logger.error(f"❌ Error loading model: {e}")
            self.model = None
    
    def deep_clean_image(self, cv_image):
        """
        Advanced image preprocessing to remove grid lines and enhance text
        Based on your Google Colab code
        """
        if not CV2_AVAILABLE:
            logger.warning("OpenCV not available, skipping advanced preprocessing")
            return Image.fromarray(cv_image)
        
        try:
            # STEP 1: RESIZE (Upscale for clarity)
            height, width = cv_image.shape[:2]
            cv_image = cv2.resize(cv_image, (width*2, height*2), interpolation=cv2.INTER_LANCZOS4)
            
            gray = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY)
            
            # STEP 2: REMOVE GRID LINES
            thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]

            # Horizontal lines removal
            horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (50, 1))
            detect_horizontal = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, horizontal_kernel, iterations=2)
            cnts = cv2.findContours(detect_horizontal, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            cnts = cnts[0] if len(cnts) == 2 else cnts[1]
            for c in cnts:
                cv2.drawContours(thresh, [c], -1, (0,0,0), 3)

            # Vertical lines removal
            vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 50))
            detect_vertical = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, vertical_kernel, iterations=2)
            cnts = cv2.findContours(detect_vertical, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            cnts = cnts[0] if len(cnts) == 2 else cnts[1]
            for c in cnts:
                cv2.drawContours(thresh, [c], -1, (0,0,0), 3)

            # STEP 3: DILATE TEXT
            result = 255 - thresh
            kernel = np.ones((2,2), np.uint8)
            result = cv2.erode(result, kernel, iterations=1)
            
            return Image.fromarray(result)
        except Exception as e:
            logger.error(f"Error in deep_clean_image: {e}")
            return Image.fromarray(cv_image)
    
    def process_image_content(self, img_to_ocr, source_name):
        """
        Extract chemical composition from image using OCR
        Based on your Google Colab code
        """
        try:
            # Convert PIL to OpenCV format
            if CV2_AVAILABLE:
                open_cv_image = np.array(img_to_ocr)
                if len(open_cv_image.shape) == 2:  # Grayscale
                    open_cv_image = cv2.cvtColor(open_cv_image, cv2.COLOR_GRAY2BGR)
                elif open_cv_image.shape[2] == 3:  # RGB
                    open_cv_image = cv2.cvtColor(open_cv_image, cv2.COLOR_RGB2BGR)
                
                # Clean and Upscale
                cleaned_img = self.deep_clean_image(open_cv_image)
            else:
                cleaned_img = img_to_ocr
            
            # Enhance contrast
            enhanced_img = ImageEnhance.Contrast(cleaned_img).enhance(2.5)
            
            # OCR with Tesseract
            text = pytesseract.image_to_string(enhanced_img, config='--oem 3 --psm 6')
            
            logger.info(f"OCR Text extracted from {source_name}:")
            logger.info(text[:200] + "..." if len(text) > 200 else text)
            
            # Extraction Logic (from your code)
            # Find numbers in format XX.XX or XX,XX
            numbers = re.findall(r"(\d{2})[\s.,](\d{2})", text)
            all_nums = [float(f"{n[0]}.{n[1]}") for n in numbers]
            
            logger.info(f"Extracted numbers: {all_nums}")
            
            # Find Eugenol (main component, typically 60-98%)
            eugenol_candidates = [n for n in all_nums if 60 <= n <= 98]
            
            if eugenol_candidates:
                eugenol = max(eugenol_candidates)
                
                # Find trace elements (0.1-5%)
                traces = [n for n in all_nums if 0.1 <= n <= 5.0]
                
                logger.info(f"Eugenol found: {eugenol}%")
                logger.info(f"Trace elements: {traces}")
                
                return {
                    'Eugenol_Percentage': eugenol,
                    'Eugenyl_Acetate_Percentage': traces[0] if len(traces) > 0 else 0.54,
                    'Linalool_Percentage': traces[1] if len(traces) > 1 else 1.76,
                    'Cinnamaldehyde_Percentage': traces[2] if len(traces) > 2 else 0.78,
                    'Safrole_Percentage': traces[3] if len(traces) > 3 else 0.76
                }
            else:
                logger.warning(f"No valid Eugenol value found in {source_name}")
                return None
                
        except Exception as e:
            logger.error(f"Error processing image content from {source_name}: {e}")
            return None
    
    def extract_from_pdf(self, file_path):
        """Extract features from PDF using pdf2image"""
        if not PDF2IMAGE_AVAILABLE:
            logger.warning("pdf2image not available, cannot process PDF")
            return None
        
        try:
            # Convert PDF to images (300 DPI for high quality)
            pages = convert_from_path(file_path, 300)
            
            logger.info(f"PDF has {len(pages)} page(s)")
            
            # Process first page (or all pages if needed)
            for i, page in enumerate(pages):
                result = self.process_image_content(page, f"{file_path}_page_{i+1}")
                if result:
                    logger.info(f"✅ Successfully extracted from page {i+1}")
                    return result
            
            logger.warning("No features extracted from any PDF page")
            return None
            
        except Exception as e:
            logger.error(f"Error processing PDF: {e}")
            return None
    
    def extract_from_image(self, file_path):
        """Extract features from image file"""
        try:
            img = Image.open(file_path)
            
            # Convert to RGB if needed
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            return self.process_image_content(img, file_path)
            
        except Exception as e:
            logger.error(f"Error processing image: {e}")
            return None
    
    def predict_quality(self, file_path):
        """
        Predict quality grade from uploaded report
        
        Args:
            file_path: Path to the uploaded file (PDF or Image)
            
        Returns:
            dict: {'grade': 'A', 'score': 85.5, 'confidence': 0.95}
        """
        logger.info(f"🔍 Predicting quality for: {file_path}")
        
        # Determine file type
        file_ext = os.path.splitext(file_path)[1].lower()
        
        # Extract features based on file type
        if file_ext == '.pdf':
            features = self.extract_from_pdf(file_path)
        elif file_ext in ['.png', '.jpg', '.jpeg']:
            features = self.extract_from_image(file_path)
        else:
            logger.warning(f"Unsupported file type: {file_ext}")
            return self._default_prediction()
        
        if not features:
            logger.warning("Could not extract features from file")
            return self._default_prediction()
        
        # Use ML model if available
        if self.model is not None:
            try:
                return self._ml_prediction(features)
            except Exception as e:
                logger.error(f"ML prediction failed: {e}")
                return self._rule_based_grading(features)
        else:
            logger.info("Model not available, using rule-based grading")
            return self._rule_based_grading(features)
    
    def _ml_prediction(self, features):
        """Use ML model for prediction"""
        try:
            # Create DataFrame with features in correct order
            input_df = pd.DataFrame([[
                features.get('Eugenol_Percentage', 0),
                features.get('Eugenyl_Acetate_Percentage', 0.54),
                features.get('Linalool_Percentage', 1.76),
                features.get('Cinnamaldehyde_Percentage', 0.78),
                features.get('Safrole_Percentage', 0.76)
            ]], columns=self.feature_names)
            
            logger.info(f"Input features for prediction:")
            logger.info(input_df.to_string())
            
            # Predict
            grade = self.model.predict(input_df)[0]
            
            # Get prediction probability if available
            confidence = 0.95
            if hasattr(self.model, 'predict_proba'):
                try:
                    probabilities = self.model.predict_proba(input_df)[0]
                    confidence = float(max(probabilities))
                except:
                    pass
            
            # Convert grade to score
            eugenol = features.get('Eugenol_Percentage', 0)
            score = eugenol  # Use Eugenol as score
            
            logger.info(f"✅ ML Prediction: Grade={grade}, Score={score}, Confidence={confidence}")
            
            return {
                'grade': str(grade),
                'score': round(score, 2),
                'confidence': round(confidence, 2)
            }
            
        except Exception as e:
            logger.error(f"Error in ML prediction: {e}")
            raise
    
    def _rule_based_grading(self, features):
        """
        Rule-based grading based on Eugenol percentage
        Matches your training logic:
        - A: Eugenol >= 85%
        - B: Eugenol 78-85%
        - C: Eugenol 70-78%
        - D: Eugenol < 70%
        """
        eugenol = features.get('Eugenol_Percentage', 0)
        
        if eugenol >= 85:
            grade = 'A'
        elif eugenol >= 78:
            grade = 'B'
        elif eugenol >= 70:
            grade = 'C'
        else:
            grade = 'D'
        
        logger.info(f"✅ Rule-based Prediction: Grade={grade}, Eugenol={eugenol}%")
        
        return {
            'grade': grade,
            'score': round(eugenol, 2),
            'confidence': 0.85
        }
    
    def _default_prediction(self):
        """Return default prediction when file can't be processed"""
        return {
            'grade': 'C',
            'score': 75.0,
            'confidence': 0.3
        }


# Singleton instance
_predictor = None

def get_predictor():
    """Get or create predictor instance"""
    global _predictor
    if _predictor is None:
        _predictor = QualityPredictor()
    return _predictor