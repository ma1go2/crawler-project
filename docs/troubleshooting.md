# 트러블슈팅 기록

배포 과정에서 실제로 겪고 해결한 문제들을 증상 → 원인 → 해결 순으로 정리했습니다.

---

## 1. Docker 빌드 시점에는 `.env` 값이 주입되지 않음

**증상**
```
decouple.UndefinedValueError: DJANGO_SECRET_KEY not found.
```
`docker compose up -d --build` 중 `RUN python manage.py collectstatic --noinput` 단계에서 실패.

**원인**
`env_file`로 지정한 `.env`는 컨테이너가 **실행**될 때만 주입되는 설정이다. Dockerfile의 `RUN` 명령은 **이미지를 빌드하는 시점**에 실행되므로, 이 시점엔 `.env` 값을 전혀 알 수 없다. `settings.py`가 `collectstatic` 실행 중 import되면서 `SECRET_KEY`를 읽으려다 값이 없어 바로 에러가 났다.

**해결**
`collectstatic`, `migrate`를 빌드 단계가 아니라 **컨테이너 시작 시점**(entrypoint)으로 옮겼다.

```bash
# entrypoint.sh
#!/bin/sh
set -e
python manage.py collectstatic --noinput
python manage.py migrate --run-syncdb --noinput
exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3
```

이렇게 하면 빌드는 코드/의존성만 담당하고, 환경변수가 필요한 작업은 모두 실행 시점으로 넘어가 `.env`가 정상적으로 적용된다. 재배포 시 `migrate`도 매번 같이 실행되는 부수 효과도 있다.

---

## 2. 집계(mart) 테이블에 PK가 없어 Django ORM 조회 실패

**증상**
```
ProgrammingError: column daily_posting_count.id does not exist
```

**원인**
`mart.daily_posting_count` 등은 `CREATE TABLE ... AS SELECT`로 집계 결과만 저장한 테이블이라 별도 PK가 없다. Django는 모델에 PK를 명시하지 않으면 자동으로 `id` AutoField가 있다고 가정하고 쿼리를 생성하는데, 실제 테이블엔 그 컬럼 자체가 없어서 에러가 났다.

**해결**
집계 테이블을 읽기 전용으로만 쓸 것이므로, DB 스키마를 바꾸는 대신 **기존 컬럼 중 하나를 Django 모델의 `primary_key=True`로 지정**했다.

```python
class DailyPostingCount(models.Model):
    crawled_date = models.DateField(primary_key=True)
    ...
    class Meta:
        managed = False
        db_table = 'daily_posting_count'
```

이 값이 실제로는 유니크하지 않지만(여러 행에 중복 등장), 목록 조회(`.all()`, `.filter()`) 용도로만 쓰기 때문에 문제가 없다. 만약 나중에 개별 row를 `get()`으로 특정하거나 Django admin에 등록해야 한다면, `row_number() OVER (...)`로 실제 유니크한 id를 집계 쿼리에서 생성해주는 방식으로 바꿔야 한다는 점도 함께 확인했다.

---

## 3. 재배포 후 502 Bad Gateway — Nginx의 upstream DNS 캐싱

**증상**
```
connect() failed (111: Connection refused) while connecting to upstream,
upstream: "http://172.19.0.3:8000/"
```
`web` 컨테이너를 재빌드(`--build`)해서 정상적으로 떠있는데도 Nginx를 거치면 502가 발생.

**원인**
Nginx의 `upstream { server web:8000; }` 설정은 **컨테이너가 시작될 때 `web`이라는 호스트명을 한 번만 DNS로 조회**해서 IP를 캐싱한다. `web` 컨테이너가 재생성되면 Docker 내부 네트워크에서 새 IP를 받는데, Nginx는 이 변경을 모르고 예전 IP로 계속 연결을 시도하다 실패한다.

**해결 (임시)**
`web`을 재배포할 때마다 Nginx도 함께 재시작하는 것을 배포 절차에 포함시켰다.
```bash
docker compose up -d --build
docker compose restart nginx
```

**근본적인 개선 방향**
Docker 내장 DNS 리졸버(`127.0.0.11`)를 명시하고 `proxy_pass`에 변수를 사용하면 매 요청마다 동적으로 IP를 재조회하게 만들 수 있다. 다음 개선 과제로 남겨둠.

---

## 4. `.env` 공백 문자 하나로 인한 `DisallowedHost` 400 에러

**증상**
HTTPS 접속 시 계속 `400 Bad Request`. TLS 핸드셰이크는 정상, Nginx 로그도 정상 전달.

**원인**
```
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,217.142.241.34, na-no.duckdns.org
```
도메인 앞에 공백이 하나 들어가 있었다. `.split(',')`로 쪼개면 값이 `" na-no.duckdns.org"`(공백 포함)가 되고, Django의 `ALLOWED_HOSTS`는 정확히 일치해야 통과되기 때문에 매칭이 계속 실패했다.

**해결**
`.env`에서 공백을 제거했고, 재발 방지를 위해 `settings.py`에서 각 항목을 `strip()` 처리하도록 변경했다.
```python
ALLOWED_HOSTS = [h.strip() for h in config('DJANGO_ALLOWED_HOSTS', default='').split(',') if h.strip()]
```

---

## 5. Nginx 설정의 도메인 불일치로 컨테이너가 재시작 루프에 빠짐

**증상**
```
Error response from daemon: Container ... is restarting, wait until the container is running
```
`nginx -t`조차 실행할 수 없을 정도로 컨테이너가 계속 재시작됨.

**원인**
`nginx.conf`의 `server_name`과 `ssl_certificate` 경로에 작성해둔 도메인(`crawling-server.duckdns.org`)이, 실제로 DuckDNS에서 발급받아 사용 중인 도메인(`na-no.duckdns.org`)과 달랐다. Certbot이 실제로 저장한 인증서 경로는 `na-no.duckdns.org` 기준인데 Nginx 설정은 존재하지 않는 경로를 참조하고 있어서, Nginx가 시작할 때마다 설정 로드에 실패하고 재시작을 반복했다.

**해결**
`nginx.conf`의 모든 도메인 참조를 실제 발급받은 도메인으로 통일. 이후 `docker exec nginx_proxy nginx -t`로 설정 유효성을 먼저 확인하고 재시작하는 순서를 습관화했다.

---

## 6. 인터넷에 열어둔 포트로 유입되는 자동화 스캔 트래픽

**증상**
```
Invalid HTTP request line: 'PRI * HTTP/2.0'
Invalid HTTP request line: '...Cookie: mstshash=Administr'
```
로그에 출처 불명의 비정상 요청이 지속적으로 유입되고, 일부는 Gunicorn 워커 타임아웃(`WORKER TIMEOUT` → `SIGKILL`)까지 유발.

**원인**
`mstshash` 패턴은 RDP(원격 데스크톱) 접속을 노리는 자동화 스캐너의 전형적인 시그니처다. 공인 IP에 포트를 `0.0.0.0/0`으로 열어두면 전 세계에서 이런 스캔이 상시 유입되며, Gunicorn의 sync worker는 비정상 요청을 받으면 타임아웃까지 블로킹되어 워커가 강제 종료되는 부작용이 있었다.

**해결 / 대응**
애플리케이션 버그가 아니라 인터넷에 노출된 서버의 일반적인 배경 노이즈임을 확인했다. Nginx를 앞단에 둬서 비정상 요청을 더 가벼운 선에서 처리하도록 구조를 개선했고, 운영 안정화 이후에는 불필요한 포트(5432, 8000)를 OCI 보안 목록에서 외부 공개 해제하는 방향으로 정리했다.

---

## 배운 점

- **빌드 시점과 실행 시점의 환경변수 차이**처럼, 설정값이 "언제" 적용되는지를 정확히 이해하지 못하면 겉보기엔 무관해 보이는 에러가 난다.
- 컨테이너 기반 배포에서는 **서비스 간 참조(DNS, IP)가 컨테이너 재생성 시점에 깨질 수 있다는 점**을 배포 절차에 반영해야 한다.
- 설정 파일의 사소한 오타(공백, 도메인 불일치)가 스택 전체를 추적하게 만드는 경우가 많아, 에러 메시지만 보지 않고 **관련 설정값을 항상 함께 대조**하는 습관이 중요했다.
