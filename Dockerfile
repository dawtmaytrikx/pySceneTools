FROM python:3.10-slim-bullseye

# Install sury.org repo, then PHP 8.0
RUN apt-get update && apt-get install -y \
  apt-transport-https \
  ca-certificates \
  gnupg2 \
  lsb-release \
  wget \
  git

RUN echo "deb https://packages.sury.org/php/ $(lsb_release -sc) main" > /etc/apt/sources.list.d/sury-php.list \
  && wget -qO - https://packages.sury.org/php/apt.gpg | apt-key add - \
  && apt-get update && apt-get install -y \
    php8.0-cli \
    php8.0-xml \
    php8.0-mbstring

WORKDIR /app
COPY requirements.txt /tmp/
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r /tmp/requirements.txt

CMD ["python3", "scene2arr.py", "-h"]