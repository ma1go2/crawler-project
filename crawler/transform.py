"""
Raw -> Staging -> Mart 변환 스크립트.

- raw.job_postings 를 읽어서
- staging.job_postings 로 정규화(경력/학력/지역 카테고리화) 하고
- mart.* 집계 테이블 3개를 다시 만든다.

데이터 규모가 작아서(수천 건 수준) 매번 전체를 다시 만드는
"풀 리프레시" 방식을 쓴다. 데이터가 훨씬 커지면 증분 처리로
바꿔야 하지만, 지금 규모에서는 이 방식이 훨씬 단순하고 안전하다.
"""
import re

from db import get_db_connection

SIDO_LIST = [
    '서울', '부산', '대구', '인천', '광주', '대전', '울산', '세종',
    '경기', '강원', '충북', '충남', '전북', '전남', '경북', '경남', '제주',
]


# ============================================================
# 정규화 규칙
# ============================================================
def classify_experience(raw: str):
    """
    반환: (category, min_years)
    category: '신입' / '신입·경력' / '경력무관' / '경력' / '확인필요'
    '확인필요'는 크롤링 과정에서 값이 밀렸거나 예상 못한 패턴인 경우
    (예: 인크루트 일부 공고에서 고용형태 태그가 추가로 붙어
    필드가 한 칸씩 밀리는 버그 - 크롤러 쪽에서 별도로 고쳐야 함)
    """
    if raw is None:
        return ('확인필요', None)
    t = str(raw).strip()
    if t == '' or t == '학력무관':
        return ('확인필요', None)
    if '경력무관' in t:
        return ('경력무관', None)
    if t.startswith('신입') and '경력' in t:
        return ('신입·경력', None)
    if t == '신입':
        return ('신입', None)
    if '경력' in t:
        nums = re.findall(r'\d+', t)
        min_years = int(nums[0]) if nums else None
        return ('경력', min_years)
    return ('확인필요', None)


def classify_education(raw: str):
    """대졸/초대졸/고졸에 붙는 '↑' 유무를 통일하고, 예상 밖 값은 확인필요로 분류."""
    if raw is None:
        return '확인필요'
    t = str(raw).strip()
    mapping = {
        '학사이하': '학사이하',
        '학력무관': '학력무관',
        '대졸↑': '대졸↑', '대졸': '대졸↑',
        '초대졸↑': '초대졸↑', '초대졸': '초대졸↑',
        '석사↑': '석사↑',
        '고졸↑': '고졸↑', '고졸': '고졸↑',
        '박사': '박사',
    }
    return mapping.get(t, '확인필요')


def split_location(raw: str):
    """
    반환: (region_sido, region_detail)
    시/도 목록에 없는 값(해외 지역, 컬럼 밀림 등)은 ('확인필요', 원본값)으로 남겨서
    나중에 원인을 추적할 수 있게 한다.
    """
    if raw is None or str(raw).strip() == '':
        return (None, None)
    t = str(raw).strip()
    if '재택' in t:
        return ('원격/재택', None)
    for sido in SIDO_LIST:
        if t.startswith(sido):
            rest = t[len(sido):].strip()
            return (sido, rest if rest else None)
    return ('확인필요', t)


# ============================================================
# Staging
# ============================================================
def create_staging_table(conn):
    with conn.cursor() as cur:
        cur.execute("CREATE SCHEMA IF NOT EXISTS staging;")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS staging.job_postings (
                id INTEGER PRIMARY KEY,
                site TEXT NOT NULL,
                keyword TEXT NOT NULL,
                title TEXT,
                company TEXT,
                region_sido TEXT,
                region_detail TEXT,
                experience_category TEXT,
                experience_min_years INTEGER,
                education_category TEXT,
                deadline DATE,
                link TEXT,
                crawled_at TIMESTAMP
            );
        """)
    conn.commit()


def rebuild_staging(conn):
    """raw.job_postings 전체를 읽어 정규화한 뒤 staging.job_postings를 통째로 다시 만든다."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id, site, keyword, title, company, location,
                   experience, education, deadline, link, crawled_at
            FROM raw.job_postings;
        """)
        rows = cur.fetchall()

    staging_rows = []
    for (id_, site, keyword, title, company, location,
         experience, education, deadline, link, crawled_at) in rows:
        region_sido, region_detail = split_location(location)
        exp_category, exp_min_years = classify_experience(experience)
        edu_category = classify_education(education)
        staging_rows.append((
            id_, site, keyword, title, company,
            region_sido, region_detail,
            exp_category, exp_min_years, edu_category,
            deadline, link, crawled_at
        ))

    with conn.cursor() as cur:
        cur.execute("TRUNCATE staging.job_postings;")
        if staging_rows:
            from psycopg2.extras import execute_values
            execute_values(cur, """
                INSERT INTO staging.job_postings
                    (id, site, keyword, title, company,
                     region_sido, region_detail,
                     experience_category, experience_min_years, education_category,
                     deadline, link, crawled_at)
                VALUES %s;
            """, staging_rows)
    conn.commit()
    print(f"[STAGING] {len(staging_rows)}건 정규화 완료")

    # 확인필요 비율이 너무 높으면 크롤러 쪽 필드 파싱이 깨졌을 가능성이 큼
    unresolved = sum(1 for r in staging_rows if r[7] == '확인필요' or r[5] == '확인필요')
    if staging_rows and unresolved / len(staging_rows) > 0.05:
        print(f"[STAGING][경고] '확인필요' 비율 {unresolved}/{len(staging_rows)} "
              f"({unresolved / len(staging_rows):.1%}) - 크롤링 파싱 로직 점검 필요")


# ============================================================
# Mart
# ============================================================
def rebuild_mart(conn):
    with conn.cursor() as cur:
        cur.execute("CREATE SCHEMA IF NOT EXISTS mart;")

        # 1) 일별/키워드별 채용 공고 수 (크롤링된 날짜 기준)
        cur.execute("""
            DROP TABLE IF EXISTS mart.daily_posting_count;
            CREATE TABLE mart.daily_posting_count AS
            SELECT
                crawled_at::date AS crawled_date,
                keyword,
                site,
                count(*) AS posting_count
            FROM staging.job_postings
            GROUP BY crawled_at::date, keyword, site
            ORDER BY crawled_date, keyword, site;
        """)

        # 2) 지역별 분포
        cur.execute("""
            DROP TABLE IF EXISTS mart.location_distribution;
            CREATE TABLE mart.location_distribution AS
            SELECT
                keyword,
                COALESCE(region_sido, '미상') AS region_sido,
                count(*) AS posting_count
            FROM staging.job_postings
            GROUP BY keyword, COALESCE(region_sido, '미상')
            ORDER BY keyword, posting_count DESC;
        """)

        # 3) 경력 요구사항 분포
        cur.execute("""
            DROP TABLE IF EXISTS mart.experience_distribution;
            CREATE TABLE mart.experience_distribution AS
            SELECT
                keyword,
                experience_category,
                count(*) AS posting_count,
                round(avg(experience_min_years)::numeric, 1) AS avg_min_years
            FROM staging.job_postings
            GROUP BY keyword, experience_category
            ORDER BY keyword, posting_count DESC;
        """)
    conn.commit()
    print("[MART] daily_posting_count / location_distribution / experience_distribution 재생성 완료")


def run_transform():
    conn = get_db_connection()
    try:
        create_staging_table(conn)
        rebuild_staging(conn)
        rebuild_mart(conn)
    finally:
        conn.close()


if __name__ == '__main__':
    run_transform()