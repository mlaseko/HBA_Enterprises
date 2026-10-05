# FF&E Studio on Replit

## Run

Use the Run button to start the `Start application` workflow:

```sh
cd ffe && python -m uvicorn app.main:app --host 0.0.0.0 --port 5000
```

The app must run from `ffe/` because its templates, static assets, and local
data paths are relative to that directory. Keep the existing FastAPI/Jinja2
structure; no framework migration is needed.

Python dependencies are in `ffe/requirements.txt`. Replit's package manager
also records the installed dependencies in the root `pyproject.toml` and
`uv.lock`.

## Required configuration

- `APP_PASSWORD`: designer login password, stored in Replit Secrets.
- `SECRET_KEY` or `SESSION_SECRET`: session-signing secret. This workspace uses
  the existing `SESSION_SECRET`; neither secret should be written into code.
- `DATABASE_URL`: used when configured; otherwise the app uses SQLite at
  `ffe/data/app.db`. The existing workspace database connection is used here.
  Tables and the initial studio settings are created at startup.

Open Preview and log in using the password you saved as `APP_PASSWORD`.
Then set studio details under Settings and create or import a project.

## Photo storage and publishing

Photo storage currently defaults to local files under `ffe/data/uploads`.
This is suitable for workspace development only. Before publishing, configure
the existing `replit` or `s3` storage backend with durable storage and ensure
the published app has its database connection and required secrets.
Do not rely on a published server's local disk for photos or SQLite.

## Setup verification

The server starts successfully, initializes its database, and serves the login
page and static files in Preview. The login page was visually checked.
The signed-in UI has not been visually verified; authentication remains in
place.
