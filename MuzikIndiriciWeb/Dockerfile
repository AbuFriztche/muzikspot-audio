FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOST=0.0.0.0 PORT=8080
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 app
WORKDIR /srv/app
COPY requirements-local.txt ./
RUN pip install --no-cache-dir -r requirements-local.txt \
    && mkdir audio-temp && chown -R app:app /srv/app
COPY --chown=app:app app.py audio_jobs.py metadata.py cloud_auth.py index.html style.css app.js particles.js ./
USER app
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8080')+'/readyz',timeout=3).close()"
CMD ["python", "app.py", "--no-browser"]
