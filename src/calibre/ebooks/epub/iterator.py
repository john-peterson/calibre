__license__   = 'GPL v3'
__copyright__ = '2008 Kovid Goyal <kovid at kovidgoyal.net>'

'''
Iterate over the HTML files in an ebook. Useful for writing viewers.
'''

import re, os, math, copy
from cStringIO import StringIO

from PyQt4.Qt import QFontDatabase

from calibre.ebooks.epub.from_any import MAP
from calibre.ebooks.epub.from_html import TITLEPAGE
from calibre.ebooks.epub import config
from calibre.ebooks.metadata.opf2 import OPF
from calibre.ptempfile import TemporaryDirectory
from calibre.ebooks.chardet import xml_to_unicode
from calibre.ebooks.html import create_dir
from calibre.utils.zipfile import safe_replace, ZipFile
from calibre.utils.config import DynamicConfig

def character_count(html):
    '''
    Return the number of "significant" text characters in a HTML string.
    '''
    count = 0
    strip_space = re.compile(r'\s+')
    for match in re.finditer(r'>[^<]+<', html):
        count += len(strip_space.sub(' ', match.group()))-2
    return count

class UnsupportedFormatError(Exception):

    def __init__(self, fmt):
        Exception.__init__(self, _('%s format books are not supported')%fmt.upper())

class SpineItem(unicode):

    def __new__(cls, *args):
        args = list(args)
        args[0] = args[0].partition('#')[0]
        obj = super(SpineItem, cls).__new__(cls, *args)
        path = args[0]
        raw = open(path, 'rb').read()
        raw, obj.encoding = xml_to_unicode(raw)
        obj.character_count = character_count(raw)
        obj.start_page = -1
        obj.pages      = -1
        obj.max_page   = -1
        return obj

def html2opf(path, tdir, opts):
    opts = copy.copy(opts)
    opts.output = tdir
    create_dir(path, opts)
    return os.path.join(tdir, 'metadata.opf')

def opf2opf(path, tdir, opts):
    return path

def is_supported(path):
    ext = os.path.splitext(path)[1].replace('.', '').lower()
    ext = re.sub(r'(x{0,1})htm(l{0,1})', 'html', ext)
    return ext in list(MAP.keys())+['html', 'opf']

class EbookIterator(object):

    CHARACTERS_PER_PAGE = 1000

    def __init__(self, pathtoebook):
        pathtoebook = pathtoebook.strip()
        self.pathtoebook = os.path.abspath(pathtoebook)
        self.config = DynamicConfig(name='iterator')
        ext = os.path.splitext(pathtoebook)[1].replace('.', '').lower()
        ext = re.sub(r'(x{0,1})htm(l{0,1})', 'html', ext)
        map = dict(MAP)
        map['html'] = html2opf
        map['opf']  = opf2opf
        if ext not in map.keys():
            raise UnsupportedFormatError(ext)
        self.to_opf = map[ext]

    def search(self, text, index):
        text = text.lower()
        for i, path in enumerate(self.spine):
            if i > index:
                if text in open(path, 'rb').read().decode(path.encoding).lower():
                    return i

    def find_embedded_fonts(self):
        '''
        This will become unnecessary once Qt WebKit supports the @font-face rule.
        '''
        for item in self.opf.manifest:
            if item.mime_type and 'css' in item.mime_type.lower():
                css = open(item.path, 'rb').read().decode('utf-8')
                for match in re.compile(r'@font-face\s*{([^}]+)}').finditer(css):
                    block  = match.group(1)
                    family = re.compile(r'font-family\s*:\s*([^;]+)').search(block)
                    url    = re.compile(r'url\s*\([\'"]*(.+?)[\'"]*\)', re.DOTALL).search(block)
                    if url:
                        path = url.group(1).split('/')
                        path = os.path.join(os.path.dirname(item.path), *path)
                        id = QFontDatabase.addApplicationFont(path)
                        if id != -1:
                            families = [unicode(f) for f in QFontDatabase.applicationFontFamilies(id)]
                            if family:
                                family = family.group(1).strip().replace('"', '')
                                if family not in families:
                                    print 'WARNING: Family aliasing not supported:', block
                                else:
                                    print 'Loaded embedded font:', repr(family)

    def __enter__(self):
        self._tdir = TemporaryDirectory('_ebook_iter')
        self.base  = self._tdir.__enter__()
        opts = config('').parse()
        self.pathtoopf = self.to_opf(self.pathtoebook, self.base, opts)
        self.opf = OPF(self.pathtoopf, os.path.dirname(self.pathtoopf))
        self.spine = [SpineItem(i.path) for i in self.opf.spine]

        cover = self.opf.cover
        if os.path.splitext(self.pathtoebook)[1].lower() in \
                                    ('.lit', '.mobi', '.prc') and cover:
            cfile = os.path.join(os.path.dirname(self.spine[0]), 'calibre_ei_cover.html')
            open(cfile, 'wb').write(TITLEPAGE%cover)
            self.spine[0:0] = [SpineItem(cfile)]

        if self.opf.path_to_html_toc is not None and \
           self.opf.path_to_html_toc not in self.spine:
            self.spine.append(SpineItem(self.opf.path_to_html_toc))


        sizes = [i.character_count for i in self.spine]
        self.pages = [math.ceil(i/float(self.CHARACTERS_PER_PAGE)) for i in sizes]
        for p, s in zip(self.pages, self.spine):
            s.pages = p
        start = 1


        for s in self.spine:
            s.start_page = start
            start += s.pages
            s.max_page = s.start_page + s.pages - 1
        self.toc = self.opf.toc

        self.find_embedded_fonts()
        self.read_bookmarks()

        return self

    def parse_bookmarks(self, raw):
        for line in raw.splitlines():
            if line.count('^') > 0:
                tokens = line.rpartition('^')
                title, ref = tokens[0], tokens[2]
                self.bookmarks.append((title, ref))

    def serialize_bookmarks(self, bookmarks):
        dat = []
        for title, bm in bookmarks:
            dat.append(u'%s^%s'%(title, bm))
        return (u'\n'.join(dat) +'\n').encode('utf-8')

    def read_bookmarks(self):
        self.bookmarks = []
        bmfile = os.path.join(self.base, 'META-INF', 'calibre_bookmarks.txt')
        raw = ''
        if os.path.exists(bmfile):
            raw = open(bmfile, 'rb').read().decode('utf-8')
        else:
            saved = self.config['bookmarks_'+self.pathtoebook]
            if saved:
                raw = saved
        self.parse_bookmarks(raw)

    def save_bookmarks(self, bookmarks=None):
        if bookmarks is None:
            bookmarks = self.bookmarks
        dat = self.serialize_bookmarks(bookmarks)
        if os.path.splitext(self.pathtoebook)[1].lower() == '.epub' and \
            os.access(self.pathtoebook, os.R_OK):
            try:
                zf = open(self.pathtoebook, 'r+b')
            except IOError:
                return
            zipf = ZipFile(zf, mode='a')
            for name in zipf.namelist():
                if name == 'META-INF/calibre_bookmarks.txt':
                    safe_replace(zf, 'META-INF/calibre_bookmarks.txt', StringIO(dat))
                    return
            zipf.writestr('META-INF/calibre_bookmarks.txt', dat)
        else:
            self.config['bookmarks_'+self.pathtoebook] = dat

    def add_bookmark(self, bm):
        dups = []
        for x in self.bookmarks:
            if x[0] == bm[0]:
                dups.append(x)
        for x in dups:
            self.bookmarks.remove(x)
        self.bookmarks.append(bm)
        self.save_bookmarks()

    def __exit__(self, *args):
        self._tdir.__exit__(*args)
