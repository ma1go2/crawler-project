import os
import re
import smtplib
from email.mime.text import MIMEText
from datetime import date, datetime, timedelta
import time

import requests
from bs4 import BeautifulSoup
from psycopg2.extras import execute_values

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException

from db import get_db_connection

from protego import Protego

# 차단 방지를 위한 헤더 설정
headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

# 검색 키워드
values = {
    '데이터분석': ['','10002372949'],
    '데이터엔지니어': ['1000236',''],
    '데이터관리': ['','100023547534925'],
}

# ============================================================
# 크롤링 가이드 확인
# ============================================================

def load_robots_from_url(robots_url, timeout=10):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    resp = requests.get(robots_url, headers=headers, timeout=timeout)
    resp.raise_for_status()    # 200
    return Protego.parse(resp.text)

CRAWLER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

saramin_robots_url = 'https://www.saramin.co.kr/robots.txt'
jobkorea_robots_url = 'https://www.jobkorea.co.kr/robots.txt'

saramin_robots = load_robots_from_url(saramin_robots_url)
jobkorea_robots = load_robots_from_url(jobkorea_robots_url)

# ============================================================
# 데이터 품질 검증
# ============================================================
def is_valid_posting(posting: dict) -> bool:
    required_fields = ['공고명', '회사명', '링크']
    for field in required_fields:
        value = posting.get(field)
        if not value or not str(value).strip():
            return False
    return True


# ============================================================
# 메일 설정 (환경변수로 받음 - 네이버 메일 기준)
# ============================================================
SMTP_CONFIG = {
    "host": os.environ.get("SMTP_HOST", "smtp.naver.com"),
    "port": int(os.environ.get("SMTP_PORT", "587")),
    "user": os.environ.get("SMTP_USER"),
    "password": os.environ.get("SMTP_PASSWORD"),
}
MAIL_TO = os.environ.get("MAIL_TO")


# ============================================================
# 메일 전송
# ============================================================
def send_email_report(stats: dict, start_time: datetime, end_time: datetime, anomalies=None):
    """
    stats: {(site, keyword): {'raw': ..., 'inserted': ...}}
    크롤링 완료 후 사이트/키워드별 수집/저장 건수를 요약해서 메일로 발송.
    anomalies가 있으면 상단에 경고로 표시.
    """
    if not SMTP_CONFIG["user"] or not SMTP_CONFIG["password"] or not MAIL_TO:
        print("[MAIL] SMTP 설정이 없어 메일 발송을 건너뜁니다.")
        return

    total_inserted = sum(s['inserted'] for s in stats.values())
    duration = (end_time - start_time).total_seconds()

    lines = [
        f"크롤링 실행 시각: {start_time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"소요 시간: {duration:.1f}초",
        f"총 신규 저장 건수: {total_inserted}건",
    ]

    if anomalies:
        lines.append("")
        lines.append("⚠️  이상 감지")
        for a in anomalies:
            lines.append(f"- {a}")

    lines.append("")
    lines.append("[사이트/키워드별 수집(raw)/신규저장(inserted) 건수]")
    for (site, keyword), s in sorted(stats.items()):
        lines.append(f"- {site} / {keyword}: raw {s['raw']}건 중 신규 {s['inserted']}건 저장")

    body = "\n".join(lines)

    subject_prefix = "[크롤러][경고]" if anomalies else "[크롤러]"
    msg = MIMEText(body)
    msg["Subject"] = (
        f"{subject_prefix} {start_time.strftime('%Y-%m-%d %H:%M')} 실행 결과 - "
        f"신규 {total_inserted}건"
    )
    msg["From"] = SMTP_CONFIG["user"]
    msg["To"] = MAIL_TO

    try:
        if SMTP_CONFIG["port"] == 465:
            # 465: 처음부터 SSL로 접속
            with smtplib.SMTP_SSL(SMTP_CONFIG["host"], SMTP_CONFIG["port"]) as server:
                server.login(SMTP_CONFIG["user"], SMTP_CONFIG["password"])
                server.sendmail(SMTP_CONFIG["user"], [MAIL_TO], msg.as_string())
        else:
            # 587(기본값) 등: 평문 연결 후 STARTTLS로 암호화 전환
            with smtplib.SMTP(SMTP_CONFIG["host"], SMTP_CONFIG["port"]) as server:
                server.starttls()
                server.login(SMTP_CONFIG["user"], SMTP_CONFIG["password"])
                server.sendmail(SMTP_CONFIG["user"], [MAIL_TO], msg.as_string())
        print(f"[MAIL] 결과 메일 발송 완료 ({MAIL_TO})")
    except Exception as e:
        print(f"[MAIL] 메일 발송 실패: {e}")


# ============================================================
# log table 생성
# ============================================================
def create_run_log_table(conn):
    with conn.cursor() as cur:
        cur.execute("CREATE SCHEMA IF NOT EXISTS mart;")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS mart.crawl_run_log (
                id SERIAL PRIMARY KEY,
                run_at TIMESTAMP NOT NULL,
                site TEXT NOT NULL,
                keyword TEXT NOT NULL,
                raw_count INTEGER NOT NULL,
                inserted_count INTEGER NOT NULL
            );
        """)
    conn.commit()


# ============================================================
# log 이력 관리
# ============================================================
def log_run_stats(conn, stats: dict, run_time: datetime):
    """이번 실행의 사이트/키워드별 raw/inserted 건수를 이력 테이블에 남긴다."""
    create_run_log_table(conn)
    rows = [
        (run_time, site, keyword, s['raw'], s['inserted'])
        for (site, keyword), s in stats.items()
    ]
    with conn.cursor() as cur:
        execute_values(cur, """
            INSERT INTO mart.crawl_run_log (run_at, site, keyword, raw_count, inserted_count)
            VALUES %s;
        """, rows)
    conn.commit()
    print(f"[LOG] 이번 실행 통계 {len(rows)}건 기록 완료")


# ============================================================
# 이상 탐지
# ============================================================
def check_anomalies(conn, stats: dict, drop_ratio=0.5, min_history=3):
    """
    두 가지를 감지한다.
    1) 즉시 감지: 이번 실행에서 원본(raw) 수집이 0건인 사이트/키워드
       -> 대부분 사이트 HTML 구조가 바뀌어 셀렉터가 깨진 경우
    2) 추세 감지: 과거 실행(최근 6회) 평균 대비 raw 건수가 절반 이하로 급감
       -> 과거 이력이 min_history회 이상 쌓였을 때만 비교 (초기 오탐 방지)
    """
    anomalies = []

    for (site, keyword), s in stats.items():
        if s['raw'] == 0:
            anomalies.append(f"[즉시감지] {site}/{keyword}: 원본 수집 0건 - 사이트 구조 변경 의심")

    with conn.cursor() as cur:
        for (site, keyword), s in stats.items():
            cur.execute("""
                SELECT raw_count FROM mart.crawl_run_log
                WHERE site = %s AND keyword = %s
                ORDER BY run_at DESC
                OFFSET 1 LIMIT 6;
            """, (site, keyword))
            history = [r[0] for r in cur.fetchall()]
            if len(history) < min_history:
                continue
            avg_history = sum(history) / len(history)
            if avg_history > 0 and s['raw'] < avg_history * drop_ratio:
                anomalies.append(
                    f"[추세감지] {site}/{keyword}: 이번 {s['raw']}건, "
                    f"최근 {len(history)}회 평균 {avg_history:.1f}건 대비 급감"
                )

    if anomalies:
        print("[ANOMALY] 이상 감지:")
        for a in anomalies:
            print(f"  - {a}")
    return anomalies

# ============================================================
# DB 함수들
# ============================================================

def create_table(conn):
    # raw 스키마: 사이트별 원본
    create_schema_sql = "CREATE SCHEMA IF NOT EXISTS raw;"
    with conn.cursor() as cur:
        cur.execute(create_schema_sql)
    conn.commit()

    create_sql = """
    CREATE TABLE IF NOT EXISTS raw.job_postings (
        id SERIAL PRIMARY KEY,
        site TEXT NOT NULL,
        keyword TEXT NOT NULL,
        title TEXT,
        company TEXT,
        location TEXT,
        experience TEXT,
        education TEXT,
        deadline DATE,
        link TEXT UNIQUE,
        crawled_at TIMESTAMP DEFAULT NOW()
    );
    """
    with conn.cursor() as cur:
        cur.execute(create_sql)
    conn.commit()

    # 채용공고 중복 방지 유니크 인덱스 생성
    add_index_sql = """
    CREATE UNIQUE INDEX IF NOT EXISTS uq_site_title_company
        ON raw.job_postings (site, title, company);
    """
    with conn.cursor() as cur:
        cur.execute(add_index_sql)
    conn.commit()
    print("[DB] 테이블 확인/생성 완료 (raw.job_postings)")


def save_to_db(conn, results, keyword, site):
    """
    반환값: 실제로 새로 저장된(중복 제외) 건수
    """
    if not results:
        print(f"[DB] 저장할 데이터 없음 (keyword={keyword})")
        return 0

    insert_sql = """
    INSERT INTO raw.job_postings
        (site, keyword, title, company, location, experience, education, deadline, link)
    VALUES %s
    ON CONFLICT (site, title, company) DO NOTHING
    RETURNING id;
    """

    rows = [
        (
            r['사이트'], keyword, r['공고명'], r['회사명'], r['위치'],
            r['경력'], r['학력'], r['마감일'], r['링크']
        )
        for r in results
    ]

    try:
        with conn.cursor() as cur:
            inserted_rows = execute_values(cur, insert_sql, rows, fetch=True)
            inserted = len(inserted_rows)
        conn.commit()
        print(f"[DB] {inserted}/{len(rows)}건 신규 저장 완료 (site={site}, keyword={keyword})")
        return inserted
    except Exception:
        # 에러 발생 시 트랜잭션을 롤백해서 이후 작업이 연쇄적으로 "current transaction is aborted" 상태에 빠지지 않게 한다.
        conn.rollback()
        raise


# ============================================================
# 사람인
# ============================================================
def set_saramin_url(keyword, page=1, postingcount=100):
    base_url = (
        f"https://www.saramin.co.kr/zf_user/search?searchType=search"
        f"{f'&searchword={keyword}' if keyword else ''}"
        f"&recruitPage={page}"
        f"&recruitPageCount={postingcount}"
    )
    return base_url


def deadline_convert_saramin(deadline):
    base_date = date.today()

    if deadline is None:
        return None

    value = deadline.strip()

    if value == "오늘마감":
        return base_date.strftime("%Y-%m-%d")

    if value == "내일마감":
        return (base_date + timedelta(days=1)).strftime("%Y-%m-%d")

    match = re.search(r"(\d{1,2})\s*/\s*(\d{1,2})", value)

    if not match:
        return None
    
    month = int(match.group(1))
    day = int(match.group(2))
    
    try:
        return date(base_date.year, month, day).strftime("%Y-%m-%d")
    except ValueError:
        return None


def crawling_saramin(keyword):
    base_url = set_saramin_url(keyword)
    if not saramin_robots.can_fetch(base_url, CRAWLER_UA):
        return []
    
    response = requests.get(base_url, headers=headers, timeout=20)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, 'html.parser')
    items = soup.select('.item_recruit')

    results = []
    for item in items:
        try:
            title = item.select_one('.job_tit a').text.strip()
            link = "https://www.saramin.co.kr" + item.select_one('.job_tit a')['href']
            company = item.select_one('.corp_name a').text.strip()
            deadline = deadline_convert_saramin(
                item.select_one('.job_date .date').text.strip()
            )
            conditions = item.select('.job_condition span')
            location = conditions[0].text
            experience = conditions[1].text
            education = conditions[2].text

            posting = {
                '사이트': '사람인', '공고명': title, '회사명': company,
                '위치': location, '경력': experience, '학력': education,
                '마감일': deadline, '링크': link
            }
            if is_valid_posting(posting):
                results.append(posting)
            else:
                print(f"[사람인] 필수 필드 누락으로 제외: {posting}")
        except Exception as e:
            print(e)
            continue

    return results


# ============================================================
# 잡코리아
# ============================================================
def set_jobkorea_url(duty, dkwrd, page=1):
    base_url = (
        f"https://www.jobkorea.co.kr/Search/?"
        f"&Page_No={page}"
        f"&duty={duty}"
        f"&dkwrd={dkwrd}"
        "&edu=5,4,3,0&ord=RelevanceDesc"
    )
    return base_url


def deadline_convert_jobkorea(spans):
    base_date = date.today()

    if spans is None:
        return None
    
    for span in spans:
        text = span.get_text(strip=True)
        if "마감" in text:
            value = text.replace("마감", "").strip()

            if value == "오늘":
                return base_date.strftime("%Y-%m-%d")

            if value == "내일":
                return (base_date + timedelta(days=1)).strftime("%Y-%m-%d")

            match = re.match(r"(\d{1,2})\s*/\s*(\d{1,2})", value)

            if not match:
                return None

            month = int(match.group(1)) 
            day = int(match.group(2))
            try:
                return date(base_date.year, month, day).strftime("%Y-%m-%d")
            except ValueError:
                return None
                
    return None


def crawling_jobkorea(keyword, duty='', dkwrd=''):
    options = Options()
    options.add_argument("--headless=new")
    # Docker 컨테이너(root, 제한된 /dev/shm)에서 headless chrome 실행하려면 필수 옵션
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    # 차단 방지 헤더 설정
    options.add_argument(
        "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    options.add_argument("--disable-blink-features=AutomationControlled")
    # DOM 구성만 끝나면 바로 진행 (광고/트래커 등 부가 리소스까지 안 기다림)
    # -> 잡코리아 같은 무거운 SPA 페이지에서 기본(normal) 전략은 타임아웃 나기 쉬움
    options.page_load_strategy = "eager"

    chrome_bin = os.environ.get("CHROME_BIN")
    if chrome_bin:
        options.binary_location = chrome_bin

    chromedriver_path = os.environ.get("CHROMEDRIVER_PATH")
    if chromedriver_path:
        service = Service(chromedriver_path)
    else:
        # 로컬(비-Docker) 환경 대비 fallback
        from webdriver_manager.chrome import ChromeDriverManager
        service = Service(ChromeDriverManager().install())

    driver = webdriver.Chrome(options=options, service=service)
    # eager 전략을 써도 만약을 대비해 상한선은 넉넉히 45초로 설정
    driver.set_page_load_timeout(45)

    results = []
    try:
        base_url = set_jobkorea_url(duty, dkwrd)
        if not jobkorea_robots.can_fetch(base_url, CRAWLER_UA):
            return []
        
        driver.get(base_url)
        # 무작정 2초 대기하는 대신, 실제 공고 카드가 나타날 때까지 최대 20초 대기
        try:
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, 'div[data-sentry-component="CardJob"]')
                )
            )
        except TimeoutException:
            print(f"[jobkorea] 첫 페이지 로딩 지연 (keyword={keyword}), 그래도 진행")

        for i in range(1, 6):
            try:
                if i != 1:
                    next_page = driver.find_element(By.CSS_SELECTOR, f"a[href*='Page_No={i}']")
                    next_page.click()
                    time.sleep(2)
                    try:
                        WebDriverWait(driver, 20).until(
                            EC.presence_of_element_located(
                                (By.CSS_SELECTOR, 'div[data-sentry-component="CardJob"]')
                            )
                        )
                    except TimeoutException:
                        print(f"[jobkorea] {i}페이지 로딩 지연 (keyword={keyword}), 그래도 진행")

                html = driver.page_source
                soup = BeautifulSoup(html, 'html.parser')
                items = soup.select('div[data-sentry-component="CardJob"]')

                for item in items:
                    try:
                        title = item.select("span.truncate")[0].text.strip()
                        link = item.select_one('a[data-sentry-component="Title"]')['href']
                        company = item.select("span.truncate")[1].text.strip()
                        deadline = deadline_convert_jobkorea(item.select("span.text-typo-c1-13.text-gray700"))
                        location = item.select("span.truncate")[2].text.strip()
                        experience = item.select_one(
                            'span.flex-shrink-0.text-gray700.text-typo-c1-13'
                        ).text.strip()
                        education = '학사이하'

                        posting = {
                            '사이트': '잡코리아', '공고명': title, '회사명': company,
                            '위치': location, '경력': experience, '학력': education,
                            '마감일': deadline, '링크': link
                        }
                        if is_valid_posting(posting):
                            results.append(posting)
                        else:
                            print(f"[잡코리아] 필수 필드 누락으로 제외: {posting}")
                    except Exception as e:
                        print(e)
                        continue
            except Exception as e:
                print(f"[jobkorea] {i}페이지 이동 실패: {e}")
                break
    finally:
        # 위에서 어떤 예외가 나든 브라우저 프로세스는 반드시 정리한다
        driver.quit()

    return results


# ============================================================
# 메인
# ============================================================
if __name__ == '__main__':
    start_time = datetime.now()
    stats = {}  # {(site, keyword): {'raw': 원본 수집 건수, 'inserted': 신규 저장 건수}}
    anomalies = []
    
    conn = get_db_connection()
    create_table(conn)

    try:
        for keyword, (duty, dkwrd) in values.items():
            # 사이트 하나가 예외로 죽어도 다른 사이트 결과는 저장되도록
            # 각각 try/except로 감싸고, 크롤링이 끝나는 대로 바로 저장한다.
            try:
                saram_result = crawling_saramin(keyword)
                inserted = save_to_db(conn, saram_result, keyword, '사람인')
                stats[('사람인', keyword)] = {'raw': len(saram_result), 'inserted': inserted}
            except Exception as e:
                print(f"[사람인] 크롤링/저장 실패 (keyword={keyword}): {e}")
                stats[('사람인', keyword)] = {'raw': 0, 'inserted': 0}

            try:
                job_result = crawling_jobkorea(keyword, duty, dkwrd)
                inserted = save_to_db(conn, job_result, keyword, '잡코리아')
                stats[('잡코리아', keyword)] = {'raw': len(job_result), 'inserted': inserted}
            except Exception as e:
                print(f"[잡코리아] 크롤링/저장 실패 (keyword={keyword}): {e}")
                stats[('잡코리아', keyword)] = {'raw': 0, 'inserted': 0}

        # 이력 기록과 이상감지는 부가 기능이라, 실패해도 크롤링 결과 메일은 보낸다
        try:
            log_run_stats(conn, stats, start_time)
        except Exception as e:
            print(f"[LOG] 실행 통계 기록 실패: {e}")
            conn.rollback()

        try:
            anomalies = check_anomalies(conn, stats)
        except Exception as e:
            print(f"[ANOMALY] 이상 감지 실패: {e}")
            conn.rollback()

    finally:
        conn.close()
        print("[DB] 연결 종료")

    end_time = datetime.now()
    send_email_report(stats, start_time, end_time, anomalies)

    try:
        import transform
        transform.run_transform()
    except Exception as e:
        print(f"[TRANSFORM] staging/mart 갱신 실패: {e}")