# URL Shortener

A small Flask URL-shortening service backed by SQLite. It creates stable short
codes for URLs, supports custom codes, records redirects, and exposes click
statistics.

## Run with Docker

Build and start the service:

```bash
docker build -t urlshortner .
docker run --rm -p 8000:8000 -v urlshortner_data:/data urlshortner
```

The service is then available at <http://localhost:8000>. The named
`urlshortner_data` volume preserves the SQLite database when the container is
stopped or replaced. Press `Ctrl+C` to stop the foreground container.

### Run with Compose

```bash
docker compose up --build
```

If your system uses the legacy Compose command, use:

```bash
docker-compose up --build
```

To stop Compose while retaining saved URLs:

```bash
docker compose down
```

To remove the saved database as well:

```bash
docker compose down --volumes
```

## API

### Create a short URL

```bash
curl -X POST http://localhost:8000/shorten \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com/docs"}'
```

The response contains the shortened URL. A newly created mapping returns
`201`; submitting the same normalized URL returns its existing code with
`200`.

```json
{"url":"http://localhost:8000/AbCdEf12"}
```

### Create a custom code

```bash
curl -X POST http://localhost:8000/custom \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.com/docs","shortcode":"docs"}'
```

### Follow a short URL

Open the returned URL in a browser, or use:

```bash
curl -I http://localhost:8000/AbCdEf12
```

The service records the redirect and responds with HTTP `302`.

### View statistics

```bash
curl http://localhost:8000/stats/AbCdEf12
```

This returns the destination URL, creation time, total click count, and up to
20 recent clicks.

### Delete a short URL

```bash
curl -X DELETE http://localhost:8000/AbCdEf12
```

## Configuration

| Variable | Default in Docker | Purpose |
| --- | --- | --- |
| `DATABASE` | `/data/urls.db` | Path to the SQLite database file. |

When running outside Docker, `DATABASE` defaults to `urls.db` alongside
`app.py`. A local `.env` file can also provide environment variables.

## Development

This project uses Python 3.14+ and `uv`.

```bash
uv sync
uv run python app.py
```

The development server listens on Flask's default address and port. For a
production-style local run, use:

```bash
uv run gunicorn -b 0.0.0.0:8000 -w 2 'app:create_app()'
```
