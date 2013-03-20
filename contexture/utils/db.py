'Simple file-based storage for the message stream'

import gzip
import os
import time
import sys

open_files = {}


def current_filename():
    'dir/filename pair based on current time'
    return time.strftime("%Y%m%d %H").split()


def current_file(dbdir):
    (dirname, filename) = current_filename()
    f = open_files.get((dirname, filename), None)
    if not f:
        flush()
        target_dir = os.path.join(dbdir, dirname)
        if not os.path.exists(target_dir):
            os.mkdir(target_dir)
        f = gzip.open(os.path.join(target_dir, filename + ".gz"), 'ab')
        print f.name
        open_files[(dirname, filename)] = f
    return f


def write(dbdir, line):
    current_file(dbdir).write(line)


def flush():
    for f in open_files.values():
        f.close()
    open_files.clear()


def main():
    dbdir = sys.argv[1]
    try:
        for line in sys.stdin:
            write(dbdir, line)
    except KeyboardInterrupt:
        flush()
        print >> sys.stderr, 'Bye.'


if __name__ == '__main__':
    main()
