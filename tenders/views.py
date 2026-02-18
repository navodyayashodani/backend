# tenders/views.py

from rest_framework import status, generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.utils import timezone
from django.db.models import Q
from .models import Tender, TenderBid
from .serializers import (
    TenderSerializer, TenderCreateSerializer, TenderBidSerializer
)
from .ml_model import get_predictor


class TenderListCreateView(generics.ListCreateAPIView):
    """
    List all tenders or create a new tender.

    GET  → manufacturers see:
             • ALL of their own tenders (any status)
             • Other manufacturers' tenders only when:
               - end_date has passed  (bidding period over)  OR
               - status == 'closed'   (winner already selected)
           buyers see everything.

    POST → manufacturers only.
    """
    serializer_class   = TenderSerializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes     = [MultiPartParser, FormParser]

    def get_queryset(self):
        user = self.request.user

        if user.role == 'manufacturer':
            today = timezone.now().date()
            return (
                Tender.objects
                # Own tenders — always visible
                .filter(manufacturer=user)
                |
                # Other manufacturers' tenders — only after closing date or if closed
                Tender.objects
                .exclude(manufacturer=user)
                .filter(Q(end_date__lt=today) | Q(status='closed'))
            ).distinct().order_by('-created_at')

        # Buyers (and any other role) see everything
        return Tender.objects.all().order_by('-created_at')

    def perform_create(self, serializer):
        if self.request.user.role != 'manufacturer':
            raise permissions.PermissionDenied("Only manufacturers can create tenders.")

        tender = serializer.save(manufacturer=self.request.user)

        # ── ML prediction on uploaded report ──
        if tender.report_file:
            try:
                predictor = get_predictor()
                result    = predictor.predict_quality(tender.report_file.path)

                tender.quality_grade = result['grade']
                tender.quality_score = min(float(result['score']), 99.99)
                tender.save()
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Quality prediction error: {e}")


class TenderDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, update or delete a tender."""
    serializer_class   = TenderSerializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes     = [MultiPartParser, FormParser]

    def get_queryset(self):
        user = self.request.user
        if user.role == 'manufacturer':
            # Can only edit/delete own tenders
            return Tender.objects.filter(manufacturer=user)
        return Tender.objects.all()


class NextTenderNumberView(APIView):
    """Return the next auto-generated tender number."""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        last_tender = Tender.objects.all().order_by('-id').first()
        if last_tender and last_tender.tender_number:
            try:
                last_number = int(last_tender.tender_number.split('-')[1])
                next_number = last_number + 1
            except (IndexError, ValueError):
                next_number = 1
        else:
            next_number = 1

        return Response({'next_tender_number': f"TND-{next_number:03d}"})


class PredictQualityView(APIView):
    """
    Preview quality prediction before creating a tender.
    POST a file → returns grade, score, confidence, and extracted features.
    """
    permission_classes = [permissions.IsAuthenticated]
    parser_classes     = [MultiPartParser, FormParser]

    def post(self, request):
        if 'file' not in request.FILES:
            return Response(
                {'error': 'No file provided.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        uploaded_file = request.FILES['file']

        # Validate extension
        allowed_extensions = ['pdf', 'doc', 'docx', 'xls', 'xlsx', 'png', 'jpg', 'jpeg']
        ext = uploaded_file.name.split('.')[-1].lower()
        if ext not in allowed_extensions:
            return Response(
                {'error': f'File type .{ext} not allowed. Allowed: {", ".join(allowed_extensions)}'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Validate size (max 10 MB)
        if uploaded_file.size > 10 * 1024 * 1024:
            return Response(
                {'error': 'File size cannot exceed 10MB.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        import tempfile, os
        with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{ext}') as tmp:
            for chunk in uploaded_file.chunks():
                tmp.write(chunk)
            temp_path = tmp.name

        try:
            predictor = get_predictor()
            result    = predictor.predict_quality(temp_path)

            return Response({
                'quality_grade': result['grade'],
                'quality_score': result['score'],
                'confidence':    result.get('confidence', 0),
                'features':      result.get('features', {}),
                'message': (
                    f"Quality Grade: {result['grade']} "
                    f"(Score: {result['score']}/100, "
                    f"Confidence: {result.get('confidence', 0)*100:.1f}%)"
                )
            })

        except Exception as e:
            return Response(
                {'error': f'Error analysing file: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)


class TenderBidListCreateView(generics.ListCreateAPIView):
    """List bids or create a new bid."""
    serializer_class   = TenderBidSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role == 'manufacturer':
            return TenderBid.objects.filter(tender__manufacturer=user)
        return TenderBid.objects.filter(buyer=user)

    def perform_create(self, serializer):
        user = self.request.user
        if user.role != 'buyer':
            raise permissions.PermissionDenied("Only buyers can place bids.")

        tender = serializer.validated_data.get('tender')
        if not tender:
            raise permissions.PermissionDenied("Tender is required to place a bid.")

        if TenderBid.objects.filter(buyer=user, tender=tender).exists():
            raise permissions.PermissionDenied("You already placed a bid on this tender.")

        serializer.save(buyer=user)


class TenderBidDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, update or delete a bid."""
    serializer_class   = TenderBidSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if user.role == 'buyer':
            return TenderBid.objects.filter(buyer=user)
        elif user.role == 'manufacturer':
            return TenderBid.objects.filter(tender__manufacturer=user)
        return TenderBid.objects.none()

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        user       = request.user
        bid        = self.get_object()
        new_status = request.data.get('status')

        if new_status and new_status != bid.status:
            if user.role != 'manufacturer':
                return Response(
                    {'error': 'Only manufacturers can update bid status.'},
                    status=status.HTTP_403_FORBIDDEN
                )

        # ✅ BUYER UPDATE LOGIC
        if user.role == 'buyer':
            # Buyers cannot change bid status
            if new_status:
                return Response(
                    {'error': 'Buyers cannot change bid status.'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # Can only update pending bids
            if bid.status != 'pending':
                return Response(
                    {'error': f'Cannot update a {bid.status} bid.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # ✅ FIX: Check if tender is still open
            today = timezone.now().date()
            if bid.tender.end_date < today or bid.tender.status == 'closed':
                return Response(
                    {'error': 'Cannot update bid. Tender has closed.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Only allow updating bid_amount and message
            allowed_fields = {'bid_amount', 'message'}
            if not set(request.data.keys()).issubset(allowed_fields):
                return Response(
                    {'error': f'Buyers can only update: {", ".join(allowed_fields)}'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            return super().update(request, *args, **kwargs)

        # ✅ MANUFACTURER UPDATE LOGIC (accepting/rejecting bids)
        if new_status == 'accepted':
            if bid.tender.end_date > timezone.now().date():
                return Response(
                    {'error': 'Cannot accept bids before tender closing date.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            if TenderBid.objects.filter(
                tender=bid.tender, status='accepted'
            ).exclude(id=bid.id).exists():
                return Response(
                    {'error': 'A bid has already been accepted for this tender.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            bid.status = 'accepted'
            bid.save()
            rejected_count = TenderBid.objects.filter(
                tender=bid.tender, status='pending'
            ).exclude(id=bid.id).update(status='rejected')

            tender        = bid.tender
            tender.status = 'closed'
            tender.save()

            return Response({
                'message':       f'Bid accepted. {rejected_count} other bid(s) rejected. Tender closed.',
                'bid':           TenderBidSerializer(bid).data
            })

        return super().update(request, *args, **kwargs)


class TenderBidsView(generics.ListAPIView):
    """All bids on a specific tender (manufacturer only)."""
    serializer_class   = TenderBidSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        tender_id = self.kwargs['tender_id']
        user      = self.request.user
        if user.role == 'manufacturer':
            return TenderBid.objects.filter(
                tender_id=tender_id,
                tender__manufacturer=user
            ).select_related('buyer', 'tender').order_by('-created_at')
        return TenderBid.objects.none()


class AcceptBidView(APIView):
    """
    Accept a specific bid and reject all others on the same tender.
    Only the manufacturer who owns the tender can do this,
    and only after the tender closing date has passed.
    """
    permission_classes = [permissions.IsAuthenticated]

    @transaction.atomic
    def post(self, request, bid_id):
        user = request.user

        if user.role != 'manufacturer':
            return Response(
                {'error': 'Only manufacturers can accept bids.'},
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            bid = TenderBid.objects.select_related('tender').get(id=bid_id)
        except TenderBid.DoesNotExist:
            return Response(
                {'error': 'Bid not found.'},
                status=status.HTTP_404_NOT_FOUND
            )

        if bid.tender.manufacturer != user:
            return Response(
                {'error': 'You can only accept bids on your own tenders.'},
                status=status.HTTP_403_FORBIDDEN
            )

        if bid.tender.end_date > timezone.now().date():
            return Response(
                {'error': 'Cannot accept bids before tender closing date.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if bid.status != 'pending':
            return Response(
                {'error': f'This bid is already {bid.status}.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if TenderBid.objects.filter(tender=bid.tender, status='accepted').exists():
            return Response(
                {'error': 'A bid has already been accepted for this tender.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        bid.status = 'accepted'
        bid.save()

        rejected_count = TenderBid.objects.filter(
            tender=bid.tender, status='pending'
        ).exclude(id=bid_id).update(status='rejected')

        tender        = bid.tender
        tender.status = 'closed'
        tender.save()

        return Response({
            'message':             'Bid accepted successfully.',
            'rejected_bids_count': rejected_count,
            'bid':                 TenderBidSerializer(bid).data,
            'tender_status':       tender.status
        }, status=status.HTTP_200_OK)