import base64
import datetime
import feedparser
import json
import os
import random
import re
import sqlite3
import ssl
import subprocess
import threading
import time
import requests
from collections import deque

import irc.bot
import irc.connection
import irc.client
from jaraco.stream import buffer  # Import the buffer module

from conf import *
from constants import *
import scene2arr

# Set the buffer class to LenientDecodingLineBuffer
irc.client.ServerConnection.buffer_class = buffer.LenientDecodingLineBuffer


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
    
    def addoldparse(self, message):
        return self._parse_message(message, "addold_regex", ["type", "release", "section", "size", "files", "genre", "timestamp"])

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
        self.ircchannels = channels
        self.password = password
        self.nickserv = nickserv
        self.nickserv_command = nickserv_command

        if self.ssl_enabled:
            ssl.wrap_socket = ssl.SSLContext().wrap_socket
            factory = irc.connection.Factory(wrapper=ssl.wrap_socket)
        else:
            factory = irc.connection.Factory()

        super(IRCBot, self).__init__(
            [(server, port, password)], nickname, realname, connect_factory=factory
        )

        self.intentional_disconnect = False
        self.connection.set_keepalive(30)

    def start(self):
        self.set_version()
        while not self.intentional_disconnect and not getattr(self, "stop_event", threading.Event()).is_set():
            try:
                super().start()
            except Exception as e:
                if not self.intentional_disconnect:
                    time.sleep(5)  # Basic backoff
                    self.logger.warning(f"{self.server}: Attempting to reconnect...")
                    continue # Loop back to try connecting again
                break
        self.disconnect()

    def on_disconnect(self, c, e):
        self.logger.warning(f"{c.server}: Disconnected from server.")
        # Let the start() loop handle reconnection

    def disconnect(self, msg="Goodbye, cruel world!"):
        self.intentional_disconnect = True
        super().disconnect(msg)

    def on_nicknameinuse(self, c, e):
        c.nick(c.get_nickname() + "_")
    
    away_messages = [
        "Away: Currently engaged in an epic battle with my refrigerator door. (Spoiler: It wins.)",
        "AFK: Investigating a suspicious noise in the kitchen. If I don't return, avenge me.",
        "BRB: Testing if my toaster is secretly an AI. Results pending.",
        "Gone: Either abducted by aliens or fell asleep at my keyboard. 50/50 chance.",
        "AFK: Seeking wisdom from the coffee oracle. Will return enlightened (or jittery).",
        "BRB: Trying to teach my cat how to IRC. Progress: [█████░░░░░] 50%",
        "Away: Pretending to be productive while actually watching cat videos.",
        "AFK: In a meeting with my couch. Topic: Naps & Snacks.",
        "Gone Fishing: By 'fishing,' I mean staring at the fridge hoping food appears.",
        "AFK: My computer chair has rejected me. Engaging in negotiations.",
        "Away: Experiencing an existential crisis about semicolons. Send help.",
        "AFK: Attempting to break the world record for longest bathroom break.",
        "Gone: I've been away so long, my plants learned to type. Please send water.",
        "BRB: Running at 1% battery. Seeking nearest charging station (aka my bed).",
        "AFK: Rebooting... please wait... (Or just pretend I'm still here.)",
        "AFK: Switching to my backup brain cell. May experience lag.",
        "Gone: Do not disturb—I'm in the middle of a staring contest with my screen saver.",
        "AFK: Currently buffering. Please stand by...",
        "Away: Not here. But if you leave a message, I'll totally pretend I saw it later.",
        "AFK: Doing something important. Or maybe not. You'll never know.",
        "Gone: Out sourcing RAM. Not for my PC—just for my memory.",
        "BRB: Off on a top-secret mission. (Okay, fine, I just went to get snacks.)",
        "AFK: Experimenting with time travel. If this message is still here, it failed.",
        "Away: Re-enacting the 'Are you still watching?' scene from Netflix.",
        "BRB: Stuck in a captcha. Send reinforcements."
    ]

    def set_away(self, message=random.choice(away_messages)):
        if message:
            self.connection.send_raw(f"AWAY :{message}")

    version_strings = [
        "HexChat 2.16.2 [x64] / Microsoft Windows 10 Pro (x64) [AMD EPYC 9655P 96-Core Processor (4.50GHz)]",
        "mIRC 6.35 / Windows XP SP3 [Intel Pentium III 1.0GHz]",
        "irssi 1.2.2 / Debian 3.1 [Sun UltraSPARC-II 450MHz]",
        "AndroIRC 5.2.1 / Android 2.3.6 [ARM Cortex-A8 1.0GHz]",
        "Colloquy 2.4 / Mac OS X 10.6 [PowerPC G4 867MHz]",
        "HexChat 2.16.2 / Tesla Model S Infotainment System [Intel Atom E8000 1.04GHz]",
        "XChat 2.7.1 / Samsung Smart TV [ARM Cortex-A9 1.0GHz]",
        "Quassel IRC 0.13.1 / Raspberry Pi Zero [ARM1176JZF-S 1.0GHz]",
        "Custom Homebrew IRC v0.1 - Nintendo Game Boy (DMG-01) - 4.19 MHz | 8 KB RAM | No multitasking, send help.",
        "GEOS-IRC v1.0 | Commodore 64",
        "Sinclair BASIC IRC [ZX Spectrum 48K] 3.5 MHz / 48 KB RAM",
        "IRCalc v0.9b [TI-83+]",
        "AmIRC 2.2 — Commodore Amiga 500",
        "ProTerm 3.1 (Apple IIe) - 1.023 MHz - 64 KB RAM - Beep boop, waiting for my 300 baud modem to catch up.",
        "IRCjr v1.00 — IBM PC XT — 4.77 MHz | 640 KB RAM",
        "UNIX BSD 4.2 IRC — DEC VAX-11/780 — 1.0 MIPS — 8 MB RAM — This client weighs more than your car.",
        "QIRC v3.0 (IBM AS/400) — 6.9 MHz",
        "CrayOS IRC v1.1 — Cray-1 — 80 MHz — 8 MB RAM — Liquid-cooled shitposting at $5M per message.",
        "ClusterIRC v9.0 — IBM Blue Gene/P — 850 MHz x 294,912 cores — 80 TB RAM — Running an IRC client across 72 racks because why not?",
        "UltraIRC v2.0 [Fujitsu Fugaku] — 48-core ARM A64FX",
        "MicroIRC v0.2 // ESP8266 // 80 MHz // 160 KB RAM",
        "TuberNet IRC v1.0 — Potato — 0.01 Hz — 0.0001 KB RAM — Electrically unstable, may disconnect when dehydrated.",
    ]

    def set_version(self, version=random.choice(version_strings)):
        if version:
            self.version=version  # Select a random version string

    def on_welcome(self, c, e):
        self.logger.info(f"{c.server}: Connected to server.")
        self.set_away()
        if self.nickserv and self.nickserv_command:
            c.privmsg(self.nickserv, self.nickserv_command)
            time.sleep(1)
        for channel in self.ircchannels:
            if "password" in channel:
                c.join(channel["name"], channel["password"])
            else:
                c.join(channel["name"])
            self.logger.info(f"{c.server}: Joined {channel['name']}")

    def get_version(self):
        return self.version  # Return the instance-specific version string
    


class InputBot(IRCBot):
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
        ircchannels,
        nickserv,
        nickserv_command,
        output_bots,
        metadata_agent,
        lock,
        password=None,
    ):
        super().__init__(args, logger, name, server, port, ssl_enabled, nickname, realname, ircchannels, nickserv, nickserv_command, password)
        self.args = args
        self.logger = logger
        self.output_bots = output_bots
        self.metadata_agent = metadata_agent
        self.lock = lock

        if args["predb"]:
            with sqlite3.connect(os.getenv("PRE_DB_FILE"), check_same_thread=False) as conn:
                self.conn = conn
                self.conn.row_factory = sqlite3.Row

        # we want a shared lock for all threads, so it is actually created outside of this class
        #try:
        #    self.lock
        #except NameError:
        #    self.lock = threading.Lock()

    def disconnect(self, msg="Goodbye, cruel world!"):
        if self.args["predb"]:
            self.conn.close()
        super().disconnect(msg)
    
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
            for channel in self.ircchannels:
                if e.target.lower() == channel["name"].lower():
                    author = channel.get("author", None)
                    if author is None or author == e.source.nick:
                        if re.search(
                            r"(((UN)(DEL)?)|(RE)|(S)|(OLD)|(MOD)|(DEL))((NUKE)|(PRE))",
                            message,
                            re.IGNORECASE,
                        ):
                            self.logger.info(f"{INFO} {c.server}/{e.target} - {message}")
                        regexes = ("pre_regex", "nuke_regex", "info_regex", "addold_regex")
                        parser = ircMessageParser(channel)
                        for current_regex in regexes:
                            if current_regex == "pre_regex":
                                if self.args["predb"]:
                                    if self.process_pre_regex(c, e, message, parser, currenttime):
                                        matched = True
                                        break
                                if self.args["irc"]:
                                    self.add_to_arr(c, e, message, parser)
                            elif current_regex == "info_regex" and self.args["predb"]:
                                if self.process_info_regex(c, e, message, parser, currenttime, False):
                                    matched = True
                                    break
                            elif current_regex == "nuke_regex" and self.args["predb"]:
                                if self.process_nuke_regex(c, e, message, parser, currenttime):
                                    matched = True
                                    break
                            elif current_regex == "addold_regex" and self.args["predb"]:
                                if self.process_addold_regex(c, e, message, parser):
                                    matched = True
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
            self.logger.critical(f"Error calling PHP script: {e}", exc_info=True)
            exit(1)
        except json.JSONDecodeError as e:
            self.logger.error(f"Error decoding JSON output: {e}", exc_info=True)
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
        if not result or not result["release"] or not result["section"]:
            return False
        parsed_release = None
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
                    INSERT INTO pre (release, type, section, source, timestamp)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        result["release"],
                        "PRE",
                        result["section"],
                        f"{c.server}/{e.target}",
                        currenttime,
                    ),
                )
                self.conn.commit()

                try:
                    output = subprocess.check_output(['php', 'parserelease.php', result["release"], result["section"]], text=True).strip()
                    parsed_release = json.loads(output)
                except subprocess.CalledProcessError as e:
                    self.logger.critical(f"Error calling PHP script: {e}", exc_info=True)
                    exit(1)
                except json.JSONDecodeError as e:
                    self.logger.error(f"Error decoding JSON output: {e}", exc_info=True)
                    return
                except Exception as e:
                    self.logger.error(f"{ERROR}: {Exception} - {e}", exc_info=True)
                    return  

                self.broadcast("pre", result, parsed_release)  # Notify the Broadcaster
        except sqlite3.Error as error:
            self.logger.error(f"{c.server}/{e.target} - {error} - {message}", exc_info=True)
        finally:
            cursor.close()
            self.lock.release()
        
        if not row and parsed_release:
            # Determine genre using MetadataAgent
            genres = self.metadata_agent.determine_genre(parsed_release)
            if genres:
                genre_string = '/'.join(genres)
                genre_message = {
                    "type": "GENRE",
                    "release": result["release"],
                    "genre": genre_string
                }
                self.process_info_regex(c, e, genre_message, parser, currenttime, True)
        
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

            # predataba.se currently doesn't report modnukes correctly
            # Check for identical modnuke in database if server is irc.predataba.se
            if c.server == 'irc.predataba.se':
                cursor.execute(
                    """SELECT release FROM nuke 
                    WHERE release=? AND type='MODNUKE' AND reason=? AND nukenet=?""",
                    (
                        result["release"],
                        result["reason"],
                        result["nukenet"],
                    ),
                )
                row = cursor.fetchone()
                if row:
                    return False

            # if any other network reports a modnuke, check for identical nukes from predataba.se and update them
            if result["type"] == 'MODNUKE':
                cursor.execute(
                    """SELECT release FROM nuke 
                    WHERE release=? AND type='NUKE' AND reason=? AND nukenet=? AND source='irc.predataba.se/#pre'""",
                    (
                        result["release"],
                        result["reason"],
                        result["nukenet"],
                    ),
                )
                row = cursor.fetchone()
                if row:
                    cursor.execute(
                        """UPDATE nuke SET type=?, source=?, timestamp=? 
                        WHERE release=? AND reason=? AND nukenet=?""",
                        (
                            result["type"],
                            f"{c.server}/{e.target}",
                            currenttime,
                            result["release"],
                            result["reason"],
                            result["nukenet"],
                        ),
                    )
                    self.conn.commit()
                    self.broadcast("nuke", result)  # Notify the Broadcaster
                    return True

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
                self.broadcast("nuke", result)  # Notify the Broadcaster
            else:
                if not row["nukenet"]:
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
            self.logger.error(f"{c.server}/{e.target} - {error} - {message}", exc_info=True)
        finally:
            cursor.close()
            self.lock.release()
        return True

    def process_info_regex(self, c, e, message, parser, currenttime, skip_parse=False):
        result = {}
        if not skip_parse:
            result = parser.infoparse(message)
            if not result or not result["release"] or not result["type"]:
                return False
            # since we're generating our own genre information, we'll disregard genre messages from IRC
            if result["type"].lower() == "genre":
                return True
            result["size"] = round(float(result["size"])) if result["size"] else None
            result["files"] = int(result["files"]) if result["files"] else None
        elif skip_parse:
            result["type"] = message.get("type")
            result["release"] = message.get("release")
            result["files"] = message.get("files")
            result["size"] = message.get("size")
            result["genre"] = message.get("genre")

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
                    cursor.execute( # TODO: Remove timestamp here, so that a later ADDOLD can add it?
                        """
                        INSERT INTO pre (release, type, size, files, source, timestamp)
                        VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            result["release"],
                            "INFO",
                            result["size"],
                            result["files"],
                            f"{c.server}/{e.target}",
                            currenttime,
                        ),
                    )
                    self.broadcast("info", result)  # Notify the Broadcaster
                if result["type"].lower() == "genre":
                    cursor.execute(
                        """
                        INSERT INTO pre (release, type, genre, source, timestamp)
                        VALUES (?, ?, ?, ?, ?)""",
                        (
                            result["release"],
                            "GENRE",
                            result["genre"],
                            f"{c.server}/{e.target}",
                            currenttime,
                        ),
                    )
                    self.broadcast("info", result)  # Notify the Broadcaster
            else:
                if not row["genre"] or len(row["genre"]) == 1:
                    if result["type"].lower() == "genre":
                        cursor.execute(
                            "UPDATE pre SET genre=? WHERE release=?",
                            (
                                result["genre"],
                                result["release"],
                            ),
                        )
                        self.broadcast("info", result)  # Notify the Broadcaster
                if not row["size"] and not row["files"]:
                    if result["type"].lower() == "info":
                        cursor.execute(
                            "UPDATE pre SET size=?, files=? WHERE release=?",
                            (
                                result["size"],
                                result["files"],
                                result["release"],
                            ),
                        )
                        self.broadcast("info", result)  # Notify the Broadcaster
            self.conn.commit()
        except sqlite3.Error as error:
            self.logger.error(f"{c.server}/{e.target} - {error} - {message}", exc_info=True)
        finally:
            cursor.close()
            self.lock.release()
        return True

    def process_addold_regex(self, c, e, message, parser):
        result = parser.addoldparse(message)
        #print(result)
        if not result or not result["release"] or not result["section"]:
            return False
        
        result["size"] = round(float(result["size"])) if result["size"] else None

        try:
            self.lock.acquire()
            cursor = self.conn.cursor()
            cursor.execute(
                "SELECT release, type, section, size, files, genre, timestamp FROM pre WHERE release=?",
                (result["release"],),
            )
            row = cursor.fetchone()
            if not row:
                cursor.execute(
                    """
                    INSERT INTO pre (release, type, section, size, files, genre, source, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        result["release"],
                        "ADDOLD",
                        result["section"] if result["section"] and result["section"] != 'None' else None,
                        result["size"] if result["size"] and result["size"] != '0' else None,
                        result["files"] if result["files"] and result["files"] != '0' else None,
                        result["genre"] if result["genre"] and result["genre"] != 'None' else None,
                        f"{c.server}/{e.target}",
                        result["timestamp"] if result["timestamp"] and result["timestamp"] != '0' else None,
                    ),
                )
            else:
                update_fields = []
                update_values = []

                if row["section"] == 'PRE' and result["section"] and result["section"] != 'PRE' and result["section"] != 'None':
                    update_fields.append("section = ?")
                    update_values.append(result["section"])

                if not row["size"] and result["size"] and result["size"] != '0':
                    update_fields.append("size = ?")
                    update_values.append(result["size"])

                if not row["files"] and result["files"] and result["files"] != '0':
                    update_fields.append("files = ?")
                    update_values.append(result["files"])

                if not row["genre"] and result["genre"] and result["genre"] != 'None':
                    update_fields.append("genre = ?")
                    update_values.append(result["genre"])
                
                if row["type"] != 'PRE' and not row["timestamp"] and result["timestamp"] and result["timestamp"] != '0':
                    update_fields.append("timestamp = ?")
                    update_values.append(result["timestamp"])
                
                if row["type"] != 'PRE':
                    update_fields.append("type = ?")
                    update_values.append("ADDOLD")

                if update_fields:
                    update_query = f"UPDATE pre SET {', '.join(update_fields)} WHERE release = ?"
                    update_values.append(result["release"])
                    cursor.execute(update_query, update_values)

            self.conn.commit()
        except sqlite3.Error as error:
            self.logger.error(f"{c.server}/{e.target} - {error} - {message}", exc_info=True)
        finally:
            cursor.close()
            self.lock.release()
        return True
        
    def broadcast(self, message_type, data, parsed_release=None):
        for bot in self.output_bots:
            bot.broadcast(message_type, data, parsed_release)

class OutputBot(IRCBot):
    def __init__(
        self,
        args,
        logger,
        name,
        host,
        port,
        ssl_enabled,
        nickname,
        realname,
        ircchannels,
        nickserv,
        nickserv_command,
        password=None,
    ):
        super().__init__(args, logger, name, host, port, ssl_enabled, nickname, realname, ircchannels, nickserv, nickserv_command, password)
        self.pre_channels = [channel["name"] for channel in ircchannels if channel["type"] == "pre"]
        self.nuke_channels = [channel["name"] for channel in ircchannels if channel["type"] == "nuke"]
        self.info_channels = [channel["name"] for channel in ircchannels if channel["type"] == "info"]
        self.logger.info(f"OutputBot {name} initialized with channels: {ircchannels}")

        # TODO: Currently we spin up a new instance for every output_server - not ideal!
        self.musicbrainz_client = MusicBrainzClient()
        self.omdb_client = OMDBClient(os.getenv("OMDB_APIKEY", ""))


    def start(self):
        self.logger.info(f"OutputBot {self.name} starting...")
        super().start()

    def determine_section(self, data):
        if data["type"] == "ABook":
            return "AUDiOBOOKS"
        elif data["type"] == "Anime":
            return "ANiME"
        elif data["type"] == "App":
            if data["os"] == "Windows":
                return "APPS"
            elif data["os"] == "Linux":
                return "LiNUX"
            elif data["os"] == "macOS":
                return "MACOS"
            else:
                return "APPS"
        elif data["type"] == "Bookware":
            return "BOOKWARE"
        elif data["type"] == "eBook":
            return "EBOOKS"
        elif data["type"] == "Font":
            return "FONTS"
        elif data["type"] == "Game":
            if data["device"] == "Nintendo Switch":
                return "NSW"
            elif data["device"] == "Playstation 5":
                return "PS5"
            elif data["device"] == "Playstation 4":
                return "PS4"
            elif data["device"] == "Microsoft Xbox One":
                return "XBOXONE"
            elif data["device"] == "Microsoft Xbox360":
                return "XBOX360"
            else:
                return "GAMES"
        elif data["type"] == "Music":
            if data["format"] == "FLAC":
                return "FLAC"
            else:
                return "MP3"
        elif data["type"] == "MusicVideo":
            return "MViD"
        elif data["type"] == "TV":
            if data["format"] == "x264" or data["format"] == "h264":
                return "TV-X264"
            elif data["format"] == "x265" or data["format"] == "h265":
                return "TV-X265"
            else:
                return "TV"
        elif data["type"] == "Sports":
            return "SPORTS"
        elif data["type"] == "XXX":
            return "XXX"
        elif data["type"] == "Movie":
            if data["format"] == "DVDR":
                return "DVDR"
            elif data.get("flags") and "Complete" in data["flags"]:
                return "BLURAY"
            elif data["format"] == "x264" or data["format"] == "h264":
                return "X264"
            elif data["format"] == "x265" or data["format"] == "h265":
                return "X265"
            #else:
        #else:
        return "PRE"

    def broadcast(self, message_type, data, parsed_release=None):
        channels = []
        if message_type == "pre":
            channels = self.pre_channels
            data["section"] = self.determine_section(parsed_release)
        elif message_type == "nuke":
            channels = self.nuke_channels
        elif message_type == "info":
            channels = self.info_channels
            if data["type"] == "GENRE" and data["genre"]:
                data["genre"] = data["genre"].split('/')
            #elif data["type"] == "GENRE" and not data["genre"]:
            #    raise ValueError(f"Invalid genre data: {data}")

        # Create a new dictionary without None values
        filtered_data = {}
        for key, value in data.items():
            if value is not None:
                filtered_data[key] = value

        message = json.dumps(filtered_data)
        for channel in channels:
            try:
                self.connection.privmsg(channel, message)
                self.logger.info(f"OutputBot {self.name} sent message to {channel}: {message}")
            # TODO: Handle reconnections gracefully
            #except irc.client.ServerNotConnectedError:
            #    pass
            except Exception as e:
                self.logger.error(f"Error sending message to {channel}: {e}", exc_info=True)

class MusicBrainzClient:
    def __init__(self):
        self.base_url = "https://musicbrainz.org/ws/2/"
        self.headers = {"User-Agent": "pySceneTools/dev (dotmatrix @t riseup.net)"}
        self.api_hits = deque()

    def log_api_hits(self):
        now = time.time()
        # Remove hits older than 24 hours
        while self.api_hits and self.api_hits[0] < now - 86400:
            self.api_hits.popleft()
        hits_last_24h = len(self.api_hits)
        
        # Count hits in the last hour
        hits_last_hour = sum(1 for hit in self.api_hits if hit >= now - 3600)
        
        print(f"MusicBrainz API hits in the last 24 hours: {hits_last_24h} - in the last hour: {hits_last_hour}")

    def normalize_title(self, title):
        # Normalize title by removing non-word characters, removing double spaces,
        # converting to lower case, and replacing "&" with "and"
        title = title.replace(" & ", " and ")
        title = re.sub(r'\W+', '', title)
        title = re.sub(r'\s+', ' ', title).lower()
        # Convert German characters to their ASCII equivalents.
        title = title.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
        return title

    def search_artist(self, artist_name):
        self.api_hits.append(time.time())
        self.log_api_hits()
        url = f"{self.base_url}artist/"
        params = {
            "query": artist_name,
            "fmt": "json"
        }
        response = requests.get(url, headers=self.headers, params=params)
        response.raise_for_status()
        return response.json()

    def search_album(self, artist_id, album_title):
        self.api_hits.append(time.time())
        self.log_api_hits()
        url = f"{self.base_url}release-group/"
        params = {
            "artist": artist_id,
            "releasegroup": album_title,
            "fmt": "json"
        }
        response = requests.get(url, headers=self.headers, params=params)
        response.raise_for_status()
        return response.json()

    def get_genres(self, artist_name, album_title):
        artist_data = self.search_artist(artist_name)
        if not artist_data['artists']:
            return None
        artist_id = artist_data['artists'][0]['id']

        album_data = self.search_album(artist_id, album_title)
        if not album_data['release-groups']:
            return None

        # Filter results by comparing normalized titles
        normalized_album_title = self.normalize_title(album_title)
        for release_group in album_data['release-groups']:
            normalized_release_title = self.normalize_title(release_group['title'])
            if normalized_release_title == normalized_album_title: # and release_group.get('score', 0) > 80:
                album_id = release_group['id']
                break
        else:
            return None

        url = f"{self.base_url}release-group/{album_id}"
        params = {
            "inc": "genres",
            "fmt": "json"
        }
        self.api_hits.append(time.time())
        self.log_api_hits()
        response = requests.get(url, headers=self.headers, params=params)
        response.raise_for_status()
        album_info = response.json()
        print(album_info)
        return [genre['name'] for genre in album_info.get('genres', [])]

class OMDBClient:
    def __init__(self, api_key):
        self.base_url = "http://www.omdbapi.com/"
        self.api_key = api_key
        self.cache = []
        self.api_hits = deque()

    def log_api_hits(self):
        now = time.time()
        # Remove hits older than 24 hours
        while self.api_hits and self.api_hits[0] < now - 86400:
            self.api_hits.popleft()
        hits_last_24h = len(self.api_hits)
        
        # Count hits in the last hour
        hits_last_hour = sum(1 for hit in self.api_hits if hit >= now - 3600)
        
        print(f"OMDB API hits in the last 24 hours: {hits_last_24h} - in the last hour: {hits_last_hour}")

    def search_title(self, title, year=None):
        self.api_hits.append(time.time())
        self.log_api_hits()
        params = {
            "t": title,
            "apikey": self.api_key
        }
        if year:
            params["y"] = year
        response = requests.get(self.base_url, params=params)
        response.raise_for_status()
        print(response.json())
        return response.json()

    def normalize_title(self, title):
        # Normalize title by removing non-word characters, removing double spaces,
        # converting to lower case, and replacing "&" with "and"
        title = title.replace(" & ", " and ")
        title = re.sub(r'\W+', '', title)
        title = re.sub(r'\s+', ' ', title).lower()
        # Convert German characters to their ASCII equivalents.
        title = title.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
        return title

    def get_genres(self, title, title_extra, country, year=None):
        search_titles = [title]
        if title_extra:
            search_titles.append(title_extra)
        if country:
            search_titles.append(f"{title} {country}")
        for search_title in search_titles:
            # Check cache first
            for cached_query in self.cache:
                if cached_query['title'] == search_title and cached_query['year'] == year:
                    return cached_query['result']
            result = self.search_title(search_title, year)
            normalized_search_title = self.normalize_title(title)
            normalized_result_title = self.normalize_title(result.get("Title", ""))
            if normalized_result_title == normalized_search_title:
                genre = result.get("Genre")
                if genre and genre.lower() == "n/a":
                    genre = None
                # Add to cache
                self.cache.append({'title': search_title, 'year': year, 'result': genre})
                # Maintain cache size
                if len(self.cache) > 50:
                    self.cache.pop(0)
                return genre
            else:
                # Cache the search with no result
                self.cache.append({'title': search_title, 'year': year, 'result': None})
        return None

class SpotifyClient:
    def __init__(self):
        self.client_id = os.getenv("SPOTIFY_CLIENT_ID")
        self.client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
        self.access_token = None
        self.token_expires_in = None
        self.token_timestamp = None
        self.api_hits = deque()
        self.get_access_token()

    def get_access_token(self):
        auth_url = 'https://accounts.spotify.com/api/token'
        auth_headers = {
            'Authorization': 'Basic ' + base64.b64encode(f'{self.client_id}:{self.client_secret}'.encode()).decode()
        }
        auth_data = {
            'grant_type': 'client_credentials'
        }
        auth_response = requests.post(auth_url, headers=auth_headers, data=auth_data)
        auth_response.raise_for_status()
        auth_response_data = auth_response.json()
        self.access_token = auth_response_data['access_token']
        self.token_expires_in = auth_response_data['expires_in']
        self.token_timestamp = time.time()

    def ensure_token_valid(self):
        if not self.access_token or (time.time() - self.token_timestamp) >= self.token_expires_in:
            self.get_access_token()

    def log_api_hits(self):
        now = time.time()
        # Remove hits older than 24 hours
        while self.api_hits and self.api_hits[0] < now - 86400:
            self.api_hits.popleft()
        hits_last_24h = len(self.api_hits)
        
        # Count hits in the last hour
        hits_last_hour = sum(1 for hit in self.api_hits if hit >= now - 3600)
        
        print(f"Spotify API hits in the last 24 hours: {hits_last_24h} - in the last hour: {hits_last_hour}")

    def search_artist(self, artist_name):
        self.ensure_token_valid()
        self.api_hits.append(time.time())
        self.log_api_hits()
        search_url = 'https://api.spotify.com/v1/search'
        search_headers = {
            'Authorization': f'Bearer {self.access_token}'
        }
        search_params = {
            'q': artist_name,
            'type': 'artist'
        }
        search_response = requests.get(search_url, headers=search_headers, params=search_params)
        search_response.raise_for_status()
        search_response_data = search_response.json()
        return search_response_data['artists']['items'][0] if search_response_data['artists']['items'] else None

    def get_genres(self, artist_name):
        artist = self.search_artist(artist_name)
        if artist:
            return artist['genres']
        return None

class TMDBClient:
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://api.themoviedb.org/3"
        self.api_hits = deque()
        self.cache = {}  # Cache keyed by normalized title (with extra params)
        # Load genre lookup for TV shows using TMDB's genre API.
        self.movie_genre_lookup = self.load_genre_lookup(media_type="movie", language="en")
        self.tv_genre_lookup = self.load_genre_lookup(media_type="tv", language="en")

    def load_genre_lookup(self, media_type, language="en"):
        # Loads a mapping from genre ID to genre name.
        url = f"{self.base_url}/genre/{media_type}/list"
        params = {"api_key": self.api_key, "language": language}
        resp = requests.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
        lookup = {genre["id"]: genre["name"] for genre in data.get("genres", [])}
        return lookup

    def log_api_hits(self):
        now = time.time()
        while self.api_hits and self.api_hits[0] < now - 86400:
            self.api_hits.popleft()
        hits_last_24h = len(self.api_hits)
        hits_last_hour = sum(1 for hit in self.api_hits if hit >= now - 3600)
        print(f"TMDB API hits in the last 24 hours: {hits_last_24h} - in the last hour: {hits_last_hour}")

    def normalize_title(self, title):
        # Normalize title by removing non-word characters, removing double spaces,
        # converting to lower case, and replacing "&" with "and"
        title = title.replace(" & ", " and ")
        title = re.sub(r'\W+', '', title)
        title = re.sub(r'\s+', ' ', title).lower()
        # Convert German characters to their ASCII equivalents.
        title = title.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
        return title

    def get_genres(self, title, year=None, language=None, region=None):
        norm_title = self.normalize_title(title)
        key = (norm_title, year, language, region)
        if key in self.cache:
            return self.cache[key]

        search_url = f"{self.base_url}/search/movie"
        params = {"api_key": self.api_key, "query": title, "include_adult": False}
        if year:
            params["year"] = year
        if language:
            params["language"] = language
        if region:
            params["region"] = region

        self.api_hits.append(time.time())
        self.log_api_hits()
        resp = requests.get(search_url, params=params)
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])
        if results:
            # Normalize and compare the search title with the result title
            normalized_result_title = self.normalize_title(results[0].get("title", ""))
            if normalized_result_title == norm_title:
                movie_id = results[0]["id"]
                detail_url = f"{self.base_url}/movie/{movie_id}"
                detail_params = {"api_key": self.api_key}
                if language:
                    detail_params["language"] = language
                self.api_hits.append(time.time())
                self.log_api_hits()
                detail_resp = requests.get(detail_url, params=detail_params)
                detail_resp.raise_for_status()
                detail_data = detail_resp.json()
                # TMDB detail may include fully expanded "genres"
                if "genres" in detail_data:
                    genres_obj = detail_data.get("genres", [])
                else:
                    # Fall back: if only genre_ids are available, map them using our lookup.
                    genre_ids = detail_data.get("genre_ids", [])
                    genres_obj = [{"id": gid, "name": self.movie_genre_lookup.get(gid, "Unknown")} for gid in genre_ids]
                genre_list = [genre["name"] for genre in genres_obj]
                self.cache[key] = genre_list
                return genre_list
        self.cache[key] = None
        return None

    def get_tv_genres(self, title, year=None, language=None, region=None):
        norm_title = self.normalize_title(title)
        key = (norm_title, year, language, region)
        if key in self.cache:
            return self.cache[key]

        search_url = f"{self.base_url}/search/tv"
        params = {"api_key": self.api_key, "query": title}
        if year:
            params["first_air_date_year"] = year
        if language:
            params["language"] = language

        self.api_hits.append(time.time())
        self.log_api_hits()
        resp = requests.get(search_url, params=params)
        resp.raise_for_status()
        data = resp.json()
        results = data.get("results", [])
        if results:
            # Use the normalize_title() method to compare release title and result title.
            normalized_result_title = self.normalize_title(results[0].get("name", ""))
            if normalized_result_title == norm_title:
                tv_id = results[0]["id"]
                detail_url = f"{self.base_url}/tv/{tv_id}"
                detail_params = {"api_key": self.api_key}
                if language:
                    detail_params["language"] = language
                self.api_hits.append(time.time())
                self.log_api_hits()
                detail_resp = requests.get(detail_url, params=detail_params)
                detail_resp.raise_for_status()
                detail_data = detail_resp.json()
                # TMDB detail may include fully expanded "genres"
                if "genres" in detail_data:
                    genres_obj = detail_data.get("genres", [])
                else:
                    # Fall back: if only genre_ids are available, map them using our lookup.
                    genre_ids = detail_data.get("genre_ids", [])
                    genres_obj = [{"id": gid, "name": self.tv_genre_lookup.get(gid, "Unknown")} for gid in genre_ids]
                genre_list = [genre["name"] for genre in genres_obj]
                self.cache[key] = genre_list
                return genre_list
        self.cache[key] = None
        return None

class TVMazeClient:
    def __init__(self):
        self.base_url = "http://api.tvmaze.com"
        self.api_hits = deque()
        self.cache = {}  # Cache keyed by normalized title

    def normalize_title(self, title):
        # Normalize title by removing non-word characters, removing double spaces,
        # converting to lower case, and replacing "&" with "and"
        title = re.sub(r'\W+', '', title)
        title = re.sub(r'\s+', ' ', title).lower()
        title = title.replace(" & ", " and ")
        # Convert German characters to their ASCII equivalents.
        title = title.replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
        return title

    def log_api_hits(self):
        now = time.time()
        while self.api_hits and self.api_hits[0] < now - 86400:
            self.api_hits.popleft()
        hits_last_24h = len(self.api_hits)
        hits_last_hour = sum(1 for hit in self.api_hits if hit >= now - 3600)
        print(f"TVMaze API hits in the last 24 hours: {hits_last_24h} - in the last hour: {hits_last_hour}")

    def get_genres(self, title):
        norm_title = self.normalize_title(title)
        if norm_title in self.cache:
            return self.cache[norm_title]

        search_url = f"{self.base_url}/search/shows"
        params = {"q": title}
        self.api_hits.append(time.time())
        self.log_api_hits()
        resp = requests.get(search_url, params=params)
        resp.raise_for_status()
        data = resp.json()
        if data:
            print(f"TVMaze search results for {title}: {data}")
            show = data[0]["show"]
            normalized_result_title = self.normalize_title(show.get("name", ""))
            if normalized_result_title == norm_title:
                genres_list = show.get("genres", [])
                if not isinstance(genres_list, list):
                    genres_list = [genres_list]
                self.cache[norm_title] = genres_list
                return genres_list
        self.cache[norm_title] = None
        return None

class MetadataAgent:
    def __init__(self, logger, output_bots, lock):
        self.musicbrainz_client = MusicBrainzClient()
        self.spotify_client = SpotifyClient()
        self.omdb_client = OMDBClient(os.getenv("OMDB_APIKEY", ""))  # TODO: just define the API key in the class, like with SpotifyClient()
        self.tmdb_client = TMDBClient(os.getenv("TMDB_APIKEY", ""))  # dto.
        self.tvmaze_client = TVMazeClient()
        self.srrdb_feed_url = "https://www.srrdb.com/feed/srrs"
        self.srrdb_api_url = "https://api.srrdb.com/v1/details/"
        self.logger = logger
        self.output_bots = output_bots
        self.lock = lock

        with sqlite3.connect(os.getenv("PRE_DB_FILE"), check_same_thread=False) as conn:
            self.conn = conn
            self.conn.row_factory = sqlite3.Row

    def normalize_genre(genre):
        # Lowercase
        genre = genre.lower()
        # Remove apostrophes and most special chars except & - and /, keep spaces for now
        genre = re.sub(r"[^\w\s&/-]", "", genre)
        # Replace ' and ', " 'n' " with &
        genre = re.sub(r"\sand\s|\s?[\s\']n[\s\']\s?", "&", genre)
        # Collapse multiple spaces
        genre = re.sub(r"\s+", " ", genre)
        # Remove leading/trailing spaces
        genre = genre.strip()
        # Replace spaces with dots
        genre = genre.replace(" ", ".")
        # Remove trailing dots
        genre = re.sub(r"^.+|.+$", "", genre)
        return genre
                 
    def determine_genre(self, parsed_release):
        try:
            if parsed_release["type"] == "Music":
                artist = parsed_release.get("artist")
                title = parsed_release.get("title")
                title_extra = parsed_release.get("title_extra")
                if artist:
                    genres = self.musicbrainz_client.get_genres(artist, title)
                # [PRE] [FLAC] VA-Hip_Hop_Classics_Volume_Three-CD-FLAC-1997-THEVOiD 
                # {'release': 'VA-Hip_Hop_Classics_Volume_Three-CD-FLAC-1997-THEVOiD', 'title': 'Various', 'title_extra': 'Hip Hop Classics Volume Three', 'group': 'THEVOiD', 'year': 1997, 'date': None, 'season': None, 'episode': None, 'disc': None, 'flags': None, 'source': 'CD', 'format': 'FLAC', 'resolution': None, 'audio': None, 'device': None, 'os': None, 'version': None, 'language': None, 'country': None, 'type': 'Music'}
                else:
                    genres = self.musicbrainz_client.get_genres(title, title_extra)
                if not genres and artist != "Various" and title != "Various":
                    genres = self.spotify_client.get_genres(artist or title)
                if genres:
                    if isinstance(genres, str):
                        genres = [g.strip() for g in genres.split(",")]
                    elif not isinstance(genres, list):
                        genres = list(genres)
                    genres = [normalize_genre(genre) for genre in genres]
                    return genres
            elif parsed_release["type"] in ["TV", "Movie"]:
                title = parsed_release.get("title")
                title_extra = parsed_release.get("title_extra")
                country = parsed_release.get("country")
                year = parsed_release.get("year")
                language = ""
                # Extract and process language information:
                # 1. If parsed_release["language"] is None, default to "en" (English)
                lang_data = parsed_release.get("language")
                if lang_data is None:
                    language = "en"
                # 2. If language is provided as a dict, it might contain multiple entries.
                #    We ignore any key named "multi" and take the first valid language code.
                #    If only "multi" is present, we default to "fr" (French) as a fallback.
                elif isinstance(lang_data, dict):
                    valid_lang_codes = [code for code in lang_data.keys() if code.lower() != "multi"]
                    lang_code = valid_lang_codes[0] if valid_lang_codes else "fr"
                    # Use Babel to convert the short language code (e.g. "en") into a full language tag (e.g. "en-US").
                    # Note: This conversion uses Babel's locale data. If conversion fails, simply use the lang_code.
                    #try:
                    #    from babel import Locale
                    #    language = Locale.parse(lang_code).to_language_tag()
                    #except Exception:
                    #    language = lang_code
                # 3. Otherwise, if language is provided as a simple string, use it as-is.
                else:
                    language = lang_data

                if parsed_release["type"] == "TV":
                    # For TV shows, try OMDB first, then TMDB, then TVMaze.
                    genres = self.omdb_client.get_genres(title, title_extra, country, year)
                    if not genres and os.getenv("TMDB_APIKEY", ""):
                        genres = self.tmdb_client.get_tv_genres(title, year, language=language, region=country)
                    if not genres:
                        genres = self.tvmaze_client.get_genres(title)
                elif parsed_release["type"] == "Movie":
                    # For movies, try OMDB first then TMDB.
                    genres = self.omdb_client.get_genres(title, title_extra, country, year)
                    if not genres and os.getenv("TMDB_APIKEY", ""):
                        genres = self.tmdb_client.get_genres(title, year, language=language, region=country)
                if genres:  # TODO: Is duplicate with code above?
                    if isinstance(genres, str):
                        genres = [g.strip() for g in genres.split(",")]
                    elif not isinstance(genres, list):
                        genres = list(genres)
                    genres = [normalize_genre(genre) for genre in genres]
                    return genres
        except requests.exceptions.HTTPError as e:
            self.logger.error(f"HTTP error occurred: {e}", exc_info=True)
        except requests.exceptions.ConnectionError as e:
            self.logger.error(f"Connection error occurred: {e}", exc_info=True)
        except Exception as e:
            self.logger.error(f"{ERROR}: {Exception} - {e}", exc_info=True)
        return None

    def determine_info(self):
        getattr(self, "stop_event", threading.Event()).wait(timeout=60) # Wait for the OutputBots to start
        while not getattr(self, "stop_event", threading.Event()).is_set():
            try:
                feed = feedparser.parse(self.srrdb_feed_url)
                if feed.bozo:
                    print(f"Feed bozo exception: {feed.bozo_exception}")
                    if hasattr(feed.bozo_exception, 'getcode'):
                        raise requests.exceptions.HTTPError(f"HTTP error {feed.bozo_exception.getcode()} occurred while fetching feed: {self.srrdb_feed_url}")

                # Process items in reversed order (oldest first)
                items = feed.entries[::-1]
                for entry in items:
                    release_name = entry.title
                    # Check the release name against the pre table
                    cursor = self.conn.cursor()
                    cursor.execute("SELECT release, files, size FROM pre WHERE release=?", (release_name,))
                    row = cursor.fetchone()
                    cursor.close()
                    if row and (row["files"] is None or row["size"] is None):
                        # Fetch details from SRRDB API
                        response = requests.get(f"{self.srrdb_api_url}{release_name}")
                        response.raise_for_status()
                        data = response.json()
                        files = data.get("files", [])
                        total_files = len([f for f in files if not f["name"].lower().endswith((".nfo", ".sfv", ".m3u")) and not any(folder in f["name"].lower() for folder in ["subs/", "proof/", "sample/"])])
                        total_size = sum(f["size"] for f in files if not f["name"].lower().endswith((".nfo", ".sfv", ".m3u")) and not any(folder in f["name"].lower() for folder in ["subs/", "proof/", "sample/"]))
                        total_size_mib = round(total_size / (1024 * 1024))

                        if total_files == 0 or total_size_mib == 0:
                            continue

                        info_message = {
                            "type": "INFO",
                            "release": release_name,
                            "files": total_files,
                            "size": total_size_mib
                        }
                        self.process_info_message(info_message)

                # Get the pubDate of the feed
                feed_pub_date = feed.feed.published_parsed
                next_pull_time = datetime.datetime(*feed_pub_date[:6]) + datetime.timedelta(seconds=65)

                # Calculate the sleep time until the next pull
                sleep_time = (next_pull_time - datetime.datetime.now()).total_seconds()
                if sleep_time > 0:
                    getattr(self, "stop_event", threading.Event()).wait(timeout=sleep_time)
                else:
                    getattr(self, "stop_event", threading.Event()).wait(timeout=60)
            except requests.exceptions.HTTPError as e:
                self.logger.error(f"HTTP error occurred: {e}", exc_info=True)
            except Exception as e:
                self.logger.error(f"Error in determine_info: {e}", exc_info=True)
                getattr(self, "stop_event", threading.Event()).wait(timeout=60)  # Check every minute

    def process_info_message(self, message):
        result = {}
        result["type"] = message.get("type")
        result["release"] = message.get("release")
        result["files"] = message.get("files")
        result["size"] = message.get("size")
        result["genre"] = message.get("genre")

        try:
            self.lock.acquire()
            cursor = self.conn.cursor()

            if result["type"].lower() == "info":
                cursor.execute(
                    "UPDATE pre SET size=?, files=? WHERE release=?",
                    (
                        result["size"],
                        result["files"],
                        result["release"],
                    ),
                )
                self.broadcast("info", result)  # Notify the Broadcaster
            self.conn.commit()
        except sqlite3.Error as error:
            self.logger.error(f"srrAPI - {error} - {message}", exc_info=True)
        finally:
            cursor.close()
            self.lock.release()

    def broadcast(self, message_type, data, parsed_release=None):
        for bot in self.output_bots:
            bot.broadcast(message_type, data, parsed_release)


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
