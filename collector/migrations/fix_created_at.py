from django.db import migrations
from django.utils import timezone

def set_created_at(apps, schema_editor):
    Article = apps.get_model('collector', 'Article')
    for article in Article.objects.filter(created_at__isnull=True):
        article.created_at = article.published_at
        article.save()

class Migration(migrations.Migration):
    dependencies = [
        ('collector', '0006_alter_source_options_remove_article_fetched_at_and_more'),
    ]

    operations = [
        migrations.RunPython(set_created_at),
    ]