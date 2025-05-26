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
        verbose_name = "Nguồn dữ liệu"
        verbose_name_plural = "Nguồn dữ liệu"


class Article(models.Model):
    """Model để lưu trữ các bài viết đã thu thập"""
    title = models.CharField(max_length=500)
    url = models.URLField(unique=True)
    source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name='articles')
    content_type = models.IntegerField(choices=Source.CONTENT_TYPE_CHOICES)
    published_at = models.DateTimeField()
    fetched_at = models.DateTimeField(auto_now_add=True)
    
    # Metadata bổ sung
    summary = models.TextField(blank=True)
    tags = models.JSONField(default=list, blank=True)
    content = models.TextField(blank=True)  # Nội dung chi tiết bài viết
    thumbnail = models.URLField(blank=True, null=True)  # Ảnh đại diện bài viết
    
    class Meta:
        verbose_name = "Bài viết"
        verbose_name_plural = "Bài viết"
        ordering = ['-published_at']
    
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
        verbose_name = "Log thu thập"
        verbose_name_plural = "Log thu thập"
        ordering = ['-fetched_at']
    
    def __str__(self):
        return f"{self.source.source} - {self.get_status_display()} ({self.fetched_at})"