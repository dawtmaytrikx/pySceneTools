#!/usr/bin/python3

# Pre DB dumps can be found at:
# https://defacto2.net/search/file > search for "database"
# https://the-eye.eu/public/Piracy/

import datetime
import json
import random
import ssl
import subprocess
import sys
import threading
import time
import yaml  # pyyaml

import irc.bot
import irc.connection
import irc.client

import argparse
import logging

from classes import *
from conf import *
from constants import *
import scene2arr

def start_argparse(): # TODO: Actually make this work
    # argument parser
    parser = argparse.ArgumentParser(
        description="This script runs an IRC bot that can parse pre, nuke, and info messages from IRC channels to build a pre database, and add new groups to your *arr instances.",
        usage=f"python3 {sys.argv[0]} [-h] [-p] [-a] [-v]",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_const",
        const=True,
        default=False,
        help="Enable verbose mode.",
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument(
        "-p",
        "--predb",
        action="store_const",
        const=True,
        default=False,
        help="Create a pre database by listening in pre channels.",
    )
    action.add_argument(
        "-a",
        "--arr",
        action="store_const",
        const=True,
        default=False,
        help="Pirate mode. Listens for new releases in the prechans, extracts the group name, and adds it to the *arr instances configured in conf.py.",
    )

    args = vars(parser.parse_args())

    return args

logging.basicConfig(
    filename="irc2arr.log",
    level=logging.ERROR,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


class IRCBot(irc.bot.SingleServerIRCBot):
    def __init__(
        self,
        args,
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
            with sqlite3.connect(IRC2ARR_DB_FILE, check_same_thread=False) as conn:
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
                    logger.warning(f"{self.server}: Attempting to reconnect...")
                    continue # Loop back to try connecting again
                break

    def on_disconnect(self, c, e):
        logger.warning(f"{c.server}: Disconnected from server.")
        # Let the start() loop handle reconnection

    def disconnect(self, message="Goodbye, cruel world!"):
        self.intentional_disconnect = True
        self.conn.close()
        super().disconnect(message)

    def on_nicknameinuse(self, c, e):
        c.nick(c.get_nickname() + "_")

    def on_welcome(self, c, e):
        logger.info(f"{c.server}: Connected to server.")
        if self.nickserv and self.nickserv_command:
            c.privmsg(self.nickserv, self.nickserv_command)
        for channel in self.prechannels:
            if "password" in channel:
                c.join(channel["name"], channel["password"])
            else:
                c.join(channel["name"])
            logger.info(f"{c.server}: Joined {channel['name']}")

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
            currenttime = datetime.datetime.now(datetime.timezone.utc)
            logger.info(f"{currenttime} - {c.server}/{e.target} - {e.source.nick}: {message}")
            for channel in self.prechannels:
                if e.target.lower() == channel["name"].lower():
                    author = channel.get("author", None)
                    if author is None or author == e.source.nick:
                        if re.search(
                            r"(((UN)(DEL)?)|(RE)|(S)|(OLD)|(MOD)|(DEL))((NUKE)|(PRE))",
                            message,
                            re.IGNORECASE,
                        ):
                            logger.info(f"{currenttime} - {c.server}/{e.target} - {message}")
                        regexes = ("pre_regex", "nuke_regex", "info_regex")
                        parser = ircMessageParser(channel)
                        for current_regex in regexes:
                            if current_regex == "pre_regex":
                                if self.args["predb"]:
                                    self.process_pre_regex(c, e, message, parser, currenttime)
                                if self.args["arr"]:
                                    self.add_to_arr(c, e, message, parser)
                                break
                            elif current_regex == "nuke_regex" and self.args["predb"]:
                                self.process_nuke_regex(c, e, message, parser, currenttime)
                                break
                            elif current_regex == "info_regex" and self.args["predb"]:
                                self.process_info_regex(c, e, message, parser, currenttime)
                                break
        except Exception as exc:
            exc_info = (type(exc), exc, exc.__traceback__)
            logger.error(logger.info(f"{c.server}/{e.target} - {message}"), exc_info=exc_info)

    def add_to_arr(self, c, e, message, parser):
        result = parser.preparse(message)
        if not result or all(value is None for value in result.values()):
            return
        release_name = result["release"]
        section = result["section"]
        # Call the PHP script to get the type of release
        try:
            output = subprocess.check_output(['php', 'parserelease.php', release_name, section], text=True).strip()
            data = json.loads(output)
        except subprocess.CalledProcessError as e:
            logger.error(f"Error calling PHP script: {e}")
            return
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding JSON output: {e}")
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
        logger.info(f"Adding {group_name} to *arr instances.")
        scene2arr.main({"add": True, "group": group_name, "remove": False, "xrel": False, "verbose": False})
    
    def process_pre_regex(self, c, e, message, parser, currenttime):
        result = parser.preparse(message)
        if not result:
            return
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
                    INSERT INTO pre (release, category, source, time)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        result["release"],
                        result["category"],
                        f"{c.server}/{e.target}",
                        currenttime,
                    ),
                )
            self.conn.commit()
        except sqlite3.Error as error:
            logger.error(f"{c.server}/{e.target} - {error} - {message}")
        finally:
            cursor.close()
            self.lock.release()

    def process_nuke_regex(self, c, e, message, parser, currenttime):
        result = parser.nukeparse(message)
        if not result:
            return
        try:
            self.lock.acquire()
            cursor = self.conn.cursor()
            cursor.execute(
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
                    INSERT INTO nuke (release, type, reason, nukenet, source, time)
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
            logger.error(f"{c.server}/{e.target} - {error} - {message}")
        finally:
            cursor.close()
            self.lock.release()

    def process_info_regex(self, c, e, message, parser, currenttime):
        result = parser.infoparse(message)
        if not result:
            return
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
                        INSERT INTO pre (release, size, files, source, time)
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
                        INSERT INTO pre (release, genre, source, time)
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
            logger.error(f"{c.server}/{e.target} - {error} - {message}")
        finally:
            cursor.close()
            self.lock.release()


def create_db(dbname):
    # set up the database
    if not os.path.exists(dbname):
        with open(dbname, "w"):
            pass

    db = DB(dbname)

    # Define the SQL statement to create the table
    db.cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS pre (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            release TEXT,
            category TEXT,
            size TEXT,
            files INTEGER,
            genre TEXT,
            source TEXT,
            time TEXT
        )
        """
    )

    db.cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS nuke (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            release TEXT,
            type TEXT,
            reason TEXT,
            nukenet TEXT,
            source TEXT,
            time TEXT
        )
        """
    )

    # Commit the changes to the database
    db.conn.commit()

    # Close the connection to the database
    db.conn.close()


def main(args=None):
    if args is None:
        args = start_argparse()

    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG if args["verbose"] else logging.INFO)

    # Add a StreamHandler to log to the console
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(console_handler)

    try:
        with open(IRC2ARR_CONFIG_FILE, "r") as ymlfile:
            cfg = yaml.safe_load(ymlfile)
    except Exception as e:
        logger.error(f"Error loading {IRC2ARR_CONFIG_FILE}:", e)
        sys.exit(1)
    if args["predb"]:
        create_db(IRC2ARR_DB_FILE)
    IRCBot.lock = threading.Lock()
    threads = []
    bots = []
    for server in cfg["servers"]:
        name = server["name"]
        host = server["host"]
        nickname = server.get("nickname") or f"guest{random.randint(100, 999)}"
        realname = server.get("realname", None)
        ssl_enabled = server.get("ssl_enabled", True)
        port = server.get("port", 6667)
        password = server.get("password", None)
        nickserv = server.get("nickserv", None)
        nickserv_command = server.get("nickserv_command", None)
        channels = server["channels"]
        bot = IRCBot(
            args,
            name,
            host,
            port,
            ssl_enabled,
            nickname,
            realname,
            channels,
            nickserv,
            nickserv_command,
            password=password,
        )
        t = threading.Thread(target=bot.start)
        threads.append(t)
        bots.append(bot)
    for t in threads:
        #t.daemon = True
        t.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt detected, exiting...")
        for bot in bots:
            try:
                bot.disconnect()
                #pass
            except Exception as e:
                logger.error(f"Error stopping bot: {e}")
        for t in threads:
            t.join()
        logger.info("All threads stopped, exiting.")


if __name__ == "__main__":
    '''
    conn = sqlite3.connect("irc2arr.db", check_same_thread=False)
    c = conn.cursor()
    c.execute("PRAGMA foreign_keys=off")
    c.execute("BEGIN TRANSACTION")
    c.execute("ALTER TABLE pre RENAME TO old_pre")
    c.execute(
        'CREATE TABLE IF NOT EXISTS pre (id INTEGER PRIMARY KEY, release TEXT, section TEXT, size TEXT, files INTEGER, genre TEXT, source TEXT, time TEXT, CONSTRAINT release UNIQUE (release))')
    c.execute("INSERT INTO pre (id, release, section, source, time) SELECT id, release, category, serverchannel, time FROM old_pre")
    c.execute("select release, size, files, genre from info")
    rows = c.fetchall()
    for row in rows:
        c.execute("update pre set size=?, files=?, genre=? where release=?", (row[1], row[2], row[3], row[0],))
    c.execute("ALTER TABLE nuke RENAME TO old_nuke")
    c.execute(
        'CREATE TABLE IF NOT EXISTS nuke (id INTEGER PRIMARY KEY, release TEXT, type TEXT, reason TEXT, nukenet TEXt, source TEXT, time TEXT)')
    c.execute("INSERT INTO nuke (id, release, type, reason, nukenet, source, time) SELECT id, release, type, reason, nukenet, serverchannel, time FROM old_nuke")
    c.execute("COMMIT")
    c.execute("PRAGMA foreign_keys=on")
    c.execute("DROP TABLE old_pre")
    c.execute("DROP TABLE info")
    c.execute("DROP TABLE old_nuke")
    conn.commit()
    c.execute("VACUUM")
    conn.close()
    '''
    
    main()