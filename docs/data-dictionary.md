# 데이터 항목 정의서

## 1. 개요

| 항목 | 내용 |
|---|---|
| DBMS | PostgreSQL |
| 스키마 | `raw`, `staging`, `mart` (3계층) |
| 테이블 수 | 6개 (raw 1 / staging 1 / mart 4) |

> 테이블 간 물리적 FK 제약은 없습니다. 테이블 사이의 관계는 변환·집계 로직에 따른 **논리적 관계**이며, [ERD](../README.md#데이터-모델)에서 점선으로 표현했습니다.

## 2. 테이블 목록

| 스키마 | 테이블명 | 한글명 | 역할 | 갱신 방식 |
|---|---|---|---|---|
| raw | `job_postings` | 채용공고(원본) | 크롤러가 수집한 원본을 가공 없이 저장 | 크롤링 시 적재 |
| staging | `job_postings` | 채용공고(정제) | raw를 정규화(경력·학력·지역 카테고리화) | `transform.py`가 TRUNCATE 후 전체 재생성 |
| mart | `daily_posting_count` | 일별 공고 수 | 수집일자·키워드·사이트별 공고 수 | `transform.py`가 DROP 후 전체 재생성 |
| mart | `location_distribution` | 지역별 분포 | 키워드·시도별 공고 수 | `transform.py`가 DROP 후 전체 재생성 |
| mart | `experience_distribution` | 경력별 분포 | 키워드·경력구분별 공고 수, 평균 최소경력 | `transform.py`가 DROP 후 전체 재생성 |
| mart | `crawl_run_log` | 크롤링 실행 로그 | 크롤링 실행 이력(수집·적재 건수) 기록 | 풀 리프레시 대상 아님 |

---

## 3. 컬럼 정의

> 타입 참고: `integer` = 32bit, `bigint` = 64bit, `timestamp` = timestamp without time zone

### 3-1. raw.job_postings (채용공고 원본)

| 순번 | 컬럼명 | 한글명 | 타입 | NULL | PK | 제약조건(허용값) | 설명 |
|---|---|---|---|---|---|---|---|
| 1 | `id` | 공고ID | integer | N | Y | | 공고 고유 식별자 |
| 2 | `site` | 사이트 | text | N | N | | 수집 출처 사이트 |
| 3 | `keyword` | 키워드 | text | N | N | | 검색 키워드 |
| 4 | `title` | 공고제목 | text | N | N | | |
| 5 | `company` | 회사명 | text | N | N | | |
| 6 | `location` | 근무지역 | text | Y | N | | 원본 문자열 그대로 (예: "서울 강남구") |
| 7 | `experience` | 경력 | text | Y | N | | 원본 문자열 그대로 (예: "신입", "경력 3년↑") |
| 8 | `education` | 학력 | text | Y | N | | 원본 문자열 그대로 (예: "대졸↑") |
| 9 | `deadline` | 마감일 | date | Y | N | | |
| 10 | `link` | 공고링크 | text | N | N | | |
| 11 | `crawled_at` | 수집일시 | timestamp | Y | N | | |

### 3-2. staging.job_postings (채용공고 정제)

| 순번 | 컬럼명 | 한글명 | 타입 | NULL | PK | 제약조건(허용값) | 설명 / 변환 규칙 |
|---|---|---|---|---|---|---|---|
| 1 | `id` | 공고ID | integer | N | Y | | raw.id 그대로 |
| 2 | `site` | 사이트 | text | N | N | 사람인, 잡코리아 | raw.site 그대로 |
| 3 | `keyword` | 키워드 | text | N | N | 데이터분석, 데이터엔지니어, 데이터관리 | raw.keyword 그대로 |
| 4 | `title` | 공고제목 | text | Y | N | | raw.title 그대로 |
| 5 | `company` | 회사명 | text | Y | N | | raw.company 그대로 |
| 6 | `region_sido` | 시도 | text | Y | N | | raw.location에서 추출. 17개 시·도로 시작하면 해당 시·도, "재택" 포함 시 `원격/재택`, 목록에 없으면 `확인필요`, 값이 비어 있으면 NULL |
| 7 | `region_detail` | 상세지역 | text | Y | N | | 시·도 이후의 나머지 문자열. `확인필요`인 경우 원인 추적을 위해 원본값을 그대로 보존 |
| 8 | `experience_category` | 경력구분 | text | Y | N | 신입, 신입·경력, 경력무관, 경력, 확인필요 | raw.experience를 규칙 기반으로 분류. 예상 밖 값(컬럼 밀림 등)은 `확인필요` |
| 9 | `experience_min_years` | 최소경력(년) | integer | Y | N | | `경력`인 경우에만 문자열에서 첫 번째 숫자를 추출, 그 외 NULL |
| 10 | `education_category` | 학력구분 | text | Y | N | 학사이하, 학력무관, 대졸↑, 초대졸↑, 고졸↑, 석사↑, 박사, 확인필요 | "대졸/대졸↑" 등 `↑` 유무를 통일, 매핑에 없는 값은 `확인필요` |
| 11 | `deadline` | 마감일 | date | Y | N | | raw.deadline 그대로 |
| 12 | `link` | 공고링크 | text | Y | N | | raw.link 그대로 |
| 13 | `crawled_at` | 수집일시 | timestamp | Y | N | | raw.crawled_at 그대로 |

### 3-3. mart.daily_posting_count (일별 공고 수)

staging.job_postings를 `수집일자 × 키워드 × 사이트`로 `GROUP BY`한 집계 테이블입니다.

| 순번 | 컬럼명 | 한글명 | 타입 | NULL | PK | 제약조건(허용값) | 설명 |
|---|---|---|---|---|---|---|---|
| 1 | `crawled_date` | 수집일자 | date | Y | N | | `crawled_at::date` |
| 2 | `keyword` | 키워드 | text | Y | N | 데이터분석, 데이터엔지니어, 데이터관리 | |
| 3 | `site` | 사이트 | text | Y | N | 사람인, 잡코리아 | |
| 4 | `posting_count` | 공고 수 | bigint | Y | N | | `count(*)` |

### 3-4. mart.location_distribution (지역별 분포)

staging.job_postings를 `키워드 × 시도`로 집계한 테이블입니다.

| 순번 | 컬럼명 | 한글명 | 타입 | NULL | PK | 제약조건(허용값) | 설명 |
|---|---|---|---|---|---|---|---|
| 1 | `keyword` | 키워드 | text | Y | N | 데이터분석, 데이터엔지니어, 데이터관리 | |
| 2 | `region_sido` | 시도 | text | Y | N | | staging.region_sido가 NULL이면 `미상`으로 대체 |
| 3 | `posting_count` | 공고 수 | bigint | Y | N | | `count(*)` |

### 3-5. mart.experience_distribution (경력별 분포)

staging.job_postings를 `키워드 × 경력구분`으로 집계한 테이블입니다.

| 순번 | 컬럼명 | 한글명 | 타입 | NULL | PK | 제약조건(허용값) | 설명 |
|---|---|---|---|---|---|---|---|
| 1 | `keyword` | 키워드 | text | Y | N | 데이터분석, 데이터엔지니어, 데이터관리 | |
| 2 | `experience_category` | 경력구분 | text | Y | N | | staging.experience_category 그대로 |
| 3 | `posting_count` | 공고 수 | bigint | Y | N | | `count(*)` |
| 4 | `avg_min_years` | 평균 최소경력(년) | numeric | Y | N | | `round(avg(experience_min_years), 1)` |

### 3-6. mart.crawl_run_log (크롤링 실행 로그)

| 순번 | 컬럼명 | 한글명 | 타입 | NULL | PK | 제약조건(허용값) | 설명 |
|---|---|---|---|---|---|---|---|
| 1 | `id` | 로그ID | integer | N | Y | | 로그 고유 식별자 |
| 2 | `run_at` | 실행일시 | timestamp | N | N | | 크롤링 실행 시각 |
| 3 | `site` | 사이트 | text | N | N | 사람인, 잡코리아 | |
| 4 | `keyword` | 키워드 | text | N | N | 데이터분석, 데이터엔지니어, 데이터관리 | |
| 5 | `raw_count` | 수집건수 | integer | N | N | | 해당 실행에서 수집한 공고 수 |
| 6 | `inserted_count` | 적재건수 | integer | N | N | | 해당 실행에서 DB에 적재된 공고 수 |

---

## 4. 설계 참고

- **FK 없음**: raw → staging은 동일 `id`로 대응되고, mart는 staging의 집계 결과입니다. 풀 리프레시 방식이라 물리적 FK를 두지 않았습니다.
- **mart 집계 테이블에는 PK가 없습니다**: `CREATE TABLE ... AS SELECT`로 생성되기 때문입니다. Django에서는 읽기 전용 unmanaged 모델로 매핑하며, 조회용이므로 기존 컬럼 하나를 `primary_key=True`로 지정해 사용합니다.
- **`확인필요` 값**: 정규화 규칙에 맞지 않는 값(크롤링 파싱 오류 등)을 따로 분류해, 전체 대비 비율이 5%를 넘으면 `transform.py`가 경고 로그를 남깁니다.
