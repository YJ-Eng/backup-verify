# Restore test checklist

Do this on a schedule (quarterly is a reasonable start) and after any major change to the system being
backed up. A backup that has never been restored is a hope, not a backup.

## Before you start
- [ ] Pick the backup set to test (not necessarily the newest) and note its date.
- [ ] Run `backup_verify.py verify` on it first (checksum integrity). Do not restore from a set that fails
      verify: its files are not what was written.
- [ ] Separately, run `freshness` (is this recovery point recent enough?). Testing an older historical set
      is allowed, so a freshness FAIL on an old set is expected. Note it in the record; it is not a reason
      to skip the test. Also test the newest set at least once per round.
- [ ] Write down the start time. The restore duration is a number you will need during a real incident.
- [ ] Have the documentation for the original system's version, configuration and credentials handy
      (retrieved from your password manager, not from the machine being tested).

## Throwaway host
- [ ] Use a fresh machine or VM that is not part of production. Same OS family and major versions as the original.
- [ ] Internal-only network: no inbound from the internet, and outbound blocked or limited to what you
      need to install packages. The restored system must not be able to send email, call payment or
      webhook endpoints, or sync to anything live.
- [ ] Disable scheduled jobs, mail sending and external integrations in the restored copy before first start.

## Inventory: what must come back
- [ ] **Databases**: every database listed. Restore, then check table counts and the newest record dates
      against what you expect.
- [ ] **File storage** (uploads, attachments, documents): restore and open several files, including
      the largest and the oldest.
- [ ] **Configuration**: service configs, environment files, scheduled jobs, TLS certificates, custom
      code or add-ons.
- [ ] **Anything outside the usual folders**: users and permissions, firewall rules, mail settings.
- [ ] Compare the inventory with the backup contents and write down anything that exists on the original but not in the backup.

## Prove it works
- [ ] The application starts without manual surgery.
- [ ] A named person who knows the data logs in and checks a few records they remember.
- [ ] A recent transaction (created in the last week before the backup) is present.
- [ ] Reports or totals that someone can verify independently match.

## Record and clean up
- [ ] Record: backup date, restore duration, what failed, what was missing, who checked it.
- [ ] Fix the gaps found (missing paths in the backup job, undocumented steps) and note the date.
- [ ] Delete the throwaway host, its disks and any copied data. Do not leave a live copy of production data lying around.
- [ ] Set the date of the next test.
