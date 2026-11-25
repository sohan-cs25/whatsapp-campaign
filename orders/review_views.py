"""
Review flow: list a processed chat file's customer orders, edit them (re-priced on the
server), approve the ones without blocking issues, and queue approved orders for sending.
"""

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Order, OrderLine, ParsedChatFile, Product
from .serializers import ProductSerializer, ReviewOrderSerializer, ReviewOrderUpdateSerializer
from .tasks import send_order_batch

SENT_STATUSES = ('sent', 'delivered', 'read')


def _orders_for(parsed_file):
    return (Order.objects.filter(parsed_file=parsed_file)
            .prefetch_related('lines__product')
            .order_by('-needs_review', 'customer_name'))


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def review_orders(request, parsed_file_id):
    pf = get_object_or_404(ParsedChatFile, id=parsed_file_id, user=request.user)
    orders = list(_orders_for(pf))
    summary = {
        'orders': len(orders),
        'needs_review': sum(o.needs_review for o in orders),
        'draft': sum(o.review_status == 'draft' for o in orders),
        'approved': sum(o.review_status == 'approved' for o in orders),
        'rejected': sum(o.review_status == 'rejected' for o in orders),
        'sent': sum(o.status in SENT_STATUSES for o in orders),
        'failed': sum(o.status == 'failed' for o in orders),
        'total_paise': sum(o.total_paise or 0 for o in orders if o.review_status != 'rejected'),
    }
    return Response({
        'parsed_file': {'id': str(pf.id), 'file_name': pf.file_name, 'processed_at': pf.processed_at},
        'summary': summary,
        'orders': ReviewOrderSerializer(orders, many=True).data,
    })


@api_view(['PATCH'])
@permission_classes([IsAuthenticated])
def update_review_order(request, order_id):
    order = get_object_or_404(Order, id=order_id, user=request.user)
    if order.status != 'pending':
        return Response({'error': 'Order already sent'}, status=status.HTTP_409_CONFLICT)
    if request.data.get('review_status') == 'approved':
        return Response({'error': 'Use the approve endpoint to approve orders'},
                        status=status.HTTP_400_BAD_REQUEST)
    serializer = ReviewOrderUpdateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    with transaction.atomic():
        for field in ('number', 'address', 'customer_name', 'review_status'):
            if field in data:
                setattr(order, field, data[field])
        if 'lines' in data:
            order.lines.all().delete()
            for spec in data['lines']:
                line = OrderLine(order=order, product=spec.get('product'), name=spec['name'],
                                 quantity=spec.get('quantity'), unit=spec.get('unit') or '')
                line.reprice()
                line.save()
        order.save()
        order.refresh_totals()
        order.needs_review = bool(order.blocking_issues())
        order.save(update_fields=['needs_review', 'updated_at'])
    return Response(ReviewOrderSerializer(order).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def approve_orders(request, parsed_file_id):
    pf = get_object_or_404(ParsedChatFile, id=parsed_file_id, user=request.user)
    candidates = Order.objects.filter(parsed_file=pf, status='pending')
    if request.data.get('all_clean'):
        candidates = candidates.filter(review_status='draft', needs_review=False)
    else:
        candidates = candidates.filter(id__in=request.data.get('order_ids') or [])

    approved, refused = [], []
    for order in candidates.order_by('customer_name'):
        issues = order.blocking_issues()
        if issues:
            if not request.data.get('all_clean'):
                refused.append({'id': str(order.id), 'issues': issues})
            continue
        order.review_status = 'approved'
        order.save(update_fields=['review_status', 'updated_at'])
        approved.append(str(order.id))
    # Keep the caller's order for explicit ids
    if not request.data.get('all_clean'):
        wanted = [str(i) for i in request.data.get('order_ids') or []]
        approved.sort(key=lambda i: wanted.index(i) if i in wanted else len(wanted))
    return Response({'approved': approved, 'refused': refused})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def send_approved_orders(request, parsed_file_id):
    pf = get_object_or_404(ParsedChatFile, id=parsed_file_id, user=request.user)
    count = Order.objects.filter(parsed_file=pf, review_status='approved', status='pending').count()
    if not count:
        return Response({'error': 'No approved orders waiting to be sent'}, status=status.HTTP_400_BAD_REQUEST)
    send_order_batch.delay(str(pf.id))
    return Response({'queued': count})


class ProductViewSet(viewsets.ModelViewSet):
    """Products and prices. Delete deactivates, so past order lines keep their product."""
    permission_classes = [IsAuthenticated]
    serializer_class = ProductSerializer
    queryset = Product.objects.all()
    pagination_class = None

    def perform_destroy(self, instance):
        instance.is_active = False
        instance.save(update_fields=['is_active', 'updated_at'])
