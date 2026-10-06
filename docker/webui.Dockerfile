FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1

EXPOSE 8080

# main.py importa tema.py como modulo hermano: Python agrega el directorio del
# script a sys.path por si solo, asi que no hace falta /app/src en PYTHONPATH.
CMD ["python", "src/webui/main.py"]
