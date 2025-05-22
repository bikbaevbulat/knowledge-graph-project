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

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
