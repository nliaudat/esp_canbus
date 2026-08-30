#!/usr/bin/env python3
"""Keep the Hoval datapoint workbook used by the preset generator up to date.

The official TTE-GW-Modbus datapoints workbook is copyrighted by Hoval AG and
is therefore NOT committed to this repository (the independent HoxPi project
does the same).  This tool:

  * downloads the current version from Hoval's CDN,
  * compares its sha256 against the last processed copy,
  * on change (--apply): regenerates the presets from the downloaded workbook
    into a staging area first; the repository is only touched once generation
    and the entity-count sanity check have both passed (previous workbook is
    backed up, the new one installed, the staged presets copied in),
  * sanity-checks the regenerated presets (entity count must not collapse).

Datapoints that a given controller firmware does not know simply never answer
on the CAN bus and stay empty in the UI — that is normal, not an error, so a
newer list can be installed without side effects.

Usage:
  python hoval_data_processing/update_datapoints.py --check   # report only
  python hoval_data_processing/update_datapoints.py --apply   # download + regenerate
"""

import argparse
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import urllib.request

URLS = (
    "https://cdn.hoval.com/toptronice-gateway-modbus-datapoints_hybris_original.xlsx",
    "https://www.hoval.com/misc/TTE/TTE-GW-Modbus-datapoints.xlsx",
)
WORKBOOK = pathlib.Path(__file__).parent / "TTE-GW-Modbus-datapoints.xlsx"
STATE = pathlib.Path(__file__).parent / "datapoints_version.json"
PRESETS_DIR = pathlib.Path(__file__).parent.parent / "esphome" / "components" / "toptronic" / "presets"


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def download(dest):
    last = None
    for url in URLS:
        try:
            print("Downloading %s ..." % url)
            urllib.request.urlretrieve(url, dest)
            return True
        except Exception as exc:  # noqa: BLE001
            last = exc
            print("  failed: %s" % exc)
    raise RuntimeError("Could not download the datapoint list (%s)" % last)


def count_entities(base=PRESETS_DIR):
    import yaml
    total = 0
    for path in pathlib.Path(base).glob("*/*.yaml"):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001
            continue
        for entries in data.values():
            total += len(entries or [])
    return total


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="only report whether the list changed, change nothing")
    ap.add_argument("--apply", action="store_true",
                    help="download the current list and regenerate the presets on change")
    args = ap.parse_args()

    if not (args.check or args.apply):
        print(__doc__)
        return 1

    state = {}
    if STATE.exists():
        try:
            state = json.loads(STATE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass

    with tempfile.TemporaryDirectory() as tmp:
        tmp_xlsx = pathlib.Path(tmp) / "datapoints.xlsx"
        download(tmp_xlsx)
        digest = sha256(tmp_xlsx)
        print("Online list sha256: %s (previous: %s)" % (digest[:16], (state.get("sha256") or "-")[:16]))

        if state.get("sha256") == digest:
            print("Already up to date - nothing to do.")
            return 0

        print("The datapoint list has changed since it was last processed.")
        if args.check:
            print("Run with --apply to install it and regenerate the presets.")
            return 2

        old_n = count_entities()

        # Regenerate the presets into a staging directory first, feeding the
        # newly downloaded workbook to the generator via --xlsx. Nothing in the
        # repository is touched until generation AND the entity-count sanity
        # check have both passed, so a failed update cannot leave the new
        # workbook or partially rewritten presets active while the state hash
        # still names the old list (a later --apply would otherwise overwrite
        # the good backup and use damaged presets as its comparison baseline).
        staging = pathlib.Path(tmp) / "presets_new"
        try:
            subprocess.run([sys.executable,
                            str(pathlib.Path(__file__).parent / "generate_presets.py"),
                            str(staging),
                            "--xlsx", str(tmp_xlsx)], check=True)
        except subprocess.CalledProcessError:
            print("ABORT: preset generation failed - nothing was changed.")
            return 1

        new_n = count_entities(staging)
        print("Preset entities: %d -> %d" % (old_n, new_n))
        if old_n and new_n < old_n * 0.9:
            print("ABORT: regenerated presets are much smaller than before - "
                  "nothing was changed; inspect the workbook layout.")
            return 3

        # Validation passed - commit the update: back up the previous workbook,
        # install the new one, then copy the regenerated presets into place.
        if WORKBOOK.exists():
            backup = WORKBOOK.with_suffix(".xlsx.bak")
            backup.write_bytes(WORKBOOK.read_bytes())
            print("Backed up previous workbook to %s" % backup)

        tmp_xlsx.replace(WORKBOOK)
        print("Installed %s" % WORKBOOK)

        shutil.copytree(staging, PRESETS_DIR, dirs_exist_ok=True)
        print("Installed regenerated presets into %s" % PRESETS_DIR)

        STATE.write_text(json.dumps({"sha256": digest}, indent=1), encoding="utf-8")
        print("State saved to %s" % STATE)
        return 0


if __name__ == "__main__":
    sys.exit(main())
