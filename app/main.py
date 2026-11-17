from fastapi import FastAPI
from fastapi.responses import HTMLResponse

app = FastAPI(
    title="Dartmaster",
    description="Tournament management for up to four darts boards.",
    version="0.1.0",
)


@app.get("/", response_class=HTMLResponse)
async def dashboard() -> str:
    """Temporary landing page pending the live four-board dashboard."""
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Dartmaster</title>
</head>
<body>
  <main>
    <h1>Dartmaster</h1>
    <p>The tournament management service is running.</p>
  </main>
</body>
</html>"""
