# -*- coding: utf-8 -*-
from __future__ import unicode_literals
from django import forms
from django.db import models
from django.contrib import admin
from django.conf import settings
from django.forms import BaseInlineFormSet, widgets
from django.forms.widgets import TextInput
from django.template.defaultfilters import safe
from django.utils import six
from django.utils.html import strip_spaces_between_tags, escape
from django.utils.safestring import mark_safe
from django.utils.text import Truncator
from django.utils.translation import ugettext, ugettext_lazy as _, ungettext

from . import settings as postoffice_settings
from .fields import CommaSeparatedEmailField
from .models import Attachment, Log, Email, EmailTemplate, STATUS, AttachmentTemplate
from .utils import render_to_template_email

class LogInline(admin.StackedInline):
    model = Log
    extra = 0

class AttachmentInline(admin.TabularInline):
    model=Attachment.emails.through
    readonly_fields = ('display_attachment',)
    fields = ('display_attachment',)
    extra=0

    def display_attachment(self,obj):
        if obj and obj.file:
            return '<a href="{obj.file.url}" target="_blank">{obj.name}</a>'.format(obj=obj)
        return '---'
    display_attachment.allow_tags= True

class AttachmentTemplateInline(admin.TabularInline):
    model=AttachmentTemplate.email_templates.through
    readonly_fields = ('display_attachment',)
    fields = ('display_attachment',)
    extra=0

    def display_attachment(self,obj):
        if obj and obj.file:
            return '<a href="{obj.file.url}" target="_blank">{obj.name}</a>'.format(obj=obj)
        return '---'
    display_attachment.allow_tags= True



class CommaSeparatedEmailWidget(TextInput):

    def __init__(self, *args, **kwargs):
        super(CommaSeparatedEmailWidget, self).__init__(*args, **kwargs)
        self.attrs.update({'class': 'vTextField'})

    def _format_value(self, value):
        # If the value is a string wrap it in a list so it does not get sliced.
        if not value:
            return ''
        if isinstance(value, six.string_types):
            value = [value, ]
        return ','.join([item for item in value])





class EmailAdmin(admin.ModelAdmin):
    list_display = ('id', 'to_display', 'subject', 'template',
                    'status', 'last_updated')
    list_filter = ['status', 'template']
    search_fields = ('to', 'subject')
    readonly_fields = ("display_mail_preview",)

    actions = ['requeue', 'set_as_sent']
    inlines = [LogInline, AttachmentInline]

    formfield_overrides = {
        CommaSeparatedEmailField: {'widget': CommaSeparatedEmailWidget}
    }

    fieldsets = (
        (None, {'fields': (
            ('subject', 'from_email',),
            ('to', "cc", "bcc",),
            ('html_message',),
            ('display_mail_preview',),
            ('status', 'priority',),
        )}),
    )

    def get_queryset(self, request):
        return super(EmailAdmin, self).get_queryset(request).select_related('template')

    def to_display(self, instance):
        return ', '.join(instance.to)
    to_display.short_description = 'to'
    to_display.admin_order_field = 'to'


    def display_mail_preview(self, obj):
        content = safe(obj.html_message)
        return strip_spaces_between_tags(mark_safe("<div style='width:860px; '><iframe width='100%' height='350px' srcdoc='{mail_message}'>PREVIEW</iframe></div>\
                            ".format(**{'mail_message': escape(strip_spaces_between_tags(content))})))
    display_mail_preview.allow_tags = True
    display_mail_preview.short_description = ugettext("Preview")

    def requeue(self, request, queryset):
        """An admin action to requeue emails."""
        rows_updated = queryset.update(status=STATUS.queued)
        self.message_user(request, ungettext('%(count)d mail was requeued',
                                             '%(count)d mails were requeued',
                                             rows_updated) % {'count': rows_updated})
    requeue.short_description = _('Requeue selected emails')

    def set_as_sent(self, request, queryset):
        """An admin action to requeue emails."""
        rows_updated = queryset.update(status=STATUS.sent)
        self.message_user(request, ungettext('%(count)d mail was set as sent',
                                             '%(count)d mails were set as sent',
                                             rows_updated) % {'count': rows_updated})
    set_as_sent.short_description = _('Set as sent selected emails')

class LogAdmin(admin.ModelAdmin):
    list_display = ('date', 'email', 'status', 'get_message_preview')

    def get_message_preview(self, instance):
        return (u'{0}...'.format(instance.message[:25]) if len(instance.message) > 25
                else instance.message)
    get_message_preview.short_description = 'Message'


class SubjectField(TextInput):
    def __init__(self, *args, **kwargs):
        super(SubjectField, self).__init__(*args, **kwargs)
        self.attrs.update({'style': 'width: 610px;'})

class EmailTemplateAdminForm(forms.ModelForm):

    language = forms.ChoiceField(choices=settings.LANGUAGES, required=False,
                                 widget=widgets.HiddenInput,
                                 help_text=_("Render template in alternative language"),
                                 label=_("Language"))

    class Meta:
        model = EmailTemplate
        exclude=()
        #fields = ('name', 'description', 'subject',
        #          'content', 'html_content', 'language', 'default_template')

class EmailTemplateInlineFormset(BaseInlineFormSet):
    def __init__(self, *args, **kwargs):
        if settings.USE_I18N:
            initial = kwargs.get('initial',[])
            languages = dict(settings.LANGUAGES).keys()
            for ix,language in enumerate(languages):
                try:
                    initial[ix].update({'language':language})
                except IndexError:
                    initial.append({'language': language})
            kwargs.update({'initial':initial})
        return super(EmailTemplateInlineFormset,self).__init__(*args, **kwargs)

class EmailTemplateInline(admin.StackedInline):
    form = EmailTemplateAdminForm
    formset = EmailTemplateInlineFormset
    model = EmailTemplate
    #extra = 0
    fields = ('language', 'template_path',
              'subject', 'content_data',
              'display_html_mail_preview', )#''content', 'html_content',)
    formfield_overrides = {
        models.CharField: {'widget': SubjectField}
    }
    readonly_fields=('display_html_mail_preview',)
    fk_name = 'default_template'

    def get_extra(self, request, obj=None, **kwargs):
        """Hook for customizing the number of extra inline forms."""
        if obj:
            return len(settings.LANGUAGES) - obj.translated_templates.count()
        else:
            return len(settings.LANGUAGES)

    def get_max_num(self, request, obj=None, **kwargs):
        return len(settings.LANGUAGES)

    def display_html_mail_preview(self,obj=None):
        print("obj : {0}".format(obj))
        content_preview = obj.html_content or (obj.default_template and obj.default_template.html_content) or ""
        content_preview = content_preview.replace('{{', '{').replace('}}', '}')
        context = {}
        content_preview = render_to_template_email(content_preview, context)
        context.update({'content': content_preview})
        help_text = '<div class="help">%s</div>' % (_('*Preview data are example data!'))
        return strip_spaces_between_tags(mark_safe("{help_text}<div style='width:860px; height:500px;'><iframe style='margin-left:107px;' width='97%' height='480px' srcdoc='{mail_message}'>PREVIEW</iframe></div>\
                                    ".format(**{'help_text': help_text,
                                                'mail_message': escape(strip_spaces_between_tags(content_preview))})))
    display_html_mail_preview.allow_tags=True
    display_html_mail_preview.short_description=_("Preview HTML")

class EmailTemplateAdmin(admin.ModelAdmin):
    form = EmailTemplateAdminForm
    list_display = ('label', 'name', 'template_path','description_shortened', 'subject', 'languages_compact', 'created')
    search_fields = ('label', 'name', 'description', 'subject')
    readonly_fields = ('display_plain_mail_preview', 'display_html_mail_preview',)
    if settings.USE_I18N:
        inlines = (EmailTemplateInline, AttachmentTemplateInline)
    else:
        inlines = (AttachmentTemplateInline,)

    fieldsets = (
        (None, {
            'fields': (
                ('name',),
                ('label', 'description'),
            )}),
        (_("Default Content"), {
            'fields': (
                ('template_path',),
                ('subject',),
                ('content_data',),
            )}),
        (_("Preview"), {
            'fields': (
                (#'display_plain_mail_preview',
                 'display_html_mail_preview'),
            )}),
    )
    formfield_overrides = {
        models.CharField: {'widget': SubjectField}
    }


    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name == 'template_path':
            kwargs.update({'initial':EmailTemplate.TEMPLATE_CHOICES[0][0]})
        return super(EmailTemplateAdmin,self).formfield_for_dbfield(db_field, request, **kwargs)

    def get_queryset(self, request):
        return self.model.objects.filter(default_template__isnull=True)

    def description_shortened(self, instance):
        return Truncator(instance.description.split('\n')[0]).chars(200)
    description_shortened.short_description = _("Description")
    description_shortened.admin_order_field = 'description'

    def languages_compact(self, instance):
        languages = [tt.language for tt in instance.translated_templates.order_by('language')]
        return ', '.join(languages)
    languages_compact.short_description = _("Languages")

    def save_model(self, request, obj, form, change):
        obj.save()
        # if the name got changed, also change the translated templates to match again
        if 'name' in form.changed_data:
            obj.translated_templates.update(name=obj.name)

    def display_html_mail_preview(self,obj=None):
        content_preview = obj.html_content
        content_preview = content_preview.replace('{{', '{').replace('}}', '}')
        context = {}
        content_preview = render_to_template_email(content_preview, context)
        context.update({'content': content_preview})
        help_text = '<div class="help">%s</div>' % (_('*Preview data are example data!'))
        return strip_spaces_between_tags(mark_safe("{help_text}<div style='width:860px; height:500px;'><iframe style='margin-left:107px;' width='97%' height='480px' srcdoc='{mail_message}'>PREVIEW</iframe></div>\
                                    ".format(**{'help_text': help_text,
                                                'mail_message': escape(strip_spaces_between_tags(content_preview))})))
    display_html_mail_preview.allow_tags=True
    display_html_mail_preview.short_description=_("Preview HTML")

    def display_plain_mail_preview(self,obj=None):
        content_preview = obj.content.replace('{{', '{').replace('}}', '}')
        context = {}
        content_preview = render_to_template_email(content_preview, context, is_plain_text=True)
        context.update({'content': content_preview})
        help_text = '<div class="help">%s</div>' % (_('*Preview data are example data!'))
        return strip_spaces_between_tags(mark_safe("{help_text}<div style='width:860px; height:500px;'><iframe style='margin-left:107px;' width='97%' height='480px' srcdoc='{mail_message}'>PREVIEW</iframe></div>\
                                            ".format(**{'help_text': help_text,
                                                        'mail_message': escape(
                                                            strip_spaces_between_tags(content_preview))})))
    display_plain_mail_preview.allow_tags=True
    display_plain_mail_preview.short_description=_("Preview Plain")


class AttachmentAdmin(admin.ModelAdmin):
    list_display = ('name', 'file', )



'''
class TabbedDjangoJqueryTranslationAdmin(TranslationAdmin):
    """
    Convenience class which includes the necessary media files for tabbed
    translation fields. Reuses Django's internal jquery version.
    """
    class Media:
        js = (
            'modeltranslation/js/force_jquery.js',
            '//ajax.googleapis.com/ajax/libs/jqueryui/1.11.2/jquery-ui.min.js',
            '//cdn.jsdelivr.net/jquery.mb.browser/0.1/jquery.mb.browser.min.js',
            'modeltranslation/js/tabbed_translation_fields.js',
        )
        css = {
            'all': ('modeltranslation/css/tabbed_translation_fields.css',),
        }


class TabbedExternalJqueryTranslationAdmin(TranslationAdmin):
    """
    Convenience class which includes the necessary media files for tabbed
    translation fields. Loads recent jquery version from a cdn.
    """
    class Media:
        js = (
            '//ajax.googleapis.com/ajax/libs/jquery/1.11.1/jquery.min.js',
            '//ajax.googleapis.com/ajax/libs/jqueryui/1.11.2/jquery-ui.min.js',
            '//cdn.jsdelivr.net/jquery.mb.browser/0.1/jquery.mb.browser.min.js',
            'modeltranslation/js/tabbed_translation_fields.js',
        )
        css = {
            'screen': ('modeltranslation/css/tabbed_translation_fields.css',),
        }

'''


admin.site.register(Email, EmailAdmin)
admin.site.register(Log, LogAdmin)
admin.site.register(EmailTemplate, EmailTemplateAdmin)
admin.site.register(Attachment, AttachmentAdmin)
