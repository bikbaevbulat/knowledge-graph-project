FROM python:3.10

WORKDIR /app
COPY . /app

# Установка системных зависимостей
RUN apt-get update && apt-get install -y \
    git \
    gcc \
    cmake \
    libssl-dev \
    libpq-dev \
    make \
    curl \
    python3-dev \
    libffi-dev \
    && rm -rf /var/lib/apt/lists/*

# Установка libmgclient
RUN git clone --depth=1 https://github.com/memgraph/mgclient.git && \
    cd mgclient && \
    cmake -Bbuild -S. -DCMAKE_BUILD_TYPE=Release && \
    cmake --build build --target install && \
    ldconfig && \
    cd .. && rm -rf mgclient

# Установка Python клиента Memgraph (mgclient)
RUN pip install pymgclient

RUN pip install --upgrade pip && pip install --no-cache-dir -r /app/backend/requirements.txt

# Загружаем модель в кэш при сборке контейнера
# Можно использовать переменные для отключения symlinks и прогресса
ENV HF_HUB_DISABLE_SYMLINKS_WARNING=1 \
    TRANSFORMERS_NO_ADVISORY_WARNINGS=1

RUN python3 -c "\
from sentence_transformers import SentenceTransformer; \
SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"


CMD ["gunicorn", "main:app", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000", "--workers=4", "--threads=2", "--timeout=120"]
