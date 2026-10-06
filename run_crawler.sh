#!/bin/bash
cd /home/ubuntu/crawler-project && docker compose run --rm crawler >> /home/ubuntu/crawler-project/crawler.log 2>&1
