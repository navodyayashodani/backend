FROM python:3.9-slim

RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    poppler-utils \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN python manage.py collectstatic --no-input

# ── Diagnostic: test that all modules import cleanly at build time ──────────
# This will FAIL THE BUILD with a clear error message if any module has a
# syntax error, bad import, or broken regex — instead of silently crashing
# at runtime on Railway.
RUN python -c "
import django, os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
django.setup()
print('Django setup: OK')

from tenders.ml_model.predictor import get_predictor
p = get_predictor()
print('Predictor import: OK')
print('Model loaded:', p.model is not None)
print('Label encoder:', p.label_encoder is not None)

from tenders.serializers import TenderSerializer
print('TenderSerializer: OK')

from tenders.views import TenderListCreateView
print('TenderListCreateView: OK')

print('ALL IMPORTS OK')
"

EXPOSE 8000

CMD python manage.py migrate && gunicorn backend.wsgi:application \
    --bind 0.0.0.0:$PORT \
    --workers 2 \
    --timeout 120 \
    --log-level debug \
    --capture-output \
    --enable-stdio-inheritance