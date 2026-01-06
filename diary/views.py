from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import DiaryCreateForm, MovementCreateForm
from .models import Diary, DiaryMovement


@login_required
def diary_list(request):
    q = (request.GET.get("q") or "").strip()
    year = (request.GET.get("year") or "").strip()

    qs = Diary.objects.all()

    if year.isdigit():
        qs = qs.filter(year=int(year))

    if q:
        # support: "2026-123" OR "123" OR text
        if "-" in q:
            y, s = q.split("-", 1)
            if y.isdigit() and s.isdigit():
                qs = qs.filter(year=int(y), sequence=int(s))
            else:
                qs = qs.filter(
                    Q(subject__icontains=q)
                    | Q(received_from__icontains=q)
                    | Q(received_diary_no__icontains=q)
                    | Q(marked_to__icontains=q)
                )
        elif q.isdigit():
            qs = qs.filter(sequence=int(q))  # across all years
        else:
            qs = qs.filter(
                Q(subject__icontains=q)
                | Q(received_from__icontains=q)
                | Q(received_diary_no__icontains=q)
                | Q(marked_to__icontains=q)
            )

    return render(request, "diary/diary_list.html", {"diaries": qs[:500], "q": q, "year": year})


@login_required
def diary_create(request):
    if request.method == "POST":
        form = DiaryCreateForm(request.POST)
        if form.is_valid():
            diary = Diary.create_with_next_number(created_by=request.user, **form.cleaned_data)

            # Create first movement automatically (Created)
            DiaryMovement.objects.create(
                diary=diary,
                year=diary.year,
                sequence=diary.sequence,
                from_office=diary.received_from or "Registry",
                to_office=diary.received_from or "Registry",
                action_type="Created",
                action_datetime=timezone.now(),
                remarks="Initial diary created",
                created_by=request.user,
            )

            # snapshot update
            diary.status = "Created"
            diary.marked_to = diary.received_from or "Registry"
            diary.marked_date = timezone.localdate()
            diary.save(update_fields=["status", "marked_to", "marked_date"])

            return redirect("diary_detail", pk=diary.pk)
    else:
        form = DiaryCreateForm()

    return render(request, "diary/diary_create.html", {"form": form})


@login_required
def diary_detail(request, pk: int):
    diary = get_object_or_404(Diary, pk=pk)
    movements = diary.movements.all()
    return render(request, "diary/diary_detail.html", {"diary": diary, "movements": movements})


@login_required
def movement_add(request, pk: int):
    diary = get_object_or_404(Diary, pk=pk)

    last = diary.movements.order_by("-action_datetime", "-id").first()
    default_from = (last.to_office if last else diary.received_from) or "Registry"

    if request.method == "POST":
        form = MovementCreateForm(request.POST)
        if form.is_valid():
            mv = form.save(commit=False)
            mv.diary = diary
            mv.year = diary.year
            mv.sequence = diary.sequence
            mv.created_by = request.user
            mv.save()

            # update snapshot
            diary.marked_to = mv.to_office
            diary.marked_date = timezone.localdate()
            diary.status = mv.action_type
            diary.save(update_fields=["marked_to", "marked_date", "status"])

            return redirect("diary_detail", pk=diary.pk)
    else:
        form = MovementCreateForm(initial={"from_office": default_from, "action_type": "Marked"})

    return render(request, "diary/movement_add.html", {"form": form, "diary": diary})
