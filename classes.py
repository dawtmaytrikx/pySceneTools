import os
import re
import sqlite3

#
# scene2arr.py
#
class IgnoreError(Exception):
    pass


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


class ircMessageParser:
    def __init__(self, channel):
        self.channel = channel

    def preparse(self, message):
        regex = self.channel.get("pre_regex", None)

        result = {}
        for group in ["release", "section"]:
            try:
                result[group] = (
                    re.match(regex, message).group(self.channel[f"pre_regex_{group}"])
                    if regex is not None and self.channel[f"pre_regex_{group}"] is not None
                    else None
                )
            except IndexError:
                continue

        return result

    def nukeparse(self, message):
        regex = self.channel.get("nuke_regex", None)

        result = {}
        for group in ["release", "type", "reason", "nukenet"]:
            try:
                result[group] = (
                    re.match(regex, message).group(self.channel[f"nuke_regex_{group}"])
                    if regex is not None and self.channel[f"nuke_regex_{group}"] is not None
                    else None
                )
            except IndexError:
                continue

        return result

    def infoparse(self, message):
        regex = self.channel.get("info_regex", None)

        result = {}
        for group in ["release", "type", "genre", "size", "files"]:
            try:
                if self.channel[f"info_regex_{group}"]:
                    result[group] = (
                        re.match(regex, message).group(self.channel[f"info_regex_{group}"])
                        if regex is not None
                        else None
                    )
            except IndexError:
                continue

        return result


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
class ReleaseNotFoundError(Exception):
    pass


class SkipFileError(Exception):
    pass


class FileToCheck(object):
    def __init__(self, dirpath, filename):
        self.dirpath = dirpath
        self.filename = filename
        self.filepath = os.path.join(dirpath, filename)
        self.releaseName = os.path.splitext(filename)[0]
        self.extension = os.path.splitext(filename)[1].lower()
        self.realName = None
        self.sizeondisk = None
        self.sizeonsrrdb = None
        self.crccalc = None
        self.crcweb = None
        self.page = None
