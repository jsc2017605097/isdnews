# Generated migration for updated models
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('collector', '0001_initial'),
    ]

    operations = [
        # Update Source model
        migrations.AddField(
            model_name='source',
            name='content_type',
            field=models.IntegerField(choices=[(1, 'Kinh tế/Tài chính'), (2, 'YouTube/Social Media'), (3, 'Công nghệ'), (4, 'Tin tức tổng hợp')], default=4),
        ),
        migrations.AddField(
            model_name='source',
            name='is_active',
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name='source',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, null=True),
        ),
        migrations.AddField(
            model_name='source',
            name='updated_at',
            field=models.DateTimeField(auto_now=True, null=True),
        ),
        migrations.AddField(
            model_name='source',
            name='fetch_interval',
            field=models.IntegerField(default=3600, help_text='Interval in seconds'),
        ),
        migrations.AddField(
            model_name='source',
            name='last_fetched',
            field=models.DateTimeField(blank=True, null=True),
        ),
        
        # Update type choices
        migrations.AlterField(
            model_name='source',
            name='type',
            field=models.CharField(choices=[('api', 'API Endpoint'), ('rss', 'RSS Feed'), ('static', 'Web Tĩnh (AgentQL)')], max_length=10),
        ),
        
        # Create Article model
        migrations.CreateModel(
            name='Article',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=500)),
                ('url', models.URLField(unique=True)),
                ('content_type', models.IntegerField(choices=[(1, 'Kinh tế/Tài chính'), (2, 'YouTube/Social Media'), (3, 'Công nghệ'), (4, 'Tin tức tổng hợp')])),
                ('published_at', models.DateTimeField()),
                ('fetched_at', models.DateTimeField(auto_now_add=True)),
                ('summary', models.TextField(blank=True)),
                ('tags', models.JSONField(blank=True, default=list)),
                ('source', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='articles', to='collector.source')),
            ],
            options={
                'verbose_name': 'Bài viết',
                'verbose_name_plural': 'Bài viết',
                'ordering': ['-published_at'],
            },
        ),
        
        # Create FetchLog model
        migrations.CreateModel(
            name='FetchLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('success', 'Thành công'), ('error', 'Lỗi'), ('partial', 'Một phần')], max_length=10)),
                ('articles_count', models.IntegerField(default=0)),
                ('error_message', models.TextField(blank=True)),
                ('execution_time', models.FloatField(help_text='Time in seconds')),
                ('fetched_at', models.DateTimeField(auto_now_add=True)),
                ('source', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='fetch_logs', to='collector.source')),
            ],
            options={
                'verbose_name': 'Log thu thập',
                'verbose_name_plural': 'Log thu thập',
                'ordering': ['-fetched_at'],
            },
        ),
    ]