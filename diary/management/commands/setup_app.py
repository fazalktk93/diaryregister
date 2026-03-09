from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from diary.models import AppConfig
import os
import sys


class Command(BaseCommand):
    help = "Interactive setup for the Diary Management System on Windows deployment"

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("=" * 70))
        self.stdout.write(self.style.SUCCESS("Diary Management System - Deployment Setup"))
        self.stdout.write(self.style.SUCCESS("=" * 70))
        self.stdout.write("")

        # Get or create the AppConfig singleton
        try:
            config = AppConfig.get_config()
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error accessing database: {e}"))
            self.stdout.write(self.style.WARNING("Please ensure Django migrations are run: python manage.py migrate"))
            return

        # Step 1: Directorate Name
        self.stdout.write(self.style.HTTP_INFO("Step 1: Directorate Name"))
        current_directorate = config.directorate_name.strip() if config.directorate_name else "(not set)"
        self.stdout.write(f"Current value: {current_directorate}")
        
        directorate_input = input("Enter directorate name (or press Enter to keep current): ").strip()
        if directorate_input:
            config.directorate_name = directorate_input
            self.stdout.write(self.style.SUCCESS(f"✓ Directorate set to: {directorate_input}"))
        else:
            self.stdout.write(self.style.WARNING(f"Keeping current value: {current_directorate}"))
        self.stdout.write("")

        # Step 2: Port Number
        self.stdout.write(self.style.HTTP_INFO("Step 2: Port Number"))
        self.stdout.write(f"Current port: {config.port}")
        
        while True:
            port_input = input("Enter port number (default 8000): ").strip()
            if not port_input:
                self.stdout.write(f"✓ Using default port: 8000")
                config.port = 8000
                break
            try:
                port = int(port_input)
                if 1 <= port <= 65535:
                    config.port = port
                    self.stdout.write(self.style.SUCCESS(f"✓ Port set to: {port}"))
                    break
                else:
                    self.stdout.write(self.style.ERROR("Port must be between 1 and 65535"))
            except ValueError:
                self.stdout.write(self.style.ERROR("Invalid port number. Please enter a number."))
        self.stdout.write("")

        # Step 3: Host Bind Address
        self.stdout.write(self.style.HTTP_INFO("Step 3: Host Bind Address"))
        self.stdout.write(f"Current host: {config.host}")
        self.stdout.write("(Use 0.0.0.0 to accept connections on all network interfaces)")
        
        host_input = input("Enter host bind address (default 0.0.0.0): ").strip()
        if host_input:
            config.host = host_input
            self.stdout.write(self.style.SUCCESS(f"✓ Host set to: {host_input}"))
        else:
            config.host = "0.0.0.0"
            self.stdout.write(self.style.SUCCESS(f"✓ Host set to default: 0.0.0.0"))
        self.stdout.write("")

        # Save configuration
        try:
            config.save()
            self.stdout.write(self.style.SUCCESS("✓ Configuration saved successfully"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error saving configuration: {e}"))
            return
        self.stdout.write("")

        # Step 4: Database Migrations
        self.stdout.write(self.style.HTTP_INFO("Step 4: Database Migrations"))
        run_migrate = input("Run database migrations? (y/n, default y): ").strip().lower()
        if run_migrate != 'n':
            self.stdout.write("Running migrations...")
            os.system(f"{sys.executable} manage.py migrate")
            self.stdout.write(self.style.SUCCESS("✓ Migrations completed"))
        self.stdout.write("")

        # Step 5: Create/Update Superuser
        self.stdout.write(self.style.HTTP_INFO("Step 5: Superuser Setup"))
        setup_admin = input("Create or update a superuser? (y/n, default n): ").strip().lower()
        if setup_admin == 'y':
            while True:
                username = input("Enter superuser username (or 'skip'): ").strip()
                if username.lower() == 'skip':
                    break
                
                # Check if user exists
                if User.objects.filter(username=username).exists():
                    update = input(f"User '{username}' already exists. Update password? (y/n): ").strip().lower()
                    if update != 'y':
                        continue
                    user = User.objects.get(username=username)
                else:
                    user = User(username=username)
                
                password = input("Enter password: ").strip()
                if len(password) < 8:
                    self.stdout.write(self.style.ERROR("Password must be at least 8 characters"))
                    continue
                
                user.set_password(password)
                user.is_staff = True
                user.is_superuser = True
                user.save()
                self.stdout.write(self.style.SUCCESS(f"✓ Superuser '{username}' created/updated"))
                break
        self.stdout.write("")

        # Step 6: Firewall Rule (Windows-specific guidance)
        self.stdout.write(self.style.HTTP_INFO("Step 6: Firewall Configuration"))
        self.stdout.write(f"To access the app from other machines, you may need to add a firewall exception.")
        self.stdout.write(f"Port: {config.port}")
        self.stdout.write("On Windows, this can be done via Windows Defender Firewall or the PowerShell setup script.")
        self.stdout.write("")

        # Summary
        self.stdout.write(self.style.SUCCESS("=" * 70))
        self.stdout.write(self.style.SUCCESS("Setup Complete!"))
        self.stdout.write(self.style.SUCCESS("=" * 70))
        self.stdout.write("")
        self.stdout.write(self.style.HTTP_SUCCESS(f"Directorate Name: {config.directorate_name or '(not set)'}"))
        self.stdout.write(self.style.HTTP_SUCCESS(f"Port: {config.port}"))
        self.stdout.write(self.style.HTTP_SUCCESS(f"Host: {config.host}"))
        self.stdout.write("")
        self.stdout.write("To start the application, run:")
        self.stdout.write(self.style.SQL_KEYWORD(f"  python manage.py runserver {config.host}:{config.port}"))
        self.stdout.write("")
        self.stdout.write("Or use the PowerShell setup script to configure auto-start:")
        self.stdout.write(self.style.SQL_KEYWORD("  powershell -ExecutionPolicy Bypass -File setup_app.ps1"))
        self.stdout.write("")
