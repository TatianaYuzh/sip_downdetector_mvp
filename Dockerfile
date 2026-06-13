FROM nginx:alpine

# Установить необходимые пакеты
RUN apk add --no-cache \
    python3 \
    py3-pip \
    dcron \
    logrotate \
    ca-certificates

# Создать директорию для скриптов
RUN mkdir -p /app/scripts

# Скопировать Python скрипт и конфиг logrotate
COPY scripts/log_processor.py /app/scripts/
COPY logrotate.conf /etc/logrotate.d/nginx

# Создать crontab для запуска каждые 5 минут и logrotate ежедневно
RUN (echo "*/5 * * * * cd /app && python3 scripts/log_processor.py >> /var/log/cron.log 2>&1"; \
     echo "19 0 * * * /usr/sbin/logrotate /etc/logrotate.d/nginx >> /var/log/cron.log 2>&1") | crontab -

# Запустить cron в фоне и затем nginx
CMD crond -f -l 2 & nginx -g "daemon off;"
