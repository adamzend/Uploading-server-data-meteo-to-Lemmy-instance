## v1.1.1 — Pillow security update (2026-10-29)

### Changes
- Merged Dependabot pull request #1: upgrade Pillow from 12.3.0 to 13.0.0 to address security vulnerabilities in image processing.
- Retains the recovery and optional source heartbeat verification introduced in v1.1.0.
- Corrects the VERSION file to match the current release.

### Upgrade
Stop the scheduled cycle before changing dependencies and wait for any running cycle to finish. Back up your installation, update the source files and run `.venv/bin/python -m pip install -r requirements.lock.txt` from the application directory. Preserve your private config.json, static description and data directory. Run the tests and generate the charts before re-enabling the schedule. No server reboot is required.

Python 3.11 or later is required; Pillow 13 no longer supports Python 3.10. The application already requires Python 3.11.

### Verification
- 27 public-application tests passed on Debian/Python 3.11 with Pillow 13.0.0 in an isolated environment.
- The operating station was updated separately: all 22 production-installation tests passed, pip reported no broken requirements, and all three current-month charts were generated successfully.
- No credentials, private configuration or measurement database are included in the release packages.

Downloads include ZIP, TAR.GZ and SHA-256 checksums. Packages require installation of Python dependencies and user configuration; they are not offline environments.
