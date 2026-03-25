#!/bin/sh
set -e
export PORT="${PORT:-3000}"
envsubst '$PORT' < /tmp/nginx.conf.template > /etc/nginx/conf.d/default.conf
exec nginx -g 'daemon off;'
