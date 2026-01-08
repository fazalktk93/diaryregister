from django.contrib import admin
from .models import Diary, DiaryMovement, Office


class DiaryMovementInline(admin.TabularInline):
    model = DiaryMovement
    extra = 0
    readonly_fields = ("created_by", "created_on")
    show_change_link = True
    ordering = ("action_datetime", "id")


@admin.register(Diary)
class DiaryAdmin(admin.ModelAdmin):
    list_display = ("diary_no", "diary_date", "received_from", "marked_to", "status", "created_by")
    search_fields = ("subject", "received_from", "received_diary_no", "marked_to")
    list_filter = ("year", "status", "diary_date")
    inlines = [DiaryMovementInline]

    # ✅ Additive admin improvements
    date_hierarchy = "diary_date"
    ordering = ("-year", "-sequence")
    list_select_related = ("created_by",)

    # Keep existing admin behavior; just protect system fields from accidental edits
    readonly_fields = ("year", "sequence", "created_by", "created_at")


@admin.register(DiaryMovement)
class DiaryMovementAdmin(admin.ModelAdmin):
    list_display = ("diary", "action_type", "from_office", "to_office", "action_datetime", "created_by")
    list_filter = ("action_type", "action_datetime")
    search_fields = ("from_office", "to_office", "remarks")

    # ✅ Additive admin improvements
    date_hierarchy = "action_datetime"
    ordering = ("-action_datetime", "-id")
    list_select_related = ("diary", "created_by")


# ✅ Add: manage offices for autocomplete / normalization
@admin.register(Office)
class OfficeAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)
    ordering = ("name",)
