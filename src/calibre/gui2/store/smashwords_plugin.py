# -*- coding: utf-8 -*-

__license__ = 'GPL 3'
__copyright__ = '2011, John Schember <john@nachtimwald.com>'
__docformat__ = 'restructuredtext en'

import random
import re
import urllib2
from contextlib import closing

from lxml import html

from calibre import browser
from calibre.gui2.store import StorePlugin
from calibre.gui2.store.basic_config import BasicStoreConfig
from calibre.gui2.store.search_result import SearchResult
from calibre.gui2.store.web_store_dialog import WebStoreDialog

class SmashwordsStore(BasicStoreConfig, StorePlugin):

    def open(self, parent=None, detail_item=None, external=False):
        settings = self.get_settings()
        aff_id = 'usernone'
        # Use Kovid's affiliate id 30% of the time.
        if random.randint(1, 10) in (1, 2, 3):
            aff_id = 'kovidgoyal'
        d = WebStoreDialog(self.gui, 'http://www.smashwords.com/?ref=%s' % aff_id, parent, detail_item)
        d.setWindowTitle(self.name)
        d.set_tags(settings.get(self.name + '_tags', ''))
        d = d.exec_()

    def search(self, query, max_results=10, timeout=60):
        url = 'http://www.smashwords.com/books/search?query=' + urllib2.quote(query)
        
        br = browser()
        
        counter = max_results
        with closing(br.open(url, timeout=timeout)) as f:
            doc = html.fromstring(f.read())
            for data in doc.xpath('//div[@id="pageCenterContent2"]//div[@class="bookCoverImg"]'):
                if counter <= 0:
                    break
                data = html.fromstring(html.tostring(data))
                
                id = None
                id_a = data.xpath('//a[@class="bookTitle"]')
                if id_a:
                    id = id_a[0].get('href', None)
                    if id:
                        id = id.split('/')[-1]
                if not id:
                    continue
                
                cover_url = ''
                c_url = data.get('style', None)
                if c_url:
                    mo = re.search(r'http://[^\'"]+', c_url)
                    if mo:
                        cover_url = mo.group()
                
                title = ''.join(data.xpath('//a[@class="bookTitle"]/text()'))
                subnote = ''.join(data.xpath('//span[@class="subnote"]/text()'))
                author = ''.join(data.xpath('//span[@class="subnote"]/a/text()'))
                price = subnote.partition('$')[2]
                price = price.split(u'\xa0')[0]
                price = '$' + price

                counter -= 1
                
                s = SearchResult()
                s.cover_url = cover_url
                s.title = title.strip()
                s.author = author.strip()
                s.price = price.strip()
                s.detail_item = '/books/view/' + id.strip()
                
                yield s
