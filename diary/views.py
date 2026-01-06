from __future__ import annotations

import re

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import DiaryCreateForm, MovementCreateForm
from .models import Diary, DiaryMovement


DIARYNO_RE = re.compile(r"^\s*(\d{4})\s*-\s*(\d+)\s*$")  # 2026-12


@login_required
def diary_list(request):
    q = (request.GET.get("q") or "").strip()
    year = (request.GET.get("year") or "").strip()
    status = (request.GET.get("status") or "").strip()

    # ---- create (modal POST) ----
    create_form = DiaryCreateForm()
    if request.method == "POST":
        create_form = DiaryCreateForm(request.POST)
        if create_form.is_valid():
            diary = Diary.create_with_next_number(created_by=request.user, **create_form.cleaned_data)

            DiaryMovement.objects.create(
                diary=diary,
                from_office=diary.received_from or "Registry",
                to_office=diary.received_from or "Registry",
                action_type=DiaryMovement.ActionType.CREATED,
                action_datetime=timezone.now(),
                remarks="Initial diary created",
                created_by=request.user,
            )

            diary.status = Diary.Status.CREATED
            diary.marked_date = timezone.localdate()
            diary.save(update_fields=["status", "marked_date"])

            messages.success(request, f"Diary created: {diary.diary_no}")
            return redirect("diary_detail", pk=diary.pk)

        messages.error(request, "Please correct the errors in the form below.")

    # ---- listing + filtering ----
    qs = Diary.objects.all()

    if year.isdigit():
        qs = qs.filter(year=int(year))

    if status:
        qs = qs.filter(status=status)

    if q:
        m = DIARYNO_RE.match(q)
        if m:
            y = int(m.group(1))
            s = int(m.group(2))
            qs = qs.filter(year=y, sequence=s)
        elif q.isdigit():
            qs = qs.filter(sequence=int(q))
        else:
            qs = qs.filter(
                Q(subject__icontains=q)
                | Q(received_from__icontains=q)
                | Q(received_diary_no__icontains=q)
                | Q(file_letter__icontains=q)
                | Q(marked_to__icontains=q)
                | Q(remarks__icontains=q)
            )

    # sequence-wise display (year desc, sequence asc)
    qs = qs.order_by("-year", "sequence")

    paginator = Paginator(qs, 25)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    return render(
        request,
        "diary/diary_list.html",
        {
            "page_obj": page_obj,
            "q": q,
            "year": year,
            "status": status,
            "status_choices": Diary.Status.choices,
            "create_form": create_form,
        },
    )


@login_required
def diary_create(request):
    # (Optional) keep this view working if you still want /new/
    if request.method == "POST":
        form = DiaryCreateForm(request.POST)
        if form.is_valid():
            diary = Diary.create_with_next_number(created_by=request.user, **form.cleaned_data)

            DiaryMovement.objects.create(
                diary=diary,
                from_office=diary.received_from or "Registry",
                to_office=diary.received_from or "Registry",
                action_type=DiaryMovement.ActionType.CREATED,
                action_datetime=timezone.now(),
                remarks="Initial diary created",
                created_by=request.user,
            )

            diary.status = Diary.Status.CREATED
            diary.marked_date = timezone.localdate()
            diary.save(update_fields=["status", "marked_date"])

            messages.success(request, f"Diary created: {diary.diary_no}")
            return redirect("diary_detail", pk=diary.pk)

        messages.error(request, "Please correct the errors below.")
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
            mv.created_by = request.user
            mv.save()

            diary.marked_to = mv.to_office
            diary.marked_date = timezone.localdate()
            diary.status = mv.action_type
            diary.save(update_fields=["marked_to", "marked_date", "status"])

            messages.success(request, "Movement added successfully.")
            return redirect("diary_detail", pk=diary.pk)

        messages.error(request, "Please correct the errors below.")
    else:
        form = MovementCreateForm(
            initial={
                "from_office": default_from,
                "action_type": DiaryMovement.ActionType.MARKED,
                "action_datetime": timezone.localtime(timezone.now()).replace(second=0, microsecond=0),
            }
        )

    return render(request, "diary/movement_add.html", {"form": form, "diary": diary})
