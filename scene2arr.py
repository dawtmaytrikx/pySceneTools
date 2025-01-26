#!/usr/bin/python3

import argparse
import datetime
from dotenv import load_dotenv
import logging
import random
import requests
import sys
import time
import yaml # PyYAML

from classes import *
from conf import *
from constants import *


def start_argparse():
    # argument parser
    parser = argparse.ArgumentParser(
        description="This script adds release groups to the *arr apps, or removes them.",
        usage=f"python3 {sys.argv[0]} [-h] ([-i] [-p]) | ([-x] | [[-a | -r] GROUP])",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_const",
        const=True,
        default=False,
        help="Enable verbose mode.",
    )
    parser.add_argument(
        "-i",
        "--irc",
        action="store_const",
        const=True,
        default=False,
        help="Listens for new releases in the IRC prechans, extracts the group name, and adds it to the *arr instances.",
    )
    parser.add_argument(
        "-p",
        "--predb",
        action="store_const",
        const=True,
        default=False,
        help="Create a pre and nuke database by listening in IRC pre channels.",
    )
    action = parser.add_mutually_exclusive_group(required=False)
    action.add_argument(
        "-x",
        "--xrel",
        action="store_const",
        const=True,
        default=False,
        help="Check xREL for new releases and add them to the *arr instances.",
    )
    action.add_argument(
        "-a",
        "--add",
        action="store_const",
        const=True,
        default=False,
        help="Add new group.",
    )
    action.add_argument(
        "-r",
        "--remove",
        action="store_const",
        const=True,
        default=False,
        help="Remove group.",
    )
    parser.add_argument(
        "group", metavar="GROUP", type=str, nargs="?", help="Name of release group."
    )

    args = vars(parser.parse_args())

    if args["add"] or args["remove"]:
        if not args["group"]:
            parser.error("Must enter GROUP if using -a or -r!")
    if args["xrel"]:
        if args["add"] or args["remove"] or args["irc"] or args["predb"] or args["group"]:
            parser.error("-x cannot be used with -a, -r, -i, -p, or GROUP")
    if args["irc"] or args["predb"]:
        if args["add"] or args["remove"] or args["xrel"] or args["group"]:
            parser.error("-i and -p cannot be used with -a, -r, -x, or GROUP")

    return args


def create_scene2arr_db(dbname):
    # set up the database
    from classes import DB  # Local import to avoid circular import issue
    if not os.path.exists(dbname):
        with open(dbname, "w"):
            pass

    db = DB(dbname)

    db.cursor.execute(
        """CREATE TABLE IF NOT EXISTS scenegroups (
        id INTEGER PRIMARY KEY,
        groupname TEXT,
        release TEXT,
        pvr TEXT,
        releasedate INTEGER,
        timestamp TEXT
        );"""
    )

    db.cursor.execute(
        """CREATE TABLE IF NOT EXISTS latest (
        category TEXT PRIMARY KEY,
        release TEXT,
        releasedate INTEGER,
        timestamp TEXT
        );"""
    )

    db.connection.commit()

    return db

def create_pre_db(dbname):
    # set up the database
    from classes import DB  # Local import to avoid circular import issue
    if not os.path.exists(dbname):
        with open(dbname, "w"):
            pass

    db = DB(dbname)

    db.cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS pre (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            release TEXT,
            section TEXT,
            size TEXT,
            files INTEGER,
            genre TEXT,
            source TEXT,
            timestamp TEXT
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
            timestamp TEXT
        )
        """
    )

    db.connection.commit()


def init_pvrs(logger):
    from classes import PVR

    sonarr = PVR("sonarr")
    sonarr4k = PVR("sonarr4k")
    radarr = PVR("radarr")
    radarr4k = PVR("radarr4k")

    sonarr.url = os.getenv("SONARR_URL", "")
    sonarr.apikey = os.getenv("SONARR_APIKEY", "")

    sonarr4k.url = os.getenv("SONARR4K_URL", "")
    sonarr4k.apikey = os.getenv("SONARR4K_APIKEY", "")

    radarr.url = os.getenv("RADARR_URL", "")
    radarr.apikey = os.getenv("RADARR_APIKEY", "")

    radarr4k.url = os.getenv("RADARR4K_URL", "")
    radarr4k.apikey = os.getenv("RADARR4K_APIKEY", "")

    pvrs = [pvr for pvr in (sonarr, sonarr4k, radarr, radarr4k) if pvr.apikey and pvr.url]

    for pvr in pvrs:
        notify_headers = {
            "content-type": "application/json",
            "accept": "application/json",
            "X-Api-Key": pvr.apikey,
        }
        pvr.response = requests.get(pvr.url, headers=notify_headers)

        if pvr.response.status_code != 200:
            logger.error(f"{ERROR} Something's wrong with {pvr.name}")
            continue

        pvr.response = pvr.response.json()
        pvr.required = pvr.response["required"]
        pvr.ignored = pvr.response["ignored"]

        if isinstance(pvr.required, str):
            pvr.required = pvr.required.split(",")
        elif not isinstance(pvr.required, list):
            logger.error(f"{ERROR} Restrictions in {pvr.name} are neither LIST nor STR.")
            pvr.skip = True

    return pvrs


def xrel(args, logger, db, pvrs):
    for category in xrel_categories:
        if args["verbose"]:
            print(f"{VERBOSE} Now processing category {category}")
        db.cursor.execute(
            "SELECT releasedate FROM latest WHERE category = ?", (category,)
        )
        result = db.cursor.fetchone()
        if result is not None:
            lastprocessed = result[0]
        else:
            lastprocessed = 1

        for page in range(1, 51):
            already_processed = []
            logger.debug(f"{VERBOSE} Now processing page {page}")
            xrel = requests.get(
                "https://api.xrel.to/v2/release/browse_category.json"
                + f"?category_name={category}&per_page=100&page={page}"
            )
            if xrel.status_code == 429:
                logger.error(f"{ERROR} Rate limited. Try again later.")
                sys.exit(1)
            elif xrel.status_code != 200:
                logger.error(f"{ERROR} xREL API failed. Try again later.")
                logger.debug(f"{VERBOSE} {xrel.status_code} - {xrel.content}")
                sys.exit(1)
            xrel = xrel.json()["list"]

            for pvr in pvrs:
                if not pvr.skip:
                    for index, release in enumerate(xrel):
                        logger.debug(
                            f"{VERBOSE} Processing release {release['dirname']} for {pvr.name}. Release #{index}"
                        )

                        if page == 1 and release == xrel[0]:
                            latestrelease = release

                        # stop processing releases after this page
                        if (
                            release["time"] <= lastprocessed
                            and pvr.name not in already_processed
                        ):
                            already_processed.append(pvr.name)

                        # don't process releases ignored by $pvr
                        if isinstance(pvr.ignored, str):
                            ignorelist = pvr.ignored.split(",")
                        elif isinstance(pvr.ignored, list):
                            ignorelist = pvr.ignored
                        else:
                            logger.error(
                                f"{ERROR} Something's wrong with the ignored in {pvr.name}."
                            )
                            sys.exit(1)

                        try:
                            for ignorepattern in ignorelist:
                                if ignorepattern in release["dirname"]:
                                    raise IgnoreError
                        except IgnoreError:
                            logger.info(f"{IGNORED} {release['dirname']} in {pvr.name}.")
                            continue
                        newrestriction = "-" + release["group_name"]

                        # don't process duplicates
                        if newrestriction in pvr.checked:
                            continue
                        else:
                            pvr.checked.append(newrestriction)

                        # don't process release, if group is already whitelisted
                        if newrestriction not in pvr.required:
                            pvr.required.append(newrestriction)
                            pvr = update_pvr(args, logger, db, pvr, newrestriction, release)
                            logger.info(
                                f"{ADDED} {newrestriction} to {pvr.name}! Release: {release['dirname']}"
                            )
                        else:
                            logger.info(
                                f"{SKIPPING} {newrestriction} is already in "
                                + f"{pvr.name}! Release: {release['dirname']}"
                            )
                            continue


            logger.debug(
                f"{VERBOSE} {len(already_processed)} out of {len(pvrs)} "
                + "PVRs have reached their last processed release."
            )
            # will only trigger after all pvrs reached the previously processed release
            # and will process the rest of the page, since sometimes releases are backfilled.
            if len(already_processed) >= len(pvrs):
                break

        if latestrelease["time"] != lastprocessed:
            db.cursor.execute(
                """INSERT INTO latest 
                (category, release, releasedate, timestamp) 
                VALUES (?, ?, ?, ?)
                ON CONFLICT (category) DO UPDATE SET 
                release=excluded.release, 
                releasedate=excluded.releasedate, 
                timestamp=excluded.timestamp""",
                (
                    category,
                    latestrelease["dirname"],
                    latestrelease["time"],
                    int(datetime.datetime.now(datetime.timezone.utc).timestamp()),
                ),
            )
            db.connection.commit()
        else:
            logger.info(f"{INFO} Nothing to do in category {category}.")


def add_remove(args, logger, db, pvrs):
    newrestriction = "-" + "".join(args["group"])
    logger.debug(f"{VERBOSE} Group: {newrestriction}")
    for pvr in pvrs:
        logger.debug(f"{VERBOSE} Now handling {pvr.name}")
        if not pvr.skip:
            if args["add"]:
                logger.debug(f"{VERBOSE} Adding {newrestriction} to {pvr.name}!")
                if newrestriction not in pvr.required:
                    pvr.required.append(newrestriction)
                    pvr = update_pvr(args, logger, db, pvr, newrestriction)
                    logger.info(f"{ADDED} {newrestriction} to {pvr.name}!")
                else:
                    logger.info(f"{INFO} {newrestriction} is already in {pvr.name}!")
                    continue
            elif args["remove"]:
                logger.debug(f"{VERBOSE} Removing {newrestriction} from {pvr.name}")
                if newrestriction in pvr.required:
                    pvr.required.remove(newrestriction)
                    pvr = update_pvr(args, logger, db, pvr, newrestriction)
                    logger.info(f"{REMOVED} {newrestriction} from {pvr.name}!")
                else:
                    logger.info(f"{INFO} {newrestriction} was not in {pvr.name}!")
                    continue


def update_pvr(args, logger, db, pvr, newrestriction, release=None):
    pvr.required = list(dict.fromkeys(pvr.required))  # remove duplicates
    if isinstance(pvr.response["required"], str):
        pvr.response["required"] = ",".join(
            pvr.required
        )  # convert list back to str for radarr
    else:
        pvr.response["required"] = pvr.required
    notify_data = pvr.response
    notify_headers = {
        "content-type": "application/json",
        "accept": "application/json",
        "X-Api-Key": pvr.apikey,
    }
    reply = requests.put(pvr.url, json=notify_data, headers=notify_headers)

    while reply.status_code != 202:
        logger.error(
            f"{ERROR} Could not modify {newrestriction} in {pvr.name}. Response code: {reply.status_code}"
        )
        logger.debug(f"{VERBOSE} {reply.content}")
        time.sleep(60)
        # TO DO: Handle errors
    if reply.status_code == 202:
        try:
            db.cursor.execute(
                """INSERT INTO scenegroups 
                (groupname, release, pvr, releasedate, timestamp)
                VALUES (?, ?, ?, ?, ?)""",
                (
                    release["group_name"],
                    release["dirname"],
                    pvr.name,
                    release["time"],
                    int(datetime.datetime.now(datetime.timezone.utc).timestamp()),
                ),
            )
        except TypeError:
            db.cursor.execute(
                """INSERT INTO scenegroups 
                (groupname, release, pvr, releasedate, timestamp) 
                VALUES (?, ?, ?, ?, ?)""",
                (
                    args["group"],
                    None,
                    pvr.name,
                    None,
                    int(datetime.datetime.now(datetime.timezone.utc).timestamp()),
                ),
            )
        db.connection.commit()

    return pvr

def main(args=None):
    load_dotenv()
    if args is None:
        args = start_argparse()

    logger = logging.getLogger(__name__)
    logger.setLevel(logging.DEBUG if args["verbose"] else logging.INFO)

    # Check if the logger already has handlers (we don't want to add more than one, if this function is called multiple times)
    if not logger.handlers:
        # Add a StreamHandler to log to the console
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        logger.addHandler(console_handler)

     
    if args["xrel"] or args["add"] or args["remove"]:
        scene2arr_db = create_scene2arr_db(SCENE2ARR_DB_FILE)

        pvrs = init_pvrs(logger)
        if args["xrel"]:
            xrel(args, logger, scene2arr_db, pvrs)
        elif args["add"] or args["remove"]:
            add_remove(args, logger, scene2arr_db, pvrs)

        scene2arr_db.connection.close()

    if args["irc"] or args["predb"]:
        pre_db = create_pre_db(PRE_DB_FILE)
        try:
            with open(IRC_CONFIG_FILE, "r") as ymlfile:
                cfg = yaml.safe_load(ymlfile)
        except Exception as e:
            logger.error(f"{ERROR} loading {IRC_CONFIG_FILE}:", e)
            sys.exit(1)
        IRCBot.lock = threading.Lock()
        threads = []
        bots = []
        for server in cfg["servers"]:
            name = server["name"]
            host = server["host"]
            nickname = server.get("nickname") or f"humanperson{random.randint(100, 999)}"
            realname = server.get("realname", None)
            ssl_enabled = server.get("ssl_enabled", True)
            port = server.get("port", 6667)
            password = server.get("password", None)
            nickserv = server.get("nickserv", None)
            nickserv_command = server.get("nickserv_command", None)
            channels = server["channels"]
            bot = IRCBot(
                args,
                logger,
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
            logger.info(f"{INFO} Keyboard interrupt detected, exiting...")
            for bot in bots:
                try:
                    bot.disconnect()
                    #pass
                except Exception as e:
                    logger.error(f"{ERROR} stopping bot: {e}")
            for t in threads:
                t.join()
            logger.info("All threads stopped, exiting.")



if __name__ == "__main__":
    main()
