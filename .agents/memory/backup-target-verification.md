---
name: Backup target verification
description: Avoid mistaking a workspace database export for a production backup.
---

Verify the source of a user-supplied production backup connection before labeling its export as production.

**Why:** A connection supplied for production initially reached the same database as the workspace, while independent production queries showed different data. Successfully creating an archive alone would not have protected live data.

**How to apply:** Compare non-sensitive record counts with a read-only managed-production query and privately compare database identity with the workspace connection. Never print connection strings. If the target is ambiguous, pause and request correction through the secure secrets flow. Distinguish archive readability checks from a fully tested restore, and warn that database exports do not include object-storage uploads.
