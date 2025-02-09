import os
import re
import sqlite3
import datetime
import json
import ssl
import subprocess
import threading
import time

import irc.bot
import irc.connection
import irc.client

from conf import *
from constants import *
import scene2arr

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

    def _parse_message(self, message, regex_key, capture_groups, check_capture_group=False):
        # Retrieve the regex pattern from the channel configuration
        regex = self.channel.get(regex_key, None)

        if regex is None:
            return None

        result = {}
        match = re.search(regex, message)
        if match:
            for capture_group in capture_groups:
                try:
                    # Check if the capture group regex is defined if required
                    if not check_capture_group or self.channel.get(f"{regex_key}_{capture_group}", None):
                        # Extract the specified capture group
                        result[capture_group] = match.group(self.channel[f"{regex_key}_{capture_group}"])
                except IndexError:
                    # If the capture group is not found, continue to the next one
                    result[capture_group] = None
        else:
            return None

        return result

    def preparse(self, message):
        return self._parse_message(message, "pre_regex", ["section", "release"])

    def nukeparse(self, message):
        return self._parse_message(message, "nuke_regex", ["type", "release", "reason", "nukenet"])

    def infoparse(self, message):
        return self._parse_message(message, "info_regex", ["type", "release", "files", "size", "genre"])

class IRCBot(irc.bot.SingleServerIRCBot):
    def __init__(
        self,
        args,
        logger,
        name,
        server,
        port,
        ssl_enabled,
        nickname,
        realname,
        channels,
        nickserv,
        nickserv_command,
        password=None,
    ):
        self.args = args
        self.logger = logger
        self.name = name
        self.server = server
        self.port = port
        self.ssl_enabled = ssl_enabled
        self.nickname = nickname
        self.realname = realname
        self.prechannels = channels
        self.password = password
        self.nickserv = nickserv
        self.nickserv_command = nickserv_command

        if self.ssl_enabled:
            factory = irc.connection.Factory(wrapper=ssl.wrap_socket)
        else:
            factory = irc.connection.Factory()

        super(IRCBot, self).__init__(
            [(server, port, password)], nickname, realname, connect_factory=factory
        )

        self.intentional_disconnect = False
        self.connection.set_keepalive(30)
        
        if args["predb"]:
            with sqlite3.connect(PRE_DB_FILE, check_same_thread=False) as conn:
                self.conn = conn

        # we want a shared lock for all threads, so it is actually created outside of this class
        try:
            self.lock
        except NameError:
            self.lock = threading.Lock()

    def start(self):
        while not self.intentional_disconnect:
            try:
                super().start()
            except Exception as e:
                if not self.intentional_disconnect:
                    time.sleep(5)  # Basic backoff
                    self.logger.warning(f"{self.server}: Attempting to reconnect...")
                    continue # Loop back to try connecting again
                break

    def on_disconnect(self, c, e):
        self.logger.warning(f"{c.server}: Disconnected from server.")
        # Let the start() loop handle reconnection

    def disconnect(self, message="Goodbye, cruel world!"):
        self.intentional_disconnect = True
        if self.args["predb"]:
            self.conn.close()
        super().disconnect(message)

    def on_nicknameinuse(self, c, e):
        c.nick(c.get_nickname() + "_")

    def on_welcome(self, c, e):
        self.logger.info(f"{c.server}: Connected to server.")
        if self.nickserv and self.nickserv_command:
            c.privmsg(self.nickserv, self.nickserv_command)
        for channel in self.prechannels:
            if "password" in channel:
                c.join(channel["name"], channel["password"])
            else:
                c.join(channel["name"])
            self.logger.info(f"{c.server}: Joined {channel['name']}")

    def get_version(self):
        return "HexChat 2.16.2 [x64] / Microsoft Windows 10 Pro (x64) [AMD EPYC 9655P 96-Core Processor (4.50GHz)]"

    def on_privmsg(self, c, e):
        self.handle_message(c, e)

    def on_pubmsg(self, c, e):
        self.handle_message(c, e)

    def handle_message(self, c, e):
        try:
            message = e.arguments[0]
            # Thanks to ZeroKnight
            # http://stackoverflow.com/questions/29247659/how-to-remove-all-irc-colour-codes-from-string
            message = re.sub(
                r"[\x02\x0F\x16\x1D\x1F]|\x03(\d{,2}(,\d{,2})?)?", "", message
            )
            currenttime = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
            self.logger.info(f"{INFO} {c.server}/{e.target} - {e.source.nick}: {message}")
            matched = False
            for channel in self.prechannels:
                if e.target.lower() == channel["name"].lower():
                    author = channel.get("author", None)
                    if author is None or author == e.source.nick:
                        if re.search(
                            r"(((UN)(DEL)?)|(RE)|(S)|(OLD)|(MOD)|(DEL))((NUKE)|(PRE))",
                            message,
                            re.IGNORECASE,
                        ):
                            self.logger.info(f"{INFO} {c.server}/{e.target} - {message}")
                        regexes = ("pre_regex", "nuke_regex", "info_regex")
                        parser = ircMessageParser(channel)
                        for current_regex in regexes:
                            if current_regex == "pre_regex":
                                if self.args["predb"]:
                                    if self.process_pre_regex(c, e, message, parser, currenttime):
                                        matched = True
                                if self.args["irc"]:
                                    self.add_to_arr(c, e, message, parser)
                                if matched:
                                    break
                            elif current_regex == "nuke_regex" and self.args["predb"]:
                                if self.process_nuke_regex(c, e, message, parser, currenttime):
                                    matched = True
                                if matched:
                                    break
                            elif current_regex == "info_regex" and self.args["predb"]:
                                if self.process_info_regex(c, e, message, parser, currenttime):
                                    matched = True
                                if matched:
                                    break
            if not matched:
                with open("unmatched_messages.log", "a") as log_file:
                    log_file.write(f"{datetime.datetime.now(datetime.timezone.utc)} - {c.server}/{e.target} - {e.source.nick}: {message}\n")
        except Exception as exc:
            exc_info = (type(exc), exc, exc.__traceback__)
            self.logger.error(f"{c.server}/{e.target} - {message}", exc_info=exc_info)

    def add_to_arr(self, c, e, message, parser):
        result = parser.preparse(message)
        if not result or any(value is None for value in result.values()):
            return
        release_name = result["release"]
        section = result["section"]
        # Call the PHP script to get the type of release
        try:
            output = subprocess.check_output(['php', 'parserelease.php', release_name, section], text=True).strip()
            data = json.loads(output)
        except subprocess.CalledProcessError as e:
            self.logger.critical(f"Error calling PHP script: {e}")
            exit(1)
        except json.JSONDecodeError as e:
            self.logger.error(f"Error decoding JSON output: {e}")
            return
        
        # Discard irrelevant releases
        type = data.get("type")
        if type not in irc_types:
            return
        
        # Handle different types of languages
        language = data.get("language")
        if language is None:
            language = set()
        elif isinstance(language, dict):
            language = set(language.keys())
        else:
            raise ValueError("Unexpected type for languages")

        # Check if languages match any set in irc_languages
        for irc_language in irc_languages:
            if language == irc_language:
                break
        else:
            return
        
        # Check if the release is in the correct format
        format = data.get("format")
        if format not in irc_formats:
            return

        group_name = data.get("group")
        self.logger.info(f"Adding {group_name} to *arr instances.")
        scene2arr.main({"add": True, "group": group_name, "remove": False, "xrel": False, "irc": False, "predb": False, "verbose": self.args["verbose"]})
        # TODO: suppress repeated messages
    
    def process_pre_regex(self, c, e, message, parser, currenttime):
        result = parser.preparse(message)
        #print(result)
        if not result or not result["release"] or not result["section"]:
            return False
        try:
            self.lock.acquire()
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT release FROM pre WHERE release=?",
                (result["release"],),
            )
            row = cursor.fetchone()
            if not row:
                cursor.execute(
                    """
                    INSERT INTO pre (release, section, source, timestamp)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        result["release"],
                        result["section"],
                        f"{c.server}/{e.target}",
                        currenttime,
                    ),
                )
            self.conn.commit()
        except sqlite3.Error as error:
            self.logger.error(f"{c.server}/{e.target} - {error} - {message}")
        finally:
            cursor.close()
            self.lock.release()
            return True

    def process_nuke_regex(self, c, e, message, parser, currenttime):
        result = parser.nukeparse(message)
        #print(result)
        if not result or not result["release"] or not result["type"] or not result["reason"]:
            return False
        
        # Convert type to uppercase
        result["type"] = result["type"].upper()

        try:
            self.lock.acquire()
            cursor = self.conn.cursor()
            cursor.execute( # TODO: Remove type from this select, because some prebots don't report it correctly? (e. g. predataba.se does not differentiate between nuke and modnuke)
                """SELECT release, type, reason, nukenet FROM nuke 
                WHERE release=? AND type=? AND reason=?""",
                (
                    result["release"],
                    result["type"],
                    result["reason"],
                ),
            )
            row = cursor.fetchone()
            if not row:
                cursor.execute(
                    """
                    INSERT INTO nuke (release, type, reason, nukenet, source, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        result["release"],
                        result["type"],
                        result["reason"],
                        result["nukenet"],
                        f"{c.server}/{e.target}",
                        currenttime,
                    ),
                )
            else:
                if not row[3]:
                    cursor.execute(
                        """
                        UPDATE nuke SET nukenet=? 
                        WHERE release=? AND type=? AND reason=?""",
                        (
                            result["nukenet"],
                            result["release"],
                            result["type"],
                            result["reason"],
                        ),
                    )
            self.conn.commit()
        except sqlite3.Error as error:
            self.logger.error(f"{c.server}/{e.target} - {error} - {message}")
        finally:
            cursor.close()
            self.lock.release()
            return True

    def process_info_regex(self, c, e, message, parser, currenttime):
        result = parser.infoparse(message)
        #print(result)
        if not result or not result["release"] or not result["type"]:
            return False
        
        try:
            self.lock.acquire()
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT release, size, files, genre FROM pre WHERE release=?",
                (result["release"],),
            )
            row = cursor.fetchone()
            if not row:
                if result["type"].lower() == "info":
                    cursor.execute(
                        """
                        INSERT INTO pre (release, size, files, source, timestamp)
                        VALUES (?, ?, ?, ?, ?)""",
                        (
                            result["release"],
                            result["size"],
                            result["files"],
                            f"{c.server}/{e.target}",
                            currenttime,
                        ),
                    )
                if result["type"].lower() == "genre":
                    cursor.execute(
                        """
                        INSERT INTO pre (release, genre, source, timestamp)
                        VALUES (?, ?, ?, ?)""",
                        (
                            result["release"],
                            result["genre"],
                            f"{c.server}/{e.target}",
                            currenttime,
                        ),
                    )
            else:
                if not row[3] or len(row[3]) == 1:
                    if result["type"].lower() == "genre":
                        cursor.execute(
                            "UPDATE pre SET genre=? WHERE release=?",
                            (
                                result["genre"],
                                result["release"],
                            ),
                        )
                if not row[1] and not row[2]:
                    if result["type"].lower() == "info":
                        cursor.execute(
                            "UPDATE pre SET size=?, files=? WHERE release=?",
                            (
                                result["size"],
                                result["files"],
                                result["release"],
                            ),
                        )
            self.conn.commit()
        except sqlite3.Error as error:
            self.logger.error(f"{c.server}/{e.target} - {error} - {message}")
        finally:
            cursor.close()
            self.lock.release()
            return True


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
