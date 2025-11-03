FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

# Install system deps: git and docker CLI are required
RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates apt-transport-https curl gnupg2 lsb-release git build-essential libssl-dev libffi-dev python3-dev openssh-client sshpass && \
    # Add Docker's official GPG key and repository
    install -m 0755 -d /etc/apt/keyrings && \
    curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg && \
    chmod a+r /etc/apt/keyrings/docker.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" > /etc/apt/sources.list.d/docker.list && \
    apt-get update && \
    # Install Docker CLI only (not the daemon)
    apt-get install -y --no-install-recommends docker-ce-cli && \
    rm -rf /var/lib/apt/lists/*

# NOTE: google-cloud-sdk (gcloud) will be installed below via Google's apt repository

# Copy requirements and install Python deps (also install ansible-core via pip)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt ansible-core

# Install Google Cloud SDK from official repo (creates keyring and repo entry)
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends curl gnupg ca-certificates apt-transport-https; \
    install -m 0755 -d /etc/apt/keyrings; \
    curl -fsSL https://packages.cloud.google.com/apt/doc/apt-key.gpg | gpg --dearmor -o /etc/apt/keyrings/cloud.google.gpg; \
    chmod a+r /etc/apt/keyrings/cloud.google.gpg; \
    echo "deb [signed-by=/etc/apt/keyrings/cloud.google.gpg] http://packages.cloud.google.com/apt cloud-sdk main" > /etc/apt/sources.list.d/google-cloud-sdk.list; \
    apt-get update; \
    apt-get install -y --no-install-recommends google-cloud-sdk; \
    rm -rf /var/lib/apt/lists/*

# Copy app sources
COPY . /app

# Default command to run the FastAPI app with uvicorn
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port 8000"]
