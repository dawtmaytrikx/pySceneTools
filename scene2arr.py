#!/usr/bin/python3

import argparse
import datetime
import requests
import sys
import time

from conf import *
from classes import *


def start_argparse():
    # argument parser
    parser = argparse.ArgumentParser(
        description="This script adds release groups to the *arr apps, or removes them.",
        usage=f"python3 {sys.argv[0]} [-h] ([-s] [[ -a | -r ] GROUP ])"
    )
    action = parser.add_mutually_exclusive_group(required=True)
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
    action.add_argument(
        "-s",
        "--scan",
        action="store_const",
        const=True,
        default=False,
        help="Check the xREL API for new groups.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_const",
        const=True,
        default=False,
        help="Enable verbose mode.",
    )
    
    args = vars(parser.parse_args())
    
    if args["add"] or args["remove"]:
        if not args["group"]:
            parser.error("Must enter GROUP if using -a or -r!")
    else:
        if args["group"]:
            parser.error("Cannot specify a GROUP with these options!")

    return args


def create_db(dbname):
    # set up the database
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
        date TEXT
        );"""
    )
    
    db.cursor.execute(
        """CREATE TABLE IF NOT EXISTS latest (
        category TEXT PRIMARY KEY,
        release TEXT,
        releasedate INTEGER,
        date TEXT
        );"""
    )
    db.connection.commit()

    return db


def init_pvrs():
    # get filters from PVR
    possible_pvrs = (sonarr, sonarr4k, radarr, radarr4k)
    pvrs = []
    for pvr in possible_pvrs:
        if pvr.apikey:
            pvrs.append(pvr)
    
    for pvr in pvrs:
        notify_headers = {
            "content-type": "application/json",
            "accept": "application/json",
            "X-Api-Key": pvr.apikey,
        }
        pvr.response = requests.get(pvr.url, headers=notify_headers)
    
        if pvr.response.status_code != 200:
            print(f"ERROR: Something's wrong with {pvr.name}")
            continue
    
        pvr.response = pvr.response.json()
        pvr.required = pvr.response["required"]
        pvr.ignored = pvr.response["ignored"]
    
        if isinstance(pvr.required, str):
            pvr.required = pvr.required.split(",")
        elif not isinstance(pvr.required, list):
            print(f"ERROR: Restrictions in {pvr.name} are neither LIST nor STR.")
            pvr.skip = True

    return pvrs


def scan():
    for category in ("MOVIES", "TV"):
        if args["verbose"]:
            print(f"VERBOSE: Now processing category {category}")
        db.cursor.execute("SELECT releasedate FROM latest WHERE category = ?", (category,))
        result = db.cursor.fetchone()
        if result is not None:
            lastprocessed = result[0]
        else:
            lastprocessed = 1

        for page in range(1, 51):
            already_processed = []
            if args["verbose"]:
                print(f"VERBOSE: Now processing page {page}")
            xrel = requests.get(
                "https://api.xrel.to/v2/release/browse_category.json"
                + f"?category_name={category}&per_page=100&page={page}"
            )
            if xrel.status_code == 429:
                print("ERROR: Rate limited. Try again later.")
                sys.exit(1)
            elif xrel.status_code != 200:
                print("ERROR: xREL API failed. Try again later.")
                if args["verbose"]:
                    print(f"VERBOSE: {xrel.status_code} - {xrel.content}")
                sys.exit(1)
            xrel = xrel.json()["list"]

            for pvr in pvrs:
                if not pvr.skip:
                    for index, release in enumerate(xrel):
                        is_ignored = False
                        if args["verbose"]:
                            print(
                                f"VERBOSE: Processing release {release['dirname']} for {pvr.name}. Release #{index}"
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
                            print(
                                f"ERROR: Something's wrong with the ignored in {pvr.name}."
                            )
                            sys.exit(1)

                        for ignorepattern in ignorelist:
                            if ignorepattern in release["dirname"]:
                                is_ignored = True  # TODO raise IgnoreError
                                break
                        if is_ignored == True:
                            print(f"IGNORED: {release['dirname']} in {pvr.name}.")
                            continue
                        else:
                            newrestriction = "-" + release["group_name"]

                        # don't process duplicates
                        if newrestriction in pvr.checked:
                            continue
                        else:
                            pvr.checked.append(newrestriction)

                        # don't process release, if group is already whitelisted
                        if newrestriction not in pvr.required:
                            pvr.required.append(newrestriction)
                            pvr = update_pvr(pvr, newrestriction, release)
                            print(f"ADDED: {newrestriction} to {pvr.name}! Release: {release['dirname']}")
                        else:
                            print(
                                f"SKIPPED: {newrestriction} is already in "
                                + f"{pvr.name}! Release: {release['dirname']}"
                            )
                            continue

            if args['verbose']:
                print(
                    f'VERBOSE: {len(already_processed)} out of {len(pvrs)} '
                    + 'PVRs have reached their last processed release.'
                )
            # will only trigger after all pvrs reached the previously processed release
            # and will process the rest of the page, since sometimes releases are backfilled.
            if len(already_processed) >= len(pvrs):
                break

        if latestrelease["time"] != lastprocessed:
            db.cursor.execute(
                """INSERT INTO latest 
                (category, release, releasedate, date) 
                VALUES (?, ?, ?, ?)
                ON CONFLICT (category) DO UPDATE SET 
                release=excluded.release, 
                releasedate=excluded.releasedate, 
                date=excluded.date""",
                (
                    category,
                    latestrelease["dirname"],
                    latestrelease["time"],
                    datetime.datetime.now(datetime.timezone.utc),
                ),
            )
            db.connection.commit()
        else:
            print(f"INFO: Nothing to do in category {category}.")


def add_remove():
    newrestriction = "-" + "".join(args["group"])
    if args["verbose"]:
        print(f"VERBOSE: Group: {newrestriction}")
    for pvr in pvrs:
        if args["verbose"]:
            print(f"VERBOSE: Now handling {pvr.name}")
        if not pvr.skip:
            if args["add"]:
                if args["verbose"]:
                    print(f"VERBOSE: Adding {newrestriction} to {pvr.name}!")
                if newrestriction not in pvr.required:
                    pvr.required.append(newrestriction)
                    pvr = update_pvr(pvr, newrestriction)
                    print(f'ADDED: {newrestriction} to {pvr.name}!')
                else:
                    print(f"INFO: {newrestriction} is already in {pvr.name}!")
                    continue
            elif args["remove"]:
                if args["verbose"]:
                    print(f"VERBOSE: Removing {newrestriction} from {pvr.name}")
                if newrestriction in pvr.required:
                    pvr.required.remove(newrestriction)
                    pvr = update_pvr(pvr, newrestriction)
                    print(f'REMOVED: {newrestriction} from {pvr.name}!')
                else:
                    print(f"INFO: {newrestriction} was not in {pvr.name}!")
                    continue


def update_pvr(pvr, newrestriction, release=None):
    pvr.required = list(dict.fromkeys(pvr.required))  # remove duplicates
    if isinstance(pvr.response["required"], str):
        pvr.response['required'] = ",".join(pvr.required)  # convert list back to str for radarr
    else:
        pvr.response['required'] = pvr.required
    notify_data = pvr.response
    notify_headers = {
        "content-type": "application/json",
        "accept": "application/json",
        "X-Api-Key": pvr.apikey,
    }
    reply = requests.put(pvr.url, json=notify_data, headers=notify_headers)

    while reply.status_code != 202:
        print(
            f"ERROR: Could not modify {newrestriction} in {pvr.name}. Response code: {reply.status_code}"
        )
        if args["verbose"]:
            print(f"VERBOSE: {reply.content}")
        time.sleep(60)
        # TO DO: Handle errors
    if reply.status_code == 202:
        try:
            db.cursor.execute(
                """INSERT INTO scenegroups 
                (groupname, release, pvr, releasedate, date)
                VALUES (?, ?, ?, ?, ?)""",
                (
                    release["group_name"],
                    release["dirname"],
                    pvr.name,
                    release["time"],
                    datetime.datetime.now(datetime.timezone.utc),
                ),
            )
        except TypeError:
            db.cursor.execute(
                """INSERT INTO scenegroups 
                (groupname, release, pvr, releasedate, date) 
                VALUES (?, ?, ?, ?, ?)""",
                (
                    args["group"],
                    None,
                    pvr.name,
                    None,
                    datetime.datetime.now(datetime.timezone.utc),
                ),
            )
        db.connection.commit()

    return pvr


if __name__ == "__main__":
    args = start_argparse()
    
    db = create_db("scene2arr.db")
    
    pvrs = init_pvrs()

    if args["scan"]:
        scan()
    elif args["add"] or args["remove"]:
        add_remove()
    
    db.connection.close()