# Generated by Django 5.2.1 on 2025-05-30 10:07

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('collector', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='systemconfig',
            name='team',
            field=models.ForeignKey(blank=True, help_text='Chọn team (chỉ áp dụng cho Teams Webhook)', null=True, on_delete=django.db.models.deletion.PROTECT, related_name='configs', to='collector.team'),
        ),
    ]
