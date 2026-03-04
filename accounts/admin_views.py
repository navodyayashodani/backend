# accounts/admin_views.py

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from django.contrib.auth import get_user_model
from django.db.models import Count
from django.utils import timezone

from tenders.models import Tender, TenderBid   # ← correct model names

User = get_user_model()


# ── Permission ─────────────────────────────────────────────────────────────────
class IsAdminRole(IsAuthenticated):
    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        return (
            request.user.is_staff or
            request.user.is_superuser or
            getattr(request.user, 'role', '') == 'admin'
        )


# ── Stats ──────────────────────────────────────────────────────────────────────
class AdminStatsView(APIView):
    permission_classes = [IsAdminRole]

    def get(self, request):
        today = timezone.now().date()

        # Truly active = end_date not yet passed AND not manually closed
        active_tenders = Tender.objects.filter(
            end_date__gte=today
        ).exclude(status='closed').count()

        return Response({
            'total_users':    User.objects.count(),
            'total_tenders':  Tender.objects.count(),
            'active_tenders': active_tenders,
            'total_bids':     TenderBid.objects.count(),

            'graded_reports': Tender.objects.filter(
                                quality_grade__isnull=False
                              ).exclude(quality_grade='').count(),
        })


# ── Users ──────────────────────────────────────────────────────────────────────
class AdminUserListView(APIView):
    permission_classes = [IsAdminRole]

    def get(self, request):
        limit  = int(request.query_params.get('limit', 100))
        search = request.query_params.get('search', '').strip()

        qs = User.objects.all().order_by('-date_joined')
        if search:
            qs = qs.filter(username__icontains=search) | \
                 qs.filter(first_name__icontains=search)

        data = [{
            'id':          u.id,
            'username':    u.username,
            'first_name':  u.first_name,
            'last_name':   u.last_name,
            'email':       u.email,
            # normalise admin identity — same logic as login view
            'role': 'admin' if (u.is_staff or u.is_superuser or u.role == 'admin') else u.role,
            'is_active':   u.is_active,
            'date_joined': u.date_joined,
        } for u in qs[:limit]]

        return Response(data)


class AdminUserDetailView(APIView):
    permission_classes = [IsAdminRole]

    def get(self, request, pk):
        try:
            u = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return Response({'error': 'User not found'}, status=404)

        return Response({
            'id':          u.id,
            'username':    u.username,
            'first_name':  u.first_name,
            'last_name':   u.last_name,
            'email':       u.email,
            'role':        'admin' if (u.is_staff or u.is_superuser or u.role == 'admin') else u.role,
            'is_active':   u.is_active,
            'date_joined': u.date_joined,
        })

    def patch(self, request, pk):
        try:
            u = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return Response({'error': 'User not found'}, status=404)

        for field in ['is_active', 'role', 'first_name', 'last_name', 'email']:
            if field in request.data:
                setattr(u, field, request.data[field])
        u.save()
        return Response({'success': True})

    def delete(self, request, pk):
        try:
            u = User.objects.get(pk=pk)
        except User.DoesNotExist:
            return Response({'error': 'User not found'}, status=404)
        u.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ── Tenders ────────────────────────────────────────────────────────────────────
class AdminTenderListView(APIView):
    permission_classes = [IsAdminRole]

    def get(self, request):
        limit    = int(request.query_params.get('limit', 100))
        status_q = request.query_params.get('status', '').strip()

        qs = Tender.objects.select_related('manufacturer').all().order_by('-created_at')
        if status_q:
            qs = qs.filter(status=status_q)

        today = timezone.now().date()
        data  = []
        for t in qs[:limit]:
            bid_count  = t.bids.count()
            is_expired = t.end_date < today or t.status == 'closed'

            if not is_expired:
                display_status = ['active']
            else:
                display_status = ['closed']
                if t.bids.filter(status='accepted').exists():
                    display_status.append('awarded')
                elif bid_count == 0:
                    display_status.append('no bids')

            data.append({
                'id':             t.id,
                'title':          t.tender_title,
                'tender_number':  t.tender_number,
                'oil_type':       t.oil_type,
                'quantity':       str(t.quantity),
                'created_by':     t.manufacturer.username,
                'status':         t.status,
                'display_status': display_status,
                'bid_count':      bid_count,
                'deadline':       t.end_date,
                'start_date':     t.start_date,
                'quality_grade':  t.quality_grade,
                'quality_score':  str(t.quality_score) if t.quality_score else None,
                'created_at':     t.created_at,
            })

        return Response(data)


class AdminTenderDetailView(APIView):
    permission_classes = [IsAdminRole]

    def get(self, request, pk):
        try:
            t = Tender.objects.select_related('manufacturer').get(pk=pk)
        except Tender.DoesNotExist:
            return Response({'error': 'Tender not found'}, status=404)

        return Response({
            'id':            t.id,
            'title':         t.tender_title,
            'tender_number': t.tender_number,
            'oil_type':      t.oil_type,
            'quantity':      str(t.quantity),
            'description':   t.tender_description,
            'created_by':    t.manufacturer.username,
            'status':        t.status,
            'bid_count':     t.bids.count(),
            'start_date':    t.start_date,
            'deadline':      t.end_date,
            'quality_grade': t.quality_grade,
            'quality_score': str(t.quality_score) if t.quality_score else None,
            'created_at':    t.created_at,
        })


# ── Bids ───────────────────────────────────────────────────────────────────────
class AdminBidListView(APIView):
    permission_classes = [IsAdminRole]

    def get(self, request):
        limit     = int(request.query_params.get('limit', 100))
        tender_id = request.query_params.get('tender_id', '').strip()

        qs = TenderBid.objects.select_related('buyer', 'tender').order_by('-created_at')
        if tender_id:
            qs = qs.filter(tender_id=tender_id)

        data = [{
            'id':            b.id,
            'tender_id':     b.tender_id,
            'tender_number': b.tender.tender_number,
            'tender_title':  b.tender.tender_title,
            'buyer':         b.buyer.username,
            'bid_amount':    str(b.bid_amount),
            'message':       b.message,
            'status':        b.status,
            'created_at':    b.created_at,
        } for b in qs[:limit]]

        return Response(data)


# ── Grading Reports ────────────────────────────────────────────────────────────
# No separate GradingReport model — graded tenders are Tender rows
# where quality_grade has been set by the ML predictor.
class AdminGradingReportListView(APIView):
    permission_classes = [IsAdminRole]

    def get(self, request):
        limit = int(request.query_params.get('limit', 100))

        qs = Tender.objects.select_related('manufacturer') \
                   .filter(quality_grade__isnull=False) \
                   .exclude(quality_grade='') \
                   .order_by('-created_at')

        data = [{
            'id':            t.id,
            'tender_number': t.tender_number,
            'tender_title':  t.tender_title,
            'manufacturer':  t.manufacturer.username,
            'oil_type':      t.oil_type,
            'grade':         t.quality_grade,
            'score':         str(t.quality_score) if t.quality_score else None,
            'created_at':    t.created_at,
        } for t in qs[:limit]]

        return Response(data)


# ── Activity Logs ──────────────────────────────────────────────────────────────
class AdminActivityLogListView(APIView):
    permission_classes = [IsAdminRole]

    def get(self, request):
        limit = int(request.query_params.get('limit', 20))
        logs  = []

        # Recent tenders
        for t in Tender.objects.select_related('manufacturer').order_by('-created_at')[:limit]:
            logs.append({
                'id':        f'tender-{t.id}',
                'action':    'Tender Created',
                'actor':     t.manufacturer.username,
                'detail':    f'{t.tender_title} ({t.tender_number})',
                'timestamp': t.created_at,
            })

        # Recent bids
        for b in TenderBid.objects.select_related('buyer', 'tender').order_by('-created_at')[:limit]:
            logs.append({
                'id':        f'bid-{b.id}',
                'action':    'Bid Submitted',
                'actor':     b.buyer.username,
                'detail':    f'on {b.tender.tender_title} ({b.tender.tender_number})',
                'timestamp': b.created_at,
            })

        # Recent ML gradings
        for t in Tender.objects.select_related('manufacturer') \
                        .filter(quality_grade__isnull=False) \
                        .exclude(quality_grade='') \
                        .order_by('-updated_at')[:limit]:
            logs.append({
                'id':        f'grade-{t.id}',
                'action':    'Quality Graded',
                'actor':     t.manufacturer.username,
                'detail':    f'{t.tender_number} graded {t.quality_grade}',
                'timestamp': t.updated_at,
            })

        logs.sort(key=lambda x: x['timestamp'], reverse=True)
        return Response(logs[:limit])


# ── Summary Report ─────────────────────────────────────────────────────────────
class AdminSummaryReportView(APIView):
    permission_classes = [IsAdminRole]

    def get(self, request):
        today = timezone.now().date()

        # Computed status counts (same logic as display_status)
        all_tenders  = Tender.objects.prefetch_related('bids').all()
        status_active   = 0
        status_closed   = 0
        status_awarded  = 0
        status_no_bids  = 0

        for t in all_tenders:
            is_expired = t.end_date < today or t.status == 'closed'
            if not is_expired:
                status_active += 1
            else:
                status_closed += 1
                if t.bids.filter(status='accepted').exists():
                    status_awarded += 1
                elif not t.bids.exists():
                    status_no_bids += 1

        tender_by_oil_type = list(
            Tender.objects.values('oil_type').annotate(count=Count('id'))
        )
        top_bidders = list(
            TenderBid.objects.values('buyer__username')
                             .annotate(total_bids=Count('id'))
                             .order_by('-total_bids')[:5]
        )
        top_manufacturers = list(
            Tender.objects.values('manufacturer__username')
                          .annotate(total_tenders=Count('id'))
                          .order_by('-total_tenders')[:5]
        )

        return Response({
            'total_users':        User.objects.count(),
            'total_tenders':      Tender.objects.count(),
            'total_bids':         TenderBid.objects.count(),
            'graded_reports':     Tender.objects.filter(
                                    quality_grade__isnull=False
                                  ).exclude(quality_grade='').count(),
            'status_active':      status_active,
            'status_closed':      status_closed,
            'status_awarded':     status_awarded,
            'status_no_bids':     status_no_bids,
            'tender_by_oil_type': tender_by_oil_type,
            'top_bidders':        top_bidders,
            'top_manufacturers':  top_manufacturers,
            'generated_at':       timezone.now(),
        })