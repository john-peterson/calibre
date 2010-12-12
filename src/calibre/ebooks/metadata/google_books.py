from __future__ import with_statement
__license__ = 'GPL 3'
__copyright__ = '2009, Kovid Goyal <kovid@kovidgoyal.net>'
__docformat__ = 'restructuredtext en'

import sys, textwrap, traceback, socket
from threading import Thread
from Queue import Queue
from urllib import urlencode
from functools import partial

from lxml import etree

from calibre import browser, preferred_encoding
from calibre.ebooks.metadata import MetaInformation
from calibre.ebooks.chardet import xml_to_unicode
from calibre.utils.config import OptionParser
from calibre.utils.date import parse_date, utcnow
from calibre.utils.cleantext import clean_ascii_chars

NAMESPACES = {
              'openSearch':'http://a9.com/-/spec/opensearchrss/1.0/',
              'atom' : 'http://www.w3.org/2005/Atom',
              'dc': 'http://purl.org/dc/terms'
            }
XPath = partial(etree.XPath, namespaces=NAMESPACES)

total_results  = XPath('//openSearch:totalResults')
start_index    = XPath('//openSearch:startIndex')
items_per_page = XPath('//openSearch:itemsPerPage')
entry          = XPath('//atom:entry')
entry_id       = XPath('descendant::atom:id')
creator        = XPath('descendant::dc:creator')
identifier     = XPath('descendant::dc:identifier')
title          = XPath('descendant::dc:title')
date           = XPath('descendant::dc:date')
publisher      = XPath('descendant::dc:publisher')
subject        = XPath('descendant::dc:subject')
description    = XPath('descendant::dc:description')
language       = XPath('descendant::dc:language')

class GoogleBooksError(Exception):
    pass

class ThreadwithResults(Thread):
    def __init__(self, func, *args, **kargs):
        self.func = func
        self.args = args
        self.kargs = kargs
        self.result = None
        Thread.__init__(self)

    def get_result(self):
        return self.result

    def run(self):
        self.result = self.func(*self.args, **self.kargs)

def report(verbose):
    if verbose:
        traceback.print_exc()


class Query(object):

    BASE_URL = 'http://books.google.com/books/feeds/volumes?'

    def __init__(self, title=None, author=None, publisher=None, isbn=None,
                 max_results=40, min_viewability='none', start_index=1):
        assert not(title is None and author is None and publisher is None and \
                   isbn is None)
        assert (max_results < 41)
        assert (min_viewability in ('none', 'partial', 'full'))
        if title == _('Unknown'):
            title=None
        if author == _('Unknown'):
            author=None
        self.sindex = str(start_index)
        self.maxresults = int(max_results)
        
        q = []
        if isbn is not None:
            q.append(('isbn:%s') % (isbn,))
        else:
            def build_term(prefix, parts):
                return ' '.join(('in%s:%s') % (prefix, x) for x in parts)
            if title is not None:
                q.append(build_term('title', title.split()))
            if author is not None:
                q.append(build_term('author', author.split()))
            if publisher is not None:
                q.append(build_term('publisher', publisher.split()))
        q='+'.join(q)
        
        if isinstance(q, unicode):
            q = q.encode('utf-8')
        self.urlbase = self.BASE_URL+urlencode({
            'q':q,
            'max-results':max_results,
            'min-viewability':min_viewability,
            })+'&start-index='

    def brcall(self, browser, url, verbose, timeout):
        if verbose:
            print _('Query: %s') % url
        
        try:
            raw = browser.open_novisit(url, timeout=timeout).read()
        except Exception, e:
            report(verbose)
            if callable(getattr(e, 'getcode', None)) and \
                    e.getcode() == 404:
                return None
            attr = getattr(e, 'args', [None])
            attr = attr if attr else [None]
            if isinstance(attr[0], socket.timeout):
                raise GoogleBooksError(_('GoogleBooks timed out. Try again later.'))
            raise GoogleBooksError(_('GoogleBooks encountered an error.'))
        if '<title>404 - ' in raw:
            return None
        raw = xml_to_unicode(raw, strip_encoding_pats=True,
                resolve_entities=True)[0]
        try:
            return etree.fromstring(raw)
        except:
            try:
                #remove ASCII invalid chars (normally not needed)
                return etree.fromstring(clean_ascii_chars(raw))
            except:
                return None

    def __call__(self, browser, verbose, timeout = 5.):
        #get a feed
        url = self.urlbase+self.sindex
        feed = self.brcall(browser, url, verbose, timeout)
        if feed is None:
            return None
        
        # print etree.tostring(feed, pretty_print=True)
        total = int(total_results(feed)[0].text)
        nbresultstoget = total if total<self.maxresults else self.maxresults
        
        start = int(start_index(feed)[0].text)
        entries = entry(feed)
        while len(entries) < nbresultstoget:
            url = self.urlbase+str(start+len(entries))
            feed = self.brcall(browser, url, verbose, timeout)
            if feed is None:
                break
            entries.extend(entry(feed))
        return entries

class ResultList(list):
    def __init__(self):
        self.thread = []

    def get_description(self, entry, verbose):
        try:
            desc = description(entry)
            if desc:
                return 'SUMMARY:\n'+desc[0].text
        except:
            report(verbose)

    def get_language(self, entry, verbose):
        try:
            l = language(entry)
            if l:
                return l[0].text
        except:
            report(verbose)

    def get_title(self, entry):
        candidates = [x.text for x in title(entry)]
        return ': '.join(candidates)

    def get_authors(self, entry):
        m = creator(entry)
        if not m:
            m = []
        m = [x.text for x in m]
        return m

    def get_author_sort(self, entry, verbose):
        for x in creator(entry):
            for key, val in x.attrib.items():
                if key.endswith('file-as'):
                    return val

    def get_identifiers(self, entry, mi):
        isbns = []
        for x in identifier(entry):
            t = str(x.text).strip()
            if t[:5].upper() in ('ISBN:', 'LCCN:', 'OCLC:'):
                if t[:5].upper() == 'ISBN:':
                    isbns.append(t[5:])
        if isbns:
            mi.isbn = sorted(isbns, cmp=lambda x,y:cmp(len(x), len(y)))[-1]

    def get_tags(self, entry, verbose):
        try:
            btags = [x.text for x in subject(entry)]
            tags = []
            for t in btags:
                tags.extend([y.strip() for y in t.split('/')])
            tags = list(sorted(list(set(tags))))
        except:
            report(verbose)
            tags = []
        return [x.replace(',', ';') for x in tags]

    def get_publisher(self, entry, verbose):
        try:
            pub = publisher(entry)[0].text
        except:
            pub = None
        return pub

    def get_date(self, entry, verbose):
        try:
            d = date(entry)
            if d:
                default = utcnow().replace(day=15)
                d = parse_date(d[0].text, assume_utc=True, default=default)
            else:
                d = None
        except:
            report(verbose)
            d = None
        return d

    def fill_MI(self, entry, data, verbose):
        x = entry
        try:
            title = self.get_title(entry)
            x = entry(data)[0]
        except Exception, e:
            if verbose:
                print _('Failed to get all details for an entry')
                print e
        authors = self.get_authors(x)
        mi = MetaInformation(title, authors)
        mi.author_sort = self.get_author_sort(x, verbose)
        mi.comments = self.get_description(x, verbose)
        self.get_identifiers(x, mi)
        mi.tags = self.get_tags(x, verbose)
        mi.publisher = self.get_publisher(x, verbose)
        mi.pubdate = self.get_date(x, verbose)
        mi.language = self.get_language(x, verbose)
        return mi

    def get_individual_metadata(self, url, br, verbose):
        if url is None:
            return None
        try:
            raw = br.open_novisit(url).read()
        except Exception, e:
            report(verbose)
            if callable(getattr(e, 'getcode', None)) and \
                    e.getcode() == 404:
                return None
            attr = getattr(e, 'args', [None])
            attr = attr if attr else [None]
            if isinstance(attr[0], socket.timeout):
                raise GoogleBooksError(_('GoogleBooks timed out. Try again later.'))
            raise GoogleBooksError(_('GoogleBooks encountered an error.'))
        if '<title>404 - ' in raw:
            report(verbose)
            return None
        raw = xml_to_unicode(raw, strip_encoding_pats=True,
                resolve_entities=True)[0]
        try:
            return etree.fromstring(raw)
        except:
            try:
                #remove ASCII invalid chars
                return etree.fromstring(clean_ascii_chars(raw))
            except:
                report(verbose)
                return None

    def fetchdatathread(self, qbr, qsync, nb, url, verbose):
        try:
            browser = qbr.get(True)
            entry = self.get_individual_metadata(url, browser, verbose)
        except:
            report(verbose)
            entry = None
        finally:
            qbr.put(browser, True)
            qsync.put(nb, True)
            return entry

    def producer(self, sync, entries, br, verbose=False):
        for i in xrange(len(entries)):
            try:
                id_url = entry_id(entries[i])[0].text
            except:
                id_url = None
                report(verbose)
            thread = ThreadwithResults(self.fetchdatathread, br, sync,
                                i, id_url, verbose)
            thread.start()
            self.thread.append(thread)

    def consumer(self, entries, sync, total_entries, verbose=False):
        res=[None]*total_entries #remove?
        i=0
        while i < total_entries:
            nb = int(sync.get(True))
            self.thread[nb].join()
            data = self.thread[nb].get_result()
            res[nb] = self.fill_MI(entries[nb], data, verbose)
            i+=1
        return res

    def populate(self, entries, br, verbose=False, brcall=3):
        #multiple entries
        pbr = Queue(brcall)
        sync = Queue(1)
        for i in xrange(brcall-1):
            pbr.put(browser(), True)
        pbr.put(br, True)
        
        prod_thread = Thread(target=self.producer, args=(sync, entries, pbr, verbose))
        cons_thread = ThreadwithResults(self.consumer, entries, sync, len(entries), verbose)
        prod_thread.start()
        cons_thread.start()
        prod_thread.join()
        cons_thread.join()
        self.extend(cons_thread.get_result())


def search(title=None, author=None, publisher=None, isbn=None,
           min_viewability='none', verbose=False, max_results=40):
    br   = browser()
    entries = Query(title=title, author=author, publisher=publisher,
                        isbn=isbn, max_results=max_results,
                            min_viewability=min_viewability)(br, verbose)

    ans = ResultList()
    ans.populate(entries, br, verbose)
    return ans

def option_parser():
    parser = OptionParser(textwrap.dedent(
        '''\
        %prog [options]

        Fetch book metadata from Google. You must specify one of title, author,
        publisher or ISBN. If you specify ISBN the others are ignored. Will
        fetch a maximum of 20 matches, so you should make your query as
        specific as possible.
        '''
    ))
    parser.add_option('-t', '--title', help='Book title')
    parser.add_option('-a', '--author', help='Book author(s)')
    parser.add_option('-p', '--publisher', help='Book publisher')
    parser.add_option('-i', '--isbn', help='Book ISBN')
    parser.add_option('-m', '--max-results', default=10,
                      help='Maximum number of results to fetch')
    parser.add_option('-v', '--verbose', default=0, action='count',
                      help='Be more verbose about errors')
    return parser

def main(args=sys.argv):
    parser = option_parser()
    opts, args = parser.parse_args(args)
    try:
        results = search(opts.title, opts.author, opts.publisher, opts.isbn,
                         verbose=opts.verbose, max_results=opts.max_results)
    except AssertionError:
        report(True)
        parser.print_help()
        return 1
    for result in results:
        print unicode(result).encode(preferred_encoding)
        print

if __name__ == '__main__':
    sys.exit(main())

# C:\Users\Pierre>calibre-debug -e "H:\Mes eBooks\Developpement\calibre\src\calibre\ebooks\metadata\google_books.py" -m 5 -a gore -v>data.html