import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')

import django
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