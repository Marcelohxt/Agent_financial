from django.contrib import admin

from .models import InboundMessage


@admin.register(InboundMessage)
class InboundMessageAdmin(admin.ModelAdmin):
    list_display = ['received_at', 'from_phone', 'membership', 'message_type', 'status']
    list_filter = ['status', 'message_type']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
