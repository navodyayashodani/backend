# tenders/serializers.py

from rest_framework import serializers
from .models import Tender, TenderBid
from accounts.serializers import UserSerializer
from .ml_model import get_predictor
from django.utils import timezone
import tempfile
import os
import logging

logger = logging.getLogger(__name__)


class TenderSerializer(serializers.ModelSerializer):
    manufacturer_details = UserSerializer(source='manufacturer', read_only=True)
    bid_count            = serializers.SerializerMethodField()
    is_active            = serializers.BooleanField(read_only=True)
    display_status       = serializers.SerializerMethodField()

    class Meta:
        model  = Tender
        fields = [
            'id', 'tender_number', 'manufacturer', 'manufacturer_details',
            'tender_title', 'oil_type', 'quantity', 'quality_grade',
            'quality_score', 'tender_description', 'report_file',
            'start_date', 'end_date', 'status', 'display_status',
            'created_at', 'updated_at', 'bid_count', 'is_active'
        ]
        read_only_fields = [
            'id', 'tender_number', 'manufacturer',
            'quality_grade', 'quality_score',
            'created_at', 'updated_at'
        ]

    def get_bid_count(self, obj):
        return obj.bids.count()

    def get_display_status(self, obj):
        today      = timezone.now().date()
        is_expired = obj.end_date < today or obj.status == 'closed'

        if not is_expired:
            return ['active']

        tags       = ['closed']
        has_winner = obj.bids.filter(status='accepted').exists()
        has_bids   = obj.bids.exists()

        if has_winner:
            tags.append('awarded')
        elif not has_bids:
            tags.append('no bids')

        return tags

    def validate(self, attrs):
        if attrs.get('end_date') and attrs.get('start_date'):
            if attrs['end_date'] <= attrs['start_date']:
                raise serializers.ValidationError({
                    'end_date': 'End date must be after start date.'
                })
        if attrs.get('quantity') and attrs['quantity'] <= 0:
            raise serializers.ValidationError({
                'quantity': 'Quantity must be greater than zero.'
            })
        return attrs

    def validate_report_file(self, value):
        max_size = 10 * 1024 * 1024  # 10 MB
        if value.size > max_size:
            raise serializers.ValidationError('File size cannot exceed 10MB.')
        allowed_extensions = ['pdf', 'doc', 'docx', 'xls', 'xlsx', 'png', 'jpg', 'jpeg']
        ext = value.name.split('.')[-1].lower()
        if ext not in allowed_extensions:
            raise serializers.ValidationError(f'File type .{ext} not allowed.')
        return value

    def create(self, validated_data):
        # Grab the file object BEFORE super().create() moves it to storage
        report_file = validated_data.get('report_file')

        # Save the tender record (Django writes file to media storage here)
        tender = super().create(validated_data)

        # Run ML prediction via a local temp file copy.
        # We do NOT use tender.report_file.path because Railway's ephemeral
        # filesystem raises NotImplementedError on cloud storage .path() calls.
        if report_file:
            ext      = report_file.name.split('.')[-1].lower()
            tmp_path = None
            try:
                report_file.seek(0)
                with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{ext}') as tmp:
                    for chunk in report_file.chunks():
                        tmp.write(chunk)
                    tmp_path = tmp.name

                predictor            = get_predictor()
                result               = predictor.predict_quality(tmp_path)
                tender.quality_grade = result['grade']
                tender.quality_score = min(float(result['score']), 99.99)
                tender.save(update_fields=['quality_grade', 'quality_score'])
                logger.info(
                    f"ML grade for {tender.tender_number}: "
                    f"Grade={result['grade']} Score={result['score']}"
                )

            except Exception as e:
                # Do NOT crash — tender is saved, grade stays null
                logger.error(f"ML prediction failed for {tender.tender_number}: {e}")

            finally:
                if tmp_path and os.path.exists(tmp_path):
                    os.remove(tmp_path)

        return tender


class TenderCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Tender
        fields = [
            'tender_title', 'oil_type', 'quantity',
            'tender_description', 'report_file',
            'start_date', 'end_date'
        ]

    def validate(self, attrs):
        if attrs['end_date'] <= attrs['start_date']:
            raise serializers.ValidationError({
                'end_date': 'End date must be after start date.'
            })
        if attrs['quantity'] <= 0:
            raise serializers.ValidationError({
                'quantity': 'Quantity must be greater than zero.'
            })
        return attrs


class TenderBidSerializer(serializers.ModelSerializer):
    buyer_details  = UserSerializer(source='buyer',  read_only=True)
    tender_details = TenderSerializer(source='tender', read_only=True)

    class Meta:
        model  = TenderBid
        fields = [
            'id', 'tender', 'tender_details',
            'buyer', 'buyer_details',
            'bid_amount', 'message', 'status',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'buyer', 'status',
            'created_at', 'updated_at'
        ]

    def validate_bid_amount(self, value):
        if value <= 0:
            raise serializers.ValidationError('Bid amount must be greater than zero.')
        return value