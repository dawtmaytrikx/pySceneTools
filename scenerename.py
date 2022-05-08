#!/usr/bin/python3

import argparse
from colorama import Fore
import datetime
from io import BytesIO
import json
# import pdb; pdb.set_trace()
import pycurl
import signal
import sys
from time import sleep
import urllib.parse
import zlib

from classes import *


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
    " (1)",
    ".(1)",
    "(1)",
    "-1",
    ".repost",
    "-BUYMORE",
    "-repost",
    "-newz",
    ".",
    "-postbot",
    "-[cx86]",
    "-BWBP",
    "-[TRP]",
    "[rarbg]",
    "-RakuvFIN",
    "-Rakuv",
]
skiptags = [  # hardcoded blacklist, add p2p groups
    "dirfix",
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
]

VERBOSE = f"{Fore.YELLOW}VERBOSE:{Fore.RESET}"
ERROR = f"{Fore.RED}ERROR:{Fore.RESET}"
RENAMED = f"{Fore.BLUE}RENAMED:{Fore.RESET}"
WRONGFILESIZE = f"{Fore.RED}WRONG FILESIZE:{Fore.RESET}"
NOTWHITELISTED = f"SKIPPING {Fore.RED}NOT WHITELISTED{Fore.RESET}:"
BLACKLISTED = f"SKIPPING {Fore.RED}BLACKLISTED{Fore.RESET}:"
SKIPPINGOK = f"SKIPPING {Fore.GREEN}OK{Fore.RESET}:"
SKIPPINGCORRUPT = f"SKIPPING {Fore.RED}CORRUPT{Fore.RESET}:"
SKIPPINGNOTFOUND = f"SKIPPING {Fore.MAGENTA}NOT FOUND{Fore.RESET}:"
SKIPPINGUNPROCESSED = f"SKIPPING {Fore.CYAN}UNPROCESSED{Fore.RESET}:"
MATCHED = f"{Fore.GREEN}MATCHED:{Fore.RESET}"
NOTFOUND = f"{Fore.MAGENTA}NOT FOUND:{Fore.RESET}"
OK = f"{Fore.GREEN}OK:{Fore.RESET}"
CORRUPT = f"{Fore.RED}CORRUPT:{Fore.RESET}"


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
        help="Tag the files in dir as being movies, shows, etc.",
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
        "-d", "--dir", nargs=1, required=True, help="folder with your media files"
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
            date TEXT
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
            date TEXT
        );"""
    )

    db.cursor.execute(
        """CREATE TABLE IF NOT EXISTS lastrun
        (
            key INTEGER PRIMARY KEY AUTOINCREMENT,
            start TEXT,
            end TEXT,
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
    end = datetime.datetime.now(datetime.timezone.utc)
    db.cursor.execute(
        "UPDATE lastrun SET end=?, exitcode=? WHERE start=?", (end, exitcode, start)
    )
    db.connection.commit()
    db.connection.close()
    c.close()


def loadpage(url):  # buffer, c
    buffer.seek(0)
    buffer.truncate()
    c.setopt(c.URL, url)
    c.perform()
    page = buffer.getvalue().decode("utf-8")

    if args["verbose"]:
        print(f"{VERBOSE} {c.getinfo(c.RESPONSE_CODE)} - {url}\r\n{page}")

    return json.loads(page)


def error(errnum, description):  # fileToCheck, db
    print(f"{ERROR} {errnum} - {description}\r\n\tfile: {fileToCheck.filename}")
    db.cursor.execute(
        """INSERT INTO errors 
        (relname, errnum, description, page, date) 
        VALUES (?, ?, ?, ?, ?)""",
        (
            os.path.join(fileToCheck.dirpath, fileToCheck.filename),
            errnum,
            str(description),
            json.dumps(fileToCheck.page, indent=4),
            datetime.datetime.now(datetime.timezone.utc),
        ),
    )


def mislabeled(fileobj):
    if os.path.exists(os.path.join(fileobj.dirpath, fileobj.realName) + fileobj.extension):
        error(13, f"Tried renaming {fileobj.releaseName} to {fileobj.realName}, but file already exists!")
        raise OSError()
    os.rename(
        os.path.join(fileobj.dirpath, fileobj.releaseName)
        + fileobj.extension,
        os.path.join(fileobj.dirpath, fileobj.realName) + fileobj.extension,
    )
    print(f"{RENAMED} {fileobj.releaseName} -> {fileobj.realName}")
    upsert_db(fileobj, "RENAMED")
    fileobj.releaseName = fileobj.realName
    fileobj.realName = None
    return fileobj


def calculatecrc(filepath):  # fileToCheck
    if args["verbose"]:
        print(f"{VERBOSE} Calculating CRC for {fileToCheck.filename}")

    with open(filepath, "rb") as afile:
        buffr = afile.read(buffersize)
        crcvalue = 0
        while len(buffr) > 0:
            crcvalue = zlib.crc32(buffr, crcvalue)
            buffr = afile.read(buffersize)
    crccalc = "{:08X}".format(crcvalue)

    if args["verbose"]:
        print(f"{VERBOSE} CRC is {crccalc}")

    return crccalc


def getsize():  # fileToCheck
    fileToCheck.sizeondisk = os.path.getsize(
        os.path.join(fileToCheck.dirpath, fileToCheck.releaseName)
        + fileToCheck.extension
    )
    fileToCheck.sizeonsrrdb = int(fileToCheck.page["archived-files"][0]["size"])

    if args["verbose"]:
        print(
            f"{VERBOSE} Size of file on disk: {fileToCheck.sizeondisk}"
            + f" - size of file on srrdb: {fileToCheck.sizeonsrrdb}"
        )

    return fileToCheck.sizeondisk, fileToCheck.sizeonsrrdb


def wrong_filesize():  # fileToCheck
    upsert_db(fileToCheck, "CORRUPT")
    print(f"{WRONGFILESIZE} {fileToCheck.releaseName}")


def skip_file(fileobj):
    # handle whitelist
    for item in args["whitelist"]:
        if item in fileobj.filename.lower():
            break
        else:
            print(f"{NOTWHITELISTED} {fileobj.filename}")
            raise SkipFileError()

    # is this even a media file?
    if fileobj.extension not in extensions:
        raise SkipFileError()

    # fix suffixes
    for suffix in suffixes:
        if fileobj.releaseName.lower().endswith(suffix.lower()):
            fileobj.realName = fileobj.releaseName[: -len(suffix)]
            fileobj = mislabeled(fileobj)

    for skiptag in skiptags:
        if skiptag.lower() in fileobj.releaseName.lower():
            print(f"{BLACKLISTED} {fileobj.releaseName}")
            raise SkipFileError()

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
            fileobj.unprocessed = True

            if args["no_comparison"]:
                print(f"{SKIPPINGUNPROCESSED} {fileobj.releaseName}")
                raise SkipFileError()

    return fileobj


def search_for_release(fileobj):
    fileobj.page = loadpage(
        "https://api.srrdb.com/v1/search/r:"
        + urllib.parse.quote_plus(fileobj.releaseName)
    )

    if "resultsCount" not in fileobj.page:
        error(
            1,
            "Problem while processing page https://api.srrdb.com/v1/search/r:"
            + urllib.parse.quote_plus(fileobj.releaseName)
            + "\r\n"
            + fileobj.page,
        )
        fileobj = search_by_sample(fileobj)

    if int(fileobj.page["resultsCount"]) == 1:
        # rename
        fileobj.page = loadpage(
            "https://api.srrdb.com/v1/details/"
            + urllib.parse.quote_plus(fileobj.page["results"][0]["release"])
        )

        try:
            if len(fileobj.page["archived-files"]) == 1:
                fileobj.sizeondisk, fileobj.sizeonsrrdb = getsize()
                if fileobj.sizeondisk == fileobj.sizeonsrrdb:
                    fileobj.realName = fileobj.page["name"]
                    fileobj = mislabeled(fileobj)
                else:
                    wrong_filesize()  # TODO: Really do this already?
                    fileobj = search_by_sample(fileobj)
            else:
                error(6, "Multiples files in release " + fileobj.page["name"])
                # TODO: add fileobj = search_by_sample(fileobj) here?
        except KeyError:
            error(
                11,
                "Problem while processing page https://api.srrdb.com/v1/details/"
                + fileobj.page["results"][0]["release"]
                + "\r\n"
                + json.dumps(fileobj.page, indent=4)
            )

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
        )

        if (
            "resultsCount" in fileobj.page
            and int(fileobj.page["resultsCount"]) == 1
        ):
            # rename
            fileobj.page = loadpage(
                "https://api.srrdb.com/v1/details/"
                + urllib.parse.quote_plus(
                    fileobj.page["results"][0]["release"]
                )
            )

            try:
                if len(fileobj.page["archived-files"]) == 1:
                    fileobj.sizeondisk, fileobj.sizeonsrrdb = getsize()
                    if fileobj.sizeondisk == fileobj.sizeonsrrdb:
                        fileobj.realName = fileobj.page["name"]
                        fileobj = mislabeled(fileobj)
                        break
                    else:  # TODO: really an error here?
                        error(
                            10,
                            "Filesize does not match that of release "
                            + fileobj.page["name"],
                        )
                        fileobj = search_by_crc(fileobj)
                else:
                    error(
                        7,
                        "Multiple files in release " + fileobj.page["name"],
                    )
                    fileobj = search_by_crc(fileobj)
            except KeyError:
                error(
                    2,
                    "Problem while processing page https://api.srrdb.com/v1/details/"
                    + fileobj.page["results"][0]["release"]
                    + "\r\n"
                    + json.dumps(fileobj.page, indent=4)
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
        fileobj.crccalc = calculatecrc(
            os.path.join(fileobj.dirpath, fileobj.releaseName) + fileobj.extension
        )

    fileobj.page = loadpage(
        "https://api.srrdb.com/v1/search/archive-crc:" + fileobj.crccalc
    )

    if int(fileobj.page["resultsCount"]) == 1:
        # rename
        fileobj.page = loadpage(
            "https://api.srrdb.com/v1/details/"
            + urllib.parse.quote_plus(fileobj.page["results"][0]["release"])
        )

        if not fileobj.page:
            # url of page
            error(11, "Error in srrDB entry!")
        else:
            try:
                if len(fileobj.page["archived-files"]) == 1:
                    fileobj.sizeondisk, fileobj.sizeonsrrdb = getsize()
                    if fileobj.sizeondisk == fileobj.sizeonsrrdb:
                        fileobj.realName = fileobj.page["name"]
                        fileobj = mislabeled(fileobj)
                        # At this point the file can be OK'd as we searched for the
                        # crc of the file. We're still grabbing the CRC from the
                        # details page as a sanity check.
                        fileobj.crcweb = fileobj.page["archived-files"][0]["crc"]
                    else:
                        error(
                            9,
                            "Filesize does not match that of release "
                            + fileobj.page["name"],
                        )
                        raise ReleaseNotFoundError()
                else:
                    error(
                        8,
                        "Multiple files in release " + fileobj.page["name"],
                    )
                    raise ReleaseNotFoundError()
            except KeyError:
                error(
                    3,
                    "Problem while processing page https://api.srrdb.com/v1/details/"
                    + fileobj.page["results"][0]["release"]
                    + "\r\n"
                    + json.dumps(fileobj.page, indent=4)
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
        "SELECT origname, crccalc, crcweb FROM srrdb WHERE relname=?",
        (relname,)
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
        (relname, origname, crccalc, crcweb, status, tag, date) 
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (relname) DO UPDATE SET 
        origname=excluded.origname, 
        crccalc=excluded.crccalc,
        crcweb=excluded.crcweb,
        status=excluded.status, 
        tag=excluded.tag, 
        date=excluded.date""",
        (
            relname,
            origname,
            fileobj.crccalc,
            fileobj.crcweb,
            status,
            args["tag"][0],
            datetime.datetime.now(datetime.timezone.utc),
        ),
    )


if __name__ == "__main__":
    # this will catch keyboard interrupts
    signal.signal(signal.SIGINT, signal_handler)

    args = start_argparse()
    if args["verbose"]:
        print(args)

    db = create_db("scenerename.db")
    start = datetime.datetime.now(datetime.timezone.utc)
    db.cursor.execute(
        "INSERT INTO lastrun (start, parameters) VALUES (?, ?)", (start, str(args))
    )
    db.connection.commit()

    buffer = BytesIO()
    c = pycurl.Curl()
    if args["no_ssl_verify"]:
        # if ssl verification fails, try this instead of enabling this option:
        # sudo dpkg-reconfigure ca-certificates -> deactivate DST_Root_CA_X3.crt (expired on Oct 1 2021)
        c.setopt(c.SSL_VERIFYPEER, 0)
        c.setopt(c.SSL_VERIFYHOST, 0)

    for dirpath, dirs, files in os.walk(args["dir"][0]):
        for filename in files:
            fileToCheck = FileToCheck(dirpath, filename)

            try:
                fileToCheck = skip_file(fileToCheck)

                c.setopt(
                    c.URL,
                    "https://api.srrdb.com/v1/details/"
                    + urllib.parse.quote_plus(fileToCheck.releaseName),
                )
                c.setopt(c.WRITEDATA, buffer)
                c.perform()

                # check response code
                # 404 only on release/details
                # 302 is redirect
                # what's with 300?
                # 400 is illegal characters (should be caught by skiptags!)
                if c.getinfo(c.RESPONSE_CODE) == 400:  # TODO: add these checks to loadpage()
                    error(5, "Illegal character in filename!")
                    continue

                while c.getinfo(c.RESPONSE_CODE) == 503:
                    print("RATE LIMITED! Sleeping 10 s ...")
                    sleep(10)
                    c.perform()

                # rename
                if c.getinfo(c.RESPONSE_CODE) == 302:
                    c.setopt(c.FOLLOWLOCATION, 1)
                    c.perform()
                    # see https://bitbucket.org/srrdb/srrdb-issues/issues/114/api-faulty-redirect-if-query-contains
                    realurl = c.getinfo(c.EFFECTIVE_URL).replace("/release/", "/v1/")
                    fileToCheck.page = loadpage(realurl)

                    if args["verbose"]:
                        print(
                            f"{VERBOSE} {c.getinfo(c.RESPONSE_CODE)} - {realurl}\r\n{fileToCheck.page}"
                        )

                    fileToCheck.realName = fileToCheck.page["name"]
                    fileToCheck = mislabeled(fileToCheck)

                fileToCheck.page = json.loads(buffer.getvalue().decode("utf-8"))
                if args["verbose"]:
                    print(
                        f"{VERBOSE} {c.getinfo(c.RESPONSE_CODE)} - https://api.srrdb.com/v1/details/"
                        + f"{urllib.parse.quote_plus(fileToCheck.releaseName)}\r\n{fileToCheck.page}"
                    )

                if c.getinfo(c.RESPONSE_CODE) == 200 and fileToCheck.page:
                    if args["no_comparison"]:
                        upsert_db(fileToCheck, None)
                        print(f"{MATCHED} {fileToCheck.releaseName}")

                # search
                if (
                    c.getinfo(c.RESPONSE_CODE) == 404
                    or not fileToCheck.page
                    or fileToCheck.unprocessed
                ):
                    fileToCheck = search_for_release(fileToCheck)

                if args["no_comparison"]:
                    continue

                # find CRC in page
                try:
                    if not fileToCheck.page["archived-files"]:
                        continue  # TODO: Add errors
                except KeyError:
                    continue

                # compare filesizes
                if not fileToCheck.sizeondisk or not fileToCheck.sizeonsrrdb:
                    fileToCheck.sizeondisk, fileToCheck.sizeonsrrdb = getsize()

                if fileToCheck.sizeondisk == fileToCheck.sizeonsrrdb:
                    fileToCheck.crcweb = fileToCheck.page["archived-files"][0]["crc"]
                else:
                    if fileToCheck.crccalc:
                        wrong_filesize()
                        continue
                    try:
                        fileToCheck = search_by_crc(fileToCheck)
                    except ReleaseNotFoundError:
                        wrong_filesize()
                        continue


                # calculate CRC
                if not fileToCheck.crccalc:
                    db.cursor.execute(
                        "SELECT crccalc FROM srrdb WHERE relname=?",
                        (fileToCheck.releaseName,),
                    )
                    record = db.cursor.fetchone()

                    if record is not None and record[0] is not None:
                        if args["verbose"]:
                            print(
                                f"{VERBOSE} Using CRC found in DB: {fileToCheck.crccalc}"
                            )
                        fileToCheck.crccalc = record[0]
                    else:
                        if args["verbose"]:
                            print(f"{VERBOSE} No CRC found in DB.")
                        fileToCheck.crccalc = calculatecrc(
                            os.path.join(fileToCheck.dirpath, fileToCheck.releaseName)
                            + fileToCheck.extension
                        )

                if fileToCheck.crccalc == fileToCheck.crcweb:
                    upsert_db(fileToCheck, "OK")
                    print(f"{OK} {fileToCheck.releaseName} {fileToCheck.crccalc}")
                else:
                    upsert_db(fileToCheck, "CORRUPT")
                    print(
                        f"{CORRUPT} {fileToCheck.releaseName} {fileToCheck.crccalc} {fileToCheck.crcweb}"
                    )

            except pycurl.error:
                error("pyCurl", pycurl.error)
                continue
            except SkipFileError:
                continue
            except ReleaseNotFoundError:
                continue
            except OSError:
                continue
            finally:
                db.connection.commit()
                buffer.seek(0)
                buffer.truncate()

    end_run(0)
