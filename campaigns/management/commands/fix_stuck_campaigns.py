from django.core.management.base import BaseCommand
from django.utils import timezone
from campaigns.models import Campaign, Message
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Fix campaigns that are stuck in running state when all messages are processed'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show what would be done without making changes',
        )
        parser.add_argument(
            '--campaign-id',
            type=int,
            help='Fix specific campaign by ID',
        )

    def handle(self, *args, **options):
        dry_run = options.get('dry_run', False)
        campaign_id = options.get('campaign_id')
        
        if dry_run:
            self.stdout.write(self.style.WARNING('DRY RUN MODE - No changes will be made'))
        
        # Get campaigns to check
        if campaign_id:
            campaigns = Campaign.objects.filter(id=campaign_id, status='running')
            if not campaigns.exists():
                self.stdout.write(self.style.ERROR(f'Campaign {campaign_id} not found or not running'))
                return
        else:
            campaigns = Campaign.objects.filter(status='running')
        
        fixed_count = 0
        
        for campaign in campaigns:
            # Check for pending messages
            pending_messages = Message.objects.filter(
                campaign_id=campaign.id,
                status__in=['queued', 'sending']
            ).count()
            
            # Get message status breakdown
            status_counts = Message.objects.filter(
                campaign_id=campaign.id
            ).values('status').annotate(count=models.Count('status'))
            
            status_dict = {item['status']: item['count'] for item in status_counts}
            
            self.stdout.write(f"\nCampaign {campaign.id} - {campaign.template_name}:")
            self.stdout.write(f"  Total Recipients: {campaign.total_recipients}")
            self.stdout.write(f"  Message Status Breakdown:")
            for status, count in status_dict.items():
                self.stdout.write(f"    {status}: {count}")
            
            if pending_messages == 0:
                self.stdout.write(self.style.SUCCESS(f"  ✓ No pending messages - should be completed"))
                
                if not dry_run:
                    campaign.status = 'completed'
                    campaign.completed_at = timezone.now()
                    campaign.save()
                    self.stdout.write(self.style.SUCCESS(f"  ✓ Campaign {campaign.id} marked as completed"))
                    fixed_count += 1
                else:
                    self.stdout.write(self.style.WARNING(f"  [DRY RUN] Would mark campaign {campaign.id} as completed"))
            else:
                self.stdout.write(self.style.WARNING(f"  ⚠ Still has {pending_messages} pending messages"))
        
        self.stdout.write(f"\n{self.style.SUCCESS('Summary:')}")
        self.stdout.write(f"  Campaigns checked: {campaigns.count()}")
        if not dry_run:
            self.stdout.write(f"  Campaigns fixed: {fixed_count}")
        else:
            self.stdout.write(f"  Campaigns that would be fixed: {fixed_count}")
        
        # Also trigger check_campaign_completion for all running campaigns
        if not dry_run and not campaign_id:
            self.stdout.write("\nTriggering completion checks for all running campaigns...")
            from campaigns.tasks import check_campaign_completion
            for campaign in Campaign.objects.filter(status='running'):
                check_campaign_completion.delay(campaign.id)
                self.stdout.write(f"  Queued check for campaign {campaign.id}")


# Add missing import
from django.db import models