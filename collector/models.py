from django.db import models
from django.core.exceptions import ValidationError
import json
from django.utils import timezone

class Source(models.Model):
    TYPE_CHOICES = [
        ('api', 'API Endpoint'),
        ('rss', 'RSS Feed'),
        ('static', 'Web Tĩnh (AgentQL)'),
    ]

    TEAM_CHOICES = [
        ('dev', 'Developer'),
        ('system', 'System'),
        ('ba', 'Business Analyst'),
    ]

    CONTENT_TYPE_CHOICES = [
        (1, 'Kinh tế/Tài chính'),
        (2, 'YouTube/Social Media'),
        (3, 'Công nghệ'),
        (4, 'Tin tức tổng hợp'),
    ]

    url = models.URLField()
    source = models.CharField(max_length=100)
    type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    team = models.CharField(max_length=10, choices=TEAM_CHOICES)
    content_type = models.IntegerField(choices=CONTENT_TYPE_CHOICES, default=4)
    params = models.JSONField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Thông tin về cấu hình thu thập
    fetch_interval = models.IntegerField(default=3600, help_text="Interval in seconds")
    last_fetched = models.DateTimeField(null=True, blank=True)
    force_collect = models.BooleanField(default=False, help_text="Bật để luôn thu thập nguồn này, bỏ qua thời gian chờ")
    
    def clean(self):
        super().clean()
        if self.params:
            try:
                # Validate JSON structure based on type
                if self.type == 'api' and 'headers' in self.params:
                    if not isinstance(self.params['headers'], dict):
                        raise ValidationError({'params': 'API headers must be a dictionary'})
                elif self.type == 'static' and 'prompt' not in self.params:
                    raise ValidationError({'params': 'Static sources must have a prompt parameter'})
            except (TypeError, KeyError) as e:
                raise ValidationError({'params': f'Invalid params structure: {e}'})

    def __str__(self):
        return f"{self.source} ({self.get_type_display()})"

    class Meta:
        verbose_name = "Data Source"
        verbose_name_plural = "Data Sources"
        ordering = ['source']
        app_label = 'collector'


class Article(models.Model):
    """Model để lưu trữ các bài viết đã thu thập"""
    title = models.CharField(max_length=500)
    url = models.URLField(unique=True)
    source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name='articles')
    content_type = models.IntegerField(choices=Source.CONTENT_TYPE_CHOICES, default=4)
    published_at = models.DateTimeField()
    created_at = models.DateTimeField(default=timezone.now)  # Changed from auto_now_add to default
    summary = models.TextField(blank=True)
    content = models.TextField(blank=True)
    thumbnail = models.URLField(blank=True)
    is_ai_processed = models.BooleanField(default=False)
    ai_type = models.CharField(max_length=10, blank=True)
    ai_content = models.TextField(blank=True)
    
    class Meta:
        verbose_name = "Article"
        verbose_name_plural = "Articles"
        ordering = ['-published_at']
        app_label = 'collector'
    
    def __str__(self):
        return self.title


class FetchLog(models.Model):
    """Log việc thu thập dữ liệu"""
    STATUS_CHOICES = [
        ('success', 'Thành công'),
        ('error', 'Lỗi'),
        ('partial', 'Một phần'),
    ]
    
    source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name='fetch_logs')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)
    articles_count = models.IntegerField(default=0)
    error_message = models.TextField(blank=True)
    execution_time = models.FloatField(help_text="Time in seconds")
    fetched_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "Fetch Log"
        verbose_name_plural = "Fetch Logs"
        ordering = ['-fetched_at']
    
    def __str__(self):
        return f"{self.source.source} - {self.get_status_display()} ({self.fetched_at})"


class AILog(models.Model):
    """Log tương tác với OpenRouter AI"""
    url = models.URLField()
    prompt = models.TextField()
    response = models.TextField(blank=True)
    result = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=[('success', 'Thành công'), ('error', 'Lỗi')], default='success')
    error_message = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Log AI (OpenRouter)"
        verbose_name_plural = "Log AI (OpenRouter)"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.url} - {self.status} ({self.created_at})"


class JobConfig(models.Model):
    JOB_TYPE_CHOICES = [
        ('crawl', 'Cào dữ liệu'),
        ('openrouter', 'Gửi OpenRouter'),
    ]
    job_type = models.CharField(max_length=50, choices=JOB_TYPE_CHOICES, unique=True)
    enabled = models.BooleanField(default=True)
    limit = models.IntegerField(default=10)
    round_robin_types = models.JSONField(default=list, blank=True)  # ['dev', 'ba', 'system']
    last_type_sent = models.CharField(max_length=20, blank=True, default='')

    def __str__(self):
        return f"{self.get_job_type_display()} (limit: {self.limit})"

    class Meta:
        verbose_name = "Job Config"
        verbose_name_plural = "Job Configs"
        app_label = "collector"


class SystemConfig(models.Model):
    """Model lưu trữ cấu hình hệ thống"""
    KEY_CHOICES = [
        ('openrouter_api_key', 'OpenRouter API Key'),
        ('teams_webhook', 'Teams Webhook URL')
    ]

    KEY_TYPES = [
        ('api_key', 'API Key'),
        ('webhook', 'Webhook URL'),
    ]

    TEAMS = [
        ('dev', 'Developer'),
        ('system', 'System Admin'),
        ('ba', 'Business Analyst'),
    ]

    key = models.CharField(max_length=100, choices=KEY_CHOICES,
                         help_text="Chọn loại cấu hình cần thiết lập")
    value = models.TextField(help_text="Nhập giá trị cấu hình (API key hoặc webhook URL)")
    key_type = models.CharField(max_length=20, choices=KEY_TYPES)
    team = models.CharField(max_length=20, choices=TEAMS, null=True, blank=True,
                          help_text="Chọn team (chỉ áp dụng cho Teams Webhook)")
    description = models.TextField(blank=True, help_text="Mô tả về cấu hình")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        super().clean()
        if self.key == 'openrouter_api_key':
            self.key_type = 'api_key'
            self.team = None
        else:  # teams_webhook
            self.key_type = 'webhook'
            if not self.team:
                raise ValidationError({'team': 'Team is required for Teams Webhook'})

    def __str__(self):
        if self.team:
            return f"{self.get_key_display()} ({self.get_team_display()})"
        return self.get_key_display()

    class Meta:
        verbose_name = "System Config"
        verbose_name_plural = "System Configs"
        ordering = ['key']
        unique_together = [('key', 'team')]  # Cho phép nhiều webhook với team khác nhau
        app_label = 'collector'