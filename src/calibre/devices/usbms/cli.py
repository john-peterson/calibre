# -*- coding: utf-8 -*-

__license__ = 'GPL 3'
__copyright__ = '2009, John Schember <john@nachtimwald.com>'
__docformat__ = 'restructuredtext en'

import os, shutil, time

from calibre.devices.errors import PathError

class File(object):

    def __init__(self, path):
        stats = os.stat(path)
        self.is_dir = os.path.isdir(path)
        self.is_readonly = not os.access(path, os.W_OK)
        self.ctime = stats.st_ctime
        self.wtime = stats.st_mtime
        self.size  = stats.st_size
        if path.endswith(os.sep):
            path = path[:-1]
        self.path = path
        self.name = os.path.basename(path)


def check_transfer(infile, dest):
    infile.seek(0)
    dest.seek(0)
    return infile.read() == dest.read()


class CLI(object):

    def get_file(self, path, outfile, end_session=True):
        path = self.munge_path(path)
        with open(path, 'rb') as src:
            shutil.copyfileobj(src, outfile)

    def put_file(self, infile, path, replace_file=False, end_session=True):
        path = self.munge_path(path)
        close = False
        if not hasattr(infile, 'read'):
            infile, close = open(infile, 'rb'), True
        infile.seek(0)
        if os.path.isdir(path):
            path = os.path.join(path, infile.name)
        if not replace_file and os.path.exists(path):
            raise PathError('File already exists: ' + path)
        d = os.path.dirname(path)
        if not os.path.exists(d):
            os.makedirs(d)
        with open(path, 'wb') as dest:
            try:
                shutil.copyfileobj(infile, dest)
            except IOError:
                print 'WARNING: First attempt to send file to device failed'
                time.sleep(0.2)
                infile.seek(0)
                dest.seek(0)
                dest.truncate()
                shutil.copyfileobj(infile, dest)
            #if not check_transfer(infile, dest): raise Exception('Transfer failed')
        if close:
            infile.close()

    def munge_path(self, path):
        if path.startswith('/') and not (path.startswith(self._main_prefix) or \
            (self._card_a_prefix and path.startswith(self._card_a_prefix)) or \
            (self._card_b_prefix and path.startswith(self._card_b_prefix))):
            path = self._main_prefix + path[1:]
        elif path.startswith('carda:'):
            path = path.replace('carda:', self._card_a_prefix[:-1])
        elif path.startswith('cardb:'):
            path = path.replace('cardb:', self._card_b_prefix[:-1])
        return path

    def list(self, path, recurse=False, end_session=True, munge=True):
        if munge:
            path = self.munge_path(path)
        if os.path.isfile(path):
            return [(os.path.dirname(path), [File(path)])]
        entries = [File(os.path.join(path, f)) for f in os.listdir(path)]
        dirs = [(path, entries)]
        for _file in entries:
            if recurse and _file.is_dir:
                dirs[len(dirs):] = self.list(_file.path, recurse=True, munge=False)
        return dirs

    def mkdir(self, path, end_session=True):
        if self.SUPPORTS_SUB_DIRS:
            path = self.munge_path(path)
            os.mkdir(path)

    def rm(self, path, end_session=True):
        path = self.munge_path(path)
        self.delete_books([path])

    def touch(self, path, end_session=True):
        path = self.munge_path(path)
        if not os.path.exists(path):
            open(path, 'w').close()
        if not os.path.isdir(path):
            os.utime(path, None)
