#!/usr/bin/env python
# vim:fileencoding=UTF-8:ts=4:sw=4:sta:et:sts=4:ai
from __future__ import with_statement

__license__   = 'GPL v3'
__copyright__ = '2009, Kovid Goyal <kovid@kovidgoyal.net>'
__docformat__ = 'restructuredtext en'


from calibre.gui2.convert.epub_output_ui import Ui_Form
from calibre.gui2.convert import Widget

class PluginWidget(Widget, Ui_Form):

    TITLE = _('EPUB Output')

    def __init__(self, parent, get_option, get_help, db=None, book_id=None):
        Widget.__init__(self, parent, 'epub_output',
                ['dont_split_on_page_breaks']
                )
        self.db, self.book_id = db, book_id
        self.initialize_options(get_option, get_help, db, book_id)

