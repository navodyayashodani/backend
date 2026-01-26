# accounts/management/commands/show_users.py

from django.core.management.base import BaseCommand
from django.utils import timezone
from accounts.models import User
from tenders.models import Tender

class Command(BaseCommand):
    help = 'Display all users and their data'

    def handle(self, *args, **kwargs):
        self.stdout.write(self.style.SUCCESS('\n=== REGISTERED USERS ===\n'))
        
        users = User.objects.all().order_by('-date_joined')
        
        if not users:
            self.stdout.write(self.style.WARNING('No users found in database.'))
            return
        
        for user in users:
            self.stdout.write(f"\n{self.style.HTTP_INFO('━' * 60)}")
            self.stdout.write(f"ID: {user.id}")
            self.stdout.write(f"Username: {self.style.SUCCESS(user.username)}")
            self.stdout.write(f"Email: {user.email}")
            self.stdout.write(f"Name: {user.first_name} {user.last_name}")
            self.stdout.write(f"Role: {self.style.WARNING(user.role.upper())}")
            self.stdout.write(f"Company: {user.company_name or 'N/A'}")
            self.stdout.write(f"Phone: {user.phone_number or 'N/A'}")
            self.stdout.write(f"Active: {'Yes' if user.is_active else 'No'}")
            self.stdout.write(f"Joined: {user.date_joined.strftime('%Y-%m-%d %H:%M')}")
            
            # Show tenders if manufacturer
            if user.role == 'manufacturer':
                tenders = Tender.objects.filter(manufacturer=user)
                self.stdout.write(f"Tenders Created: {tenders.count()}")
                
                if tenders:
                    for tender in tenders[:3]:  # Show first 3
                        self.stdout.write(f"  • {tender.tender_number}: {tender.tender_title} ({tender.status})")
        
        self.stdout.write(f"\n{self.style.HTTP_INFO('━' * 60)}")
        self.stdout.write(self.style.SUCCESS(f'\nTotal Users: {users.count()}'))
        self.stdout.write(f"Manufacturers: {users.filter(role='manufacturer').count()}")
        self.stdout.write(f"Buyers: {users.filter(role='buyer').count()}")