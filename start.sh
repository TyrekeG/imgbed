#!/bin/bash
cd /opt/imgbed
export $(grep -v '^#' .env | xargs)
exec python3 imgbed.py
