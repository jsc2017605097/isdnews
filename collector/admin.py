from django.contrib import admin
from .models import Source

@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = ('source', 'url', 'type', 'team')
    search_fields = ('source', 'url')
    list_filter = ('type', 'team')
