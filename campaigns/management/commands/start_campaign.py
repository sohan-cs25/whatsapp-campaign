
from django.core.management.base import BaseCommand
from campaigns.models import Campaign, Message
from campaigns.tasks import start_campaign_task

class Command(BaseCommand):
    help = 'Start a campaign'

    def add_arguments(self, parser):
        parser.add_argument('campaign_id', type=int, help='Campaign ID to start')

    def handle(self, *args, **options):
        campaign_id = options['campaign_id']
        
        try:
            campaign = Campaign.objects.get(id=campaign_id)
            
            self.stdout.write(f"Campaign: {campaign.template_name}")
            self.stdout.write(f"Status: {campaign.status}")
            self.stdout.write(f"Recipients: {campaign.total_recipients}")
            
            messages = Message.objects.filter(campaign=campaign).count()
            self.stdout.write(f"Messages: {messages}")
            
            if campaign.status != 'pending':
                self.stdout.write(self.style.ERROR(f"Campaign status must be 'pending' to start. Current: {campaign.status}"))
                return
            
            if messages == 0:
                self.stdout.write(self.style.ERROR("No messages found. File may not be processed."))
                return
            
            # Start the campaign
            self.stdout.write("Starting campaign...")
            campaign.status = 'running'
            campaign.save()
            
            # Trigger task
            start_campaign_task.delay(campaign_id)
            
            self.stdout.write(self.style.SUCCESS(f"Campaign {campaign_id} started successfully!"))
            
        except Campaign.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"Campaign {campaign_id} not found"))