# Generated by Django 2.1.8 on 2019-09-26 18:54

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('data_refinery_common', '0041_auto_20190925_2041'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='originalfile',
            index=models.Index(fields=['source_url'], name='original_fi_source__b838ff_idx'),
        ),
    ]