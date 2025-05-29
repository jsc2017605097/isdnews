from django.contrib import admin
from .models import Source, FetchLog, AILog, JobConfig, Article
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from django.contrib import messages
from collector.task import collect_data_from_all_sources

# Đăng ký các model theo thứ tự hiển thị trong admin
@admin.register(Source)
class SourceAdmin(admin.ModelAdmin):
    class Media:
        css = {'all': ('admin/css/custom.css',)}

    verbose_name = _('Nguồn dữ liệu')
    verbose_name_plural = _('Nguồn dữ liệu')
    ordering = ['source']

    list_display = ('source', 'url', 'type', 'team', 'is_active', 'fetch_interval', 'force_collect')
    search_fields = ('source', 'url')
    list_filter = ('type', 'team', 'is_active', 'force_collect')
    order = 1  # Đặt thứ tự hiển thị

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

@admin.register(JobConfig)
class JobConfigAdmin(admin.ModelAdmin):
    list_display = ['job_type', 'enabled', 'limit', 'round_robin_types', 'last_type_sent']
    list_editable = ['enabled']
    search_fields = ['job_type']
    list_filter = ['enabled', 'job_type']

    def get_fields(self, request, obj=None):
        fields = ['job_type', 'enabled', 'round_robin_types', 'last_type_sent']
        if not obj or obj.job_type == 'crawl':
            fields.insert(2, 'limit')
        return fields

    def get_readonly_fields(self, request, obj=None):
        return ['last_type_sent']

@admin.register(Article) 
class ArticleAdmin(admin.ModelAdmin):
    class Media:
        css = {'all': ('admin/css/custom.css',)}

    verbose_name = _('Bài viết')
    verbose_name_plural = _('Bài viết')
    ordering = ['-published_at']

    def short_content(self, obj):
        if obj.content and len(obj.content) > 100:
            return format_html('<span title="{}">{}&hellip;</span>', obj.content, obj.content[:100])
        return obj.content or ''
    short_content.short_description = 'Nội dung'

    def short_summary(self, obj):
        if obj.summary and len(obj.summary) > 100:
            return format_html('<span title="{}">{}&hellip;</span>', obj.summary, obj.summary[:100])
        return obj.summary or ''
    short_summary.short_description = 'Tóm tắt'

    def short_ai_content(self, obj):
        if obj.ai_content and len(obj.ai_content) > 100:
            return format_html('<span title="{}">{}&hellip;</span>', obj.ai_content, obj.ai_content[:100])
        return obj.ai_content or ''
    short_ai_content.short_description = 'Nội dung AI'

    list_display = ('title', 'source', 'content_type', 'published_at', 'short_summary', 'short_content', 'short_ai_content', 'is_ai_processed')
    list_filter = ('source', 'content_type', 'is_ai_processed', 'published_at')
    search_fields = ('title', 'content', 'summary', 'ai_content')
    date_hierarchy = 'published_at' 
    ordering = ('-published_at',)

# Sắp xếp menu trong admin
def get_app_list(self, request, app_label=None):
    """
    Tùy chỉnh thứ tự hiển thị các model trong admin
    """
    app_dict = self._build_app_dict(request, app_label)
    app_list = sorted(app_dict.values(), key=lambda x: x['name'].lower())

    for app in app_list:
        if app['app_label'] == 'collector':
            app['models'].sort(key=lambda x: {
                'Source': 1,
                'Article': 2,
                'FetchLog': 3,
                'AILog': 4,
                'JobConfig': 5,
            }.get(x['object_name'], 10))
    return app_list

admin.AdminSite.get_app_list = get_app_list