from datetime import date
from django.shortcuts import render
from django.db.models import Sum
from .models import JobPosting, DailyPostingCount, LocationDistribution, ExperienceDistribution

def today_dashboard(request):
    today = date.today()

    # 오늘 수집된 원본 공고 (상세 리스트용)
    today_postings = JobPosting.objects.filter(
        crawled_at__date=today
    ).order_by('-crawled_at')

    # 오늘자 사이트/키워드별 건수
    today_counts = DailyPostingCount.objects.filter(crawled_date=today)
    total_today = today_counts.aggregate(total=Sum('posting_count'))['total'] or 0

    region_dist = LocationDistribution.objects.all()
    exp_dist = ExperienceDistribution.objects.all()

    return render(request, 'dashboard/today.html', {
        'today': today,
        'total_today': total_today,
        'today_counts': today_counts,
        'today_postings': today_postings[:100],
        'region_dist': region_dist,
        'exp_dist': exp_dist,
    })
