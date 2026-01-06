from django.contrib import admin
from .models import Diary, DiaryMovement


class DiaryMovementInline(admin.TabularInline):
    model = DiaryMovement
    extra = 0
    readonly_fields = ("created_by", "created_on")


@admin.register(Diary)
class DiaryAdmin(admin.ModelAdmin):
    list_display = ("diary_no", "diary_date", "received_from", "marked_to", "status", "created_by")
    search_fields = ("subject", "received_from", "received_diary_no", "marked_to")
    list_filter = ("year", "status", "diary_date")
    inlines = [DiaryMovementInline]


@admin.register(DiaryMovement)
class DiaryMovementAdmin(admin.ModelAdmin):
    list_display = ("diary", "action_type", "from_office", "to_office", "action_datetime", "created_by")
    list_filter = ("action_type", "action_datetime")
    search_fields = ("from_office", "to_office", "remarks")
