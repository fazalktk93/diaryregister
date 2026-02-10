from __future__ import annotations

import re

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, Max, Prefetch, Count
from django.db.models.functions import ExtractMonth
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.http import JsonResponse
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.utils import timezone
import io
from django.http import HttpResponse
from django.http import HttpResponse, StreamingHttpResponse
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Flowable, Image
from reportlab.pdfgen.canvas import Canvas

from django.conf import settings

from .forms import DiaryCreateForm, MovementCreateForm
from .models import Diary, DiaryMovement, Office


DIARYNO_RE = re.compile(r"^\s*(\d{4})\s*-\s*(\d+)\s*$")  # 2026-12


def create_diary_with_movement(diary_data: dict, created_by, initial_remarks: str = "Initial diary created") -> Diary:
    """
    Helper function to create a diary and its initial movement record.
    Prevents code duplication across views.
    
    Args:
        diary_data: Cleaned form data dictionary
        created_by: User instance who is creating the diary
        initial_remarks: Optional remarks for the initial movement
    
    Returns:
        Created Diary instance with status CREATED and initial movement
    """
    diary = Diary.create_with_next_number(created_by=created_by, **diary_data)

    DiaryMovement.objects.create(
        diary=diary,
        from_office=diary.received_from or settings.DEFAULT_OFFICE_NAME,
        to_office=diary.marked_to or (diary.received_from or settings.DEFAULT_OFFICE_NAME),
        action_type=DiaryMovement.ActionType.CREATED,
        action_datetime=timezone.now(),
        remarks=initial_remarks,
        created_by=created_by,
    )

    diary.status = Diary.Status.CREATED
    diary.marked_date = timezone.localdate()
    diary.save(update_fields=["status", "marked_date"])

    return diary


@login_required
def diary_list(request):
    """Display list of diaries with filtering and search. Allows creating new diaries via modal."""
    q = (request.GET.get("q") or "").strip()
    year = (request.GET.get("year") or "").strip()
    status = (request.GET.get("status") or "").strip()

    # ---- create (modal POST) ----
    is_admin = request.user.is_superuser or request.user.groups.filter(name="admin").exists()
    create_form = DiaryCreateForm()
    if request.method == "POST":
        create_form = DiaryCreateForm(request.POST)
        if create_form.is_valid():
            diary = create_diary_with_movement(dict(create_form.cleaned_data), request.user)
            messages.success(request, f"Diary created: {diary.diary_no}")
            # Stay on the listing page after create; preserve any query params
            qs = request.GET.urlencode()
            if qs:
                return redirect(f"{request.path}?{qs}")
            return redirect("diary_list")

        messages.error(request, "Please correct the errors in the form below.")

    # ---- listing + filtering ----
    qs = (
        Diary.objects.all()
        # Prefetch movements ordered newest-first so we can cheaply access last remarks
        .prefetch_related(Prefetch("movements", queryset=DiaryMovement.objects.order_by("-action_datetime", "-id")))
    )

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

    # show diaries in sequential order: year asc, sequence asc (1,2,3...)
    qs = qs.order_by("-diary_date", "-sequence")

    paginator = Paginator(qs, settings.DEFAULT_PAGE_SIZE)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    # Attach a lightweight `current_remarks` attribute on each diary for the template.
    # Prefer `diary.remarks` if present, otherwise use the most recent movement's remarks.
    for d in page_obj.object_list:
        # `movements` was prefetched ordered newest-first, so first element (index 0) is latest
        mvs = list(getattr(d, "movements").all()) if hasattr(d, "movements") else []
        last_mv = mvs[0] if mvs else None
        last_movement_remarks = (last_mv.remarks or "") if last_mv else ""
        d.current_remarks = (d.remarks or "") or last_movement_remarks

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
            "can_view_sensitive": is_admin,
        },
    )


@login_required
def diary_create(request):
    """Create a new diary. Can be accessed directly or from modal on diary_list."""
    is_admin = request.user.is_superuser or request.user.groups.filter(name="admin").exists()
    if request.method == "POST":
        form = DiaryCreateForm(request.POST)
        if form.is_valid():
            diary = create_diary_with_movement(dict(form.cleaned_data), request.user)
            messages.success(request, f"Diary created: {diary.diary_no}")
            # After creation when coming from a create page, return to listing
            return redirect("diary_list")

        messages.error(request, "Please correct the errors below.")
    else:
        form = DiaryCreateForm()

    return render(request, "diary/diary_create.html", {"form": form})


@login_required
def diary_detail(request, pk: int):
    """Display detailed view of a single diary with its movement history."""
    diary = get_object_or_404(Diary, pk=pk)
    movements = diary.movements.all().order_by("action_datetime", "id")
    # Provide last movement remarks as a fallback when diary.remarks is empty
    last_movement = diary.movements.order_by("-action_datetime", "-id").first()
    last_movement_remarks = (last_movement.remarks or "") if last_movement else ""
    # Only admin group (or superuser) can view creator/updater sensitive fields
    is_admin = request.user.is_superuser or request.user.groups.filter(name="admin").exists()
    return render(
        request,
        "diary/diary_detail.html",
        {
            "diary": diary,
            "movements": movements,
            "can_view_sensitive": is_admin,
            "last_movement_remarks": last_movement_remarks,
        },
    )

@login_required
def reports_home(request):
    years = list(
        Diary.objects.values_list("year", flat=True)
        .distinct()
        .order_by("-year")
    )
    latest_year = years[0] if years else None

    # allow quick open by ?year=2026
    y = (request.GET.get("year") or "").strip()
    if y.isdigit() and len(y) == 4:
        return redirect("diary_year_report", year=int(y))

    return render(request, "diary/reports_home.html", {"years": years, "latest_year": latest_year})


@login_required
def movement_add(request, pk: int):
    """Add a movement record to a diary, updating its status and current location."""
    diary = get_object_or_404(Diary, pk=pk)

    last = diary.movements.order_by("-action_datetime", "-id").first()
    default_from = (last.to_office if last else diary.received_from) or settings.DEFAULT_OFFICE_NAME

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
            # If this was an AJAX request, return JSON so frontend can close modal
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                return JsonResponse({"success": True})

            return redirect("diary_detail", pk=diary.pk)

        # On validation error, return partial HTML for AJAX consumers
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            html = render_to_string("diary/_movement_form.html", {"form": form, "diary": diary, "offices": Office.objects.values_list("name", flat=True).order_by("name")}, request=request)
            return JsonResponse({"success": False, "html": html})
        messages.error(request, "Please correct the errors below.")
    else:
        form = MovementCreateForm(
            initial={
                "from_office": default_from,
                "action_type": DiaryMovement.ActionType.MARKED,
                "action_datetime": timezone.localtime(timezone.now()).replace(second=0, microsecond=0),
            }
        )

        # If AJAX GET, return only the form fragment
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            html = render_to_string("diary/_movement_form.html", {"form": form, "diary": diary, "offices": Office.objects.values_list("name", flat=True).order_by("name")}, request=request)
            return JsonResponse({"success": True, "html": html})

    # Pass offices for autocomplete datalist
    offices = Office.objects.values_list("name", flat=True).order_by("name")
    return render(request, "diary/movement_add.html", {"form": form, "diary": diary, "offices": offices})


@login_required
def diary_edit(request, pk: int):
    """Edit an existing diary (admin only)."""
    is_admin = request.user.is_superuser or request.user.groups.filter(name="admin").exists()
    if not is_admin:
        messages.error(request, "Only admins can edit diaries.")
        return redirect("diary_detail", pk=pk)
    
    diary = get_object_or_404(Diary, pk=pk)
    
    if request.method == "POST":
        form = DiaryCreateForm(request.POST)
        if form.is_valid():
            # Update diary fields from cleaned form data
            diary.diary_date = form.cleaned_data["diary_date"]
            diary.received_diary_no = form.cleaned_data.get("received_diary_no", "")
            diary.received_from = form.cleaned_data.get("received_from", "")
            diary.file_letter = form.cleaned_data.get("file_letter", "")
            diary.no_of_folders = form.cleaned_data.get("no_of_folders", 0)
            diary.subject = form.cleaned_data.get("subject", "")
            diary.remarks = form.cleaned_data.get("remarks", "")
            diary.marked_to = form.cleaned_data.get("marked_to", "")
            diary.save()
            
            messages.success(request, f"Diary {diary.diary_no} updated successfully.")
            return redirect("diary_detail", pk=diary.pk)
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = DiaryCreateForm(initial={
            "diary_date": diary.diary_date,
            "received_diary_no": diary.received_diary_no,
            "received_from": diary.received_from,
            "file_letter": diary.file_letter,
            "no_of_folders": diary.no_of_folders,
            "subject": diary.subject,
            "remarks": diary.remarks,
            "marked_to": diary.marked_to,
        })
    
    return render(request, "diary/diary_edit.html", {"form": form, "diary": diary})


@login_required
def diary_delete(request, pk: int):
    """Delete a diary (admin only)."""
    is_admin = request.user.is_superuser or request.user.groups.filter(name="admin").exists()
    if not is_admin:
        messages.error(request, "Only admins can delete diaries.")
        return redirect("diary_detail", pk=pk)
    
    diary = get_object_or_404(Diary, pk=pk)
    
    if request.method == "POST":
        diary_no = diary.diary_no
        diary.delete()
        messages.success(request, f"Diary {diary_no} deleted successfully.")
        return redirect("diary_list")
    
    return redirect("diary_detail", pk=pk)


@login_required
def reports_table(request):
    """
    Reports page with per-column filters for detailed diary analysis.
    Uses pagination and prefetch to stay performant.
    """
    year = (request.GET.get("year") or "").strip()

    f_diary_no = (request.GET.get("diary_no") or "").strip()
    f_received_diary_no = (request.GET.get("received_diary_no") or "").strip()
    f_received_from = (request.GET.get("received_from") or "").strip()
    f_file_letter = (request.GET.get("file_letter") or "").strip()
    f_no_of_folders = (request.GET.get("no_of_folders") or "").strip()
    f_subject = (request.GET.get("subject") or "").strip()
    f_remarks = (request.GET.get("remarks") or "").strip()
    f_status = (request.GET.get("status") or "").strip()
    f_marked_to = (request.GET.get("marked_to") or "").strip()

    qs = (
        Diary.objects.all()
        .only(
            "id", "year", "sequence", "diary_date",
            "received_diary_no", "received_from",
            "file_letter", "no_of_folders",
            "subject", "remarks", "status", "marked_to"
        )
        # Prefetch movements with explicit ordering to avoid N+1 queries when
        # code accesses d.movements.order_by(...) or iterates in order.
        .prefetch_related(Prefetch("movements", queryset=DiaryMovement.objects.order_by("action_datetime", "id")))
    ).exclude(sequence=0)

    if year.isdigit() and len(year) == 4:
        qs = qs.filter(year=int(year))

    # diary_no supports "2026-000012" or "2026-12" etc.
    if f_diary_no:
        m = DIARYNO_RE.match(f_diary_no)
        if m:
            y = int(m.group(1))
            s = int(m.group(2))
            qs = qs.filter(year=y, sequence=s)
        else:
            # fallback search
            qs = qs.filter(
                Q(year__icontains=f_diary_no) | Q(sequence__icontains=f_diary_no)
            )

    if f_received_diary_no:
        qs = qs.filter(received_diary_no__icontains=f_received_diary_no)

    if f_received_from:
        qs = qs.filter(received_from__icontains=f_received_from)

    if f_file_letter:
        qs = qs.filter(file_letter__icontains=f_file_letter)

    if f_no_of_folders.isdigit():
        qs = qs.filter(no_of_folders=int(f_no_of_folders))

    if f_subject:
        qs = qs.filter(subject__icontains=f_subject)

    if f_remarks:
        qs = qs.filter(remarks__icontains=f_remarks)

    if f_status:
        qs = qs.filter(status=f_status)

    if f_marked_to:
        qs = qs.filter(marked_to__icontains=f_marked_to)

    # keep reports newest-first in the web UI (so report page shows latest on top)
    qs = qs.order_by("-year", "-sequence")

    paginator = Paginator(qs, settings.DEFAULT_PAGE_SIZE)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    return render(
        request,
        "diary/reports_table.html",
        {
            "page_obj": page_obj,
            "status_choices": Diary.Status.choices,
            "filters": {
                "year": year,
                "diary_no": f_diary_no,
                "received_diary_no": f_received_diary_no,
                "received_from": f_received_from,
                "file_letter": f_file_letter,
                "no_of_folders": f_no_of_folders,
                "subject": f_subject,
                "remarks": f_remarks,
                "status": f_status,
                "marked_to": f_marked_to,
            },
            "can_view_sensitive": request.user.is_superuser or request.user.groups.filter(name="admin").exists(),
        },
    )


@login_required
def reports_pdf(request, year: int):
    """
    Generate Year PDF report in a new tab.
    Includes movement history with deduplication for cleaner register-style output.
    Adds page numbers and optional watermark branding.
    """
    # Only admin group (or superusers) may download the PDF
    is_admin = request.user.is_superuser or request.user.groups.filter(name="admin").exists()
    if not is_admin:
        return HttpResponse(status=403)

    qs = (
        Diary.objects.filter(year=year)
        .only(
            "id", "year", "sequence", "diary_date",
            "received_diary_no", "received_from",
            "file_letter", "no_of_folders",
            "subject", "remarks", "status", "marked_to"
        )
        # Prefetch ordered movements to avoid per-diary queries in PDF generation
        .prefetch_related(Prefetch("movements", queryset=DiaryMovement.objects.order_by("action_datetime", "id")))
        .exclude(sequence=0)
        .order_by("sequence")
    )

    buf = io.BytesIO()
    # Use an 'oficio' like page size (8.5 x 13 in) in landscape to give more width
    oficio_size = (8.5 * inch, 13 * inch)
    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(oficio_size),
        leftMargin=18,
        rightMargin=18,
        topMargin=18,
        bottomMargin=18,
        title=f"Diary Register Report {year}",
    )

    styles = getSampleStyleSheet()
    normal = styles["Normal"]
    normal.fontSize = 8
    normal.leading = 10

    title = Paragraph(f"<b>Diary Record of Administration Directorate year {year}</b>", styles["Title"])
    story = []

    # Add logo on first page (left-aligned) using the same static image
    try:
        from pathlib import Path
        logo_path = Path(__file__).resolve().parent.parent / "static" / "diary" / "logo.png"
        if logo_path.exists():
            # scale logo to fit left side without overlapping; keep height ~0.6 inch
            logo = Image(str(logo_path), width=1.5 * inch, height=0.6 * inch)
            logo.hAlign = "LEFT"
            story.append(logo)
            story.append(Spacer(1, 6))
    except Exception:
        pass

    story.append(title)
    story.append(Spacer(1, 10))

    # PDF: omit Remarks and Status columns for a compact register-style export
    # PDF: header label rename: History -> Movement
    data = [
        ["Diary No", "Date", "Rcvd No", "Rcvd From", "File/Letter", "Folders", "Subject", "Movement"]
    ]

    for d in qs:
        # Build history for PDF: deduplicate consecutive movements
        mvs = list(d.movements.all())
        mvs = sorted(mvs, key=lambda mv: (mv.action_datetime, mv.id))
        if not mvs:
            history_flowable = Paragraph("-", normal)
        else:
            # Deduplicate consecutive entries
            deduped = []
            prev_txt = None
            for mv in mvs:
                dt = timezone.localtime(mv.action_datetime).date().strftime("%d-%m")
                to_office = (mv.to_office or '-')
                txt = f"{to_office} {dt}"
                if txt != prev_txt:
                    deduped.append(txt)
                    prev_txt = txt
            
            history_text = " / ".join(deduped)
            history_flowable = Paragraph(history_text, normal)

        # Folder display: only show number for File or Service Book, otherwise '-'
        folders_display = str(d.no_of_folders) if (d.file_letter in ("File", "Service Book") and (d.no_of_folders or 0) > 0) else "-"
        data.append([
            str(d.sequence),
            d.diary_date.strftime("%d-%m-%Y") if d.diary_date else "-",
            Paragraph((d.received_diary_no or "-").replace("\n", "<br/>"), normal),
            Paragraph((d.received_from or "-").replace("\n", "<br/>"), normal),
            d.file_letter or "-",
            folders_display,
            Paragraph((d.subject or "-").replace("\n", "<br/>"), normal),
            history_flowable,
        ])

    # Helper canvas maker to insert page numbers "Page X of Y" in the footer
    class NumberedCanvas(Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._saved_page_states = []

        def showPage(self):
            # Save state for later when we'll draw page numbers, but do not
            # start a new real page here (that will be done in save()).
            self._saved_page_states.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            # Add page info to each saved page and then save
            num_pages = len(self._saved_page_states)
            for state in self._saved_page_states:
                self.__dict__.update(state)
                self._draw_page_number(num_pages)
                super().showPage()
            super().save()

        def _draw_page_number(self, page_count):
            try:
                from pathlib import Path
                
                self.setFont("Helvetica", 8)
                w = self._pagesize[0]
                h = self._pagesize[1]
                # Draw right-aligned page number at bottom-right
                x = w - 36
                y = 12
                self.drawRightString(x, y, f"Page {self._pageNumber} of {page_count}")

                # Watermark removed per requirements; no background drawing here.
            except Exception:
                pass

    class StrikeThroughHistory(Flowable):
        """Flowable that draws a history line with strike-through for older entries.

        Expects `entries` as a list of (text, is_last) where is_last is True for
        the most recent entry. Older entries are drawn and a strike line is
        rendered across them.
        """
        def __init__(self, entries, fontName="Helvetica", fontSize=8, sep=" / "):
            super().__init__()
            self.entries = entries
            self.fontName = fontName
            self.fontSize = fontSize
            self.sep = sep

        def wrap(self, availWidth, availHeight):
            # compute width and height required
            from reportlab.pdfbase.pdfmetrics import stringWidth

            widths = []
            total_w = 0
            for text, is_last in self.entries:
                w = stringWidth(text, self.fontName, self.fontSize)
                widths.append(w)
                total_w += w
            # add separators width
            sep_w = stringWidth(self.sep, self.fontName, self.fontSize)
            total_w += sep_w * (max(0, len(self.entries) - 1))

            # single line height (fontSize + small padding)
            height = int(self.fontSize * 1.4)
            self._calculated_width = min(availWidth, total_w)
            self._calculated_height = height
            return (self._calculated_width, self._calculated_height)

        def draw(self):
            c = self.canv
            x = 0
            y = 0
            c.setFont(self.fontName, self.fontSize)
            for i, (text, is_last) in enumerate(self.entries):
                # Draw text
                c.drawString(x, y, text)
                w = c.stringWidth(text, self.fontName, self.fontSize)
                # If not last, draw strike-through line across the text
                if not is_last:
                    # compute vertical position roughly centered over text
                    descent = self.fontSize * 0.15
                    y_line = y + self.fontSize * 0.35
                    c.setLineWidth(0.7)
                    c.setStrokeColorRGB(0.5, 0.5, 0.5)
                    c.line(x, y_line, x + w, y_line)
                    c.setStrokeColorRGB(0, 0, 0)
                x += w
                # add separator if not last
                if i != len(self.entries) - 1:
                    c.drawString(x, y, self.sep)
                    x += c.stringWidth(self.sep, self.fontName, self.fontSize)
    # Do NOT append rows again here — it duplicates the PDF output.

    table = Table(
        data,
        repeatRows=1,
        # Adjusted widths for oficio-landscape and fewer columns
        colWidths=[60, 50, 45, 80, 60, 40, 240, 320],
    )
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.black),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.whitesmoke, colors.lightgrey]),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))

    story.append(table)
    # Use our NumberedCanvas so the PDF has a footer 'Page X of Y'
    doc.build(story, canvasmaker=NumberedCanvas)

    pdf = buf.getvalue()
    buf.close()

    resp = HttpResponse(pdf, content_type="application/pdf")
    resp["Content-Disposition"] = f'inline; filename="diary-report-{year}.pdf"'
    return resp


def _build_pdf_data_for_year(year):
    """
    Helper for testing: build the PDF table data without rendering the PDF.
    Returns the data list (header + rows).
    """
    qs = (
        Diary.objects.filter(year=year)
        .only(
            "id", "year", "sequence", "diary_date",
            "received_diary_no", "received_from",
            "file_letter", "no_of_folders",
            "subject", "remarks", "status", "marked_to"
        )
        .prefetch_related(Prefetch("movements", queryset=DiaryMovement.objects.order_by("action_datetime", "id")))
        .exclude(sequence=0)
        .order_by("sequence")
    )

    styles = getSampleStyleSheet()
    normal = styles["Normal"]
    normal.fontSize = 8
    normal.leading = 10

    data = [
        ["Diary No", "Date", "Rcvd No", "Rcvd From", "File/Letter", "Folders", "Subject", "Movement"]
    ]

    for d in qs:
        # Include all movements for testable PDF data (deduplicated)
        mvs = list(d.movements.all())
        mvs = sorted(mvs, key=lambda mv: (mv.action_datetime, mv.id))
        if not mvs:
            history_text = "-"
        else:
            # Deduplicate consecutive entries
            deduped = []
            prev_txt = None
            for mv in mvs:
                dt = timezone.localtime(mv.action_datetime).date().strftime("%d-%m")
                to_office = (mv.to_office or '-')
                txt = f"{to_office} {dt}"
                if txt != prev_txt:
                    deduped.append(txt)
                    prev_txt = txt
            
            history_text = " / ".join(deduped)

        folders_display = str(d.no_of_folders) if (d.file_letter in ("File", "Service Book") and (d.no_of_folders or 0) > 0) else "-"
        data.append([
            str(d.sequence),
            d.diary_date.strftime("%d-%m-%Y") if d.diary_date else "-",
            Paragraph((d.received_diary_no or "-").replace("\n", "<br/>"), normal),
            Paragraph((d.received_from or "-").replace("\n", "<br/>"), normal),
            d.file_letter or "-",
            folders_display,
            Paragraph((d.subject or "-").replace("\n", "<br/>"), normal),
            Paragraph(history_text, normal),
        ])

    return data


def _csv_rows_for_year(year):
    qs = (
        Diary.objects.filter(year=year)
        .only("year", "sequence", "diary_date", "received_diary_no", "received_from", "file_letter", "no_of_folders", "subject", "remarks", "status", "marked_to")
        .prefetch_related(Prefetch("movements", queryset=DiaryMovement.objects.order_by("action_datetime", "id")))
        .exclude(sequence=0)
        .order_by("-sequence")
    )

    # header
    yield ["Diary No", "Date", "Rcvd No", "Rcvd From", "File/Letter", "Folders", "Subject", "Remarks", "Status", "History"]

    for d in qs:
        # Exclude CREATED and MARKED from CSV history; deduplicate and mark old destinations
        mvs = [mv for mv in d.movements.all() if mv.action_type not in (DiaryMovement.ActionType.CREATED, DiaryMovement.ActionType.MARKED)]
        mvs = sorted(mvs, key=lambda mv: (mv.action_datetime, mv.id))
        if not mvs:
            history = "-"
        else:
            # Deduplicate consecutive entries
            deduped = []
            prev_txt = None
            for mv in mvs:
                dt = timezone.localtime(mv.action_datetime).date().strftime("%d-%m")
                to_office = (mv.to_office or '-')
                txt = f"{to_office} {dt}"
                if txt != prev_txt:
                    deduped.append(txt)
                    prev_txt = txt
            
            history = " / ".join(deduped)

        folders_display = str(d.no_of_folders) if (d.file_letter in ("File", "Service Book") and (d.no_of_folders or 0) > 0) else "-"
        yield [
            d.diary_no_short,
            str(d.diary_date),
            d.received_diary_no or "-",
            d.received_from or "-",
            d.file_letter or "-",
            folders_display,
            (d.subject or "-").replace("\n", " "),
            (d.remarks or "-").replace("\n", " "),
            d.get_status_display() if hasattr(d, "get_status_display") else (d.status or "-"),
            history,
        ]


def reports_csv(request, year: int):
    import csv
    import io

    filename = f"diary-register-{year}.csv"

    def stream():
        for row in _csv_rows_for_year(year):
            buf = io.StringIO()
            writer = csv.writer(buf)
            writer.writerow(row)
            yield buf.getvalue()

    resp = StreamingHttpResponse(stream(), content_type="text/csv")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


@login_required
def diary_year_report(request, year: int):
    """End-of-year report: one row per diary, with movement history in a single column."""
    qs = (
        Diary.objects.filter(year=year)
        .select_related("created_by")
        .prefetch_related(Prefetch("movements", queryset=DiaryMovement.objects.order_by("action_datetime", "id")))
        .exclude(sequence=0)
        .order_by("-sequence")
    )

    return render(
        request,
        "diary/year_report.html",
        {
            "year": year,
            "diaries": qs,
        },
    )


@login_required
def dashboard(request):
    """Dashboard main page showing month-wise counts for the current year and quick actions."""
    # ---- create (modal POST) ----
    is_admin = request.user.is_superuser or request.user.groups.filter(name="admin").exists()
    create_form = DiaryCreateForm()
    if request.method == "POST":
        create_form = DiaryCreateForm(request.POST)
        if create_form.is_valid():
            diary = create_diary_with_movement(dict(create_form.cleaned_data), request.user)
            messages.success(request, f"Diary created: {diary.diary_no}")
            return redirect("diary_detail", pk=diary.pk)

        messages.error(request, "Please correct the errors in the form below.")
    today = timezone.localdate()
    year = request.GET.get("year") or str(today.year)
    try:
        year_i = int(year)
    except Exception:
        year_i = today.year

    # Year-wise totals
    years_qs = (
        Diary.objects.values("year")
        .annotate(count=Count("id"))
        .order_by("-year")
    )

    years = [ {"year": r["year"], "count": r["count"]} for r in years_qs ]

    # Month-wise counts for selected year
    month_qs = (
        Diary.objects.filter(year=year_i)
        .annotate(month=ExtractMonth("diary_date"))
        .values("month")
        .annotate(count=Count("id"))
        .order_by("month")
    )

    months = {m: 0 for m in range(1, 13)}
    for row in month_qs:
        months[row["month"]] = row["count"]

    # Build months list with names for template
    import calendar
    months_list = []
    for i in range(1, 13):
        months_list.append({"month": i, "name": calendar.month_name[i], "count": months.get(i, 0)})

    return render(request, "diary/dashboard.html", {"year": year_i, "months": months_list, "years": years, "create_form": create_form, "can_view_sensitive": is_admin})


@login_required
def dashboard_data(request, year: int):
    """Return JSON data for dashboard for a given year (and optional month).
    Used by AJAX to update dashboard without navigation.
    """
    try:
        year_i = int(year)
    except Exception:
        return JsonResponse({"error": "invalid year"}, status=400)

    # Month-wise counts for selected year
    from django.db.models.functions import ExtractMonth
    from django.db.models import Count
    month_qs = (
        Diary.objects.filter(year=year_i)
        .annotate(month=ExtractMonth("diary_date"))
        .values("month")
        .annotate(count=Count("id"))
        .order_by("month")
    )

    months = {m: 0 for m in range(1, 13)}
    for row in month_qs:
        months[row["month"]] = row["count"]

    import calendar
    months_list = []
    for i in range(1, 13):
        months_list.append({"month": i, "name": calendar.month_name[i], "count": months.get(i, 0)})

    total = sum(m["count"] for m in months_list)

    # If month param provided, return simple diary count for that month
    month = request.GET.get("month")
    month_count = None
    if month and month.isdigit():
        m_i = int(month)
        month_count = Diary.objects.filter(year=year_i, diary_date__month=m_i).count()

    return JsonResponse({"year": year_i, "months": months_list, "total": total, "month_count": month_count})


@login_required
def offices_directory(request):
    """Display directory of all offices for reference."""
    qs = Office.objects.order_by("name")
    return render(request, "diary/offices.html", {"offices": qs})


@login_required
def change_password(request):
    """Allow users to change their password in-system using old+new password."""
    if request.method == 'POST':
        old = request.POST.get('old_password')
        new1 = request.POST.get('new_password1')
        new2 = request.POST.get('new_password2')
        user = request.user
        if not user.check_password(old or ''):
            messages.error(request, 'Old password is incorrect.')
        elif not new1 or not new2:
            messages.error(request, 'Please enter the new password twice.')
        elif new1 != new2:
            messages.error(request, 'New passwords do not match.')
        else:
            user.set_password(new1)
            user.save()
            update_session_auth_hash(request, user)
            messages.success(request, 'Password changed successfully.')
            return redirect('dashboard')

    return render(request, 'registration/change_password.html', {})
