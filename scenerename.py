#!/usr/bin/python3

import argparse
import datetime
from dotenv import load_dotenv
import json
import random
import requests
import signal
import sys
from time import sleep
import urllib.parse
import zlib

from classes import *
from constants import *


# set up some constants
buffersize = 65536
extensions = [".mkv", ".avi", ".mp4"]
sampletags = ["", "-sample", ".sample"]
suffixes = [  # common additions from usenet
    "-AsRequested",
    "-NZBgeek",
    "-SickBeard",
    "-Obfuscated",
    "-Scrambled",
    "-RP",
    ".1",
    "(1)",
    "-1",
    ".repost",
    "-repost",
    "-BUYMORE",
    "-newz",
    ".",
    " ",
    "-postbot",
    "-[cx86]",
    "-BWBP",
    "-[TRP]",
    "[rarbg]",
    "-RakuvFIN",
    "-Rakuv",
]
skiptags = [  # hardcoded blacklist, add p2p groups
    "dirfix", # a dirfix release doesn't include the actual data
    "_S0",
    "_S1",
    "-d0rks",
    "-BTN",
    "-WiKi",
    "-2Maverick",
    "-NTb",
    "-BTW",
    "-McTav",
    "M3lloW",
    "itouch-mw",
    "[Fullmetal]",
    "-CtrlHD",
]


# here come our functions
def start_argparse():
    # set up ArgumentParser
    parser = argparse.ArgumentParser(
        description="This script renames SCENE media files and compares their hashes to those stored at srrDB."
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
        "-f",
        "--skip-not-found",
        action="store_const",
        const=True,
        default=False,
        help="Disable processing of files that were previously marked as not found.",
    )
    parser.add_argument(
        "-n",
        "--no-comparison",
        action="store_const",
        const=True,
        default=False,
        help="Disables hashing of files for comparison with hashes stored at srrDB to check for corruption."
        + "Will still hash files to identify and rename them.",
    )
    parser.add_argument(
        "-s",
        "--no-ssl-verify",
        action="store_const",
        const=True,
        default=False,
        help="Disable SSL verification (not secure).",
    )
    parser.add_argument(
        "-t",
        "--tag",
        action="store",
        default="",
        nargs=1,
        help="Tag the files in DIR as being MOViES, TV, etc.",
    )
    parser.add_argument(
        "-w",
        "--whitelist",
        action="store",
        default="",
        nargs="+",
        metavar="ARG",
        help="Only process files that include at least one of the arguments (case insensitive).",
    )
    parser.add_argument(
        "-d", "--dir", nargs=1, required=True, help="Folder with your media files."
    )
    # TODO: skip errors

    return vars(parser.parse_args())


def create_db(dbname):
    if not os.path.exists(dbname):
        with open(dbname, "w"):
            pass

    db = DB(dbname)

    db.cursor.execute(
        """CREATE TABLE IF NOT EXISTS srrdb 
        (
            relname TEXT PRIMARY KEY,
            origname TEXT,
            crccalc TEXT,
            crcweb TEXT,
            status TEXT,
            tag TEXT,
            timestamp INTEGER
        );"""
    )

    db.cursor.execute(
        """CREATE TABLE IF NOT EXISTS errors 
        (
            key INTEGER PRIMARY KEY AUTOINCREMENT,
            relname TEXT,
            errnum TEXT,
            description TEXT,
            page TEXT,
            timestamp INTEGER
        );"""
    )

    db.cursor.execute(
        """CREATE TABLE IF NOT EXISTS lastrun
        (
            key INTEGER PRIMARY KEY AUTOINCREMENT,
            start INTEGER,
            end INTEGER,
            exitcode INTEGER,
            parameters TEXT
        );"""
    )
    db.connection.commit()

    return db


def signal_handler(sig, frame):
    end_run(1)
    print("KeyboardInterrupt caught, program ended gracefully.")
    sys.exit(1)


def end_run(exitcode):
    # clean up db
    if random.randrange(1, 11) == 1:
        if args["verbose"]:
            print(f"{VERBOSE} Cleaning up DB ...")
        db.cursor.execute("VACUUM")

    end = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
    db.cursor.execute(
        "UPDATE lastrun SET end=?, exitcode=? WHERE start=?", (end, exitcode, start)
    )
    db.connection.commit()
    db.connection.close()
    session.close()


def loadpage(url):
    response = session.get(url)

    while response.status_code == 503:
        print("RATE LIMITED! Sleeping 10 s ...")
        sleep(10)
        response = session.get(response.url)

    if args["verbose"]:
        print(f"{VERBOSE} {response.status_code} - {url}\r\n{response.json()}")

    return response


def error(errnum, description, fileobj):
    print(f"{ERROR} {errnum} - {description}\r\n\tfile: {fileobj.filename}")
    db.cursor.execute(
        """INSERT INTO errors 
        (relname, errnum, description, page, timestamp) 
        VALUES (?, ?, ?, ?, ?)""",
        (
            fileobj.filepath,
            errnum,
            str(description),
            json.dumps(fileobj.page, indent=4),
            int(datetime.datetime.now(datetime.timezone.utc).timestamp()),
        ),
    )


def mislabeled(fileobj):
    newfilepath = os.path.join(fileobj.dirpath, fileobj.realName) + fileobj.extension
    if os.path.exists(newfilepath):
        error(
            13,
            f"Tried renaming {fileobj.releaseName} to {fileobj.realName}, but file already exists!",
            fileobj,
        )
        raise OSError()
    os.rename(fileobj.filepath, newfilepath)
    print(f"{RENAMED} {fileobj.releaseName} -> {fileobj.realName}")
    upsert_db(fileobj, "RENAMED")  # TODO: move this down and simplify upsert_db()
    fileobj.filepath = newfilepath
    fileobj.releaseName = fileobj.realName
    fileobj.realName = None
    return fileobj


def calculatecrc(fileobj):
    if args["verbose"]:
        print(f"{VERBOSE} Calculating CRC for {fileobj.filename}")

    with open(fileobj.filepath, "rb") as afile:
        buffr = afile.read(buffersize)
        crcvalue = 0
        while len(buffr) > 0:
            crcvalue = zlib.crc32(buffr, crcvalue)
            buffr = afile.read(buffersize)
    fileobj.crccalc = "{:08X}".format(crcvalue)

    if args["verbose"]:
        print(f"{VERBOSE} CRC is {fileobj.crccalc}")

    return fileobj


def getsize(fileobj):
    fileobj.sizeondisk = os.path.getsize(fileobj.filepath)
    fileobj.sizeonsrrdb = int(fileobj.page["archived-files"][0]["size"])

    if args["verbose"]:
        print(
            f"{VERBOSE} Size of file on disk: {fileobj.sizeondisk}"
            + f" - size of file on srrdb: {fileobj.sizeonsrrdb}"
        )

    return fileobj


def wrong_filesize(fileobj):
    upsert_db(fileobj, "CORRUPT")
    print(f"{WRONGFILESIZE} {fileobj.releaseName}")


def process_files(path):
    for dirpath, dirs, files in os.walk(path):
        for filename in files:
            fileobj = FileToCheck(dirpath, filename)

            try:
                fileobj = skip_file(fileobj)

                response = loadpage(
                    "https://api.srrdb.com/v1/details/"
                    + urllib.parse.quote_plus(fileobj.releaseName),
                )

                # check response code
                # 404 only on release/details
                # 302 is redirect
                # what's with 300?
                # 400 is illegal characters (should be caught by skiptags!)
                if response.status_code == 400:
                    error(5, "Illegal character in filename!", fileobj)
                    continue

                # rename
                if response.history:  # if response.status_code == 302:
                    # see https://bitbucket.org/srrdb/srrdb-issues/issues/114/api-faulty-redirect-if-query-contains
                    realurl = response.url.replace("/release/", "/v1/")
                    fileobj.page = loadpage(realurl).json()

                    if args["verbose"]:
                        print(
                            f"{VERBOSE} {response.status_code} - {realurl}\r\n{fileobj.page}"
                        )

                    fileobj.realName = fileobj.page["name"]
                    fileobj = mislabeled(fileobj)

                fileobj.page = response.json()

                if response.status_code == 200 and fileobj.page:
                    if args["no_comparison"]:
                        upsert_db(fileobj, None)
                        print(f"{MATCHED} {fileobj.releaseName}")

                # search for release
                if response.status_code == 404 or not fileobj.page:
                    fileobj = search_for_release(fileobj)

                if args["no_comparison"]:
                    continue

                # find CRC in page
                try:
                    if not fileobj.page["archived-files"]:
                        raise KeyError
                except KeyError:
                    error(14, "No files in release " + fileobj.releaseName, fileobj)
                    continue

                # compare filesizes
                if not fileobj.sizeondisk or not fileobj.sizeonsrrdb:
                    fileobj = getsize(fileobj)

                if fileobj.sizeondisk == fileobj.sizeonsrrdb:
                    fileobj.crcweb = fileobj.page["archived-files"][0]["crc"]
                else:
                    if fileobj.crccalc:
                        wrong_filesize(fileobj)
                        continue
                    try:
                        fileobj = search_by_crc(fileobj)
                    except ReleaseNotFoundError:
                        continue

                # calculate CRC
                if not fileobj.crccalc:
                    db.cursor.execute(
                        "SELECT crccalc FROM srrdb WHERE relname=?",
                        (fileobj.releaseName,),
                    )
                    record = db.cursor.fetchone()

                    if record is not None and record[0] is not None:
                        if args["verbose"]:
                            print(f"{VERBOSE} Using CRC found in DB: {fileobj.crccalc}")
                        fileobj.crccalc = record[0]
                    else:
                        if args["verbose"]:
                            print(f"{VERBOSE} No CRC found in DB.")
                        fileobj = calculatecrc(fileobj)

                if fileobj.crccalc == fileobj.crcweb:
                    upsert_db(fileobj, "OK")
                    print(f"{OK} {fileobj.releaseName} {fileobj.crccalc}")
                else:
                    upsert_db(fileobj, "CORRUPT")
                    print(
                        f"{CORRUPT} {fileobj.releaseName} {fileobj.crccalc} {fileobj.crcweb}"
                    )

            except requests.exceptions.RequestException as e:
                error("pyCurl", e, fileobj)
                continue
            except SkipFileError:
                continue
            except ReleaseNotFoundError:
                continue
            except OSError:
                continue
            finally:
                try:
                    db.connection.commit()
                except sqlite3.ProgrammingError:  # triggers at KeyBoardInterrupt
                    pass


def skip_file(fileobj):
    # is this even a media file?
    if fileobj.extension not in extensions:
        raise SkipFileError()

    # handle whitelist
    for item in args["whitelist"]:
        if item in fileobj.filename.lower():
            break
        else:
            print(f"{NOTWHITELISTED} {fileobj.filename}")
            raise SkipFileError()

    # fix suffixes
    restart = True
    while restart:
        for suffix in suffixes:
            restart = False
            if fileobj.releaseName.lower().endswith(suffix.lower()):
                fileobj.realName = fileobj.releaseName[: -len(suffix)]
                fileobj = mislabeled(fileobj)
                restart = True

    # skip, if already processed
    # TODO: skip manually renamed
    db.cursor.execute(
        "SELECT status FROM srrdb WHERE relname=?", (fileobj.releaseName,)
    )
    record = db.cursor.fetchone()

    if record is not None:
        if record[0] == "OK":
            print(f"{SKIPPINGOK} {fileobj.releaseName}")
            raise SkipFileError()

        elif record[0] == "CORRUPT":
            print(f"{SKIPPINGCORRUPT} {fileobj.releaseName}")
            raise SkipFileError()

        elif record[0] == "NOT FOUND" and args["skip_not_found"]:
            print(f"{SKIPPINGNOTFOUND} {fileobj.releaseName}")
            raise SkipFileError()

        elif record[0] is None or record[0] == "RENAMED":
            if args["no_comparison"]:
                print(f"{SKIPPINGUNPROCESSED} {fileobj.releaseName}")
                raise SkipFileError()

    for skiptag in skiptags:
        if skiptag.lower() in fileobj.releaseName.lower():
            print(f"{BLACKLISTED} {fileobj.releaseName}")
            raise SkipFileError()

    return fileobj


def search_for_release(fileobj):
    fileobj.page = loadpage(
        "https://api.srrdb.com/v1/search/r:"
        + urllib.parse.quote_plus(fileobj.releaseName)
    ).json()

    if "resultsCount" not in fileobj.page:
        error(
            1,
            "Problem while processing page https://api.srrdb.com/v1/search/r:"
            + urllib.parse.quote_plus(fileobj.releaseName)
            + "\r\n"
            + fileobj.page,
            fileobj,
        )
        fileobj = search_by_sample(fileobj)

    if int(fileobj.page["resultsCount"]) == 1:
        # rename
        fileobj.page = loadpage(
            "https://api.srrdb.com/v1/details/"
            + urllib.parse.quote_plus(fileobj.page["results"][0]["release"])
        ).json()

        try:
            if len(fileobj.page["archived-files"]) == 1:
                fileobj = getsize(fileobj)
                if fileobj.sizeondisk == fileobj.sizeonsrrdb:
                    fileobj.realName = fileobj.page["name"]
                    fileobj = mislabeled(fileobj)
                else:
                    # wrong_filesize(fileobj)
                    error(
                        15,
                        "Filesize does not match that of release "
                        + fileobj.page["name"],
                        fileobj,
                    )
                    fileobj = search_by_sample(fileobj)
            else:
                error(6, "Multiples files in release " + fileobj.page["name"], fileobj)
                fileobj = search_by_sample(fileobj)
        except KeyError:
            error(
                11,
                "Problem while processing page https://api.srrdb.com/v1/details/"
                + fileobj.page["results"][0]["release"]
                + "\r\n"
                + json.dumps(fileobj.page, indent=4),
                fileobj,
            )
            fileobj = search_by_sample(fileobj)

    # search for sample name
    else:
        fileobj = search_by_sample(fileobj)

    return fileobj


def search_by_sample(fileobj):
    for index, sampletag in enumerate(sampletags):
        samplename = fileobj.releaseName + sampletag + fileobj.extension
        fileobj.page = loadpage(
            "https://api.srrdb.com/v1/search/store-real-filename:"
            + urllib.parse.quote_plus(samplename)
        ).json()

        if "resultsCount" in fileobj.page and int(fileobj.page["resultsCount"]) == 1:
            # rename
            fileobj.page = loadpage(
                "https://api.srrdb.com/v1/details/"
                + urllib.parse.quote_plus(fileobj.page["results"][0]["release"])
            ).json()

            try:
                if len(fileobj.page["archived-files"]) == 1:
                    fileobj = getsize(fileobj)
                    if fileobj.sizeondisk == fileobj.sizeonsrrdb:
                        fileobj.realName = fileobj.page["name"]
                        fileobj = mislabeled(fileobj)
                        break
                    else:
                        # wrong_filesize(fileobj)
                        error(
                            10,
                            "Filesize does not match that of release "
                            + fileobj.page["name"],
                            fileobj,
                        )
                        fileobj = search_by_crc(fileobj)
                else:
                    error(
                        7, "Multiple files in release " + fileobj.page["name"], fileobj
                    )
                    fileobj = search_by_crc(fileobj)
            except KeyError:
                error(
                    2,
                    "Problem while processing page https://api.srrdb.com/v1/details/"
                    + fileobj.page["results"][0]["release"]
                    + "\r\n"
                    + json.dumps(fileobj.page, indent=4),
                    fileobj,
                )
                fileobj = search_by_crc(fileobj)

        if index == len(sampletags) - 1:
            fileobj = search_by_crc(fileobj)

    return fileobj


def search_by_crc(fileobj):  # db
    # if crc has already been calculated, don't do it again
    db.cursor.execute(
        "SELECT crccalc FROM srrdb WHERE relname=?", (fileobj.releaseName,)
    )
    record = db.cursor.fetchone()

    if record is not None and record[0] is not None:
        fileobj.crccalc = record[0]
    else:
        fileobj = calculatecrc(fileobj)

    fileobj.page = loadpage(
        "https://api.srrdb.com/v1/search/archive-crc:" + fileobj.crccalc
    ).json()

    if int(fileobj.page["resultsCount"]) == 1:
        # rename
        fileobj.page = loadpage(
            "https://api.srrdb.com/v1/details/"
            + urllib.parse.quote_plus(fileobj.page["results"][0]["release"])
        ).json()

        if not fileobj.page:
            # url of page
            error(11, "Error in srrDB entry!", fileobj)
        else:
            try:
                if len(fileobj.page["archived-files"]) == 1:
                    fileobj = getsize(fileobj)
                    if fileobj.sizeondisk == fileobj.sizeonsrrdb:
                        fileobj.realName = fileobj.page["name"]
                        fileobj = mislabeled(fileobj)
                        # At this point the file can be OK'd as we searched for the
                        # crc of the file. We're still grabbing the CRC from the
                        # details page as a sanity check.
                        fileobj.crcweb = fileobj.page["archived-files"][0]["crc"]
                    else:
                        # wrong_filesize(fileobj)
                        error(
                            9,
                            "Filesize does not match that of release "
                            + fileobj.page["name"],
                            fileobj,
                        )
                        raise ReleaseNotFoundError()
                else:
                    error(
                        8, "Multiple files in release " + fileobj.page["name"], fileobj
                    )
                    raise ReleaseNotFoundError()
            except KeyError:
                error(
                    3,
                    "Problem while processing page https://api.srrdb.com/v1/details/"
                    + fileobj.page["results"][0]["release"]
                    + "\r\n"
                    + json.dumps(fileobj.page, indent=4),
                    fileobj,
                )
                raise ReleaseNotFoundError()
    else:
        upsert_db(fileobj, "NOT FOUND")
        print(f"{NOTFOUND} {fileobj.releaseName} {fileobj.crccalc}")
        raise ReleaseNotFoundError()

    return fileobj


def upsert_db(fileobj, status):
    if fileobj.realName:
        # can't simply do
        # fileobj.realName, fileobj.releaseName = fileobj.releaseName, fileobj.realName
        # ... this changes the variables outside of this scope!
        relname, origname = fileobj.realName, fileobj.releaseName
    else:
        relname, origname = fileobj.releaseName, None

    db.cursor.execute(
        "SELECT origname, crccalc, crcweb FROM srrdb WHERE relname=?", (relname,)
    )
    record = db.cursor.fetchone()

    # make sure, we don't overwrite anything useful
    if record:
        if record[0]:  # if the file has been previously renamed, preserve origname
            origname = record[0]
        if not fileobj.crccalc:
            fileobj.crccalc = record[1]
        if not fileobj.crcweb:
            fileobj.crcweb = record[2]

    db.cursor.execute(
        """INSERT OR REPLACE INTO srrdb 
        (relname, origname, crccalc, crcweb, status, tag, timestamp) 
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (relname) DO UPDATE SET 
        origname=excluded.origname, 
        crccalc=excluded.crccalc,
        crcweb=excluded.crcweb,
        status=excluded.status, 
        tag=excluded.tag, 
        timestamp=excluded.timestamp""",
        (
            relname,
            origname,
            fileobj.crccalc,
            fileobj.crcweb,
            status,
            args["tag"][0],
            int(datetime.datetime.now(datetime.timezone.utc).timestamp()),
        ),
    )


if __name__ == "__main__":
    load_dotenv()

    # this will catch keyboard interrupts
    signal.signal(signal.SIGINT, signal_handler)

    # set up argparse
    args = start_argparse()
    if args["verbose"]:
        print(args)

    # set up database
    db = create_db(SCENERENAME_DB_FILE)
    start = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
    db.cursor.execute(
        "INSERT INTO lastrun (start, parameters) VALUES (?, ?)", (start, str(args))
    )
    db.connection.commit()

    # clean error log
    db.cursor.execute(
        "DELETE FROM errors WHERE timestamp < ?", (start - int(datetime.timedelta(days=2).total_seconds()),)
    )
    db.connection.commit()

    # set up requests
    session = requests.Session()
    if args["no_ssl_verify"]:
        # if ssl verification fails, try this instead of enabling this option:
        # sudo dpkg-reconfigure ca-certificates -> deactivate DST_Root_CA_X3.crt (expired on Oct 1 2021)
        session.verify = False

    process_files(args["dir"][0])

    end_run(0)
