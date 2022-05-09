# pySceneTools

## scene2arr.py
This script lets you add new scene groups to a sonarr release profile / radarr restriction as a required tag.

### setup
Initially `conf.py.example` needs to be renamed to `conf.py` and filled with the URLs to the *arr APIs and respective 
API keys. The `/1` at the end of the URLs in the example refer to the id of the release profile or restriction in the 
sonarr/radarr database. Check those databases to find the correct ID.

### usage
```
usage: python3 scene2arr.py [-h] ([-s] [[ -a | -r ] GROUP ])

This script adds release groups to the *arr apps, or removes them.

positional arguments:
  GROUP          Name of release group.

optional arguments:
  -h, --help     show this help message and exit
  -a, --add      Add new group.
  -r, --remove   Remove group.
  -s, --scan     Check the xREL API for new groups.
  -v, --verbose  Enable verbose mode.
```

Using `-s` will scan the xREL API for new scene groups and automatically add new groups as they appear. It's recommended
to run the script once manually and then add a cronjob that runs the script every minute. The xREL API allows for 300
hits per hour, which lets you check all 50 pages of up to 6 categories.

The `-a` and `-r` options let you manually add or remove groups respectively. Right now a `-` is automatically prepended
to the `GROUP`, i. e. using `-a GROUP` will actually add `-GROUP` to your restrictions.

## scenerename.py
This tool will rename media files (currently only MOViE/TV content) to the directory name stored at srrDB.

### usage
```
python3 usage: scenerename.py [-h] [-v] [-f] [-n] [-s] [-t TAG] [-w ARG [ARG ...]] -d DIR

This script renames SCENE media files and compares their hashes to those stored at srrDB.

optional arguments:
  -h, --help            show this help message and exit
  -v, --verbose         Enable verbose mode.
  -f, --skip-not-found  Disable processing of files that were previously marked as not found.
  -n, --no-comparison   Disables hashing of files for comparison with hashes stored at srrDB to check for corruption.
                        Will still hash files to identify and rename them.
  -s, --no-ssl-verify   Disable SSL verification (not secure).
  -t TAG, --tag TAG     Tag the files in dir as being movies, shows, etc.
  -w ARG [ARG ...], --whitelist ARG [ARG ...]
                        Only process files that include at least one of the arguments (case insensitive).
  -d DIR, --dir DIR     Folder with your media files.
```
All the collected metadata (filenames, hashes) are stored in a sqlite database to ensure releases are only processed 
once. Deleting the database is a bad idea.
