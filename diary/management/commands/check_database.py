from django.core.management.base import BaseCommand, CommandError
from django.db import connection, DatabaseError
from config.database_errors import connection_failure_message


class Command(BaseCommand):
    help = 'Check the configured PostgreSQL connection without exposing credentials.'

    def handle(self, *args, **options):
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1')
                cursor.fetchone()
        except DatabaseError as error:
            raise CommandError(connection_failure_message(error, connection.settings_dict.get('HOST', ''))) from None
        self.stdout.write(self.style.SUCCESS('Database connection verified.'))
