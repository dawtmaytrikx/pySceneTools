import datetime
import logging
import os
import re
import sqlite3

# Configure logger
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def get_db_version(db_path):
    logging.info(f"Getting database version for {db_path}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("PRAGMA user_version")
    version = cursor.fetchone()[0]
    conn.close()
    logging.info(f"Database version for {db_path} is {version}")
    return version

def set_db_version(db_path, version):
    logging.info(f"Setting database version for {db_path} to {version}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA user_version = {version}")
    conn.commit()
    conn.close()
    logging.info(f"Database version for {db_path} set to {version}")

def convert_scene2arr_db_v2(dbname):
    logging.info(f"Converting {dbname} to version 2")
    conn = sqlite3.connect(dbname)
    cursor = conn.cursor()

    logging.info("Creating new tables with the updated schema")
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS scenegroups_new (
        id INTEGER PRIMARY KEY,
        groupname TEXT,
        release TEXT,
        pvr TEXT,
        releasedate INTEGER,
        timestamp INTEGER
        );"""
    )

    cursor.execute(
        """CREATE TABLE IF NOT EXISTS latest_new (
        category TEXT PRIMARY KEY,
        release TEXT,
        releasedate INTEGER,
        timestamp INTEGER
        );"""
    )

    logging.info("Copying data from old tables to new tables, converting date/time format")
    cursor.execute("SELECT id, groupname, release, pvr, releasedate, date FROM scenegroups")
    rows = cursor.fetchall()
    for row in rows:
        date = int(datetime.datetime.fromisoformat(row[5]).timestamp()) if row[5] else None
        cursor.execute(
            """INSERT INTO scenegroups_new (id, groupname, release, pvr, releasedate, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (row[0], row[1], row[2], row[3], row[4], date)
        )

    cursor.execute("SELECT category, release, releasedate, date FROM latest")
    rows = cursor.fetchall()
    for row in rows:
        date = int(datetime.datetime.fromisoformat(row[3]).timestamp()) if row[3] else None
        cursor.execute(
            """INSERT INTO latest_new (category, release, releasedate, timestamp)
            VALUES (?, ?, ?, ?)""",
            (row[0], row[1], row[2], date)
        )

    logging.info("Dropping old tables")
    cursor.execute("DROP TABLE scenegroups")
    cursor.execute("DROP TABLE latest")

    logging.info("Renaming new tables to original names")
    cursor.execute("ALTER TABLE scenegroups_new RENAME TO scenegroups")
    cursor.execute("ALTER TABLE latest_new RENAME TO latest")

    conn.commit()
    cursor.execute("VACUUM")
    conn.close()
    set_db_version(dbname, 2)  # Set the new version after conversion
    logging.info(f"Conversion of {dbname} to version 2 completed")

def convert_pre_db_v2(dbname):
    logging.info(f"Converting {dbname} to version 2")
    conn = sqlite3.connect(dbname)
    cursor = conn.cursor()

    logging.info("Creating new tables with the updated schema")
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS pre_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            release TEXT,
            section TEXT,
            size INTEGER,
            files INTEGER,
            genre TEXT,
            source TEXT,
            timestamp INTEGER
        )"""
    )

    cursor.execute(
        """CREATE TABLE IF NOT EXISTS nuke_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            release TEXT,
            type TEXT,
            reason TEXT,
            nukenet TEXT,
            source TEXT,
            timestamp INTEGER
        )"""
    )

    logging.info("Copying data from old tables to new tables, converting date/time format")
    cursor.execute("SELECT id, release, category, size, files, genre, source, time FROM pre")
    rows = cursor.fetchall()
    for row in rows:
        size = round(float(row[3])) if row[3] else None
        time = int(datetime.datetime.fromisoformat(row[7]).timestamp()) if row[7] else None
        cursor.execute(
            """INSERT INTO pre_new (id, release, section, size, files, genre, source, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (row[0], row[1], row[2], size, row[4], row[5], row[6], time)
        )

    cursor.execute("SELECT id, release, type, reason, nukenet, source, time FROM nuke")
    rows = cursor.fetchall()
    for row in rows:
        time = int(datetime.datetime.fromisoformat(row[6]).timestamp()) if row[6] else None
        cursor.execute(
            """INSERT INTO nuke_new (id, release, type, reason, nukenet, source, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (row[0], row[1], row[2], row[3], row[4], row[5], time)
        )

    logging.info("Dropping old tables")
    cursor.execute("DROP TABLE pre")
    cursor.execute("DROP TABLE nuke")

    logging.info("Renaming new tables to original names")
    cursor.execute("ALTER TABLE pre_new RENAME TO pre")
    cursor.execute("ALTER TABLE nuke_new RENAME TO nuke")

    conn.commit()
    cursor.execute("VACUUM")
    conn.close()
    set_db_version(dbname, 2)  # Set the new version after conversion
    logging.info(f"Conversion of {dbname} to version 2 completed")

def convert_scenerename_db_v2(dbname):
    logging.info(f"Converting {dbname} to version 2")
    conn = sqlite3.connect(dbname)
    cursor = conn.cursor()

    logging.info("Creating new tables with the updated schema")
    cursor.execute(
        """CREATE TABLE IF NOT EXISTS srrdb_new (
            relname TEXT PRIMARY KEY,
            origname TEXT,
            crccalc TEXT,
            crcweb TEXT,
            status TEXT,
            tag TEXT,
            timestamp INTEGER
        );"""
    )

    cursor.execute(
        """CREATE TABLE IF NOT EXISTS errors_new (
            key INTEGER PRIMARY KEY AUTOINCREMENT,
            relname TEXT,
            errnum TEXT,
            description TEXT,
            page TEXT,
            timestamp INTEGER
        );"""
    )

    cursor.execute(
        """CREATE TABLE IF NOT EXISTS lastrun_new (
            key INTEGER PRIMARY KEY AUTOINCREMENT,
            start INTEGER,
            end INTEGER,
            exitcode INTEGER,
            parameters TEXT
        );"""
    )

    logging.info("Copying data from old tables to new tables, converting date/time format")
    cursor.execute("SELECT relname, origname, crccalc, crcweb, status, tag, date FROM srrdb")
    rows = cursor.fetchall()
    for row in rows:
        date = int(datetime.datetime.fromisoformat(row[6]).timestamp()) if row[6] else None
        cursor.execute(
            """INSERT INTO srrdb_new (relname, origname, crccalc, crcweb, status, tag, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (row[0], row[1], row[2], row[3], row[4], row[5], date)
        )

    cursor.execute("SELECT key, relname, errnum, description, page, date FROM errors")
    rows = cursor.fetchall()
    for row in rows:
        date = int(datetime.datetime.fromisoformat(row[5]).timestamp()) if row[5] else None
        cursor.execute(
            """INSERT INTO errors_new (key, relname, errnum, description, page, timestamp)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (row[0], row[1], row[2], row[3], row[4], date)
        )

    cursor.execute("SELECT key, start, end, exitcode, parameters FROM lastrun")
    rows = cursor.fetchall()
    for row in rows:
        start = int(datetime.datetime.fromisoformat(row[1]).timestamp()) if row[1] else None
        end = int(datetime.datetime.fromisoformat(row[2]).timestamp()) if row[2] else None
        cursor.execute(
            """INSERT INTO lastrun_new (key, start, end, exitcode, parameters)
            VALUES (?, ?, ?, ?, ?)""",
            (row[0], start, end, row[3], row[4])
        )

    logging.info("Dropping old tables")
    cursor.execute("DROP TABLE srrdb")
    cursor.execute("DROP TABLE errors")
    cursor.execute("DROP TABLE lastrun")

    logging.info("Renaming new tables to original names")
    cursor.execute("ALTER TABLE srrdb_new RENAME TO srrdb")
    cursor.execute("ALTER TABLE errors_new RENAME TO errors")
    cursor.execute("ALTER TABLE lastrun_new RENAME TO lastrun")

    conn.commit()
    cursor.execute("VACUUM")
    conn.close()
    set_db_version(dbname, 2)  # Set the new version after conversion
    logging.info(f"Conversion of {dbname} to version 2 completed")

def convert_pre_db_v3(dbname):
    logging.info(f"Converting {dbname} to version 3")
    conn = sqlite3.connect(dbname)
    cursor = conn.cursor()

    logging.info("Creating new table with the desired schema")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pre_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            release TEXT UNIQUE,
            type TEXT,
            section TEXT,
            size INTEGER,
            files INTEGER,
            genre TEXT,
            source TEXT,
            timestamp INTEGER
        )
    """)

    logging.info("Copying data from old table to new table")
    cursor.execute("""
        INSERT OR IGNORE INTO pre_new (id, release, type, section, size, files, genre, source, timestamp)
        SELECT id, release, 'PRE', section, size, files, genre, source, timestamp
        FROM pre
    """)

    logging.info("Dropping old table")
    cursor.execute("DROP TABLE pre")

    logging.info("Renaming new table to original name")
    cursor.execute("ALTER TABLE pre_new RENAME TO pre")

    logging.info("Removing bogus nukes from predataba.se if an equivalent modnuke from another source is present")
    cursor.execute("""
        DELETE FROM nuke
        WHERE source = 'irc.predataba.se/#pre'
        AND EXISTS (
            SELECT 1 FROM nuke AS modnuke
            WHERE modnuke.release = nuke.release
            AND modnuke.reason = nuke.reason
            AND modnuke.nukenet = nuke.nukenet
            AND modnuke.type = 'MODNUKE'
            AND modnuke.source != 'irc.predataba.se/#pre'
        )
    """)

    conn.commit()
    cursor.execute("VACUUM")
    conn.close()
    set_db_version(dbname, 3)  # Set the new version after conversion
    logging.info(f"Conversion of {dbname} to version 3 completed")

def update_irc_yaml(yaml_file):
    logging.info(f"Updating IRC YAML file: {yaml_file}")

    with open(yaml_file, 'r') as file:
        content = file.read()

    # Replace 'servers:' key with 'input_servers:' only if it is a key (followed by a space or newline)
    updated_content = re.sub(r'(?m)^(servers:)', r'input_servers:', content)

    with open(yaml_file, 'w') as file:
        file.write(updated_content)

    logging.info(f"IRC YAML file {yaml_file} updated")

# Convert databases if they exist and haven't been converted yet
if os.path.exists('./scene2arr.db') and get_db_version('./scene2arr.db') < 2:
    convert_scene2arr_db_v2('./scene2arr.db')

if os.path.exists('./test/irc2arr.db') and get_db_version('./test/irc2arr.db') < 2:
    convert_pre_db_v2('./test/irc2arr.db')

if os.path.exists('./scenerename.db') and get_db_version('./scenerename.db') < 2:
    convert_scenerename_db_v2('./scenerename.db')

# Rename the irc2arr.db to pre.db if it exists and hasn't been renamed yet
if os.path.exists('./test/irc2arr.db'):
    logging.info("Renaming './test/irc2arr.db' to './pre.db'")
    os.rename('./test/irc2arr.db', './pre.db')

# Convert pre.db to version 3 if it exists and hasn't been converted yet
if os.path.exists('./pre.db') and get_db_version('./pre.db') < 3:
    convert_pre_db_v3('./pre.db')

if os.path.exists('./pre.db'):
    update_irc_yaml('./irc.yaml')