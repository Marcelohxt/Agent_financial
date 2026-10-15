from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Membership, User, Workspace

admin.site.register(User, UserAdmin)


class MembershipInline(admin.TabularInline):
    model = Membership
    extra = 0


@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    list_display = ['name', 'created_at']
    inlines = [MembershipInline]
