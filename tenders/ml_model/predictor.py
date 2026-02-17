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
import json

logger = logging.getLogger(__name__)

# Configure tesseract
pytesseract.pytesseract.tesseract_cmd = "/opt/homebrew/bin/tesseract"
# pytesseract.pytesseract.tesseract_cmd = "/usr/bin/tesseract"  # Ubuntu
# pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"  # Windows

try:
    import cv2
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    logger.warning("OpenCV (cv2) not installed. Advanced image preprocessing disabled.")

try:
    from pdf2image import convert_from_path
    PDF2IMAGE_AVAILABLE = True
except ImportError:
    PDF2IMAGE_AVAILABLE = False
    logger.warning("pdf2image not installed. PDF processing will be limited.")


class QualityPredictor:
    """
    Enhanced ML Model for predicting cinnamon oil quality grade
    Uses the new cinnamon_model_enhanced.pkl with label encoder
    """
    
    def __init__(self):
        self.model = None
        self.label_encoder = None
        self.metadata = None
        self.feature_names = [
            'Eugenol_Percentage',
            'Eugenyl_Acetate_Percentage',
            'Linalool_Percentage',
            'Cinnamaldehyde_Percentage',
            'Safrole_Percentage'
        ]
        self.load_model()
    
    def load_model(self):
        """Load the trained ML model, label encoder, and metadata"""
        model_dir = os.path.join(os.path.dirname(__file__))
        
        model_path = os.path.join(model_dir, 'cinnamon_model_enhanced.pkl')
        encoder_path = os.path.join(model_dir, 'label_encoder.pkl')
        metadata_path = os.path.join(model_dir, 'model_metadata.json')
        
        try:
            # Load model
            if os.path.exists(model_path):
                self.model = joblib.load(model_path)
                logger.info("✅ Enhanced ML Model loaded successfully")
                logger.info(f"Model type: {type(self.model).__name__}")
            else:
                logger.warning(f"❌ Model file not found at {model_path}")
                self.model = None
            
            # Load label encoder
            if os.path.exists(encoder_path):
                self.label_encoder = joblib.load(encoder_path)
                logger.info(f"✅ Label encoder loaded: {self.label_encoder.classes_}")
            else:
                logger.warning(f"❌ Label encoder not found at {encoder_path}")
                self.label_encoder = None
            
            # Load metadata
            if os.path.exists(metadata_path):
                with open(metadata_path, 'r') as f:
                    self.metadata = json.load(f)
                logger.info(f"✅ Metadata loaded - Model: {self.metadata.get('model_type')}")
                logger.info(f"   Test Accuracy: {self.metadata.get('performance', {}).get('test_accuracy', 'N/A')}")
            else:
                logger.warning(f"⚠️ Metadata not found at {metadata_path}")
                
        except Exception as e:
            logger.error(f"❌ Error loading model: {e}")
            self.model = None
    
    def deep_clean_image(self, cv_image):
        """Advanced image preprocessing to remove grid lines and enhance text"""
        if not CV2_AVAILABLE:
            return Image.fromarray(cv_image)
        
        try:
            height, width = cv_image.shape[:2]
            cv_image = cv2.resize(cv_image, (width*2, height*2), 
                                 interpolation=cv2.INTER_LANCZOS4)
            
            gray = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY)
            thresh = cv2.threshold(gray, 0, 255, 
                                  cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]

            # Remove horizontal lines
            horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (50, 1))
            detect_horizontal = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, 
                                                horizontal_kernel, iterations=2)
            cnts = cv2.findContours(detect_horizontal, cv2.RETR_EXTERNAL, 
                                   cv2.CHAIN_APPROX_SIMPLE)
            cnts = cnts[0] if len(cnts) == 2 else cnts[1]
            for c in cnts:
                cv2.drawContours(thresh, [c], -1, (0,0,0), 3)

            # Remove vertical lines
            vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 50))
            detect_vertical = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, 
                                              vertical_kernel, iterations=2)
            cnts = cv2.findContours(detect_vertical, cv2.RETR_EXTERNAL, 
                                   cv2.CHAIN_APPROX_SIMPLE)
            cnts = cnts[0] if len(cnts) == 2 else cnts[1]
            for c in cnts:
                cv2.drawContours(thresh, [c], -1, (0,0,0), 3)

            result = 255 - thresh
            kernel = np.ones((2,2), np.uint8)
            result = cv2.erode(result, kernel, iterations=1)
            
            return Image.fromarray(result)
        except Exception as e:
            logger.error(f"Error in deep_clean_image: {e}")
            return Image.fromarray(cv_image)
    
    def process_image_content(self, img_to_ocr, source_name):
        """Extract chemical composition from image using OCR"""
        try:
            # Convert PIL to OpenCV format
            if CV2_AVAILABLE:
                open_cv_image = np.array(img_to_ocr)
                if len(open_cv_image.shape) == 2:
                    open_cv_image = cv2.cvtColor(open_cv_image, cv2.COLOR_GRAY2BGR)
                elif open_cv_image.shape[2] == 4:
                    open_cv_image = cv2.cvtColor(open_cv_image, cv2.COLOR_RGBA2BGR)
                elif open_cv_image.shape[2] == 3:
                    open_cv_image = cv2.cvtColor(open_cv_image, cv2.COLOR_RGB2BGR)
                
                cleaned_img = self.deep_clean_image(open_cv_image)
            else:
                cleaned_img = img_to_ocr
            
            # Enhance contrast
            enhanced_img = ImageEnhance.Contrast(cleaned_img).enhance(2.5)
            
            # OCR
            text = pytesseract.image_to_string(enhanced_img, config='--oem 3 --psm 6')
            logger.info(f"OCR Text from {source_name}: {text[:200]}...")
            
            # Extract numbers
            numbers = re.findall(r"(\d{2})[\s.,](\d{2})", text)
            all_nums = [float(f"{n[0]}.{n[1]}") for n in numbers]
            
            # Find Eugenol (60-98%)
            eugenol_candidates = [n for n in all_nums if 60 <= n <= 98]
            
            if eugenol_candidates:
                eugenol = max(eugenol_candidates)
                traces = [n for n in all_nums if 0.1 <= n <= 5.0]
                
                logger.info(f"✅ Eugenol: {eugenol}%, Traces: {traces}")
                
                return {
                    'Eugenol_Percentage': eugenol,
                    'Eugenyl_Acetate_Percentage': traces[0] if len(traces) > 0 else 1.31,
                    'Linalool_Percentage': traces[1] if len(traces) > 1 else 3.05,
                    'Cinnamaldehyde_Percentage': traces[2] if len(traces) > 2 else 2.00,
                    'Safrole_Percentage': traces[3] if len(traces) > 3 else 1.30
                }
            else:
                logger.warning(f"No valid Eugenol found in {source_name}")
                return None
                
        except Exception as e:
            logger.error(f"Error processing {source_name}: {e}")
            return None
    
    def extract_from_pdf(self, file_path):
        """Extract features from PDF"""
        if not PDF2IMAGE_AVAILABLE:
            logger.warning("pdf2image not available")
            return None
        
        try:
            pages = convert_from_path(file_path, 300)
            logger.info(f"PDF has {len(pages)} page(s)")
            
            for i, page in enumerate(pages):
                result = self.process_image_content(page, f"{file_path}_page_{i+1}")
                if result:
                    return result
            
            return None
        except Exception as e:
            logger.error(f"Error processing PDF: {e}")
            return None
    
    def extract_from_image(self, file_path):
        """Extract features from image file"""
        try:
            img = Image.open(file_path)
            if img.mode != 'RGB':
                img = img.convert('RGB')
            return self.process_image_content(img, file_path)
        except Exception as e:
            logger.error(f"Error processing image: {e}")
            return None
    
    def predict_quality(self, file_path):
        """
        Predict quality grade from uploaded report
        
        Returns:
            dict: {'grade': 'A', 'score': 85.5, 'confidence': 0.95}
        """
        logger.info(f"🔍 Predicting quality for: {file_path}")
        
        # Determine file type
        file_ext = os.path.splitext(file_path)[1].lower()
        
        # Extract features
        if file_ext == '.pdf':
            features = self.extract_from_pdf(file_path)
        elif file_ext in ['.png', '.jpg', '.jpeg']:
            features = self.extract_from_image(file_path)
        else:
            logger.warning(f"Unsupported file type: {file_ext}")
            return self._default_prediction()
        
        if not features:
            logger.warning("Could not extract features")
            return self._default_prediction()
        
        # Use ML model if available
        if self.model is not None and self.label_encoder is not None:
            try:
                return self._ml_prediction(features)
            except Exception as e:
                logger.error(f"ML prediction failed: {e}")
                return self._rule_based_grading(features)
        else:
            logger.info("Model not available, using rule-based grading")
            return self._rule_based_grading(features)
    
    def _ml_prediction(self, features):
        """Use enhanced ML model for prediction"""
        try:
            # Create DataFrame
            input_df = pd.DataFrame([[
                features.get('Eugenol_Percentage', 0),
                features.get('Eugenyl_Acetate_Percentage', 1.31),
                features.get('Linalool_Percentage', 3.05),
                features.get('Cinnamaldehyde_Percentage', 2.00),
                features.get('Safrole_Percentage', 1.30)
            ]], columns=self.feature_names)
            
            logger.info(f"Input features:\n{input_df.to_string()}")
            
            # Predict
            prediction = self.model.predict(input_df)[0]
            proba = self.model.predict_proba(input_df)[0]
            
            # Decode grade
            grade = self.label_encoder.inverse_transform([prediction])[0]
            confidence = float(np.max(proba))
            
            # Score is Eugenol percentage
            score = features.get('Eugenol_Percentage', 0)
            
            logger.info(f"✅ ML Prediction: Grade={grade}, Score={score}, Confidence={confidence*100:.1f}%")
            
            return {
                'grade': str(grade),
                'score': round(score, 2),
                'confidence': round(confidence, 2)
            }
            
        except Exception as e:
            logger.error(f"Error in ML prediction: {e}")
            raise
    
    def _rule_based_grading(self, features):
        """Fallback rule-based grading"""
        eugenol = features.get('Eugenol_Percentage', 0)
        
        if eugenol >= 75:
            grade = 'A'
        elif eugenol >= 60:
            grade = 'B'
        else:
            grade = 'C'
        
        logger.info(f"✅ Rule-based: Grade={grade}, Eugenol={eugenol}%")
        
        return {
            'grade': grade,
            'score': round(eugenol, 2),
            'confidence': 0.85
        }
    
    def _default_prediction(self):
        """Default prediction when file can't be processed"""
        return {
            'grade': 'C',
            'score': 70.0,
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