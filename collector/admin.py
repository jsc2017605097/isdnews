from django.contrib import admin
from .models import Source, FetchLog

@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = ('source', 'url', 'type', 'team')
    search_fields = ('source', 'url')
    list_filter = ('type', 'team')

@admin.register(FetchLog)
class FetchLogAdmin(admin.ModelAdmin):
    list_display = ('fetched_at', 'source', 'status', 'articles_count', 'execution_time', 'error_message')
    list_filter = ('status', 'source', 'fetched_at')
    search_fields = ('error_message', 'source__source')
    date_hierarchy = 'fetched_at'
    readonly_fields = [f.name for f in FetchLog._meta.fields]
