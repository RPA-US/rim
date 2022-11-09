FROM python:3.10.7-slim-buster
ARG branch=main

RUN apt-get update
RUN apt-get install -y gcc git postgresql-server-dev-all musl-dev libffi-dev cmake python-tk g++ ffmpeg libsm6 libxext6 redis
# RUN apt-get install -y postgresql postgresql-client
# Allows docker to cache installed dependencies between builds

# Clones the repository
RUN git clone https://github.com/RPA-US/rim.git
WORKDIR /rim
RUN git checkout -t origin/$branch

# Installs python dependencies
RUN /usr/local/bin/python -m venv venv
RUN ./venv/bin/python -m pip install --upgrade pip
RUN ./venv/bin/python -m pip install --no-cache-dir -r requirements.txt