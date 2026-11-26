"""
Review flow: list a processed chat file's customer orders, edit them (re-priced on the
server), approve the ones without blocking issues, and queue approved orders for sending.
"""

import uuid

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import DjangoModelPermissions, IsAuthenticated
from rest_framework.response import Response

from .models import (ChatMessage, CustomerContact, Order, OrderLine, ParsedChatFile, Product, flat_key,
                     normalize_phone)
from .serializers import (CustomerContactSerializer, ProductSerializer, ReviewOrderSerializer,
                          ReviewOrderUpdateSerializer, chat_message_data)
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
    messages = list(ChatMessage.objects.filter(parsed_file=pf))
    by_sender = {}
    for m in messages:
        by_sender.setdefault(m.sender, []).append(m)
    ordering = {o.chat_sender for o in orders}
    return Response({
        'parsed_file': {'id': str(pf.id), 'file_name': pf.file_name, 'processed_at': pf.processed_at},
        'summary': summary,
        'orders': ReviewOrderSerializer(orders, many=True, context={'messages_by_sender': by_sender}).data,
        'seller_messages': [chat_message_data(m) for m in messages if m.is_seller],
        # customers who wrote but got no order (a photo of a list, a question, an unclear message)
        'unordered_messages': [chat_message_data(m) for m in messages
                               if not m.is_seller and m.sender not in ordering],
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
        if 'number' in data:  # '98000 00001' -> '919800000001'; unusable input is kept as typed
            data['number'] = normalize_phone(data['number']) or data['number']
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
        if 'number' in data and order.number:
            # remembered for this flat, so next time this customer's phone fills itself in
            CustomerContact.remember(order.user, order.address, order.number, order.customer_name)
        elif 'address' in data and not order.number:
            order.number = CustomerContact.phone_for(order.user, order.address)
            if order.number and 'phone_from_directory' not in order.review_flags:
                order.review_flags = list(order.review_flags or []) + ['phone_from_directory']
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
        ids = request.data.get('order_ids') or []
        try:
            ids = [str(uuid.UUID(str(i))) for i in ids]
        except ValueError:
            return Response({'error': 'order_ids must be order UUIDs'}, status=status.HTTP_400_BAD_REQUEST)
        candidates = candidates.filter(id__in=ids)

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
        wanted = ids
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
    """Products and prices. Delete deactivates, so past order lines keep their product.
    Any signed-in user can read; changing prices needs the orders add/change/delete_product
    permission (superusers have it)."""
    permission_classes = [IsAuthenticated, DjangoModelPermissions]
    serializer_class = ProductSerializer
    queryset = Product.objects.all()
    pagination_class = None

    def perform_destroy(self, instance):
        instance.is_active = False
        instance.save(update_fields=['is_active', 'updated_at'])


class CustomerContactViewSet(viewsets.ModelViewSet):
    """The signed-in seller's flat -> phone directory. Saving a contact also fills the phone
    on that flat's orders that are still waiting for one."""
    permission_classes = [IsAuthenticated]
    serializer_class = CustomerContactSerializer
    pagination_class = None

    def get_queryset(self):
        return CustomerContact.objects.filter(user=self.request.user)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data
        contact, _ = CustomerContact.objects.update_or_create(
            user=request.user, flat_key=flat_key(d['flat']),
            defaults={'flat': d['flat'], 'phone': d['phone'], **({'name': d['name']} if d.get('name') else {})})
        return Response(self._with_fill(contact), status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        response = super().update(request, *args, **kwargs)
        response.data = self._with_fill(self.get_object())
        return response

    def _with_fill(self, contact):
        return {**CustomerContactSerializer(contact).data, 'orders_filled': fill_phones_from_directory(contact)}


def fill_phones_from_directory(contact) -> int:
    """Give this contact's phone to the user's unsent, unapproved orders for the flat that have none."""
    filled = 0
    waiting = Order.objects.filter(user=contact.user, number='', status='pending', review_status='draft')
    for order in waiting:
        if flat_key(order.address) != contact.flat_key:
            continue
        order.number = contact.phone
        order.review_flags = list(order.review_flags or []) + ['phone_from_directory']
        order.needs_review = bool(order.blocking_issues()) or bool(
            set(order.review_flags) - {'address_from_other_orders', 'phone_from_directory'})
        order.save(update_fields=['number', 'review_flags', 'needs_review', 'updated_at'])
        filled += 1
    return filled
