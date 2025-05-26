from django.db import models

class Source(models.Model):
    TYPE_CHOICES = [
        ('api', 'API Endpoint'),
        ('static', 'Web Tĩnh'),
    ]

    TEAM_CHOICES = [
        ('dev', 'Developer'),
        ('system', 'System'),
        ('ba', 'Business Analyst'),
    ]

    url = models.URLField()
    source = models.CharField(max_length=100)
    type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    team = models.CharField(max_length=10, choices=TEAM_CHOICES)
    params = models.JSONField(blank=True, null=True)  # Django 3.1+ hỗ trợ JSON

    def __str__(self):
        return f"{self.source} ({self.url})"
