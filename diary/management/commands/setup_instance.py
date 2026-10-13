from django.core.management.base import BaseCommand
from setup_instance import main


class Command(BaseCommand):
    help = 'Configure PostgreSQL once and save secrets in the OS credential store.'

    def handle(self, *args, **options):
        main()
