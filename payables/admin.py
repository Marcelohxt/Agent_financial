from django.contrib import admin

from .models import Bill, Document, Holder, Payment, PaymentAllocation, Supplier


@admin.register(Holder)
class HolderAdmin(admin.ModelAdmin):
    list_display = ['name', 'document_type', 'document', 'workspace']


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ['name', 'document', 'workspace']


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ['kind', 'original_name', 'source', 'received_at', 'workspace']
    readonly_fields = ['sha256']


@admin.register(Bill)
class BillAdmin(admin.ModelAdmin):
    list_display = ['description', 'supplier', 'amount', 'due_date', 'status', 'workspace']
    list_filter = ['status', 'workspace']
    # Status e aprovação só mudam pelas regras em payables.services, nunca editando aqui.
    readonly_fields = [
        'status', 'approved_by', 'approved_at', 'cancelled_by', 'cancelled_at', 'created_by',
    ]


class AllocationInline(admin.TabularInline):
    model = PaymentAllocation
    extra = 0
    can_delete = False
    readonly_fields = ['bill', 'amount']

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ['paid_at', 'amount', 'method', 'registered_by', 'workspace']
    inlines = [AllocationInline]

    def has_change_permission(self, request, obj=None):
        return False

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
