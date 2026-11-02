"""Inspect the actual deliverables, without assuming a template is parser-safe."""
from pathlib import Path
import re
from app.ats.score import normalize_text

def inspect_files(docx_path, pdf_path, *, expected_name='', expected_email=''):
    report={}
    from docx import Document
    from pypdf import PdfReader
    for kind,path in [('docx',docx_path),('pdf',pdf_path)]:
        checks={};text='';pages=None
        try:
            path=Path(path)
            checks['exists']=path.is_file()
            checks['size_under_2_5mb']=path.stat().st_size<2500000
            if kind=='docx':
                doc=Document(path);text='\n'.join(p.text for p in doc.paragraphs)
                checks['no_tables']=not doc.tables
                checks['single_column']=all(int(s._sectPr.xpath('./w:cols')[0].get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}num','1'))==1 for s in doc.sections if s._sectPr.xpath('./w:cols'))
                checks['no_contact_in_header_footer']=not expected_email or not any(expected_email in '\n'.join(p.text for p in part.paragraphs) for section in doc.sections for part in (section.header,section.footer))
            else:
                reader=PdfReader(path);pages=len(reader.pages);text='\n'.join(p.extract_text() or '' for p in reader.pages)
            normalized=normalize_text(text)
            checks['text_extractable']=len(normalized)>40
            checks['no_replacement_characters']='�' not in text
            if expected_email: checks['email_preserved']=expected_email.lower() in normalized
            if expected_name:
                # Presentation forms are normalized; report extraction issues rather than hiding RTL errors.
                checks['name_preserved']=normalize_text(expected_name) in normalized
            report[kind]={'status':'passed' if all(checks.values()) else 'needs_review','checks':checks,'pages':pages,'characters':len(text)}
        except Exception:
            report[kind]={'status':'failed','checks':checks,'message':'استخراج یا بررسی فایل موفق نبود.'}
    return {'status':'passed' if all(v['status']=='passed' for v in report.values()) else 'needs_review','files':report}
