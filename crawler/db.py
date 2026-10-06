"""
DB 연결 설정 공유 모듈.
main.py(크롤링)와 transform.py(정제/집계)가 같은 접속 정보와
재시도 로직을 쓰도록 여기 한 곳에 모아둔다.
"""
import os
import time

import psycopg2

DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "localhost"),
    "port": os.environ.get("DB_PORT", "5432"),
    "dbname": os.environ.get("DB_NAME", "crawler_db"),
    "user": os.environ.get("DB_USER", "crawler"),
    "password": os.environ.get("DB_PASSWORD", "password"),
}


def get_db_connection(retries=10, delay=3):
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            conn = psycopg2.connect(**DB_CONFIG)
            print(f"[DB] 연결 성공 (시도 {attempt}회)")
            return conn
        except psycopg2.OperationalError as e:
            last_err = e
            print(f"[DB] 연결 실패, {delay}초 후 재시도... ({attempt}/{retries})")
            time.sleep(delay)
    raise last_err