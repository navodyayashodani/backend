# tenders/views.py
# Add this import at the top
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import AllowAny, IsAuthenticated
import tempfile
import os


from rest_framework import status, generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser
from django.shortcuts import get_object_or_404
from django.db import transaction
from django.utils import timezone
from .models import Tender, TenderBid
from .serializers import (
    TenderSerializer, TenderCreateSerializer, TenderBidSerializer
)
from .ml_model import get_predictor

class TenderListCreateView(generics.ListCreateAPIView):
    """
    List all tenders or create a new tender
    """
    serializer_class = TenderSerializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    
    def get_queryset(self):
        """
        Filter tenders based on user role
        """
        user = self.request.user
        if user.role == 'manufacturer':
            # Manufacturers see only their own tenders
            return Tender.objects.filter(manufacturer=user)
        else:
            # Buyers see all active tenders
            return Tender.objects.all()  # Changed to show ALL tenders to buyers
    
    def perform_create(self, serializer):
        """
        Create tender with current user as manufacturer
        """
        if self.request.user.role != 'manufacturer':
            raise permissions.PermissionDenied(
                "Only manufacturers can create tenders"
            )
        
        # Save tender with current user
        tender = serializer.save(manufacturer=self.request.user)
        
        # Predict quality from uploaded report
        if tender.report_file:
            try:
                predictor = get_predictor()
                result = predictor.predict_quality(tender.report_file.path)
                
                tender.quality_grade = result['grade']
                tender.quality_score = result['score']
                tender.save()
            except Exception as e:
                print(f"Error predicting quality: {e}")


class TenderDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    Retrieve, update or delete a tender
    """
    serializer_class = TenderSerializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    
    def get_queryset(self):
        """
        Manufacturers can access their own tenders
        Buyers can view all tenders
        """
        user = self.request.user
        if user.role == 'manufacturer':
            return Tender.objects.filter(manufacturer=user)
        else:
            return Tender.objects.all()  # Buyers can see all tenders


class NextTenderNumberView(APIView):
    """
    Get the next available tender number
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        # Get the last tender
        last_tender = Tender.objects.all().order_by('-id').first()
        
        if last_tender and last_tender.tender_number:
            try:
                last_number = int(last_tender.tender_number.split('-')[1])
                next_number = last_number + 1
            except (IndexError, ValueError):
                next_number = 1
        else:
            next_number = 1
        
        next_tender_number = f"TND-{next_number:03d}"
        
        return Response({
            'next_tender_number': next_tender_number
        })


class PredictQualityView(APIView):
    """
    Predict quality grade from uploaded report (preview before saving)
    """
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    
    def post(self, request):
        """
        Accept file upload and return quality prediction
        """
        if 'file' not in request.FILES:
            return Response(
                {'error': 'No file provided'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        uploaded_file = request.FILES['file']
        
        # Validate file type
        allowed_extensions = ['pdf', 'doc', 'docx', 'xls', 'xlsx', 'png', 'jpg', 'jpeg']
        ext = uploaded_file.name.split('.')[-1].lower()
        
        if ext not in allowed_extensions:
            return Response(
                {'error': f'File type not allowed. Allowed: {", ".join(allowed_extensions)}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Validate file size (max 10MB)
        max_size = 10 * 1024 * 1024
        if uploaded_file.size > max_size:
            return Response(
                {'error': 'File size cannot exceed 10MB'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Save file temporarily
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{ext}') as temp_file:
            for chunk in uploaded_file.chunks():
                temp_file.write(chunk)
            temp_path = temp_file.name
        
        try:
            # Predict quality
            predictor = get_predictor()
            result = predictor.predict_quality(temp_path)
            
            return Response({
                'quality_grade': result['grade'],
                'quality_score': result['score'],
                'confidence': result.get('confidence', 0),
                'message': f'Quality Grade: {result["grade"]} (Score: {result["score"]}/100)'
            })
        except Exception as e:
            return Response(
                {'error': f'Error analyzing file: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        finally:
            # Clean up temp file
            import os
            if os.path.exists(temp_path):
                os.remove(temp_path)


class TenderBidListCreateView(generics.ListCreateAPIView):
    """
    List bids or create a new bid
    """
    serializer_class = TenderBidSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        """
        Manufacturers see bids on their tenders
        Buyers see ONLY their own bids
        """
        user = self.request.user

        if user.role == 'manufacturer':
            return TenderBid.objects.filter(tender__manufacturer=user)

        return TenderBid.objects.filter(buyer=user)

    def perform_create(self, serializer):
        """
        Create bid with current user as buyer
        Prevent duplicate bids on same tender
        """
        user = self.request.user

        if user.role != 'buyer':
            raise permissions.PermissionDenied(
                "Only buyers can place bids."
            )

        tender = serializer.validated_data.get('tender')

        if not tender:
            raise permissions.PermissionDenied(
                "Tender is required to place a bid."
            )

        # Prevent duplicate bids
        if TenderBid.objects.filter(buyer=user, tender=tender).exists():
            raise permissions.PermissionDenied(
                "You already placed a bid on this tender."
            )

        # ✅ buyer is set automatically
        serializer.save(buyer=user)


class TenderBidDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    Retrieve, update or delete a bid
    Buyers can update their own bids (amount/message)
    Manufacturers can update bid status (accept/reject)
    """
    serializer_class = TenderBidSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        """
        Buyers can only access their own bids
        Manufacturers can see bids on their tenders
        """
        user = self.request.user
        if user.role == 'buyer':
            return TenderBid.objects.filter(buyer=user)
        elif user.role == 'manufacturer':
            # Manufacturers can see bids on their tenders
            return TenderBid.objects.filter(tender__manufacturer=user)
        return TenderBid.objects.none()
    
    @transaction.atomic
    def update(self, request, *args, **kwargs):
        """
        Override update to handle:
        1. Buyers updating their own bid amount/message
        2. Manufacturers accepting/rejecting bids
        """
        user = request.user
        bid = self.get_object()
        
        # Check if updating status to 'accepted' or 'rejected'
        new_status = request.data.get('status')
        
        # If status is being changed, only manufacturer can do it
        if new_status and new_status != bid.status:
            if user.role != 'manufacturer':
                return Response(
                    {'error': 'Only manufacturers can update bid status'},
                    status=status.HTTP_403_FORBIDDEN
                )
        
        # If buyer is updating their own bid (amount/message only)
        if user.role == 'buyer':
            # Buyers can only update bid_amount and message, not status
            if new_status:
                return Response(
                    {'error': 'Buyers cannot change bid status'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # Check if bid is still pending
            if bid.status != 'pending':
                return Response(
                    {'error': f'Cannot update a {bid.status} bid'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Allow buyers to update only bid_amount and message
            allowed_fields = {'bid_amount', 'message'}
            update_fields = set(request.data.keys())
            
            if not update_fields.issubset(allowed_fields):
                return Response(
                    {'error': f'Buyers can only update: {", ".join(allowed_fields)}'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Perform the update
            return super().update(request, *args, **kwargs)
        
        # Manufacturer accepting a bid
        if new_status == 'accepted':
            # ✅ Check if tender closing date has passed
            if bid.tender.end_date > timezone.now().date():
                return Response(
                    {'error': 'Cannot accept bids before tender closing date. Please wait until the tender closes.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Check if another bid is already accepted for this tender
            existing_accepted = TenderBid.objects.filter(
                tender=bid.tender,
                status='accepted'
            ).exclude(id=bid.id).exists()
            
            if existing_accepted:
                return Response(
                    {'error': 'A bid has already been accepted for this tender'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Accept this bid
            bid.status = 'accepted'
            bid.save()
            
            # Reject all other pending bids on this tender
            rejected_count = TenderBid.objects.filter(
                tender=bid.tender,
                status='pending'
            ).exclude(id=bid.id).update(status='rejected')
            
            # Close the tender
            tender = bid.tender
            tender.status = 'closed'
            tender.save()
            
            return Response({
                'message': f'Bid accepted successfully. {rejected_count} other bids rejected and tender closed.',
                'bid': TenderBidSerializer(bid).data
            })
        
        # For other updates, use the standard update method
        return super().update(request, *args, **kwargs)


class TenderBidsView(generics.ListAPIView):
    """
    View all bids on a specific tender
    ONLY the manufacturer who created the tender can see its bids
    """
    serializer_class = TenderBidSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        tender_id = self.kwargs['tender_id']
        user = self.request.user
        
        # Only manufacturer of the tender can see its bids
        if user.role == 'manufacturer':
            return TenderBid.objects.filter(
                tender_id=tender_id,
                tender__manufacturer=user
            ).select_related('buyer', 'tender').order_by('-created_at')
        
        # Buyers cannot see other buyers' bids
        return TenderBid.objects.none()


class AcceptBidView(APIView):
    """
    Accept a bid and reject all other bids for the same tender
    Only manufacturer who owns the tender can accept bids
    Can only accept bids AFTER tender closing date has passed
    """
    permission_classes = [permissions.IsAuthenticated]
    
    @transaction.atomic
    def post(self, request, bid_id):
        user = request.user
        
        # Only manufacturers can accept bids
        if user.role != 'manufacturer':
            return Response(
                {'error': 'Only manufacturers can accept bids.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            # Get the bid
            bid = TenderBid.objects.select_related('tender').get(id=bid_id)
            
            # Check if the manufacturer owns this tender
            if bid.tender.manufacturer != user:
                return Response(
                    {'error': 'You can only accept bids on your own tenders.'},
                    status=status.HTTP_403_FORBIDDEN
                )
            
            # ✅ FIXED: Check if tender closing date has passed
            # Current date must be AFTER or EQUAL to end_date
            # Use > instead of >= to allow acceptance on the closing date
            if bid.tender.end_date > timezone.now().date():
                return Response(
                    {'error': 'Cannot accept bids before tender closing date. The tender must be closed first.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Check if bid is already accepted or rejected
            if bid.status != 'pending':
                return Response(
                    {'error': f'This bid is already {bid.status}.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Check if another bid is already accepted
            existing_accepted = TenderBid.objects.filter(
                tender=bid.tender,
                status='accepted'
            ).exists()
            
            if existing_accepted:
                return Response(
                    {'error': 'A bid has already been accepted for this tender.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Accept this bid
            bid.status = 'accepted'
            bid.save()
            
            # Reject all other pending bids for this tender
            rejected_count = TenderBid.objects.filter(
                tender=bid.tender,
                status='pending'
            ).exclude(
                id=bid_id
            ).update(status='rejected')
            
            # Update tender status to closed
            tender = bid.tender
            tender.status = 'closed'
            tender.save()
            
            return Response({
                'message': 'Bid accepted successfully.',
                'rejected_bids_count': rejected_count,
                'bid': TenderBidSerializer(bid).data,
                'tender_status': tender.status
            }, status=status.HTTP_200_OK)
            
        except TenderBid.DoesNotExist:
            return Response(
                {'error': 'Bid not found.'},
                status=status.HTTP_404_NOT_FOUND
            )
        

    # Add this new view class
class BatchPredictQualityView(APIView):
    """
    Batch predict quality from multiple uploaded files
    """
    parser_classes = [MultiPartParser, FormParser]
    permission_classes = [IsAuthenticated]  # ← FIXED: Changed from AllowAny
    
    def post(self, request):
        files = request.FILES.getlist('files')
        
        if not files:
            return Response(
                {'error': 'No files provided'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        predictor = get_predictor()
        all_results = []
        
        for uploaded_file in files:
            file_extension = uploaded_file.name.split('.')[-1].lower()
            
            if file_extension not in ['jpg', 'jpeg', 'png', 'pdf']:
                all_results.append({
                    'filename': uploaded_file.name,
                    'status': 'error',
                    'message': 'Invalid file type'
                })
                continue
            
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=f'.{file_extension}') as temp_file:
                    for chunk in uploaded_file.chunks():
                        temp_file.write(chunk)
                    temp_path = temp_file.name
                
                result = predictor.predict_quality(temp_path)
                result['filename'] = uploaded_file.name
                result['status'] = 'success'
                all_results.append(result)
                
                os.remove(temp_path)
                
            except Exception as e:
                all_results.append({
                    'filename': uploaded_file.name,
                    'status': 'error',
                    'message': str(e)
                })
        
        return Response({'results': all_results}, status=status.HTTP_200_OK)
