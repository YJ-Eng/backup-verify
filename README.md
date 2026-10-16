# backup-verify

A small, stdlib-only Python tool that checks whether a backup folder is still trustworthy.

**Why it exists.** Many small companies run a nightly backup job and assume it works because it has never
complained. Nobody opens the backup, nobody checks that last night's copy actually arrived, and nobody has
ever tried a restore. This tool covers the cheap, scriptable part of that gap: are the files intact, is the
newest set recent, and did the last transfer end in a state we understand. It does not replace a real
restore test, so a checklist for one is included.

**It is not a backup tool, it is a verifier.** It never copies, deletes or modifies your backup data. The only
file it writes is `MANIFEST.sha256` inside the folder you point it at (and only for the `manifest` command).

Requires Python 3.10+. No dependencies. Single file: `backup_verify.py`.

## Usage

```
python3 backup_verify.py manifest  FOLDER                       # write FOLDER/MANIFEST.sha256
python3 backup_verify.py verify    FOLDER                       # compare files with the manifest
python3 backup_verify.py freshness FOLDER [--hours 30] [--rsync-exit CODE]
python3 backup_verify.py report    FOLDER [--hours 30] [--rsync-exit CODE]
```

- **manifest** hashes every regular file under FOLDER (SHA-256, `sha256sum` line format, so
  `sha256sum -c` also works) and writes `MANIFEST.sha256`. Run it right after a backup completes.
- **verify** re-hashes and compares. Changed or missing files are a FAIL. Files that are not in the
  manifest are a WARN.
- **freshness** looks at the modification time of the newest file in FOLDER (or of `--marker FILE`, see
  below). If it is older than `--hours` (default 30, which tolerates a nightly job that runs late; must be
  a finite number above 0), it prints a loud message and exits 2. An empty folder fails. A timestamp more
  than an hour in the future is a WARN ("clock skew?").
- **rsync exit codes** (`--rsync-exit`): pass the exit status of your last rsync run. `0` is OK.
  `24` ("some source files vanished before they could be transferred") is a WARN, because on a live
  system files do disappear mid-run. Every other non-zero code is a FAIL, including `23` (partial
  transfer), which can hide real data loss.
- **report** runs all of the above and prints a one-screen plain-text status with an OVERALL line.

### Exit codes

| Code | Meaning |
|------|---------|
| 0 | OK |
| 1 | WARN (e.g. rsync 24, extra files, no manifest yet in `report`) |
| 2 | FAIL (stale, missing or changed files, bad rsync code, bad arguments) |

Example for cron or a wrapper script. Do not run `rsync --delete` against the folder that holds the
manifest without excluding it (`--exclude MANIFEST.sha256`), or rsync will remove it:

```
rsync -a --delete --exclude MANIFEST.sha256 user@source:/data/ /backups/data/; rc=$?
python3 backup_verify.py report /backups/data --rsync-exit $rc || mail -s "backup check" you@example.com < /dev/null
```

Manifest lifecycle:
- Create the manifest on the source, right after the dump finishes.
- It is pulled to the backup destination together with the data (so do not exclude it in that case).
- Verify on the destination, after the pull.
- Regenerate it deliberately, on the source after a new dump, never as a side effect of an rsync run.

Try it without touching anything real: `./example/run_example.sh`.
Run the tests: `python3 -m unittest discover -s tests`.

## Limits

- A matching manifest proves the files are the same as when the manifest was written. If the backup was
  already bad or incomplete at that point (for example a database dump taken mid-write), this tool cannot tell.
- The manifest lives next to the data. Someone who can change the data can change the manifest too. Keep a
  copy elsewhere if you care about tampering rather than accidents.
- Freshness checks the newest file's modification time, not a whole "set". One freshly touched file can
  mask an otherwise stale backup, and preserved source mtimes (rsync `-a`) can make a good backup look old.
  The reliable way is a `LAST_BACKUP_OK` marker file that your backup job writes (touches) only when it
  finished successfully, then use `--marker /backups/data/LAST_BACKUP_OK`.
- Symlinks and special files are skipped. Hashing large folders takes as long as reading them.
- The real test of a backup is restoring it. See `restore-test-checklist.md`.

## License

MIT, see `LICENSE`.
