FROM python:3.12-slim
WORKDIR /app

# Non-root user
RUN useradd -m appuser && chown -R appuser /app
USER appuser
ENV PATH="/home/appuser/.local/bin:${PATH}"

COPY --chown=appuser:appuser backend/requirements.txt ./backend/
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY --chown=appuser:appuser backend/ ./backend/
COPY --chown=appuser:appuser data/ ./data/

ENV PORT=8081
EXPOSE 8081
CMD ["sh", "-c", "exec uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8081} --timeout-graceful-shutdown 15"]
