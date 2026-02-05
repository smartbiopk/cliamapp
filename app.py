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

# ---------- ANALYTICS STORAGE ----------
# Use /tmp for Vercel serverless (only writable directory)
# For persistent storage, we'll use a JSON file in /tmp (resets on cold start but works for single session)
# For production, you should use Vercel KV or a database
ANALYTICS_FILE = "/tmp/mnhc_analytics.json"

def _init_analytics():
    """Initialize analytics file if it doesn't exist"""
    if not os.path.exists(ANALYTICS_FILE):
        with open(ANALYTICS_FILE, 'w') as f:
            json.dump({
                'page_views': [],
                'calculations': [],
                'pdf_generations': [],
                'district_stats': {},
                'monthly_claims': {}
            }, f)

def _log_event(event_type, data):
    """Log an analytics event"""
    try:
        _init_analytics()
        with open(ANALYTICS_FILE, 'r') as f:
            analytics = json.load(f)
        
        timestamp = datetime.utcnow().isoformat()
        event_data = {
            'timestamp': timestamp,
            'date': datetime.utcnow().strftime('%Y-%m-%d'),
            'time': datetime.utcnow().strftime('%H:%M:%S'),
            'month': datetime.utcnow().strftime('%Y-%m'),
            'year': datetime.utcnow().year,
            'type': event_type
        }
        event_data.update(data)
        
        if event_type == 'page_view':
            analytics['page_views'].append(event_data)
        elif event_type == 'calculation':
            analytics['calculations'].append(event_data)
        elif event_type == 'pdf_generation':
            analytics['pdf_generations'].append(event_data)
        
        # Update district stats
        district = data.get('district', 'unknown')
        if district not in analytics['district_stats']:
            analytics['district_stats'][district] = {'views': 0, 'calculations': 0, 'pdfs': 0, 'total_amount': 0}
        
        if event_type == 'page_view':
            analytics['district_stats'][district]['views'] += 1
        elif event_type == 'calculation':
            analytics['district_stats'][district]['calculations'] += 1
            analytics['district_stats'][district]['total_amount'] += data.get('total', 0)
        elif event_type == 'pdf_generation':
            analytics['district_stats'][district]['pdfs'] += 1
        
        # Monthly aggregation
        month_key = datetime.utcnow().strftime('%Y-%m')
        if month_key not in analytics['monthly_claims']:
            analytics['monthly_claims'][month_key] = {'count': 0, 'total_amount': 0, 'districts': {}}
        
        if event_type in ['calculation', 'pdf_generation']:
            analytics['monthly_claims'][month_key]['count'] += 1
            analytics['monthly_claims'][month_key]['total_amount'] += data.get('total', 0)
            if district not in analytics['monthly_claims'][month_key]['districts']:
                analytics['monthly_claims'][month_key]['districts'][district] = 0
            analytics['monthly_claims'][month_key]['districts'][district] += 1
        
        with open(ANALYTICS_FILE, 'w') as f:
            json.dump(analytics, f, indent=2)
            
    except Exception as e:
        print(f"Analytics error: {e}")

def _get_analytics_summary():
    """Get summary for pharma presentation"""
    try:
        _init_analytics()
        with open(ANALYTICS_FILE, 'r') as f:
            analytics = json.load(f)
        
        total_views = len(analytics['page_views'])
        total_calcs = len(analytics['calculations'])
        total_pdfs = len(analytics['pdf_generations'])
        unique_districts = len([d for d in analytics['district_stats'].keys() if d != 'unknown'])
        
        # Calculate active users (last 30 days)
        recent_cutoff = datetime.utcnow().timestamp() - (30 * 24 * 60 * 60)
        active_users = len(set([
            pv.get('district', 'unknown') 
            for pv in analytics['page_views'] 
            if datetime.fromisoformat(pv['timestamp']).timestamp() > recent_cutoff
        ]))
        
        return {
            'total_page_views': total_views,
            'total_calculations': total_calcs,
            'total_pdfs_generated': total_pdfs,
            'unique_districts_active': unique_districts,
            'monthly_active_districts': active_users,
            'district_breakdown': analytics['district_stats'],
            'monthly_trends': analytics['monthly_claims']
        }
    except Exception as e:
        return {'error': str(e)}

# ---------- HELPERS ----------
def format_date_ddmmyyyy(date_str):
    if not date_str: 
        return ''
    try:
        return datetime.strptime(date_str, '%Y-%m-%d').strftime('%d/%m/%Y')
    except:
        return date_str

# ---------- ROUTES ----------
@app.route('/')
def index():
    district = request.args.get('district', 'default')
    ad = ADS_DB.get(district, ADS_DB['default'])
    
    # Log page view analytics (privacy-safe)
    _log_event('page_view', {
        'district': district,
        'ip_hash': hashlib.sha256(request.remote_addr.encode()).hexdigest()[:16],  # anonymized
        'user_agent': request.user_agent.string[:50] if request.user_agent else 'unknown'
    })
    
    districts = [
        'Attock', 'Bahawalnagar', 'Bahawalpur', 'Bhakkar', 'Chakwal', 'Chiniot',
        'Dera Ghazi Khan', 'Faisalabad', 'Gujranwala', 'Gujrat', 'Hafizabad',
        'Jhang', 'Jhelum', 'Kasur', 'Khanewal', 'Khushab', 'Lahore', 'Layyah',
        'Lodhran', 'Mandi Bahauddin', 'Mianwali', 'Multan', 'Muzaffargarh',
        'Nankana Sahib', 'Narowal', 'Okara', 'Pakpattan', 'Rahim Yar Khan',
        'Rajanpur', 'Rawalpindi', 'Sahiwal', 'Sargodha', 'Sheikhupura',
        'Sialkot', 'Toba Tek Singh', 'Vehari'
    ]
    
    # Build month/year lists
    now = datetime.utcnow()
    years = list(range(2020, now.year + 2))
    months = list(range(1, 13))
    sel_year = request.args.get('year', now.year, type=int)
    sel_month = request.args.get('month', now.month, type=int)
    
    return render_template("index.html", ad=ad, districts=districts, 
                          selected_district=district,
                          years=years, months=months, 
                          sel_year=sel_year, sel_month=sel_month)

@app.route('/calculate', methods=['POST'])
def calculate():
    try:
        data = request.json
        results, total = {}, 25000
        
        for key, rate in RATES.items():
            val = int(data.get(key, 0))
            actual = min(val, CAPS[key])
            amount = actual * rate
            total += amount
            results[key] = {
                'amount': amount, 
                'capped': val > CAPS[key], 
                'entered': val, 
                'cap': CAPS[key]
            }
        results['total'] = total
        
        # Log calculation analytics
        _log_event('calculation', {
            'district': data.get('district', 'unknown'),
            'total': total,
            'services_used': [k for k in RATES.keys() if int(data.get(k, 0)) > 0]
        })
        
        return jsonify(results)
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ---------- ANALYTICS DASHBOARD ----------
@app.route('/analytics')
def analytics_dashboard():
    """Public analytics dashboard for pharma companies"""
    summary = _get_analytics_summary()
    
    # Create a nice HTML dashboard
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>MNHC Platform Analytics</title>
        <style>
            body {{ font-family: Arial, sans-serif; margin: 40px; background: #f5f5f5; }}
            .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
            h1 {{ color: #2E7D32; border-bottom: 3px solid #2E7D32; padding-bottom: 10px; }}
            .stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin: 30px 0; }}
            .stat-card {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px; border-radius: 8px; text-align: center; }}
            .stat-number {{ font-size: 2.5em; font-weight: bold; margin: 10px 0; }}
            table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
            th, td {{ padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }}
            th {{ background: #2E7D32; color: white; }}
            tr:hover {{ background: #f5f5f5; }}
            .footer {{ margin-top: 40px; padding-top: 20px; border-top: 1px solid #ddd; color: #666; font-size: 0.9em; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>📊 MNHC Health Platform - Usage Analytics</h1>
            <p style="color: #666; font-size: 1.1em;">
                Real-time platform engagement metrics for pharmaceutical advertising partners
            </p>
            
            <div class="stats-grid">
                <div class="stat-card">
                    <div>Total Page Views</div>
                    <div class="stat-number">{summary.get('total_page_views', 0):,}</div>
                </div>
                <div class="stat-card" style="background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);">
                    <div>Claims Calculated</div>
                    <div class="stat-number">{summary.get('total_calculations', 0):,}</div>
                </div>
                <div class="stat-card" style="background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);">
                    <div>PDFs Generated</div>
                    <div class="stat-number">{summary.get('total_pdfs_generated', 0):,}</div>
                </div>
                <div class="stat-card" style="background: linear-gradient(135deg, #43e97b 0%, #38f9d7 100%);">
                    <div>Active Districts</div>
                    <div class="stat-number">{summary.get('unique_districts_active', 0)}</div>
                </div>
            </div>
            
            <h2>🏥 District-Level Engagement</h2>
            <table>
                <tr>
                    <th>District</th>
                    <th>Page Views</th>
                    <th>Calculations</th>
                    <th>PDFs Generated</th>
                    <th>Est. Claim Value (PKR)</th>
                </tr>
    """
    
    # Sort districts by activity
    districts = summary.get('district_breakdown', {})
    sorted_districts = sorted(districts.items(), key=lambda x: x[1].get('views', 0), reverse=True)
    
    for district, stats in sorted_districts:
        if district != 'unknown':
            html += f"""
                <tr>
                    <td><strong>{district}</strong></td>
                    <td>{stats.get('views', 0):,}</td>
                    <td>{stats.get('calculations', 0):,}</td>
                    <td>{stats.get('pdfs', 0):,}</td>
                    <td>PKR {stats.get('total_amount', 0):,}</td>
                </tr>
            """
    
    html += f"""
            </table>
            
            <h2>📈 Monthly Trends</h2>
            <table>
                <tr>
                    <th>Month</th>
                    <th>Total Interactions</th>
                    <th>Total Claim Value</th>
                    <th>Top Districts</th>
                </tr>
    """
    
    monthly = summary.get('monthly_trends', {})
    for month in sorted(monthly.keys(), reverse=True)[:6]:  # Last 6 months
        data = monthly[month]
        top_districts = sorted(data.get('districts', {}).items(), key=lambda x: x[1], reverse=True)[:3]
        top_dist_str = ', '.join([f"{d} ({c})" for d, c in top_districts])
        
        html += f"""
            <tr>
                <td>{month}</td>
                <td>{data.get('count', 0):,}</td>
                <td>PKR {data.get('total_amount', 0):,}</td>
                <td>{top_dist_str}</td>
            </tr>
        """
    
    html += f"""
            </table>
            
            <div class="footer">
                <p><strong>Platform Health:</strong> 🟢 Active | 
                <strong>Target Audience:</strong> 3,000+ Health Managers across 36 districts of Punjab |
                <strong>Contact for Advertising:</strong> smartbiopk@gmail.com</p>
                <p style="font-size: 0.8em; color: #999;">
                    Last updated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')} | 
                    Data is anonymized and privacy-compliant
                </p>
            </div>
        </div>
    </body>
    </html>
    """
    
    return html

@app.route('/analytics/json')
def analytics_json():
    """API endpoint for raw analytics data"""
    return jsonify(_get_analytics_summary())

# ---------- PDF GENERATION ----------
@app.route('/generate_pdf', methods=['POST'])
def generate_pdf():
    try:
        data = request.form
        district = data.get('district', 'unknown')
        
        signature_data = data.get('signature', '')
        sig_image = None
        if signature_data and ',' in signature_data:
            try:
                img_data = base64.b64decode(signature_data.split(',')[1])
                sig_image = Image.open(io.BytesIO(img_data))
            except Exception as e:
                print("Signature error:", e)

        # Build PDF in memory
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

        table = Table(table_data, colWidths=[1.3*cm, 8.5*cm, 2.4*cm, 2.8*cm, 3.5*cm], 
                     rowHeights=[0.9*cm] + [0.75*cm]*12 + [0.9*cm])
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
        decl_style = ParagraphStyle('Decl', parent=styles['Normal'], 
                                   fontSize=12, leading=16, alignment=4, 
                                   spaceBefore=10, spaceAfter=10)
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
        info_table = Table(info_data, colWidths=[4.5*cm, 7*cm, 2.5*cm, 5*cm], 
                          rowHeights=[0.8*cm]*5)
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

        # Log PDF generation analytics
        _log_event('pdf_generation', {
            'district': district,
            'total': int(total),
            'manager_name_hash': hashlib.sha256(data.get('manager_name', '').encode()).hexdigest()[:16]  # anonymized
        })

        # Return PDF
        pdf_buffer.seek(0)
        return send_file(pdf_buffer, as_attachment=True,
                        download_name=f"MNHC_Claim_{data.get('manager_name', 'User')}_{datetime.utcnow().strftime('%Y%m%d')}.pdf")

    except Exception as e:
        return str(e), 500

# ---------- RUN ----------
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
