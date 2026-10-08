# Writing workbench (phase 9)

This is the first-version static workbench. It only queries and operates tasks through the unified backend REST API. It does not talk to Agents, Harness, or the database directly. Local `./scripts/dev_up.sh` serves the page and `/api` on the same port. For a separate deploy, host the static files and proxy `/api` to the backend.

Current coverage: task status, pause, resume, retry planning, retry writing, and cancel. Prose, review reports, and memory proposals reuse backend query APIs. Lists and version views come later.
