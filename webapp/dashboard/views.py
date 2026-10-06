from datetime import date
from django.shortcuts import render
from django.db.models import Sum
from .models import JobPosting, DailyPostingCount, LocationDistribution, ExperienceDistribution

def today_dashboard(request):
    today = date.today()

    # 오늘자 전체 (필터 옵션 구성용 + 필터 전 기준)
    today_qs = JobPosting.objects.filter(crawled_at__date=today)

    # --- 필터 값 읽기 ---
    selected_keyword = request.GET.get('keyword', '')
    selected_region = request.GET.get('region', '')
    selected_exp = request.GET.get('experience', '')

    # --- 필터 옵션 (오늘 데이터 기준 고유값) ---
    keyword_options = (
        today_qs.exclude(keyword__isnull=True)
        .values_list('keyword', flat=True).distinct().order_by('keyword')
    )
    region_options = (
        today_qs.exclude(region_sido__isnull=True)
        .values_list('region_sido', flat=True).distinct().order_by('region_sido')
    )
    exp_options = (
        today_qs.exclude(experience_category__isnull=True)
        .values_list('experience_category', flat=True).distinct().order_by('experience_category')
    )

    # --- 필터 적용 ---
    filtered_qs = today_qs
    if selected_keyword:
        filtered_qs = filtered_qs.filter(keyword=selected_keyword)
    if selected_region:
        filtered_qs = filtered_qs.filter(region_sido=selected_region)
    if selected_exp:
        filtered_qs = filtered_qs.filter(experience_category=selected_exp)

    today_postings = filtered_qs.order_by('-crawled_at')

    today_counts = DailyPostingCount.objects.filter(crawled_date=today)
    total_today = today_counts.aggregate(total=Sum('posting_count'))['total'] or 0

    region_dist = LocationDistribution.objects.all()
    exp_dist = ExperienceDistribution.objects.all()

    return render(request, 'dashboard/today.html', {
        'today': today,
        'total_today': total_today,
        'today_counts': today_counts,
        'today_postings': today_postings[:100],
        'filtered_total': filtered_qs.count(),
        'region_dist': region_dist,
        'exp_dist': exp_dist,
        'keyword_options': keyword_options,
        'region_options': region_options,
        'exp_options': exp_options,
        'selected_keyword': selected_keyword,
        'selected_region': selected_region,
        'selected_exp': selected_exp,
    })