# Generated by Django 2.1.8 on 2019-07-19 12:33

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('data_refinery_common', '0022_auto_20190607_1505'),
    ]

    operations = [
        migrations.AddField(
            model_name='downloaderjob',
            name='volume_index',
            field=models.CharField(max_length=3, null=True),
        ),
    ]
