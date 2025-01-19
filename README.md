# pySceneTools
Download the scripts via:
```
git clone --recurse-submodules https://github.com/dawtmaytrikx/pySceneTools.git
```

Install the required Python packages by running:
```
pip install -r requirements.txt
```

If you need to update the repo do the following:
```
git pull --recurse-submodules
git submodule update --recursive --remote
```

**⚠️ Please note that the database schema has recently changed.** In order to update
it, you may need to run `python3 run_post_update.py`. Also note the comment about breaking
changes below.


## scene2arr.py
This script lets you add new scene groups to *arr release profiles as a required 
tag, ensuring only releases from these groups are downloaded. As a secondary
function, it can create a predb by listening in appropriate IRC channels.

### setup
Initially `.env.example` needs to be renamed to `.env` and filled with the
URLs to the *arr APIs and respective API keys. Leave the API key empty if you don't want to 
use all of the PVRs. The `/1` at the end of the URLs in the example refer to the id of the 
release profile in thesonarr/radarr database. Check those databases to find the correct ID:
```
sqlite3 sonarr.db "SELECT id, name FROM releaseprofiles;"
```
which should output something like
```
1|Scene
2|P2P
3|...
```

Rename `conf.py.example` to `conf.py` and configure the categories for the xREL
API and/or different filters for use with the IRC bot.

If you plan on using the IRC functionality, you can rename `irc.yaml.example` to `irc.yaml` 
and configure your prechans there. It comes preconfigured with a couple of public channels. 
The submodule [scene-release-parser-php](https://github.com/pr0pz/scene-release-parser-php) 
requires at least PHP 8.0.


### usage
```
usage: python3 scene2arr.py [-h] ([-i] [-p]) | ([-x] | [[-a | -r] GROUP])

This script adds release groups to the *arr apps, or removes them.

positional arguments:
  GROUP          Name of release group.

options:
  -h, --help     show this help message and exit
  -v, --verbose  Enable verbose mode.
  -i, --irc      Listens for new releases in the IRC prechans, extracts the group name, and adds it to the *arr instances.
  -p, --predb    Create a pre and nuke database by listening in IRC pre channels.
  -x, --xrel     Check xREL for new releases and add them to the *arr instances.
  -a, --add      Add new group.
  -r, --remove   Remove group.
```
Running with `-i` will start an IRC bot that listens for new releases in prechans
configured in `irc.yaml`. Whenever a release is pre'd that matches the filters 
set in `conf.py`, the group name is extracted and added to the release profile
as a required tag, ensuring releases from this group can be downloaded in the
future. Enabling `-p` will create a pre (and nuke) database in `pre.db`.

Using `-x` will check the xREL API for new scene groups and automatically add
new groups as they appear. (**⚠️ Breaking Change: The `-x` option used to be
called `-s` / `--scan`. Please update your scripts accordingly!**) It's
recommended to run the script once manually and then add a cronjob that runs the
script every minute. The xREL API allows for 300 hits per hour, which lets you
check all 50 pages of up to 6 categories.

The `-a` and `-r` options let you manually add or remove groups respectively.
Right now a `-` is automatically prepended to the `GROUP`, i. e. using `-a
GROUP` will actually add `-GROUP` to your restrictions.

## scenerename.py
This tool will rename media files (currently only MOViE/TV content) to the
directory name stored at srrDB.

### usage
```
python3 usage: scenerename.py [-h] [-v] [-f] [-n] [-s] [-t TAG] [-w ARG [ARG ...]] -d DIR

This script renames SCENE media files and compares their hashes to those stored
at srrDB.

optional arguments:
  -h, --help            show this help message and exit
  -v, --verbose         Enable verbose mode.
  -f, --skip-not-found  Disable processing of files that were previously marked
                        as not found.
  -n, --no-comparison   Disables hashing of files for comparison with hashes
                        stored at srrDB to check for corruption. Will still
                        hash files to identify and rename them.
  -s, --no-ssl-verify   Disable SSL verification (not secure).
  -t TAG, --tag TAG     Tag the files in dir as being movies, shows, etc.
  -w ARG [ARG ...], --whitelist ARG [ARG ...]
                        Only process files that include at least one of the
                        arguments (case insensitive).
  -d DIR, --dir DIR     Folder with your media files.
```
All the collected metadata (filenames, hashes) are stored in a sqlite database
to ensure releases are only processed once. Deleting the database is a bad idea.
