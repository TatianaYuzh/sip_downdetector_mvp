crond -f -l 2 &
CROND_PID=$!
echo "$(date) - Started crond (PID: $CROND_PID)"
exec "$@"
