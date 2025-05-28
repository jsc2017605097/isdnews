from django.db import migrations

class Migration(migrations.Migration):
    dependencies = [
        ('collector', '0004_jobconfig_article_ai_content_article_ai_type_and_more'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='jobconfig',
            name='interval',
        ),
    ]