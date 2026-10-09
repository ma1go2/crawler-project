# ERD

> 테이블 간 물리적 FK 제약은 없습니다. 점선은 변환·집계에 따른 **논리적 관계**를 나타냅니다.

```mermaid
erDiagram
    RAW_JOB_POSTINGS {
        int id PK "공고ID"
        text site "사이트"
        text keyword "키워드"
        text title "공고제목"
        text company "회사명"
        text location "근무지역"
        text experience "경력"
        text education "학력"
        date deadline "마감일"
        text link "공고링크"
        timestamp crawled_at "수집일시"
    }

    STAGING_JOB_POSTINGS {
        int id PK "공고ID"
        text site "사이트"
        text keyword "키워드"
        text title "공고제목"
        text company "회사명"
        text region_sido "시도"
        text region_detail "상세지역"
        text experience_category "경력구분"
        int experience_min_years "최소경력(년)"
        text education_category "학력구분"
        date deadline "마감일"
        text link "공고링크"
        timestamp crawled_at "수집일시"
    }

    MART_DAILY_POSTING_COUNT {
        date crawled_date "수집일자"
        text keyword "키워드"
        text site "사이트"
        bigint posting_count "공고 수"
    }

    MART_LOCATION_DISTRIBUTION {
        text keyword "키워드"
        text region_sido "시도"
        bigint posting_count "공고 수"
    }

    MART_EXPERIENCE_DISTRIBUTION {
        text keyword "키워드"
        text experience_category "경력구분"
        bigint posting_count "공고 수"
        numeric avg_min_years "평균 최소경력(년)"
    }

    MART_CRAWL_RUN_LOG {
        int id PK "로그ID"
        timestamp run_at "실행일시"
        text site "사이트"
        text keyword "키워드"
        int raw_count "수집건수"
        int inserted_count "적재건수"
    }

    RAW_JOB_POSTINGS ||..|| STAGING_JOB_POSTINGS : "정규화 (id 동일)"
    MART_DAILY_POSTING_COUNT ||..|{ STAGING_JOB_POSTINGS : "일자·키워드·사이트별 집계"
    MART_LOCATION_DISTRIBUTION ||..|{ STAGING_JOB_POSTINGS : "키워드·시도별 집계"
    MART_EXPERIENCE_DISTRIBUTION ||..|{ STAGING_JOB_POSTINGS : "키워드·경력구분별 집계"
    MART_CRAWL_RUN_LOG ||..o{ RAW_JOB_POSTINGS : "실행 이력 (site·keyword 기준)"
```

## 읽는 방법

| 구분 | 엔티티 | 스키마 |
|---|---|---|
| 원본 | `RAW_JOB_POSTINGS` | raw |
| 정제 | `STAGING_JOB_POSTINGS` | staging |
| 집계 | `MART_DAILY_POSTING_COUNT`, `MART_LOCATION_DISTRIBUTION`, `MART_EXPERIENCE_DISTRIBUTION` | mart |
| 이력 | `MART_CRAWL_RUN_LOG` | mart |

- **raw → staging**: 같은 `id`로 1:1 대응합니다. staging은 매번 raw 전체를 읽어 다시 만듭니다.
- **staging → mart**: mart의 한 행은 staging의 여러 행을 집계한 결과입니다.
- **mart 집계 테이블에 PK가 없는 이유**: `CREATE TABLE ... AS SELECT`로 생성하기 때문입니다.
- 컬럼별 상세 정의는 [데이터 항목 정의서](./data-dictionary.md)를 참고하세요.
