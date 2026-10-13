import calendar
import csv
import io
from datetime import date
from xml.sax.saxutils import escape
from django.contrib import messages
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.db.models.functions import ExtractMonth
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.http import require_POST
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from django.contrib.staticfiles import finders
from .access import audit, membership_for, require_roles, scoped_diaries
from .forms import DiaryCreateForm
from .models import Diary, DiaryMovement, Directorate, DirectorateSettings, Membership, AuditLog
from .v2_forms import AccountForm, DirectorateForm, SettingsForm
from .movement_forms import MovementForm, role_group


READ = ('admin', 'operator', 'viewer', 'auditor', 'system')


class RegisterCanvas(Canvas):
    """Original register footer with Page X of Y."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.page_states = []

    def showPage(self):
        self.page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self.page_states)
        for state in self.page_states:
            self.__dict__.update(state)
            self.setFont('Helvetica', 8)
            self.drawRightString(self._pagesize[0] - 18, 12, f'Page {self._pageNumber} of {total}')
            super().showPage()
        super().save()


def modal_request(request):
    return request.headers.get('x-requested-with') == 'XMLHttpRequest'


def form_response(request, form, title):
    context = {'form': form, 'title': title, 'is_diary_form': isinstance(form, DiaryCreateForm), 'is_movement_form': isinstance(form, MovementForm)}
    if isinstance(form, (DiaryCreateForm, MovementForm)):
        from .models import Office
        context['offices'] = Office.objects.filter(directorate=request.membership.directorate).order_by('name')
    if modal_request(request):
        context['in_modal'] = True
        html = render_to_string('v2/_form.html', context, request=request)
        if request.method == 'POST':
            return JsonResponse({'success': False, 'html': html}, status=422)
        return HttpResponse(html)
    return render(request, 'v2/form.html', context)


def saved_response(request, name, **kwargs):
    if modal_request(request):
        return JsonResponse({'success': True})
    return redirect(name, **kwargs)


def filtered(request, year=None):
    qs = scoped_diaries(request.user).prefetch_related('movements')
    try:
        value = year if year is not None else request.GET.get('year')
        if value:
            year = int(value)
            if not 1 <= year <= 9999:
                raise ValueError
            qs = qs.filter(year=year)
        month = request.GET.get('month')
        if month:
            month = int(month)
            if not 1 <= month <= 12:
                raise ValueError
            qs = qs.filter(diary_date__month=month)
        for key, lookup in [('date_from', 'diary_date__gte'), ('date_to', 'diary_date__lte')]:
            if request.GET.get(key):
                qs = qs.filter(**{lookup: date.fromisoformat(request.GET[key])})
        if request.GET.get('date_from') and request.GET.get('date_to') and request.GET['date_from'] > request.GET['date_to']:
            raise ValueError
    except (ValueError, TypeError):
        raise ValueError('Enter a valid year, month, and ISO date range.')
    q = request.GET.get('q', '').strip()
    for name in ['received_from', 'received_diary_no', 'file_letter', 'subject', 'remarks', 'marked_to']:
        if request.GET.get(name):
            qs = qs.filter(**{name + '__icontains': request.GET[name].strip()})
    if request.GET.get('no_of_folders'):
        try:
            folders = int(request.GET['no_of_folders'])
            if folders < 0 or folders > 2147483647:
                raise ValueError
        except ValueError:
            raise ValueError('Enter a valid folder count.')
        qs = qs.filter(no_of_folders=folders)
    if q:
        if q.isdigit() and len(q) <= 10:
            qs = qs.filter(sequence=int(q))
        else:
            qs = qs.filter(Q(subject__icontains=q) | Q(received_from__icontains=q) | Q(received_diary_no__icontains=q) | Q(marked_to__icontains=q) | Q(remarks__icontains=q))
    return qs.order_by('-year', '-sequence')


def filter_error(error):
    return HttpResponse(str(error), status=400, content_type='text/plain')


@require_roles(*READ)
def dashboard(request):
    if request.membership.role == 'system' and not request.membership.directorate_id:
        return redirect('users')
    qs = scoped_diaries(request.user)
    today = timezone.localdate()
    try:
        year = int(request.GET.get('year', today.year))
        if not 1 <= year <= 9999:
            raise ValueError
    except (ValueError, TypeError):
        return filter_error('Invalid year.')
    counts = dict(qs.filter(year=year).annotate(month=ExtractMonth('diary_date')).values('month').annotate(count=Count('id')).values_list('month', 'count'))
    months = [{'month': m, 'name': calendar.month_name[m], 'count': counts.get(m, 0)} for m in range(1, 13)]
    return render(request, 'v2/dashboard.html', {'year': year, 'months': months,
        'years': qs.values('year').annotate(count=Count('id')).order_by('-year'),
        'total': qs.filter(year=year).count(), 'today_count': qs.filter(diary_date=today).count(),
        'month_count': qs.filter(year=today.year, diary_date__month=today.month).count(), 'recent': qs[:10], 'today': today})


@require_roles(*READ)
def dashboard_data(request, year):
    qs = scoped_diaries(request.user).filter(year=year)
    return JsonResponse({'year': year, 'total': qs.count(), 'months': list(qs.annotate(month=ExtractMonth('diary_date')).values('month').annotate(count=Count('id')))})


@require_roles(*READ)
def diary_list(request, year=None):
    try:
        qs = filtered(request, year)
    except ValueError as error:
        return filter_error(error)
    params = request.GET.copy()
    params.pop('page', None)
    is_report = request.resolver_match.url_name in ('reports_table', 'diary_year_report')
    return render(request, 'v2/reports.html' if is_report else 'v2/register.html', {'page_obj': Paginator(qs, 50).get_page(request.GET.get('page')), 'total': qs.count(), 'filter_query': params.urlencode(), 'report_year': year,
        'report_months': [{'month': month, 'name': calendar.month_name[month]} for month in range(1, 13)]})


def snapshot(diary):
    return {field: str(getattr(diary, field)) for field in ['diary_date', 'received_from', 'received_diary_no', 'file_letter', 'no_of_folders', 'service_included', 'subject', 'marked_to', 'remarks', 'archived']}


@require_roles('admin', 'operator')
@transaction.atomic
def diary_create(request):
    form = DiaryCreateForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        data = dict(form.cleaned_data)
        data.pop('diary_type', None)
        diary = Diary.create_with_next_number(created_by=request.user, **data)
        DiaryMovement.objects.create(diary=diary, to_office=diary.marked_to, from_office=diary.received_from, action_type='Created', created_by=request.user)
        audit(request.user, 'diary.created', diary.pk, {'after': snapshot(diary)}, request)
        messages.success(request, f'Diary {diary.diary_no} registered for {diary.year}.')
        return saved_response(request, 'diary_detail', pk=diary.pk)
    return form_response(request, form, 'Register diary')


@require_roles(*READ)
def diary_detail(request, pk):
    diary = get_object_or_404(scoped_diaries(request.user), pk=pk)
    movements = diary.movements.select_related('created_by').order_by('-action_datetime', '-pk')
    return render(request, 'v2/detail.html', {'diary': diary, 'movements': movements})


@require_roles('admin', 'operator')
@transaction.atomic
def movement_add(request, pk):
    diary = get_object_or_404(scoped_diaries(request.user).select_for_update(), pk=pk)
    form = MovementForm(request.POST or None, diary=diary)
    if request.method == 'POST' and form.is_valid():
        before = {'marked_to': diary.marked_to}
        movement = form.save(commit=False)
        movement.diary = diary
        movement.created_by = request.user
        movement.action_type = DiaryMovement.ActionType.FORWARDED
        movement.save()
        diary.marked_to = movement.to_office
        diary.marked_date = timezone.localtime(movement.action_datetime).date()
        diary.save(update_fields=['marked_to', 'marked_date'])
        audit(request.user, 'diary.movement.created', movement.pk, {'diary_id': diary.pk, 'before': before,
            'after': {'from_office': movement.from_office, 'to_office': movement.to_office,
                'action_datetime': movement.action_datetime.isoformat(), 'remarks': movement.remarks}}, request)
        messages.success(request, f'Movement recorded for diary {diary.diary_no}.')
        return saved_response(request, 'diary_list')
    return form_response(request, form, f'Movement — diary {diary.diary_no}')


@require_roles('admin', 'operator')
@transaction.atomic
def diary_edit(request, pk):
    diary = get_object_or_404(scoped_diaries(request.user).select_for_update(), pk=pk)
    before = snapshot(diary)
    form = DiaryCreateForm(request.POST or None, instance=diary)
    if request.method == 'POST' and form.is_valid():
        updated = form.save(commit=False)
        updated.file_letter = form.cleaned_data['file_letter']
        updated.service_included = form.cleaned_data['service_included']
        updated.save()
        audit(request.user, 'diary.modified', diary.pk, {'before': before, 'after': snapshot(updated)}, request)
        messages.success(request, 'Diary updated.')
        return saved_response(request, 'diary_detail', pk=diary.pk)
    return form_response(request, form, f'Edit diary {diary.diary_no}')


@require_roles('admin', 'operator')
@require_POST
@transaction.atomic
def diary_delete(request, pk):
    diary = get_object_or_404(scoped_diaries(request.user).select_for_update(), pk=pk)
    diary.archived = True
    diary.save(update_fields=['archived'])
    audit(request.user, 'diary.archived', diary.pk, {'archived': True}, request)
    messages.success(request, 'Diary removed from the active register; its number and history are preserved.')
    return redirect('diary_list')


def report_rows(qs):
    yield ['Diary No', 'Year', 'Diary Date', 'Registered', 'Received No', 'Received From', 'Type', 'Folders', 'Subject', 'Destination', 'Remarks', 'Movement']
    for diary in qs:
        yield [diary.diary_no, str(diary.year), str(diary.diary_date), str(timezone.localtime(diary.created_at).date()), diary.received_diary_no, diary.received_from,
            diary.file_letter + (' + Service Book' if diary.service_included else ''), str(diary.no_of_folders), diary.subject, diary.marked_to, diary.remarks, diary.movement_history_plain()]


def csv_safe(value):
    value = str(value)
    return "'" + value if value.lstrip().startswith(('=', '+', '-', '@')) else value


@require_roles(*READ)
def reports_csv(request, year=None):
    try:
        qs = filtered(request, year)
    except ValueError as error:
        return filter_error(error)
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="diary-register.csv"'
    writer = csv.writer(response)
    for row in report_rows(qs):
        writer.writerow([csv_safe(cell) for cell in row])
    audit(request.user, 'diary.export.csv', changes={'count': qs.count()}, request=request)
    return response


@require_roles(*READ)
def reports_pdf(request, year=None):
    try:
        qs = filtered(request, year)
    except ValueError as error:
        return filter_error(error)
    buffer = io.BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=landscape((8.5 * inch, 13 * inch)), leftMargin=18, rightMargin=18, topMargin=18, bottomMargin=26)
    style = getSampleStyleSheet()['Normal']
    style.fontSize = 8
    style.leading = 10
    heading_style = ParagraphStyle('RegisterHeading', parent=style, fontSize=12, leading=16, alignment=TA_CENTER)
    column_style = ParagraphStyle('ColumnHeading', parent=style, fontName='Helvetica-Bold', textColor=colors.white)
    directorate = request.membership.directorate
    preferences = DirectorateSettings.objects.filter(directorate=directorate).first()
    directorate_title = preferences.report_title if preferences and preferences.report_title else directorate.name
    selected_year = year or request.GET.get('year')
    title = f'<b>Diary Record of {escape(directorate_title)}<br/>{"Year " + str(selected_year) if selected_year else "All years"}</b>'
    period = ', '.join(f'{key}: {request.GET[key]}' for key in ['year', 'month', 'date_from', 'date_to', 'q', 'received_from', 'received_diary_no', 'file_letter', 'no_of_folders', 'subject', 'remarks', 'marked_to'] if request.GET.get(key))
    if year:
        period = f'Year: {year}, ' + period
    data = [[Paragraph(label, column_style) for label in ['Diary No', 'Date', 'Rcvd No', 'Rcvd From', 'File/Letter', 'Folders', 'Subject', 'Movement']]]
    for diary in qs.order_by('year', 'sequence'):
        values = [diary.diary_no, diary.diary_date.strftime('%d-%m-%Y'), diary.received_diary_no or '-', diary.received_from or '-',
            diary.file_letter + (' + Service Book' if diary.service_included else ''),
            str(diary.no_of_folders) if diary.file_letter == 'File' else '-', diary.subject or '-', diary.movement_history_plain()]
        data.append([Paragraph(escape(str(value)).replace('\n', '<br/>'), style) for value in values])
    table = Table(data, repeatRows=1, colWidths=[60, 50, 45, 80, 60, 40, 240, 320])
    table.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.black), ('GRID', (0, 0), (-1, -1), .25, colors.grey),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'), ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.whitesmoke, colors.lightgrey]),
        ('LEFTPADDING', (0, 0), (-1, -1), 4), ('RIGHTPADDING', (0, 0), (-1, -1), 4), ('TOPPADDING', (0, 0), (-1, -1), 3), ('BOTTOMPADDING', (0, 0), (-1, -1), 3)]))
    logo = Image(finders.find('diary/logo.png'))
    original_logo_width, original_logo_height = logo.imageWidth, logo.imageHeight
    logo.drawWidth = 80
    logo.drawHeight = 80 * original_logo_height / original_logo_width
    logo.hAlign = 'LEFT'
    header = Table([[logo, Paragraph(title, heading_style), '']], colWidths=[90, 720, 90])
    header.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0), ('LINEBELOW', (0, 0), (-1, -1), .5, colors.grey)]))
    document.build([header, Spacer(1, 8), Paragraph(escape(period or 'All available years') + f' | Total: {len(data)-1}', style), Spacer(1, 8), table], canvasmaker=RegisterCanvas)
    audit(request.user, 'diary.export.pdf', changes={'count': len(data)-1}, request=request)
    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = 'inline; filename="diary-register.pdf"'
    return response


@require_roles('system', 'admin')
def users(request):
    qs = Membership.objects.select_related('user', 'directorate')
    if request.membership.role != 'system':
        qs = qs.filter(directorate=request.membership.directorate).exclude(role='system')
    account_stats = qs.aggregate(total=Count('pk'), active=Count('pk', filter=Q(user__is_active=True)), inactive=Count('pk', filter=Q(user__is_active=False)))
    q = request.GET.get('q', '')
    if q:
        qs = qs.filter(Q(user__username__icontains=q) | Q(user__email__icontains=q) | Q(user__first_name__icontains=q) | Q(user__last_name__icontains=q))
    params = request.GET.copy()
    params.pop('page', None)
    return render(request, 'v2/users.html', {'page_obj': Paginator(qs.order_by('user__username'), 50).get_page(request.GET.get('page')), 'filter_query': params.urlencode(), 'account_stats': account_stats})


def managed_user(request, pk):
    qs = get_user_model().objects.all()
    if request.membership.role != 'system':
        qs = qs.filter(membership__directorate=request.membership.directorate, membership__role__in=['operator', 'viewer', 'auditor'], is_superuser=False, is_staff=False)
    return get_object_or_404(qs, pk=pk)


@require_roles('system', 'admin')
@transaction.atomic
def user_edit(request, pk=None):
    target = managed_user(request, pk) if pk else None
    previous = None
    if target:
        previous = account_snapshot(target)
    form = AccountForm(request.POST or None, instance=target, actor=request.membership)
    if request.method == 'POST' and form.is_valid():
        if target and target.pk == request.user.pk:
            form.add_error(None, 'Use Change password for your own account. Ask another administrator to change your role or status.')
        else:
            user = form.save(commit=False)
            if form.cleaned_data['password']:
                user.set_password(form.cleaned_data['password'])
            user.save()
            Membership.objects.update_or_create(user=user, defaults={'directorate': form.cleaned_data['directorate'], 'role': form.cleaned_data['role']})
            assign_role_permissions(user)
            audit(request.user, 'user.modified' if target else 'user.created', user.pk, {'before': previous, 'after': account_snapshot(user)}, request, directorate=form.cleaned_data['directorate'])
            if form.cleaned_data['password']:
                audit(request.user, 'password.reset.admin', user.pk, request=request, directorate=form.cleaned_data['directorate'])
            messages.success(request, 'Account saved.')
            return saved_response(request, 'users')
    return form_response(request, form, 'Edit user' if target else 'Create user')


def account_snapshot(user):
    membership = Membership.objects.filter(user=user).first()
    return {'username': user.username, 'email': user.email, 'first_name': user.first_name, 'last_name': user.last_name, 'active': user.is_active, 'role': membership.role if membership else None, 'directorate': membership.directorate_id if membership else None}


def assign_role_permissions(user):
    role = user.membership.role
    group = role_group(role)
    user.groups.set([group])
    user.user_permissions.clear()


@require_roles('system', 'admin')
@transaction.atomic
def user_password(request, pk):
    target = managed_user(request, pk)
    form = SetPasswordForm(target, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        form.save()
        audit(request.user, 'password.reset.admin', target.pk, request=request, directorate=target.membership.directorate)
        messages.success(request, 'Password reset. Existing sessions for this user will be invalidated.')
        return saved_response(request, 'users')
    return form_response(request, form, f'Reset password for {target.username}')


@require_roles('system')
def directorates(request):
    return render(request, 'v2/directorates.html', {'directorates': Directorate.objects.order_by('name')})


@require_roles('system')
@transaction.atomic
def directorate_edit(request, pk=None):
    obj = get_object_or_404(Directorate, pk=pk) if pk else None
    before = {'name': obj.name, 'code': obj.code, 'is_active': obj.is_active} if obj else None
    form = DirectorateForm(request.POST or None, instance=obj)
    if request.method == 'POST' and form.is_valid():
        directorate = form.save()
        DirectorateSettings.objects.get_or_create(directorate=directorate)
        audit(request.user, 'directorate.modified' if obj else 'directorate.created', directorate.pk, {'before': before, 'after': form.cleaned_data}, request, directorate=directorate)
        return saved_response(request, 'directorates')
    return form_response(request, form, 'Directorate configuration')


@require_roles('admin')
@transaction.atomic
def directorate_settings(request):
    obj, _ = DirectorateSettings.objects.get_or_create(directorate=request.membership.directorate)
    before = obj.report_title
    form = SettingsForm(request.POST or None, instance=obj)
    if request.method == 'POST' and form.is_valid():
        form.save()
        audit(request.user, 'settings.modified', obj.pk, {'before': before, 'after': obj.report_title}, request)
        messages.success(request, 'Settings saved.')
        return saved_response(request, 'directorate_settings')
    return form_response(request, form, 'Directorate settings')


@require_roles('system', 'admin', 'auditor')
def audit_logs(request):
    qs = AuditLog.objects.select_related('user', 'directorate').order_by('-timestamp', '-pk')
    if request.membership.role == 'system':
        qs = qs.exclude(action__startswith='diary.')
    else:
        qs = qs.filter(directorate=request.membership.directorate)
    if request.GET.get('q'):
        qs = qs.filter(action__icontains=request.GET['q'])
    params = request.GET.copy()
    params.pop('page', None)
    return render(request, 'v2/audit.html', {'page_obj': Paginator(qs, 50).get_page(request.GET.get('page')), 'filter_query': params.urlencode()})


@login_required
@transaction.atomic
def change_password(request):
    form = PasswordChangeForm(request.user, request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        audit(user, 'password.changed', user.pk, request=request)
        update_session_auth_hash(request, user)
        messages.success(request, 'Password changed.')
        return saved_response(request, 'dashboard')
    return form_response(request, form, 'Change password')


@require_roles(*READ)
def offices_directory(request):
    from .models import Office
    scoped_diaries(request.user)
    return render(request, 'v2/offices.html', {'offices': Office.objects.filter(directorate=request.membership.directorate).order_by('name')})
