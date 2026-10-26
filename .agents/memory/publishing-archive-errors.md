---
name: Publishing archive errors
description: Limits of dependency-install fixes for recurring publish archive failures.
---

Do not assume a publishing `archive/tar: write too long` error is caused solely by mixed package installers.

**Why:** The error recurred on a newly installed dependency's executable even after the manifests were aligned and the redundant pip build step was removed. Local imports and local archiving passed; that does not verify Replit's publish packaging.

**How to apply:** Read each new failed build's logs. If failure is pushing the Repl layer before app startup, do not change authentication, database settings, or server ports without separate evidence. Verify declared dependencies are installed locally, distinguish that preparation from a proven fix, and require a new publish to confirm. If packaging keeps failing despite valid configuration, direct the user to Replit support rather than repeatedly changing unrelated app code.
