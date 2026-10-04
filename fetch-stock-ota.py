#!/usr/bin/env python3
"""Download a stock Creality K2 Pro OTA image and unpack its kernel and rootfs.

    fetch-stock-ota.py VERSION OUTDIR [--board CR0CN200400C10]

The image comes from Creality's public firmware index and CDN (the same
source k2oh-mcu-fw uses on the printer). The kernel and rootfs members are
checked against the image's own cpio_item_md5 list, written to OUTDIR as
"kernel" and "rootfs", and the image is deleted.
"""

import argparse
import hashlib
import importlib.machinery
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "rootfs", "usr", "bin", "k2oh-mcu-fw")


def load_tool():
    loader = importlib.machinery.SourceFileLoader("k2oh_mcu_fw", TOOL)
    spec = importlib.util.spec_from_loader("k2oh_mcu_fw", loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("version")
    parser.add_argument("outdir")
    parser.add_argument("--board", default="CR0CN200400C10")
    args = parser.parse_args()
    tool = load_tool()

    releases = {r["version"]: r for r in tool.search_releases(args.board)}
    if args.version not in releases:
        sys.exit("version %s is not in Creality's index (found: %s)"
                 % (args.version, ", ".join(sorted(releases, key=tool.version_key))))
    release = releases[args.version]
    os.makedirs(args.outdir, exist_ok=True)
    image = os.path.join(args.outdir, release["name"])
    print("downloading %s (%d MB)" % (release["name"], release["size"] >> 20), flush=True)
    tool.download(release["url"], image, release["size"])
    try:
        with open(image, "rb") as f:
            members = tool.cpio_members(f)
            off, size = members["cpio_item_md5"]
            f.seek(off)
            md5s = {}
            for line in f.read(size).decode().splitlines():
                parts = line.split()
                if len(parts) == 2:
                    md5s[parts[1]] = parts[0]
            for name in ("kernel", "rootfs"):
                off, size = members[name]
                if tool.member_md5(f, off, size) != md5s.get(name):
                    sys.exit("%s MD5 does not match the image's cpio_item_md5" % name)
                f.seek(off)
                left = size
                with open(os.path.join(args.outdir, name), "wb") as out:
                    while left:
                        chunk = f.read(min(left, 1 << 20))
                        out.write(chunk)
                        left -= len(chunk)
                print("%s: %d bytes, MD5 ok" % (name, size))
    finally:
        os.unlink(image)


if __name__ == "__main__":
    main()
