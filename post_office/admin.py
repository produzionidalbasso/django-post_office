# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import logging
import warnings


from django import forms
from django.contrib import admin
from django.conf import settings
from django.core.exceptions import ValidationError, ImproperlyConfigured
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

logger = logging.getLogger(__name__)

class LogInline(admin.StackedInline):
    model = Log
    extra = 0

class AttachmentInline(admin.TabularInline):
    model=Attachment.emails.through
    readonly_fields = ('display_attachment',)
    fields = ('display_attachment',)
    extra=0

    def display_attachment(self,obj):
        if obj and obj.attachment and obj.attachment.file:
            return mark_safe('<a href="{0}" target="_blank">{1}</a>'.format(obj.attachment.file.url, obj.attachment.name))
        return '---'


class AttachmentTemplateInline(admin.TabularInline):
    model=AttachmentTemplate.email_templates.through
    fields = ('attachmenttemplate',)
    extra=0
    verbose_name = _("Email Attachment")
    verbose_name_plural = _("Email Attachments")

    @mark_safe
    def display_attachment(self,obj):
        if obj and obj.file:
            return '<a href="{obj.file.url}" target="_blank">{obj.name}</a>'.format(obj=obj)
        return '---'


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

    @mark_safe
    def display_mail_preview(self, obj):
        content = safe(obj.html_message)
        return strip_spaces_between_tags("<div style='width:860px; '><iframe width='100%' height='350px' srcdoc='{mail_message}'>PREVIEW</iframe></div>\
                            ".format(**{'mail_message': escape(strip_spaces_between_tags(content))}))
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
                                 label=_("Language"),)

    class Meta:
        model = EmailTemplate
        exclude=()


class EmailTemplateInlineFormset(BaseInlineFormSet):

    def __init__(self, *args, **kwargs):
        if settings.USE_I18N:
            initial = kwargs.get('initial',[])
            languages = dict(settings.LANGUAGES).keys()
            instance = kwargs.get('instance', None)
            if not instance:
                # If there isn't the instance, I add all project languages
                for ix,language in enumerate(languages):
                    if language != settings.LANGUAGE_CODE:
                        try:
                            initial[ix].update({'language':language})
                        except IndexError:
                            initial.append({'language': language})
            else:
                # if there is the instance, I add only languages that miss in the translated_templated
                for ix,language in enumerate(languages):
                    # boolean variable that is used to find languages to add in 'initial'
                    lang_finded = False
                    # iteration on translated_templates
                    for translated_template in instance.translated_templates.all():
                        if translated_template.language == language:
                            # translated_template finded --> language not to be included in initial
                            lang_finded = True
                            break
                    # I add language only if it isn't in translated_templates
                    if not lang_finded:
                        if language != settings.LANGUAGE_CODE:
                            try:
                                initial[ix].update({'language':language})
                            except IndexError:
                                initial.append({'language': language})
            kwargs.update({'initial':initial})
        return super(EmailTemplateInlineFormset,self).__init__(*args, **kwargs)

class EmailTemplateAdminMixin(object):

    def get_readonly_fields(self, request, obj=None):
        """
        Hook for specifying custom readonly fields.
        """
        _readonly_fields = super(EmailTemplateAdminMixin,self).get_readonly_fields(request, obj=obj)
        return list(_readonly_fields) + ['display_html_mail_preview',
                                         'display_plain_mail_preview',]

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name == 'subject':
            kwargs.update({'widget': SubjectField,
                           'required': True})
        elif db_field.name == 'content_data':
            kwargs.update({'required': True,})
            _editor_found=False
            for _editor in postoffice_settings.get_wysiwyg_editors():
                try:
                    _module_name = _editor[0]
                    _widget = _editor[1]
                    _widget_attrs = _editor[2]
                    WysiwygEditor = getattr(__import__(_module_name, {}, {}, [_widget]), _widget)
                    kwargs.update({
                        'widget': WysiwygEditor(**_widget_attrs)
                    })
                    editor_found = True
                    break
                except ImportError:
                    logger.exception("Error Importing WYSIWYG Editor")
                except IndexError:
                    raise ImproperlyConfigured("POST_OFFICE.WYSIWYG_EDITORS setting entries are not in form of (<module>,<Editor>) ")
            if not _editor_found:
                warnings.warn("Cannot use any editor between {0} because they are not installed. "
                              "Have you installed and configured one of them properly?"
                              "Either you can configure POSTOFFICE_WYSIWYG_EDITORS to use your own editor"
                              "".format([_editor[1]
                                         for _editor
                                         in postoffice_settings.get_wysiwyg_editors()]),
                              ImportWarning)
        return super(EmailTemplateAdminMixin,self).formfield_for_dbfield(db_field, request, **kwargs)

    def display_html_mail_preview(self,obj=None):
        content_preview = render_to_template_email(obj.html_content.replace('{{', '{').replace('}}', '}'), {},
                                                   is_plain_text=False)
        return mark_safe(strip_spaces_between_tags(mark_safe("""
            <div>
                <iframe width='97%' height='480px' srcdoc='{mail_message}'>PREVIEW</iframe>
                <div class='help' style='margin-left:0;padding-left:0'>{help_text}</div>
            </div>
            """.format(**{'help_text': _('*The field in brackets are variables!'),
                         'mail_message': escape(strip_spaces_between_tags(content_preview))})
        )))
    display_html_mail_preview.short_description=_("Preview HTML")

    def display_plain_mail_preview(self,obj=None):
        content_preview = render_to_template_email(obj.html_content.replace('{{', '{').replace('}}', '}'), {},
                                                   is_plain_text=True)
        return mark_safe(strip_spaces_between_tags(mark_safe("""
                <div style='width: 100%;'>
                    <iframe width='97%' height='480px' srcdoc='{mail_message}'>PREVIEW</iframe>
                    <div class='help' style='margin-left:0;padding-left:0'>{help_text}</div>
                </div>
                """.format(**{'help_text': _('*The field in brackets are variables!'),
                              'mail_message': escape(strip_spaces_between_tags(content_preview))})
                                                             )))
    display_plain_mail_preview.short_description=_("Preview Plain")

class EmailTemplateInline(EmailTemplateAdminMixin,
                          admin.StackedInline):
    form = EmailTemplateAdminForm
    formset = EmailTemplateInlineFormset
    model = EmailTemplate
    verbose_name_plural = _("Email Contents")
    #extra = 0
    fk_name = 'default_template'

    fieldsets = ((None, {
        'fields': (
            ('language', 'template_path','subject',),
            ('content_data',),
            ('display_html_mail_preview',),
        ),
    }),)


    def get_extra(self, request, obj=None, **kwargs):
        """Hook for customizing the number of extra inline forms."""
        if obj:
            return len(settings.LANGUAGES) - 1 - obj.translated_templates.count()
        else:
            return len(settings.LANGUAGES) - 1

    def get_max_num(self, request, obj=None, **kwargs):
        return len(settings.LANGUAGES) - 1

class EmailTemplateAdmin(EmailTemplateAdminMixin,
                         admin.ModelAdmin):
    change_form_template = 'admin/post_office/email_template_change_form.html'
    form = EmailTemplateAdminForm
    list_display = ('label', 'name', 'template_path','description_shortened', 'subject', 'languages_compact', 'created')
    search_fields = ('label', 'name', 'description', 'subject')
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
        (None, {
            'fields': (
                ('template_path','subject',),
                ('content_data',),
                ('display_html_mail_preview'),
            ),
            'classes':['js-move-to-tabs-default']
        }),
    )


    def render_change_form(self, request, context, **kwargs):
        context = context or {}
        context.update({
            "DEFAULT_LANGUAGE": settings.LANGUAGE_CODE,
            "USE_I18N": settings.USE_I18N
        })
        return super(EmailTemplateAdmin,self).render_change_form(request, context, **kwargs)

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


class AttachmentAdmin(admin.ModelAdmin):
    list_display = ('name', 'file', 'mimetype')

class AttachmentTemplateAdmin(admin.ModelAdmin):
    list_display = ('name', 'file', 'mimetype')
    fields = ('name', 'file', 'mimetype')



admin.site.register(Email, EmailAdmin)
admin.site.register(Log, LogAdmin)
admin.site.register(EmailTemplate, EmailTemplateAdmin)
admin.site.register(Attachment, AttachmentAdmin)
admin.site.register(AttachmentTemplate, AttachmentTemplateAdmin)