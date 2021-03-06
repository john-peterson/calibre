# -*- coding: utf-8 -*-

from __future__ import (unicode_literals, division, absolute_import, print_function)

__license__ = 'GPL 3'
__copyright__ = '2011, John Schember <john@nachtimwald.com>'
__docformat__ = 'restructuredtext en'

from calibre.utils.mreplace import MReplace

_mreplace = MReplace({
        '&#8211;': '--',
        '&ndash;': '--',
        '–': '--',
        '&#8212;': '---',
        '&mdash;': '---',
        '—': '---',
        '&#8230;': '...',
        '&hellip;': '...',
        '…': '...',
        '&#8220;': '"',
        '&#8221;': '"',
        '&#8243;': '"',
        '&ldquo;': '"',
        '&rdquo;': '"',
        '&Prime;': '"',
        '“':'"',
        '”':'"',
        '″':'"',
        '&#8216;':"'",
        '&#8217;':"'",
        '&#8242;':"'",
        '&lsquo;':"'",
        '&rsquo;':"'",
        '&prime;':"'",
        '‘':"'",
        '’':"'",
        '′':"'",
})

unsmarten_text = _mreplace.mreplace


