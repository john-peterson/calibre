__license__   = 'GPL v3'
__copyright__ = '2008, Kovid Goyal <kovid at kovidgoyal.net>'
import os, textwrap, traceback, time
from datetime import timedelta, datetime
from operator import attrgetter
from collections import deque 
from math import cos, sin, pi
from itertools import repeat
from PyQt4.QtGui import QTableView, QProgressDialog, QAbstractItemView, QColor, \
                        QItemDelegate, QPainterPath, QLinearGradient, QBrush, \
                        QPen, QStyle, QPainter, QLineEdit, \
                        QPalette, QImage, QApplication
from PyQt4.QtCore import QAbstractTableModel, QVariant, Qt, QString, \
                         QCoreApplication, SIGNAL, QObject, QSize, QModelIndex, \
                         QTimer

from calibre import Settings, preferred_encoding
from calibre.ptempfile import PersistentTemporaryFile
from calibre.library.database import LibraryDatabase, text_to_tokens
from calibre.gui2 import NONE, TableView, qstring_to_unicode

class LibraryDelegate(QItemDelegate):
    COLOR    = QColor("blue")
    SIZE     = 16
    PEN      = QPen(COLOR, 1, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    
    def __init__(self, parent):
        QItemDelegate.__init__(self, parent)
        self.star_path = QPainterPath()
        self.star_path.moveTo(90, 50)
        for i in range(1, 5):
            self.star_path.lineTo(50 + 40 * cos(0.8 * i * pi), \
                                  50 + 40 * sin(0.8 * i * pi))
        self.star_path.closeSubpath()
        self.star_path.setFillRule(Qt.WindingFill)
        gradient = QLinearGradient(0, 0, 0, 100)
        gradient.setColorAt(0.0, self.COLOR)
        gradient.setColorAt(1.0, self.COLOR)
        self.brush = QBrush(gradient)
        self.factor = self.SIZE/100.

    def sizeHint(self, option, index):
        #num = index.model().data(index, Qt.DisplayRole).toInt()[0]
        return QSize(5*(self.SIZE), self.SIZE+4)
    
    def paint(self, painter, option, index):
        num = index.model().data(index, Qt.DisplayRole).toInt()[0]
        def draw_star(): 
            painter.save()
            painter.scale(self.factor, self.factor)
            painter.translate(50.0, 50.0)
            painter.rotate(-20)
            painter.translate(-50.0, -50.0)
            painter.drawPath(self.star_path)
            painter.restore()
        
        painter.save()
        if hasattr(QStyle, 'CE_ItemViewItem'):
            QApplication.style().drawControl(QStyle.CE_ItemViewItem, option, painter)
        elif option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())
        try:
            painter.setRenderHint(QPainter.Antialiasing)
            y = option.rect.center().y()-self.SIZE/2. 
            x = option.rect.right()  - self.SIZE
            painter.setPen(self.PEN)      
            painter.setBrush(self.brush)      
            painter.translate(x, y)
            i = 0
            while i < num:
                draw_star()
                painter.translate(-self.SIZE, 0)
                i += 1
        except Exception, e:
            traceback.print_exc(e)
        painter.restore()
        
    def createEditor(self, parent, option, index):
        sb = QItemDelegate.createEditor(self, parent, option, index)
        sb.setMinimum(0)
        sb.setMaximum(5)
        return sb

class BooksModel(QAbstractTableModel):
    coding = zip(
    [1000,900,500,400,100,90,50,40,10,9,5,4,1],
    ["M","CM","D","CD","C","XC","L","XL","X","IX","V","IV","I"]
    )
    @classmethod
    def roman(cls, num):
        if num <= 0 or num >= 4000 or int(num) != num:
            return str(num)
        result = []
        for d, r in cls.coding:
            while num >= d:
                result.append(r)
                num -= d
        return ''.join(result)

    def __init__(self, parent=None, buffer=20):
        QAbstractTableModel.__init__(self, parent)
        self.db = None
        self.cols = ['title', 'authors', 'size', 'date', 'rating', 'publisher', 'tags', 'series']
        self.editable_cols = [0, 1, 4, 5, 6]
        self.default_image = QImage(':/images/book.svg')
        self.sorted_on = (3, Qt.AscendingOrder)
        self.last_search = '' # The last search performed on this model
        self.read_config()
        self.buffer_size = buffer
        self.clear_caches()
        self.load_timer = QTimer()
        self.connect(self.load_timer, SIGNAL('timeout()'), self.load)
        self.load_timer.start(50)
        
    def clear_caches(self):
        self.buffer = {}
        self.load_queue = deque()
        
    def read_config(self):
        self.use_roman_numbers = Settings().get('use roman numerals for series number', True)
        
    
    def set_database(self, db):
        if isinstance(db, (QString, basestring)):
            if isinstance(db, QString):
                db = qstring_to_unicode(db)    
            db = LibraryDatabase(os.path.expanduser(db))
        self.db = db
        
    def refresh_ids(self, ids, current_row=-1):
        rows = self.db.refresh_ids(ids)
        for row in rows:
            self.buffer.pop(row, None)
            if row == current_row:
                self.emit(SIGNAL('new_bookdisplay_data(PyQt_PyObject)'), 
                          self.get_book_display_info(row))
            self.emit(SIGNAL('dataChanged(QModelIndex,QModelIndex)'), 
                      self.index(row, 0), self.index(row, self.columnCount(None)-1))
        
    def close(self):
        self.db.close()
        self.db = None
        self.reset()
        
    def add_books(self, paths, formats, metadata, uris=[], add_duplicates=False):
        return self.db.add_books(paths, formats, metadata, uris, 
                                 add_duplicates=add_duplicates)
        
    def row_indices(self, index):
        ''' Return list indices of all cells in index.row()'''
        return [ self.index(index.row(), c) for c in range(self.columnCount(None))]
        
    def save_to_disk(self, rows, path, single_dir=False, single_format=None):
        rows = [row.row() for row in rows]
        if single_format is None:
            return self.db.export_to_dir(path, rows, self.sorted_on[0] == 1, single_dir=single_dir)
        else:
            return self.db.export_single_format_to_dir(path, rows, single_format)
        
        
    def delete_books(self, indices):
        ids = [ self.id(i) for i in indices ]
        for id in ids:
            row = self.db.index(id)
            self.beginRemoveRows(QModelIndex(), row, row)
            self.db.delete_book(id)
            self.endRemoveRows()
        self.clear_caches()
        self.reset()
    
    def search_tokens(self, text):
        return text_to_tokens(text)
            
    def search(self, text, refinement, reset=True):
        tokens, OR = self.search_tokens(text)
        self.db.filter(tokens, refilter=refinement, OR=OR)
        self.last_search = text
        if reset:
            self.clear_caches()
            self.reset()
            
    def sort(self, col, order, reset=True):
        if not self.db:
            return
        ascending = order == Qt.AscendingOrder
        self.db.refresh(self.cols[col], ascending)
        self.research()
        if reset:
            self.clear_caches()
            self.reset()     
        self.sorted_on = (col, order)
        
    def resort(self, reset=True):
        self.sort(*self.sorted_on, **dict(reset=reset))
        
    def research(self, reset=True):
        self.search(self.last_search, False, reset=reset)
        
    def database_needs_migration(self):
        path = os.path.expanduser('~/library.db')
        return self.db.is_empty() and \
               os.path.exists(path) and\
               LibraryDatabase.sizeof_old_database(path) > 0
            
    def columnCount(self, parent):
        return len(self.cols)
    
    def rowCount(self, parent):
        return self.db.rows() if self.db else 0
    
    def count(self):
        return self.rowCount(None)
    
    def load(self):
        if self.load_queue:
            index = self.load_queue.popleft()
            if self.buffer.has_key(index):
                return
            data = self.db.cover(index)
            img = QImage()
            img.loadFromData(data)
            if img.isNull():
                img = self.default_image
            self.buffer[index] = img
    
    def get_book_display_info(self, idx):
        data = {}
        cdata = self.cover(idx)
        if cdata:
            data['cover'] = cdata
        tags = self.db.tags(idx)
        if tags:
            tags = tags.replace(',', ', ')
        else:
            tags = _('None')
        data[_('Tags')] = tags
        formats = self.db.formats(idx)
        if formats:
            formats = formats.replace(',', ', ')
        else:
            formats = _('None')
        data[_('Formats')] = formats
        comments = self.db.comments(idx)
        if not comments:
            comments = _('None')
        data[_('Comments')] = comments
        series = self.db.series(idx)
        if series:
            sidx = self.db.series_index(idx)
            sidx = self.__class__.roman(sidx) if self.use_roman_numbers else str(sidx)
            data[_('Series')] = _('Book <font face="serif">%s</font> of %s.')%(sidx, series)
            
        return data
    
    def current_changed(self, current, previous, emit_signal=True):
        
        idx = current.row()
        
        for key in self.buffer.keys():
            if abs(key - idx) > self.buffer_size:
                self.buffer.pop(key)
        for i in range(max(0, idx-self.buffer_size), min(self.count(), idx+self.buffer_size)):
            if not self.buffer.has_key(i):
                self.load_queue.append(i)
        
        data = self.get_book_display_info(idx)
        if emit_signal:
            self.emit(SIGNAL('new_bookdisplay_data(PyQt_PyObject)'), data)
        else:
            return data
        
    def get_book_info(self, index):
        data = self.current_changed(index, None, False)
        row = index.row()
        data[_('Title')] = self.db.title(row)
        au = self.db.authors(row)
        if not au:
            au = _('Unknown')
        au = ', '.join([a.strip() for a in au.split(',')])
        data[_('Author(s)')] = au
        return data
        
    
    def get_metadata(self, rows):
        metadata = []
        for row in rows:
            row = row.row()
            au = self.db.authors(row)
            tags = self.db.tags(row)
            if not au:
                au = 'Unknown'
            au = au.split(',')
            if len(au) > 1:
                t = ', '.join(au[:-1])
                t += ' & ' + au[-1]
                au = t
            else:
                au = ' & '.join(au)
            if not tags:
                tags = []
            else:
                tags = tags.split(',')
            series = self.db.series(row)
            if series is not None:
                tags.append(series)
            mi = {
                  'title'   : self.db.title(row),
                  'authors' : au,
                  'cover'   : self.db.cover(row),
                  'tags'    : tags,
                  'comments': self.db.comments(row),
                  }
            if series is not None:
                mi['tag order'] = {series:self.db.books_in_series_of(row)} 
            
            metadata.append(mi)
        return metadata
    
    def get_preferred_formats(self, rows, formats, paths=False):
        ans = []
        for row in (row.row() for row in rows):
            format = None
            for f in self.db.formats(row).split(','):
                if f.lower() in formats:
                    format = f
                    break
            if format:
                pt = PersistentTemporaryFile(suffix='.'+format)
                pt.write(self.db.format(row, format))
                pt.flush()
                pt.close() if paths else pt.seek(0)
                ans.append(pt)                
            else:
                ans.append(None)
        return ans
    
    def id(self, row):
        return self.db.id(getattr(row, 'row', lambda:row)())
    
    def title(self, row_number):
        return self.db.title(row_number)
    
    def cover(self, row_number):
        img = self.buffer.get(row_number, -1)
        if img == -1:
            data = self.db.cover(row_number)
            img = QImage()
            img.loadFromData(data)
            if img.isNull():
                img = self.default_image
            self.buffer[row_number] = img
        return img
    
    def data(self, index, role):
        if role == Qt.DisplayRole or role == Qt.EditRole:      
            row, col = index.row(), index.column()
            if col == 0:
                text = self.db.title(row)
                if text:
                    return QVariant(text)
            elif col == 1: 
                au = self.db.authors(row)
                if au:
                    au = au.split(',')
                    return QVariant("\n".join(au))
            elif col == 2:
                size = self.db.max_size(row)
                if size:
                    return QVariant(BooksView.human_readable(size))
            elif col == 3:
                dt = self.db.timestamp(row)
                if dt:
                    dt = dt - timedelta(seconds=time.timezone) + timedelta(hours=time.daylight)
                    return QVariant(dt.strftime(BooksView.TIME_FMT).decode(preferred_encoding, 'replace'))
            elif col == 4: 
                r = self.db.rating(row)
                r = r/2 if r else 0
                return QVariant(r)
            elif col == 5: 
                pub = self.db.publisher(row)
                if pub: 
                    return QVariant(pub)
            elif col == 6:
                tags = self.db.tags(row)
                if tags:
                    return QVariant(', '.join(tags.split(',')))                
            elif col == 7:
                series = self.db.series(row)
                if series:
                    return QVariant(series  + ' [%d]'%self.db.series_index(row))
            return NONE
        elif role == Qt.TextAlignmentRole and index.column() in [2, 3, 4]:
            return QVariant(Qt.AlignRight | Qt.AlignVCenter)
        elif role == Qt.ToolTipRole and index.isValid():            
            if index.column() in self.editable_cols:
                return QVariant(_("Double click to <b>edit</b> me<br><br>"))
        return NONE
    
    def headerData(self, section, orientation, role):    
        if role != Qt.DisplayRole:
            return NONE
        text = ""
        if orientation == Qt.Horizontal:      
            if   section == 0: text = _("Title")
            elif section == 1: text = _("Author(s)")
            elif section == 2: text = _("Size (MB)")
            elif section == 3: text = _("Date")
            elif section == 4: text = _("Rating")
            elif section == 5: text = _("Publisher")
            elif section == 6: text = _("Tags")
            elif section == 7: text = _("Series")
            return QVariant(text)
        else: 
            return QVariant(section+1)
        
    def flags(self, index):
        flags = QAbstractTableModel.flags(self, index)
        if index.isValid():       
            if index.column() in self.editable_cols:  
                flags |= Qt.ItemIsEditable    
        return flags
    
    def setData(self, index, value, role):
        done = False
        if role == Qt.EditRole:
            row, col = index.row(), index.column()
            if col not in self.editable_cols:
                return False
            val = unicode(value.toString().toUtf8(), 'utf-8').strip() if col != 4 else \
                  int(value.toInt()[0])
            if col == 4:
                val = 0 if val < 0 else 5 if val > 5 else val
                val *= 2
            column = self.cols[col]
            self.db.set(row, column, val)           
            self.emit(SIGNAL("dataChanged(QModelIndex, QModelIndex)"), \
                                index, index)
            if col == self.sorted_on[0]:
                self.sort(col, self.sorted_on[1])
            done = True
        return done

class BooksView(TableView):
    TIME_FMT = '%d %b %Y'
    wrapper = textwrap.TextWrapper(width=20)
    
    @classmethod
    def wrap(cls, s, width=20):         
        cls.wrapper.width = width
        return cls.wrapper.fill(s)
    
    @classmethod
    def human_readable(cls, size, precision=1):
        """ Convert a size in bytes into megabytes """
        return ('%.'+str(precision)+'f') % ((size/(1024.*1024.)),)
    
    def __init__(self, parent, modelcls=BooksModel):
        TableView.__init__(self, parent)
        self.display_parent = parent
        self._model = modelcls(self)
        self.setModel(self._model)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSortingEnabled(True)
        if self.__class__.__name__ == 'BooksView': # Subclasses may not have rating as col 4
            self.setItemDelegateForColumn(4, LibraryDelegate(self))        
        QObject.connect(self.selectionModel(), SIGNAL('currentRowChanged(QModelIndex, QModelIndex)'),
                        self._model.current_changed)
        # Adding and removing rows should resize rows to contents
        QObject.connect(self.model(), SIGNAL('rowsRemoved(QModelIndex, int, int)'), self.resizeRowsToContents)
        QObject.connect(self.model(), SIGNAL('rowsInserted(QModelIndex, int, int)'), self.resizeRowsToContents)
        # Resetting the model should resize rows (model is reset after search and sort operations)
        QObject.connect(self.model(), SIGNAL('modelReset()'), self.resizeRowsToContents)
        self.set_visible_columns()
        
    @classmethod
    def paths_from_event(cls, event):
        ''' 
        Accept a drop event and return a list of paths that can be read from 
        and represent files with extensions.
        '''
        if event.mimeData().hasFormat('text/uri-list'):
            urls = [qstring_to_unicode(u.toLocalFile()) for u in event.mimeData().urls()]
            return [u for u in urls if os.path.splitext(u)[1] and os.access(u, os.R_OK)]
    
    def dragEnterEvent(self, event):
        if int(event.possibleActions() & Qt.CopyAction) + \
           int(event.possibleActions() & Qt.MoveAction) == 0:
            return
        paths = self.paths_from_event(event)
        
        if paths:
            event.acceptProposedAction()
    
    def dragMoveEvent(self, event):
        event.acceptProposedAction()
    
    def dropEvent(self, event):
        paths = self.paths_from_event(event)
        event.setDropAction(Qt.CopyAction)
        event.accept()
        self.emit(SIGNAL('files_dropped(PyQt_PyObject)'), paths, Qt.QueuedConnection) 
             
    
    def set_database(self, db):
        self._model.set_database(db)
        
    def close(self):
        self._model.close()
        
    def migrate_database(self):
        if self.model().database_needs_migration():
            print 'Migrating database from pre 0.4.0 version'
            path = os.path.abspath(os.path.expanduser('~/library.db'))
            progress = QProgressDialog('Upgrading database from pre 0.4.0 version.<br>'+\
                                       'The new database is stored in the file <b>'+self._model.db.dbpath,
                                       QString(), 0, LibraryDatabase.sizeof_old_database(path),
                                       self)
            progress.setModal(True)
            progress.setValue(0)
            app = QCoreApplication.instance()
            
            def meter(count):
                progress.setValue(count)
                app.processEvents()
            progress.setWindowTitle('Upgrading database')
            progress.show()
            LibraryDatabase.import_old_database(path, self._model.db.conn, meter)
            
    def connect_to_search_box(self, sb):
        QObject.connect(sb, SIGNAL('search(PyQt_PyObject, PyQt_PyObject)'), 
                        self._model.search)
        
    def connect_to_book_display(self, bd):
        QObject.connect(self._model, SIGNAL('new_bookdisplay_data(PyQt_PyObject)'),
                        bd)
    

class DeviceBooksView(BooksView):
    
    def __init__(self, parent):
        BooksView.__init__(self, parent, DeviceBooksModel)
        self.columns_resized = False
        self.resize_on_select = False
        
    def resizeColumnsToContents(self):
        QTableView.resizeColumnsToContents(self)
        self.columns_resized = True
        
    def connect_dirtied_signal(self, slot):
        QObject.connect(self._model, SIGNAL('booklist_dirtied()'), slot)

class DeviceBooksModel(BooksModel):
    
    def __init__(self, parent):
        BooksModel.__init__(self, parent)
        self.db  = []
        self.map = []
        self.sorted_map = []
        self.unknown = str(self.trUtf8('Unknown'))
        self.marked_for_deletion = {}
        
    
    def mark_for_deletion(self, id, rows):
        self.marked_for_deletion[id] = self.indices(rows)
        for row in rows:
            indices = self.row_indices(row)
            self.emit(SIGNAL('dataChanged(QModelIndex, QModelIndex)'), indices[0], indices[-1])
        
            
    def deletion_done(self, id, succeeded=True):
        if not self.marked_for_deletion.has_key(id):
            return
        rows = self.marked_for_deletion.pop(id)
        for row in rows:
            if not succeeded:
                indices = self.row_indices(self.index(row, 0))
                self.emit(SIGNAL('dataChanged(QModelIndex, QModelIndex)'), indices[0], indices[-1])        
    
    def paths_deleted(self, paths):
        self.map = list(range(0, len(self.db)))
        self.resort(False)
        self.research(True)
    
    def indices_to_be_deleted(self):
        ans = []
        for v in self.marked_for_deletion.values():
            ans.extend(v)
        return ans
    
    def flags(self, index):
        if self.map[index.row()] in self.indices_to_be_deleted():
            return Qt.ItemIsUserCheckable  # Can't figure out how to get the disabled flag in python
        flags = QAbstractTableModel.flags(self, index)
        if index.isValid():       
            if index.column() in [0, 1] or (index.column() == 4 and self.db.supports_tags()):  
                flags |= Qt.ItemIsEditable  
        return flags
        
    
    def search(self, text, refinement, reset=True):
        tokens, OR = self.search_tokens(text)
        base = self.map if refinement else self.sorted_map
        result = []
        for i in base:
            q = ['', self.db[i].title, self.db[i].authors, '', ', '.join(self.db[i].tags)] + list(repeat('', 10))
            if OR:
                add = False
                for token in tokens:
                    if token.match(q):
                        add = True
                        break
                if add:
                    result.append(i)
            else:
                add = True
                for token in tokens:
                    if not token.match(q):
                        add = False
                        break
                if add:
                    result.append(i)
        
        self.map = result

        if reset:
            self.reset()
        self.last_search = text
    
    def sort(self, col, order, reset=True):
        descending = order != Qt.AscendingOrder
        def strcmp(attr):
            ag = attrgetter(attr)
            def _strcmp(x, y):
                x = ag(self.db[x])
                y = ag(self.db[y])
                if x == None:
                    x = ''
                if y == None:
                    y = ''
                x, y = x.strip().lower(), y.strip().lower()
                return cmp(x, y)
            return _strcmp
        def datecmp(x, y):            
            x = self.db[x].datetime
            y = self.db[y].datetime
            return cmp(datetime(*x[0:6]), datetime(*y[0:6]))
        def sizecmp(x, y):
            x, y = int(self.db[x].size), int(self.db[y].size)
            return cmp(x, y)
        def tagscmp(x, y):
            x, y = ','.join(self.db[x].tags), ','.join(self.db[y].tags)
            return cmp(x, y)
        fcmp = strcmp('title_sorter') if col == 0 else strcmp('authors') if col == 1 else \
               sizecmp if col == 2 else datecmp if col == 3 else tagscmp 
        self.map.sort(cmp=fcmp, reverse=descending)
        if len(self.map) == len(self.db):
            self.sorted_map = list(self.map)
        else:
            self.sorted_map = list(range(len(self.db)))
            self.sorted_map.sort(cmp=fcmp, reverse=descending)
        self.sorted_on = (col, order)
        if reset:
            self.reset()
    
    def columnCount(self, parent):
        return 5
    
    def rowCount(self, parent):
        return len(self.map)
    
    def set_database(self, db):
        self.db = db
        self.map = list(range(0, len(db)))
    
    def current_changed(self, current, previous):
        data = {}
        item = self.db[self.map[current.row()]]
        cdata = item.thumbnail
        if cdata:
            img = QImage()
            img.loadFromData(cdata)
            if img.isNull():
                img = self.default_image
            data['cover'] = img
        type = _('Unknown')
        ext = os.path.splitext(item.path)[1]
        if ext:
            type = ext[1:].lower()
        data[_('Format')] = type
        data[_('Path')] = item.path
        dt = item.datetime
        dt = datetime(*dt[0:6])
        dt = dt - timedelta(seconds=time.timezone) + timedelta(hours=time.daylight)
        data[_('Timestamp')] = dt.ctime()
        data[_('Tags')] = ', '.join(item.tags)
        self.emit(SIGNAL('new_bookdisplay_data(PyQt_PyObject)'), data)
        
    def paths(self, rows):
        return [self.db[self.map[r.row()]].path for r in rows ]
    
    def indices(self, rows):
        '''
        Return indices into underlying database from rows
        '''
        return [ self.map[r.row()] for r in rows]
    
    
    def data(self, index, role):
        if role == Qt.DisplayRole or role == Qt.EditRole:      
            row, col = index.row(), index.column()
            if col == 0:
                text = self.db[self.map[row]].title
                if not text:
                    text = self.unknown
                return QVariant(text)
            elif col == 1: 
                au = self.db[self.map[row]].authors
                if not au:
                    au = self.unknown
                if role == Qt.EditRole:
                    return QVariant(au)
                au = au.split(',')
                authors = []
                for i in au:
                    authors += i.strip().split('&')
                jau = [ a.strip() for a in authors ]
                return QVariant("\n".join(jau))
            elif col == 2:
                size = self.db[self.map[row]].size
                return QVariant(BooksView.human_readable(size))
            elif col == 3:
                dt = self.db[self.map[row]].datetime
                dt = datetime(*dt[0:6])
                dt = dt - timedelta(seconds=time.timezone) + timedelta(hours=time.daylight)
                return QVariant(dt.strftime(BooksView.TIME_FMT))
            elif col == 4:
                tags = self.db[self.map[row]].tags                
                if tags:
                    return QVariant(', '.join(tags))                
        elif role == Qt.TextAlignmentRole and index.column() in [2, 3]:
            return QVariant(Qt.AlignRight | Qt.AlignVCenter)
        elif role == Qt.ToolTipRole and index.isValid():
            if self.map[index.row()] in self.indices_to_be_deleted():
                return QVariant('Marked for deletion')            
            col = index.column()
            if col in [0, 1] or (col == 4 and self.db.supports_tags()):
                return QVariant("Double click to <b>edit</b> me<br><br>")
        return NONE
    
    def headerData(self, section, orientation, role):    
        if role != Qt.DisplayRole:
            return NONE
        text = ""
        if orientation == Qt.Horizontal:      
            if   section == 0: text = _("Title")
            elif section == 1: text = _("Author(s)")
            elif section == 2: text = _("Size (MB)")
            elif section == 3: text = _("Date")
            elif section == 4: text = _("Tags")
            return QVariant(text)
        else: 
            return QVariant(section+1)
    
    def setData(self, index, value, role):
        done = False
        if role == Qt.EditRole:
            row, col = index.row(), index.column()
            if col in [2, 3]:
                return False
            val = qstring_to_unicode(value.toString()).strip() 
            idx = self.map[row]
            if col == 0:
                self.db[idx].title = val
                self.db[idx].title_sorter = val
            elif col == 1:
                self.db[idx].authors = val
            elif col == 4:
                tags = [i.strip() for i in val.split(',')]
                tags = [t for t in tags if t]
                self.db.set_tags(self.db[idx], tags)
            self.emit(SIGNAL("dataChanged(QModelIndex, QModelIndex)"), index, index)
            self.emit(SIGNAL('booklist_dirtied()'))
            if col == self.sorted_on[0]:
                self.sort(col, self.sorted_on[1])
            done = True
        return done

class SearchBox(QLineEdit):
    
    INTERVAL = 1000 #: Time to wait before emitting search signal
    
    def __init__(self, parent):
        QLineEdit.__init__(self, parent)
        self.help_text = _('Search (For Advanced Search click the button to the left)')
        self.initial_state = True
        self.default_palette = QApplication.palette(self)
        self.gray = QPalette(self.default_palette)
        self.gray.setBrush(QPalette.Text, QBrush(QColor('gray')))
        self.prev_search = ''
        self.timer = None
        self.clear_to_help()
        QObject.connect(self, SIGNAL('textEdited(QString)'), self.text_edited_slot)
        
        
    def normalize_state(self):
        self.setText('')
        self.setPalette(self.default_palette)
        
    def clear_to_help(self):
        self.setPalette(self.gray)
        self.setText(self.help_text)
        self.home(False)        
        self.initial_state = True
        
    def clear(self):
        self.clear_to_help()
        self.emit(SIGNAL('search(PyQt_PyObject, PyQt_PyObject)'), '', False)
        
        
    def keyPressEvent(self, event):
        if self.initial_state:
            self.normalize_state()
            self.initial_state = False
        QLineEdit.keyPressEvent(self, event)
        
    def mouseReleaseEvent(self, event):
        if self.initial_state:
            self.normalize_state()
            self.initial_state = False
        QLineEdit.mouseReleaseEvent(self, event)
    
    def text_edited_slot(self, text):
        text = qstring_to_unicode(text) if isinstance(text, QString) else unicode(text)
        self.prev_text = text
        self.timer = self.startTimer(self.__class__.INTERVAL)
        
    def timerEvent(self, event):
        self.killTimer(event.timerId())
        if event.timerId() == self.timer:
            text = qstring_to_unicode(self.text())
            refinement = text.startswith(self.prev_search) and ':' not in text
            self.prev_search = text
            self.emit(SIGNAL('search(PyQt_PyObject, PyQt_PyObject)'), text, refinement)
            
    def set_search_string(self, txt):
        self.normalize_state()
        self.setText(txt)
        self.emit(SIGNAL('search(PyQt_PyObject, PyQt_PyObject)'), txt, False)
        self.end(False)
        self.initial_state = False
