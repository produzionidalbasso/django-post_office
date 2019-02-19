# -*- coding: utf-8 -*-
import logging

from django.apps import apps
from django.conf import settings
from django.core.exceptions import ValidationError, ImproperlyConfigured
from django.core.files import File
from django.template import Template, Context
from django.utils.encoding import force_text

from post_office import cache
from .compat import string_types
from .settings import get_default_priority, PRIORITY, STATUS
from .validators import validate_email_with_name

import warnings

logger = logging.getLogger(__name__)

def send_mail(subject, message, from_email, recipient_list, html_message='',
              scheduled_time=None, headers=None, priority=PRIORITY.medium):
    """
    Add a new message to the mail queue. This is a replacement for Django's
    ``send_mail`` core email method.
    """

    subject = force_text(subject)
    status = None if priority == PRIORITY.now else STATUS.queued
    emails = []
    for address in recipient_list:
        emails.append(
            apps.get_model('post_office.Email').objects.create(
                from_email=from_email, to=address, subject=subject,
                message=message, html_message=html_message, status=status,
                headers=headers, priority=priority, scheduled_time=scheduled_time
            )
        )
    if priority == PRIORITY.now:
        for email in emails:
            email.dispatch()
    return emails


def get_email_template(name, language=''):
    """
    Function that returns an email template instance, from cache or DB.
    """
    use_cache = getattr(settings, 'POST_OFFICE_CACHE', True)
    if use_cache:
        use_cache = getattr(settings, 'POST_OFFICE_TEMPLATE_CACHE', True)
    if not use_cache:
        return apps.get_model('post_office.EmailTemplate').objects.get(name=name,
                                                                       language=language)
    else:
        composite_name = '%s:%s' % (name, language)
        email_template = cache.get(composite_name)
        if email_template is not None:
            return email_template
        else:
            email_template = apps.get_model('post_office.EmailTemplate').objects.get(
                name=name, language=language)
            cache.set(composite_name, email_template)
            return email_template


def split_emails(emails, split_count=1):
    # Group emails into X sublists
    # taken from http://www.garyrobinson.net/2008/04/splitting-a-pyt.html
    # Strange bug, only return 100 email if we do not evaluate the list
    if list(emails):
        return [emails[i::split_count] for i in range(split_count)]


def create_attachments(attachment_files):
    """
    Create Attachment instances from files

    attachment_files is a dict of:
        * Key - the filename to be used for the attachment.
        * Value - file-like object, or a filename to open OR a dict of {'file': file-like-object, 'mimetype': string}

    Returns a list of Attachment objects
    """
    attachments = []
    for filename, filedata in attachment_files.items():

        if isinstance(filedata, dict):
            content = filedata.get('file', None)
            mimetype = filedata.get('mimetype', None)
        else:
            content = filedata
            mimetype = None

        opened_file = None

        if isinstance(content, string_types):
            # `content` is a filename - try to open the file
            opened_file = open(content, 'rb')
            content = File(opened_file)

        attachment = apps.get_model('post_office.Attachment')
        if mimetype:
            attachment.mimetype = mimetype
        attachment.file.save(filename, content=content, save=True)

        attachments.append(attachment)

        if opened_file is not None:
            opened_file.close()

    return attachments


def parse_priority(priority):
    if priority is None:
        priority = get_default_priority()
    # If priority is given as a string, returns the enum representation
    if isinstance(priority, string_types):
        priority = getattr(PRIORITY, priority, None)

        if priority is None:
            raise ValueError('Invalid priority, must be one of: %s' %
                             ', '.join(PRIORITY._fields))
    return priority


def parse_emails(emails):
    """
    A function that returns a list of valid email addresses.
    This function will also convert a single email address into
    a list of email addresses.
    None value is also converted into an empty list.
    """

    if isinstance(emails, string_types):
        emails = [emails]
    elif emails is None:
        emails = []

    for email in emails:
        try:
            validate_email_with_name(email)
        except ValidationError:
            raise ValidationError('%s is not a valid email address' % email)
    return emails


def render_to_template_email(content='', context=None, is_plain_text=False):
    try:
        template_object = Template(content)
        context_object = Context(context or {})
        template = template_object.render(context_object)
        if is_plain_text:
            template = transform_html_to_plain(template)
            print("plain template: {0}".format(template))
        return template
    except Exception as ex:
        print("content : {0}".format(content))
        warnings.warn(
            "Error in render_to_template_email : {0}".format(ex),
            RuntimeWarning
        )
        return "Preview unavailable"



def transform_html_to_plain(html_content):
    try:
        import html2text
        return html2text.html2text(html_content)
    except ImportError:
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html_content)
            return soup.get_text()
        except ImportError:
            pass
    warnings.warn(
        "Install html2text or BeautifulSoup to render properly email plain content",
        RuntimeWarning
    )
    return html_content

def make_raw_template(template_path, content, block_name="content"):
    """
    function that returns templates who overrides from `template_path` and inject content in the template_path's
    block `block_name`, loading same template_tags and filters used by `template_path`
    :param template_path:
    :param content:
    :param block_name:
    :return: template
    """
    #template_path = template_path or "post_office/base_mail.html"
    from django.template import Context, Engine, TemplateDoesNotExist, loader
    from django.template.base import (
        TOKEN_BLOCK, TOKEN_COMMENT, TOKEN_TEXT, TOKEN_VAR, TRANSLATOR_COMMENT_MARK,
        Lexer)
    from django.core.files.base import ContentFile
    # from pygments import highlight
    # from pygments.lexers import HtmlDjangoLexer
    # from pygments.formatters import HtmlFormatter
    template_dirs = settings.TEMPLATES[0]['DIRS']
    engine = Engine.get_default()

    # Fix for Django 1.8
    html = ''
    for loader in engine.template_loaders:
        html, display_name = loader.load_template_source(
            template_path, template_dirs)
        break

    load_string = ""
    block_content_found = False
    for token_block in Lexer(html, template_path).tokenize():
        if token_block.token_type == TOKEN_BLOCK:
            if token_block.split_contents()[0] == 'load':
                load_string += "{{% {load_str} %}}".format(load_str=token_block.contents)
            elif (token_block.split_contents()[0] == 'block' and
                  token_block.split_contents()[1] == block_name):
                block_content_found = True

    if not block_content_found:
        raise ImproperlyConfigured("`{{% block {block_name} %}}` not found in selected template"
                                   "".format(block_name=block_name))
    raw_template = "{{% extends '{template_path}' %}}".format(template_path=template_path)
    raw_template += load_string
    raw_template += ("{{% block {block_name} %}}{content}{{% endblock {block_name} %}}"
                     "".format(content=content.encode('utf-8'), block_name=block_name))
    return raw_template

def get_template_blocks(template_path="post_office/base_mail.html"):
    from django.template import Context, Engine, TemplateDoesNotExist, loader
    from django.template.base import (
        TOKEN_BLOCK, TOKEN_COMMENT, TOKEN_TEXT, TOKEN_VAR, TRANSLATOR_COMMENT_MARK,
        Lexer)
    from django.core.files.base import ContentFile
    #from pygments import highlight
    #from pygments.lexers import HtmlDjangoLexer
    #from pygments.formatters import HtmlFormatter
    template_dirs = settings.TEMPLATES[0]['DIRS']
    engine = Engine(dirs=template_dirs)
    html = engine.get_template(template_path).source

    #html = loader.get_template(template_path).render()
    _token_opened = False
    _token_closed = False
    _token_block_name = ''
    for t in Lexer(html).tokenize():
        print("-------------------------------\ntype:{0}\n** CONTENT **\n{1}\n## SPLIT CONTENTS {2}"
              "".format(t.token_type, t.contents, t.split_contents()))
        """
        es. 
        {% block content %}lorem 2{% endblock content %}
        
        ...
        -------------------------------
        type:2
        ** CONTENT **
        block content
        ## SPLIT CONTENTS ['block', 'content']
        -------------------------------
        type:0
        ** CONTENT **
        fuffa content
        ## SPLIT CONTENTS ['lorem', '2']
        -------------------------------
        type:2
        ** CONTENT **
        endblock content
        ## SPLIT CONTENTS ['endblock', 'content']
        -------------------------------
        ...
        
        """
        _tokens = []
        if t.token_type == TOKEN_BLOCK:
            if t.split_contents()[0] == 'block':
                _token_opened = True
                _token_block_name = t.split_contents()[1]
                _tokens.append(_token_block_name)
            elif t.split_contents()[0] == 'endblock':
                _token_closed = True
                try:
                    _token_block_name = t.split_contents()[1]
                except IndexError:
                    _token_block_name = _token_block_name
            if _token_opened:
                _token_opened = False
                try:
                    _token_block_name = t.split_contents()[1]
                except IndexError:
                    _token_block_name = ''
            else:
                _token_opened = True
                _token_block_name = t.split_contents()[1]