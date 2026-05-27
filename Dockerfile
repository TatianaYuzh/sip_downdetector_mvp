FROM nginx:alpine

# Установить необходимые пакеты
RUN apk add --no-cache \
    python3 \
    py3-pip \
    dcron \
    ca-certificates

# Создать директорию для скриптов
RUN mkdir -p /app/scripts

# Скопировать Python скрипт
COPY scripts/log_processor.py /app/scripts/

# Скопировать entrypoint
COPY docker-entrypoint.sh /
RUN chmod +x /docker-entrypoint.sh

# Создать crontab для запуска каждые 5 минут
RUN echo "*/5 * * * * cd /app && python3 scripts/log_processor.py >> /var/log/cron.log 2>&1" | crontab -

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["nginx", "-g", "daemon off;"]
