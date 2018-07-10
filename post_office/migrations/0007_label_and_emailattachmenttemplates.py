# -*- coding: utf-8 -*-
# Generated by Django 1.11.14 on 2018-07-10 09:02
from __future__ import unicode_literals

from django.db import migrations, models
import post_office.models


class Migration(migrations.Migration):

    dependencies = [
        ('post_office', '0006_attachment_mimetype'),
    ]

    operations = [
        migrations.CreateModel(
            name='AttachmentTemplate',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('file', models.FileField(upload_to=post_office.models.get_upload_path, verbose_name='File')),
                ('name', models.CharField(help_text='The original filename', max_length=255, verbose_name='Name')),
                ('mimetype', models.CharField(blank=True, default='', max_length=255)),
            ],
            options={
                'verbose_name': 'Attachment Template',
                'verbose_name_plural': 'Attachments Template',
            },
        ),
        migrations.AddField(
            model_name='emailtemplate',
            name='label',
            field=models.CharField(blank=True, max_length=255, verbose_name='Label'),
        ),
        migrations.AlterField(
            model_name='attachment',
            name='emails',
            field=models.ManyToManyField(related_name='attachments', to='post_office.Email', verbose_name='Emails'),
        ),
        migrations.AlterField(
            model_name='log',
            name='message',
            field=models.TextField(blank=True, verbose_name='Message'),
        ),
        migrations.AddField(
            model_name='attachmenttemplate',
            name='email_templates',
            field=models.ManyToManyField(related_name='attachments', to='post_office.EmailTemplate', verbose_name='Email templates'),
        ),
    ]
