from django.core.management.base import BaseCommand
from campaigns.models import Campaign, Message


class Command(BaseCommand):
    help = 'Sync campaign counters with actual message statuses'

    def add_arguments(self, parser):
        parser.add_argument(
            '--campaign-id',
            type=int,
            help='Sync specific campaign ID (optional)',
        )

    def handle(self, *args, **options):
        if options['campaign_id']:
            campaigns = Campaign.objects.filter(id=options['campaign_id'])
        else:
            campaigns = Campaign.objects.all()

        self.stdout.write(f'Syncing {campaigns.count()} campaigns...')

        for campaign in campaigns:
            self.sync_campaign_counters(campaign)

        self.stdout.write(
            self.style.SUCCESS('Successfully synced all campaign counters')
        )

    def sync_campaign_counters(self, campaign):
        """Recalculate campaign counters from actual message statuses"""
        messages = Message.objects.filter(campaign=campaign)
        
        # Calculate actual counts based on message statuses
        sent_count = messages.filter(status__in=['sent', 'delivered', 'read']).count()
        delivered_count = messages.filter(status__in=['delivered', 'read']).count()
        read_count = messages.filter(status='read').count()
        failed_count = messages.filter(status='failed').count()
        
        # Store old values for comparison
        old_sent = campaign.sent_count
        old_delivered = campaign.delivered_count
        old_read = campaign.read_count
        old_failed = campaign.failed_count
        
        # Update campaign with correct counts
        campaign.sent_count = sent_count
        campaign.delivered_count = delivered_count
        campaign.read_count = read_count
        campaign.failed_count = failed_count
        campaign.save()
        
        # Report changes
        self.stdout.write(f'Campaign #{campaign.id} ({campaign.template_name}):')
        if old_sent != sent_count:
            self.stdout.write(f'  Sent: {old_sent} → {sent_count}')
        if old_delivered != delivered_count:
            self.stdout.write(f'  Delivered: {old_delivered} → {delivered_count}')
        if old_read != read_count:
            self.stdout.write(f'  Read: {old_read} → {read_count}')
        if old_failed != failed_count:
            self.stdout.write(f'  Failed: {old_failed} → {failed_count}')
            
        # Validate counters
        total_processed = sent_count + failed_count
        if total_processed > campaign.total_recipients:
            self.stdout.write(
                self.style.ERROR(
                    f'  ⚠️  Total processed ({total_processed}) > Recipients ({campaign.total_recipients})'
                )
            )
        else:
            self.stdout.write(self.style.SUCCESS('  ✅ Counters are consistent'))