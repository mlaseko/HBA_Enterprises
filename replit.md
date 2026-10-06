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

Photo storage is selected by `STORAGE_BACKEND`. Without that setting, it defaults
to Replit Object Storage when running on Replit (the bucket in `.replit`), and to
local files under `ffe/data/uploads` elsewhere. Local files are not shared between
the workspace and the published app, so photos saved there do not show on other
computers. A photo still found on the server's disk is copied into the bucket the
first time it is viewed.
For publishing, use the existing `replit` or `s3` backend with durable storage and
ensure the published app has its database connection and required secrets.
Do not rely on a published server's local disk for photos or SQLite.

Publishing uses the root `.replit`, not `ffe/.replit`. Its build command installs
`ffe/requirements.txt`, and its run command starts Uvicorn from `ffe/` on port
5000, exactly as the workspace workflow does. Do not use the root `main.py` as
the publishing entrypoint: it is a generated scaffold that prints a message and
exits, not the app server.

Publishing startup checks require an unauthenticated `GET /` to return HTTP 200.
The root therefore renders the existing login page directly for unauthenticated
visitors; other protected pages still redirect to login. Preserve authentication
when changing this behavior.

Configuration changes take effect only when the user republishes.

## Setup verification

The server starts successfully, initializes its database, and serves the login
page and static files in Preview. The root returns HTTP 200 without a redirect,
and protected settings still redirect unauthenticated requests to login.
The login page was visually checked.
The signed-in UI has not been visually verified; authentication remains in
place.
