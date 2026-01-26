# tenders/ml_model/predictor.py

import pickle
import os
import numpy as np
from django.conf import settings
import PyPDF2
import docx
from PIL import Image
import pytesseract
import pandas as pd

import pytesseract

pytesseract.pytesseract.tesseract_cmd = "/opt/homebrew/bin/tesseract"


class QualityPredictor:
    """
    ML Model for predicting cinnamon oil quality grade
    """
    
    def __init__(self):
        self.model = None
        self.load_model()
    
    def load_model(self):
        """Load the trained ML model"""
        model_path = os.path.join(
            os.path.dirname(__file__),
            'model.pkl'
        )
        
        try:
            if os.path.exists(model_path):
                with open(model_path, 'rb') as f:
                    self.model = pickle.load(f)
                print("ML Model loaded successfully")
            else:
                print(f"Model file not found at {model_path}")
                self.model = None
        except Exception as e:
            print(f"Error loading model: {e}")
            self.model = None
    
    def extract_text_from_pdf(self, file_path):
        """Extract text from PDF file"""
        try:
            with open(file_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                text = ""
                for page in pdf_reader.pages:
                    text += page.extract_text()
                return text
        except Exception as e:
            print(f"Error extracting PDF text: {e}")
            return ""
    
    def extract_text_from_docx(self, file_path):
        """Extract text from DOCX file"""
        try:
            doc = docx.Document(file_path)
            text = "\n".join([para.text for para in doc.paragraphs])
            return text
        except Exception as e:
            print(f"Error extracting DOCX text: {e}")
            return ""
    
    def extract_text_from_image(self, file_path):
        """Extract text from image using OCR"""
        try:
            image = Image.open(file_path)
            text = pytesseract.image_to_string(image)
            return text
        except Exception as e:
            print(f"Error extracting image text: {e}")
            return ""
    
    def extract_features_from_text(self, text):
        """
        Extract numerical features from report text
        This is a placeholder - adjust based on your actual model requirements
        """
        # Example feature extraction
        features = {}
        
        # Look for common quality indicators in text
        text_lower = text.lower()
        
        # Example features (adjust based on your actual model)
        features['density'] = self._extract_value(text, ['density', 'specific gravity'])
        features['viscosity'] = self._extract_value(text, ['viscosity'])
        features['purity'] = self._extract_value(text, ['purity', 'pure'])
        features['cinnamaldehyde'] = self._extract_value(text, ['cinnamaldehyde', 'aldehyde'])
        features['eugenol'] = self._extract_value(text, ['eugenol'])
        
        return features
    
    def _extract_value(self, text, keywords):
        """Extract numerical value associated with keywords"""
        # Simple extraction - look for number after keyword
        import re
        for keyword in keywords:
            pattern = rf'{keyword}[:\s]+(\d+\.?\d*)'
            match = re.search(pattern, text.lower())
            if match:
                return float(match.group(1))
        return 0.0
    
    def predict_quality(self, file_path):
        """
        Predict quality grade from uploaded report
        
        Returns:
            dict: {'grade': 'A+', 'score': 95.5, 'confidence': 0.92}
        """
        # Extract text based on file type
        file_ext = os.path.splitext(file_path)[1].lower()
        
        if file_ext == '.pdf':
            text = self.extract_text_from_pdf(file_path)
        elif file_ext in ['.doc', '.docx']:
            text = self.extract_text_from_docx(file_path)
        elif file_ext in ['.png', '.jpg', '.jpeg']:
            text = self.extract_text_from_image(file_path)
        else:
            return {'grade': 'N/A', 'score': 0, 'confidence': 0}
        
        # Extract features from text
        features = self.extract_features_from_text(text)
        
        # If model is loaded, use it for prediction
        if self.model is not None:
            try:
                # Convert features to format expected by your model
                # Adjust this based on your actual model's input format
                feature_array = np.array([list(features.values())])
                
                # Make prediction
                prediction = self.model.predict(feature_array)[0]
                score = float(prediction)
                
                # Convert score to grade
                grade = self._score_to_grade(score)
                
                return {
                    'grade': grade,
                    'score': round(score, 2),
                    'confidence': 0.85  # Placeholder
                }
            except Exception as e:
                print(f"Prediction error: {e}")
                # Fall back to simple rule-based grading
                return self._simple_grading(features)
        else:
            # Use simple rule-based grading if model not available
            return self._simple_grading(features)
    
    def _simple_grading(self, features):
        """
        Simple rule-based grading as fallback
        Adjust thresholds based on your requirements
        """
        # Calculate average of available features
        values = [v for v in features.values() if v > 0]
        if not values:
            return {'grade': 'C', 'score': 50.0, 'confidence': 0.5}
        
        avg_score = sum(values) / len(values)
        
        # Normalize to 0-100 scale (adjust as needed)
        score = min(avg_score, 100)
        grade = self._score_to_grade(score)
        
        return {
            'grade': grade,
            'score': round(score, 2),
            'confidence': 0.7
        }
    
    def _score_to_grade(self, score):
        """Convert numerical score to letter grade"""
        if score >= 95:
            return 'A+'
        elif score >= 90:
            return 'A'
        elif score >= 85:
            return 'A-'
        elif score >= 80:
            return 'B+'
        elif score >= 75:
            return 'B'
        elif score >= 70:
            return 'B-'
        elif score >= 65:
            return 'C+'
        elif score >= 60:
            return 'C'
        else:
            return 'C-'


# Singleton instance
_predictor = None

def get_predictor():
    """Get or create predictor instance"""
    global _predictor
    if _predictor is None:
        _predictor = QualityPredictor()
    return _predictor