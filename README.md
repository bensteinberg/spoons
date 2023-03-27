spoons
======
This is an experiment in managing and exposing a pool of Firecracker VMs for use in web capture using [scoop](https://github.com/harvard-lil/scoop).

It uses [waitress](https://docs.pylonsproject.org/projects/waitress/en/stable/) as a WSGI application server; initial experiments with gunicorn did not work, probably because this code can only run in a single process.

Outstanding questions include:

- Is [ignite](https://github.com/weaveworks/ignite) the right tool for managing Firecracker VMs? It may not be under active development, and it may not provide enough control:
- How can ignite (or some other tool) be made to implement a [blocklist like Scoop's](https://github.com/harvard-lil/scoop/blob/main/options.js#L38-L68)?
- Can the mechanism for concurrency used here be rewritten to run safely in multiple processes? It may make more sense to move to something like a Redis cache or a database table for maintaining the list of VMs.
- In an earlier iteration, arguments were passed in using Click. Waitress does not allow arguments to be passed on the command line, so this will probably need a way to collect them from the environment.
- This will need a process or a cron job to clean up old captures.

Installation
------------
```
pipx install git+https://github.com/bensteinberg/spoons.git
```

Usage
-----
To run locally, in development:
```
poetry run waitress-serve --host '127.0.0.1' --call 'spoons.main:create_app_dev'
```

To run in production, presumably in a systemd service file:
```
waitress-serve --host '127.0.0.1' --call 'spoons.main:create_app'
```
