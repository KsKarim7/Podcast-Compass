FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Requirements are copied and installed before the code, so a code-only change reuses
# this layer from the build cache instead of reinstalling every dependency.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app.py ./
COPY podcast_compass ./podcast_compass
COPY samples ./samples
COPY .streamlit/config.toml ./.streamlit/config.toml

# The files stay owned by root, so the app user can read the code but not change it.
RUN useradd --create-home --uid 10001 app
USER app

EXPOSE 8501

# The slim image has no curl, so the probe uses the Python that is already here.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health', timeout=4)"]

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
