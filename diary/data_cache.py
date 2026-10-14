"""Cache small tenant-scoped summaries, never permissions or diary records."""
from uuid import uuid4
from django.core.cache import caches
from django.db import transaction
from django.db.models import Count, Q
from django.db.models.functions import ExtractMonth
from django.utils import timezone
from .models import Office


def generation_key(kind, directorate_id):
    return f'diary-data:v1:{kind}:{directorate_id}:generation'


def cached_data(kind, directorate_id, suffix, load, timeout):
    cache = caches['diary_data']
    generation_name = generation_key(kind, directorate_id)
    generation = cache.get(generation_name)
    if generation is None:
        cache.add(generation_name, uuid4().hex, timeout=86400)
        generation = cache.get(generation_name)
    key = f'diary-data:v1:{kind}:{directorate_id}:{generation}:{suffix}'
    value = cache.get(key)
    if value is None:
        value = load()
        cache.set(key, value, timeout=timeout)
    return value


def invalidate_after_commit(kind, directorate_ids, using=None):
    # Rotate the namespace only after the change succeeds. A concurrent reader
    # cannot repopulate the new namespace using an old in-flight query result.
    for directorate_id in set(directorate_ids) - {None}:
        transaction.on_commit(lambda pk=directorate_id: caches['diary_data'].set(
            generation_key(kind, pk), uuid4().hex, timeout=86400), using=using)


def office_choices(directorate_id):
    return cached_data('offices', directorate_id, 'names', lambda: list(
        Office.objects.filter(directorate_id=directorate_id).order_by('name').values('name')), timeout=300)


def dashboard_summary(qs, directorate_id, year, today):
    def load():
        counts = dict(qs.filter(year=year).order_by().annotate(month=ExtractMonth('diary_date'))
            .values('month').annotate(count=Count('pk')).values_list('month', 'count'))
        totals = qs.aggregate(today_count=Count('pk', filter=Q(diary_date=today)),
            month_count=Count('pk', filter=Q(year=today.year, diary_date__month=today.month)))
        return {'month_counts': counts, 'total': sum(counts.values()), **totals,
            'years': list(qs.values('year').annotate(count=Count('pk')).order_by('-year'))}
    return cached_data('dashboard', directorate_id,
        f'{timezone.get_current_timezone_name()}:{today.isoformat()}:{year}', load, timeout=60)
