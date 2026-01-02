# Используем легкий образ Python 3.11
FROM python:3.11-slim

# Отключаем создание кеш-файлов .pyc
ENV PYTHONDONTWRITEBYTECODE 1
# Отключаем буферизацию вывода (чтобы логи сразу летели в консоль Render)
ENV PYTHONUNBUFFERED 1

# Создаем рабочую директорию
WORKDIR /app

# Сначала копируем только requirements, чтобы кэшировать слои
COPY requirements.txt .

# Обновляем pip и устанавливаем зависимости
RUN pip install --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Копируем остальной код проекта
COPY . .

# Указываем, что контейнер будет слушать порт (для документации)
# Render сам пробросит нужный порт через переменную окружения PORT
EXPOSE 8080

# Команда запуска
CMD ["python", "main.py"]