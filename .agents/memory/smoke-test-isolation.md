---
name: Smoke-test isolation
description: Why the smoke suite must not inherit live AI configuration.
---

Keep smoke tests isolated from ambient service credentials; do not loosen assertions until feature flags and environment assumptions are checked.

**Why:** A setup test intentionally expected AI autofill to be disabled. An inherited workspace credential enabled it, changed the draft redirect, and allowed a live AI call before the fake AI implementation was installed. The original redirect assertion was correct for the intended test setup.

**How to apply:** Configure test-only service behavior before importing the app. Exercise enabled AI paths with fake credentials and mocked calls, without changing workspace or production secrets.
