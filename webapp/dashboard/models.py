from django.db import models

class JobPosting(models.Model):
    """staging.job_postings"""
    id = models.IntegerField(primary_key=True)
    site = models.CharField(max_length=50)
    keyword = models.CharField(max_length=100)
    title = models.TextField(null=True)
    company = models.TextField(null=True)
    region_sido = models.CharField(max_length=50, null=True)
    region_detail = models.TextField(null=True)
    experience_category = models.CharField(max_length=50, null=True)
    experience_min_years = models.IntegerField(null=True)
    education_category = models.CharField(max_length=50, null=True)
    deadline = models.DateField(null=True)
    link = models.TextField(null=True)
    crawled_at = models.DateTimeField(null=True)

    class Meta:
        managed = False
        db_table = 'job_postings'  # search_path에 staging이 있어서 접두어 불필요


class DailyPostingCount(models.Model):
    """mart.daily_posting_count"""
    crawled_date = models.DateField(primary_key=True)
    keyword = models.CharField(max_length=100)
    site = models.CharField(max_length=50)
    posting_count = models.IntegerField()

    class Meta:
        managed = False
        db_table = 'daily_posting_count'


class LocationDistribution(models.Model):
    """mart.location_distribution"""
    keyword = models.CharField(max_length=100, primary_key=True)
    region_sido = models.CharField(max_length=50)
    posting_count = models.IntegerField()

    class Meta:
        managed = False
        db_table = 'location_distribution'


class ExperienceDistribution(models.Model):
    """mart.experience_distribution"""
    keyword = models.CharField(max_length=100, primary_key=True)
    experience_category = models.CharField(max_length=50)
    posting_count = models.IntegerField()
    avg_min_years = models.DecimalField(max_digits=5, decimal_places=1, null=True)

    class Meta:
        managed = False
        db_table = 'experience_distribution'
