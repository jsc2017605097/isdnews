from django.contrib import admin
from .models import Source, FetchLog, AILog
from django.utils.html import format_html
from django.contrib import messages
from collector.task import collect_data_from_all_sources

@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = ('source', 'url', 'type', 'team', 'is_active', 'fetch_interval', 'force_collect')
    search_fields = ('source', 'url')
    list_filter = ('type', 'team', 'is_active', 'force_collect')

    actions = ['run_collect_all_job']
    def run_collect_all_job(self, request, queryset):
        collect_data_from_all_sources.delay()
        self.message_user(request, "Đã gửi job thu thập tất cả nguồn (chạy nền)!", messages.SUCCESS)
    run_collect_all_job.short_description = "Chạy job thu thập tất cả nguồn (Celery)"

@admin.register(FetchLog)
class FetchLogAdmin(admin.ModelAdmin):
    list_display = ('fetched_at', 'source', 'status', 'articles_count', 'execution_time', 'error_message')
    list_filter = ('status', 'source', 'fetched_at')
    search_fields = ('error_message', 'source__source')
    date_hierarchy = 'fetched_at'
    readonly_fields = [f.name for f in FetchLog._meta.fields]

@admin.register(AILog)
class AILogAdmin(admin.ModelAdmin):
    def short_prompt(self, obj):
        if len(obj.prompt) > 100:
            return format_html('<span title="{}">{}...</span>', obj.prompt, obj.prompt[:100])
        return obj.prompt
    short_prompt.short_description = 'Prompt'

    def short_result(self, obj):
        if len(obj.result) > 100:
            return format_html('<span title="{}">{}...</span>', obj.result, obj.result[:100])
        return obj.result
    short_result.short_description = 'Result'

    list_display = ('created_at', 'url', 'status', 'error_message', 'short_prompt', 'response', 'short_result')
    search_fields = ('url', 'prompt', 'result', 'error_message')
    list_filter = ('status', 'created_at')
    readonly_fields = [f.name for f in AILog._meta.fields]
    date_hierarchy = 'created_at'
