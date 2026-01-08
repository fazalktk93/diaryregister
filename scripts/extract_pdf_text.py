from pathlib import Path
p = Path(__file__).resolve().parents[1] / 'generated_diary_report.pdf'
if not p.exists():
    print('PDF not found at', p)
    raise SystemExit(1)
try:
    import PyPDF2
except Exception as e:
    print('PyPDF2 not installed:', e)
    raise SystemExit(2)
try:
    r = PyPDF2.PdfReader(str(p))
    txt = ''
    for page in r.pages:
        try:
            txt += page.extract_text() or ''
        except Exception:
            pass
    print('Extracted length:', len(txt))
    print('Has Diary No:', 'Diary No' in txt)
    print('Has Test Office:', 'Test Office' in txt)
    print('Has watermark text:', 'Administration Directorate Diary System' in txt)
    # Optionally write extracted text
    out = p.with_suffix('.txt')
    out.write_text(txt, encoding='utf-8')
    print('Wrote extracted text to', out)
except Exception as e:
    print('Failed to extract PDF text:', e)
    raise
