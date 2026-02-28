from flask import Flask, render_template, request, jsonify, send_file
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image as RLImage
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from datetime import datetime
from PIL import Image
import io
import base64
import os
import hashlib
import json

app = Flask(__name__)

# ---------- CAPPING & RATES ----------
CAPS = {
    'opd': 1100, 'anc': 200, 'pnc': 50, 'del': 30, 'tb': 30,
    'epi': 200, 'nut': 250, 'ppfp': 20, 'short': 60, 'long': 30
}
RATES = {
    'opd': 400, 'anc': 600, 'pnc': 200, 'del': 6500, 'tb': 200,
    'epi': 100, 'nut': 200, 'ppfp': 300, 'short': 150, 'long': 400
}

# ---------- ADS ----------
ADS_DB = {
    'Faisalabad': {'text': 'Advertise Here - Reach 3000+ Health Managers contact smartbiopk@gmail.com', 'link': '#'},
    'Lahore': {'text': 'Advertise Here - Reach 3000+ Health Managers smartbiopk@gmail.com', 'link': '#'},
    'default': {'text': 'Advertise Here - Reach 3000+ Health Managers smartbiopk@gmail.com', 'link': '/advertise'}
}

# ---------- ANALYTICS SETUP (Vercel KV) ----------
# Analytics will work only if KV is configured, otherwise silently skip
try:
    from vercel.kv import KV
    kv_store = KV()
    KV_AVAILABLE = True
except:
    kv_store = None
    KV_AVAILABLE = False

def log_analytics(event_type, district=None, metadata=None):
    """
    Privacy-safe analytics logging for pharma advertisement metrics.
    Stores: timestamp, district, event type, anonymous session hash
    NO personal data (names, CNICs, patient counts) is stored.
    """
    if not KV_AVAILABLE:
        return
    
    try:
        timestamp = datetime.utcnow()
        date_str = timestamp.strftime("%Y-%m-%d")
        hour_str = timestamp.strftime("%H")
        
        # Create anonymous session ID (no personal data)
        session_seed = f"{request.remote_addr}{request.user_agent.string}{timestamp.strftime('%Y%m%d')}"
        session_hash = hashlib.sha256(session_seed.encode()).hexdigest()[:12]
        
        # Key structure: analytics:{date}:{event_type}:{district or 'all'}
        district_key = district.replace(' ', '_') if district else 'unknown'
        
        # 1. Increment daily event counter
        daily_key = f"analytics:daily:{date_str}:{event_type}:{district_key}"
        kv_store.incr(daily_key)
        
        # 2. Store hourly distribution
        hourly_key = f"analytics:hourly:{date_str}:{hour_str}:{event_type}"
        kv_store.incr(hourly_key)
        
        # 3. Unique sessions per day (using set for uniqueness)
        sessions_key = f"analytics:sessions:{date_str}:{district_key}"
        kv_store.sadd(sessions_key, session_hash)
        
        # 4. Monthly aggregation key
        month_str = timestamp.strftime("%Y-%m")
        monthly_key = f"analytics:monthly:{month_str}:{event_type}"
        kv_store.incr(monthly_key)
        
        # 5. District popularity (sorted set)
        popularity_key = f"analytics:districts:{month_str}"
        kv_store.zincrby(popularity_key, 1, district_key)
        
        # Set expiry for daily keys (keep 90 days)
        kv_store.expire(daily_key, 7776000)
        kv_store.expire(sessions_key, 7776000)
        kv_store.expire(hourly_key, 7776000)
        
    except Exception as e:
        # Fail silently - don't break app if analytics fail
        print(f"Analytics error: {e}")

# ---------- HELPERS ----------
def format_date_ddmmyyyy(date_str):
    if not date_str: return ''
    try:
        return datetime.strptime(date_str, '%Y-%m-%d').strftime('%d/%m/%Y')
    except:
        return date_str

# ---------- ROUTES ----------
@app.route('/')
def index():
    district = request.args.get('district', 'default')
    ad = ADS_DB.get(district, ADS_DB['default'])
    
    # Log page view for analytics (privacy-safe)
    log_analytics('page_view', district=district)
    
    districts = [
        'Attock', 'Bahawalnagar', 'Bahawalpur', 'Bhakkar', 'Chakwal', 'Chiniot',
        'Dera Ghazi Khan', 'Faisalabad', 'Gujranwala', 'Gujrat', 'Hafizabad',
        'Jhang', 'Jhelum', 'Kasur', 'Khanewal', 'Khushab', 'Lahore', 'Layyah',
        'Lodhran', 'Mandi Bahauddin', 'Mianwali', 'Multan', 'Muzaffargarh',
        'Nankana Sahib', 'Narowal', 'Okara', 'Pakpattan', 'Rahim Yar Khan',
        'Rajanpur', 'Rawalpindi', 'Sahiwal', 'Sargodha', 'Sheikhupura',
        'Sialkot', 'Toba Tek Singh', 'Vehari'
    ]
    
    now = datetime.utcnow()
    years = list(range(2020, now.year + 2))
    months = list(range(1, 13))
    sel_year = request.args.get('year', now.year, type=int)
    sel_month = request.args.get('month', now.month, type=int)
    
    return render_template("index.html", ad=ad, districts=districts, selected_district=district,
                         years=years, months=months, sel_year=sel_year, sel_month=sel_month)

@app.route('/calculate', methods=['POST'])
def calculate():
    data = request.json
    district = data.get('district', 'unknown')
    
    # Log calculation event
    log_analytics('calculation', district=district)
    
    results, total = {}, 25000
    for key, rate in RATES.items():
        val = int(data.get(key, 0))
        actual = min(val, CAPS[key])
        amount = actual * rate
        total += amount
        results[key] = {'amount': amount, 'capped': val > CAPS[key], 'entered': val, 'cap': CAPS[key]}
    results['total'] = total
    return jsonify(results)

# ---------- ADMIN & ANALYTICS DASHBOARD ----------
@app.route('/admin')
def admin_panel():
    sel_year = request.args.get('year', datetime.utcnow().year, type=int)
    sel_month = request.args.get('month', datetime.utcnow().month, type=int)
    year_month = f"{sel_year}-{sel_month:02d}"
    
    # Get analytics from KV if available
    analytics_data = {}
    if KV_AVAILABLE:
        try:
            # Get monthly stats
            monthly_pv = kv_store.get(f"analytics:monthly:{year_month}:page_view") or 0
            monthly_calc = kv_store.get(f"analytics:monthly:{year_month}:calculation") or 0
            monthly_pdf = kv_store.get(f"analytics:monthly:{year_month}:pdf_generated") or 0
            
            # Get district rankings
            district_rankings = kv_store.zrange(f"analytics:districts:{year_month}", 0, -1, withscores=True)
            
            analytics_data = {
                'page_views': int(monthly_pv),
                'calculations': int(monthly_calc),
                'pdfs_generated': int(monthly_pdf),
                'top_districts': district_rankings[-5:] if district_rankings else []  # Top 5
            }
        except Exception as e:
            analytics_data = {'error': str(e)}
    
    return render_template("admin.html", year=sel_year, month=sel_month,
                         years=list(range(2020, datetime.utcnow().year + 2)),
                         months=list(range(1, 13)), analytics=analytics_data)

@app.route('/admin/analytics')
def admin_analytics_api():
    """API endpoint for rich analytics data (for charts)"""
    if not KV_AVAILABLE:
        return jsonify({'error': 'Analytics not available'}), 503
    
    try:
        year = request.args.get('year', datetime.utcnow().year, type=int)
        month = request.args.get('month', datetime.utcnow().month, type=int)
        
        # Generate daily data for the month
        days_in_month = 31  # Simplified
        daily_views = []
        daily_calcs = []
        
        for day in range(1, days_in_month + 1):
            date_str = f"{year}-{month:02d}-{day:02d}"
            pv = kv_store.get(f"analytics:daily:{date_str}:page_view") or 0
            calc = kv_store.get(f"analytics:daily:{date_str}:calculation") or 0
            daily_views.append(int(pv))
            daily_calcs.append(int(calc))
        
        # Hourly distribution
        hourly_data = []
        for hour in range(24):
            hour_str = f"{hour:02d}"
            # Sum across all days in month (simplified)
            hourly_total = 0
            for day in range(1, 32):
                date_str = f"{year}-{month:02d}-{day:02d}"
                val = kv_store.get(f"analytics:hourly:{date_str}:{hour_str}:page_view") or 0
                hourly_total += int(val)
            hourly_data.append(hourly_total)
        
        return jsonify({
            'daily_views': daily_views,
            'daily_calculations': daily_calcs,
            'hourly_distribution': hourly_data,
            'total_users': sum(daily_views)
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ---------- PDF GENERATION ----------
@app.route('/generate_pdf', methods=['POST'])
def generate_pdf():
    try:
        data = request.form
        district = data.get('district', 'unknown')
        
        # Log PDF generation for analytics
        log_analytics('pdf_generated', district=district)
        
        signature_data = data.get('signature', '')
        sig_image = None
        if signature_data and ',' in signature_data:
            try:
                img_data = base64.b64decode(signature_data.split(',')[1])
                sig_image = Image.open(io.BytesIO(img_data))
            except Exception as e:
                print("Signature error:", e)

        # Build PDF in memory (no filesystem writes!)
        pdf_buffer = io.BytesIO()
        doc = SimpleDocTemplate(pdf_buffer, pagesize=A4,
                              rightMargin=1*cm, leftMargin=1*cm,
                              topMargin=1*cm, bottomMargin=0.8*cm)
        elements = []
        styles = getSampleStyleSheet()

        # Title
        title_style = ParagraphStyle('Title', parent=styles['Heading1'],
                                   fontSize=16, alignment=1, spaceAfter=15,
                                   fontName='Helvetica-Bold')
        elements.append(Paragraph("Claim/Expenses Payment Form - Maryam Nawaz Health Clinic", title_style))

        # Dates
        period_start = format_date_ddmmyyyy(data.get('period_start', ''))
        period_end = format_date_ddmmyyyy(data.get('period_end', ''))
        claim_date = format_date_ddmmyyyy(data.get('date', ''))

        # Certification
        cert_style = ParagraphStyle('Cert', parent=styles['Normal'],
                                  fontSize=12, leading=16, spaceAfter=12)
        cert = f"""It is certified that the following healthcare services have been provided at Mariam Nawaz Health Clinic <b>{data.get('clinic_name', '')}</b> under the supervision of the undersigned Health Manager during the period <b>{period_start}</b> to <b>{period_end}</b>."""
        elements.append(Paragraph(cert, cert_style))

        # Calculate & table
        values, total = {}, 25000
        for key in RATES:
            val = int(data.get(key, 0))
            actual = min(val, CAPS[key])
            values[key] = actual * RATES[key]
            total += values[key]

        table_data = [
            ['Sr.#', 'Services/Visit Type', 'Patients', 'Unit (PKR)', 'Total (PKR)'],
            ['1', 'OPD (Medicines Dispensed)', data.get('opd', '0'), '400', f"{values['opd']:,}"],
            ['2', 'Antenatal Care (ANC) Visits', data.get('anc', '0'), '600', f"{values['anc']:,}"],
            ['3', 'Postnatal Care (PNC) Visits', data.get('pnc', '0'), '200', f"{values['pnc']:,}"],
            ['4', 'Normal Deliveries Conducted', data.get('del', '0'), '6,500', f"{values['del']:,}"],
            ['5', 'Tuberculosis (TB) Patients Checked', data.get('tb', '0'), '200', f"{values['tb']:,}"],
            ['6', 'EPI Vaccination Services', data.get('epi', '0'), '100', f"{values['epi']:,}"],
            ['7', 'Treatment & Nutrition Screening', data.get('nut', '0'), '200', f"{values['nut']:,}"],
            ['8', 'Post-Partum/Abortion FP Services', data.get('ppfp', '0'), '300', f"{values['ppfp']:,}"],
            ['9', 'Family Planning Services', '', '', ''],
            ['', '    Short-Acting Methods', data.get('short', '0'), '150', f"{values['short']:,}"],
            ['', '    Long-Acting Methods', data.get('long', '0'), '400', f"{values['long']:,}"],
            ['10', 'Repair & Maintenance Cost', '-', '-', '25,000'],
            ['', 'Total Claims/Expenses', '', '', f"{total:,}"]
        ]

        table = Table(table_data, colWidths=[1.3*cm, 8.5*cm, 2.4*cm, 2.8*cm, 3.5*cm], rowHeights=[0.9*cm] + [0.75*cm]*12 + [0.9*cm])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2E7D32')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('ALIGN', (1, 1), (1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 12),
            ('FONTSIZE', (0, 1), (-1, -1), 11),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
            ('TOPPADDING', (0, 1), (-1, -1), 8),
            ('BACKGROUND', (0, 1), (-1, -1), colors.white),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
            ('BACKGROUND', (0, -1), (-1, -1), colors.lightgrey),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('FONTNAME', (0, -2), (-1, -2), 'Helvetica-Bold'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        elements.append(table)
        elements.append(Spacer(1, 0.5*cm))

        # Declaration
        decl_style = ParagraphStyle('Decl', parent=styles['Normal'], fontSize=12, leading=16, alignment=4, spaceBefore=10, spaceAfter=10)
        decl = """The above-mentioned claims/expenses are calculated as per contract, patient data entered in Electronic Medical Record (EMR), program guidelines and patients treated under my supervision. This bill is submitted for payment of claims/expenses (as per fixed rates under signed contract) to undersigned and official record.<br/><br/>
        Undersigned authorize competent authority to withhold/deduct amount from total claim, if any discrepancy/duplication found against patient visit entered in EMR."""
        elements.append(Paragraph(decl, decl_style))

        # Manager Info
        info_data = [
            ['Health Manager Name:', data.get('manager_name', ''), 'Date:', claim_date],
            ['CNIC Number:', data.get('cnic', ''), '', ''],
            ['Account Title:', data.get('account_title', ''), '', ''],
            ['IBAN Account Number:', data.get('iban', ''), '', ''],
            ['District:', data.get('district', ''), 'Signature & Stamp:', '']
        ]
        info_table = Table(info_data, colWidths=[4.5*cm, 7*cm, 2.5*cm, 5*cm], rowHeights=[0.8*cm]*5)
        info_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 12),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('SPAN', (1, 1), (3, 1)),
            ('SPAN', (1, 2), (3, 2)),
            ('SPAN', (1, 3), (3, 3)),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        elements.append(info_table)

        # Signature
        if sig_image:
            sig_buffer = io.BytesIO()
            sig_image.save(sig_buffer, format='PNG')
            sig_buffer.seek(0)
            elements.append(Spacer(1, 0.4*cm))
            elements.append(RLImage(sig_buffer, width=6*cm, height=1.5*cm))

        # Build PDF
        doc.build(elements)

        # Return PDF (no local logging to filesystem!)
        pdf_buffer.seek(0)
        return send_file(pdf_buffer, as_attachment=True,
                        download_name=f"MNHC_Claim_{data.get('manager_name', 'User')}.pdf")

    except Exception as e:
        return str(e), 500

# Health check endpoint for Vercel
@app.route('/api/health')
def health_check():
    return jsonify({
        'status': 'healthy',
        'kv_available': KV_AVAILABLE,
        'timestamp': datetime.utcnow().isoformat()
    })

# ---------- RUN ----------
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
