FROM python:3.12-slim-bookworm

# MS ODBC-driver til SQL Server + systembiblioteker til WeasyPrint
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl gnupg2 ca-certificates \
 && curl -fsSL https://packages.microsoft.com/keys/microsoft.asc \
      | gpg --dearmor -o /usr/share/keyrings/microsoft-prod.gpg \
 && curl -fsSL https://packages.microsoft.com/config/debian/12/prod.list \
      > /etc/apt/sources.list.d/mssql-release.list \
 && apt-get update \
 && ACCEPT_EULA=Y apt-get install -y --no-install-recommends \
      msodbcsql18 unixodbc tzdata \
      libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0 \
      libcairo2 libffi8 shared-mime-info fonts-dejavu-core \
 && apt-get purge -y curl gnupg2 \
 && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

ENV PYTHONUNBUFFERED=1
# Uden denne kører containeren UTC, og tidsstemplet i PDF'en bliver 1-2 timer bagud
ENV TZ=Europe/Copenhagen
CMD ["python", "-m", "app.main"]
