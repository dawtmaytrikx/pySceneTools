import os
import sqlite3

#
# scene2arr.py
#
class PVR(object):
    def __init__(self, name):
        self.url = None
        self.apikey = None
        self.response = None
        self.required = None
        self.ignored = None
        self.checked = []
        self.skip = False
        self.name = name


#
# scene2arr.py, scenerename.py
#
class DB(object):
    def __init__(self, dbname):
        self.connection = sqlite3.connect(dbname)
        self.cursor = self.connection.cursor()


#
# scenerename.py
#
class SkipFileError(Exception): pass
class ReleaseNotFoundError(Exception): pass
class FileToCheck(object):
    def __init__(self, dirpath, filename):
        self.dirpath = dirpath
        self.filename = filename
        self.releaseName = os.path.splitext(filename)[0]
        self.extension = os.path.splitext(filename)[1].lower()
        self.realName = None
        self.unprocessed = False
        self.sizeondisk = None
        self.sizeonsrrdb = None
        self.crccalc = None
        self.crcweb = None
        self.page = None

