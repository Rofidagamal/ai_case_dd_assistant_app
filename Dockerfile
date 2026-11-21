# AI Case Differential-Diagnosis Assistant - teaching tool, not medical advice.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    STREAMLIT_SERVER_MAX_UPLOAD_SIZE=200 \
    DATA_DIR=/data \
    PORT=8501

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Run as a normal user; /data holds settings, logs and your own knowledge library
RUN useradd --create-home --uid 10001 app \
 && mkdir -p /data/knowledge_base \
 && cp -n knowledge_base/README.txt /data/knowledge_base/ 2>/dev/null || true \
 && chown -R app:app /app /data
USER app
VOLUME ["/data"]
EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/_stcore/health' % os.environ.get('PORT','8501'), timeout=4)"

CMD ["sh", "-c", "exec streamlit run app.py --server.port=${PORT:-8501}"]
