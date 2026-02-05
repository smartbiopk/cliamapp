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

# ---------- UPSTASH KV CONFIGURATION ----------
# Get environment variables from Vercel/Upstash integration
UPSTASH_REDIS_REST_URL = os.environ.get('KV_REST_API_URL')
UPSTASH_REDIS_REST_TOKEN = os.environ.get('KV_REST_API_TOKEN')

# Import Upstash Redis client
try:
    from upstash_redis import Redis
    redis_client = None
    if UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN:
        redis_client = Redis(url=UPSTASH_REDIS_REST_URL, token=UPSTASH_REDIS_REST_TOKEN)
        print("✓ Upstash KV connected successfully")
    else:
        print("✗ Upstash KV credentials not found, using fallback")
except ImportError:
    redis_client = None
    print("✗ upstash_redis not installed, using fallback storage")

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

# ---------- ANALYTICS STORAGE (UPSTASH KV) ----------
ANALYTICS_KEY = "mnhc_analytics_v2"

def _get_analytics_data():
    """Get analytics data from Upstash KV or fallback to empty structure"""
    if redis_client:
        try:
            data = redis_client.get(ANALYTICS_KEY)
            if data:
                return json.loads(data)
        except Exception as e:
            print(f"KV read error: {e}")
    
    # Fallback structure
    return {
        'page_views': [],
        'calculations': [],
        'pdf_generations': [],
        'district_stats': {},
        'monthly_claims': {}
    }

def _save_analytics_data(data):
    """Save analytics data to Upstash KV"""
    if redis_client:
        try:
            redis_client.set(ANALYTICS_KEY, json.dumps(data))
            return True
        except Exception as e:
            print(f"KV write error: {e}")
    return False

def _log_event(event_type, event_data):
    """Log an analytics event to Upstash KV"""
    try:
        analytics = _get_analytics_data()
        
        timestamp = datetime.utcnow().isoformat()
        full_event = {
            'timestamp': timestamp,
            'date': datetime.utcnow().strftime('%Y-%m-%d'),
            'time': datetime.utcnow().strftime('%H:%M:%S'),
            'month': datetime.utcnow().strftime('%Y-%m'),
            'year': datetime.utcnow().year,
            'type': event_type
        }
        full_event.update(event_data)
        
        # Add to event lists (keep last 1000 events per type to prevent bloat)
        if event_type == 'page_view':
            analytics['page_views'].append(full_event)
            analytics['page_views'] = analytics['page_views'][-1000:]  # Keep last 1000
        elif event_type == 'calculation':
            analytics['calculations'].append(full_event)
            analytics['calculations'] = analytics['calculations'][-1000:]
        elif event_type == 'pdf_generation':
            analytics['pdf_generations'].append(full_event)
            analytics['pdf_generations'] = analytics['pdf_generations'][-1000:]
        
        # Update district stats
        district = event_data.get('district', 'unknown')
        if district not in analytics['district_stats']:
            analytics['district_stats'][district] = {'views': 0, 'calculations': 0, 'pdfs': 0, 'total_amount': 0}
        
        if event_type == 'page_view':
            analytics['district_stats'][district]['views'] += 1
        elif event_type == 'calculation':
            analytics['district_stats'][district]['calculations'] += 1
            analytics['district_stats'][district]['total_amount'] += event_data.get('total', 0)
        elif event_type == 'pdf_generation':
            analytics['district_stats'][district]['pdfs'] += 1
        
        # Monthly aggregation
        month_key = datetime.utcnow().strftime('%Y-%m')
        if month_key not in analytics['monthly_claims']:
            analytics['monthly_claims'][month_key] = {'count': 0, 'total_amount': 0, 'districts': {}}
        
        if event_type in ['calculation', 'pdf_generation']:
            analytics['monthly_claims'][month_key]['count'] += 1
            analytics['monthly_claims'][month_key]['total_amount'] += event_data.get('total', 0)
            if district not in analytics['monthly_claims'][month_key]['districts']:
                analytics['monthly_claims'][month_key]['districts'][district] = 0
            analytics['monthly_claims'][month_key]['districts'][district] += 1
        
        # Save to KV
        _save_analytics_data(analytics)
        
    except Exception as e:
        print(f"Analytics logging error: {e}")

def _get_analytics_summary():
    """Get summary for pharma presentation"""
    try:
        analytics = _get_analytics_data()
        
        total_views = len(analytics['page_views'])
        total_calcs = len(analytics['calculations'])
        total_pdfs = len(analytics['pdf_generations'])
        unique_districts = len([d for d in analytics['district_stats'].keys() if d != 'unknown'])
        
        # Calculate active users (last 30 days)
        recent_cutoff = datetime.utcnow().timestamp() - (30 * 24 * 60 * 60)
        active_districts = set()
        
        for pv in analytics['page_views']:
            try:
                if datetime.fromisoformat(pv['timestamp']).timestamp() > recent_cutoff:
                    active_districts.add(pv.get('district', 'unknown'))
            except:
                pass
        
        # Calculate total platform value
        total_value = sum(d.get('total_amount', 0) for d in analytics['district_stats'].values())
        
        return {
            'total_page_views': total_views,
            'total_calculations': total_calcs,
            'total_pdfs_generated': total_pdfs,
            'unique_districts_active': unique_districts,
            'monthly_active_districts': len(active_districts),
            'total_platform_value': total_value,
            'district_breakdown': analytics['district_stats'],
            'monthly_trends': analytics['monthly_claims'],
            'last_updated': datetime.utcnow().isoformat(),
            'storage_type': 'Upstash KV' if redis_client else 'Fallback (Memory)'
        }
    except Exception as e:
        return {'error': str(e), 'storage_type': 'Error'}

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
        'ip_hash': hashlib.sha256(request.remote_addr.encode()).hexdigest()[:16],
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
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>MNHC Platform Analytics | SmartBio Solutions</title>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            :root {{
                --primary: #2E7D32;
                --primary-dark: #1B5E20;
                --accent: #1976D2;
                --bg: #f5f7fa;
                --card: #ffffff;
                --text: #2c3e50;
                --text-light: #607d8b;
            }}
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{ 
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                background: var(--bg);
                color: var(--text);
                line-height: 1.6;
            }}
            .container {{ max-width: 1200px; margin: 0 auto; padding: 40px 20px; }}
            header {{ 
                background: linear-gradient(135deg, var(--primary) 0%, var(--primary-dark) 100%);
                color: white;
                padding: 40px 20px;
                text-align: center;
                margin-bottom: 40px;
            }}
            header h1 {{ font-size: 2.5rem; margin-bottom: 10px; }}
            header p {{ opacity: 0.9; font-size: 1.1rem; }}
            .stats-grid {{ 
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
                gap: 24px;
                margin-bottom: 40px;
            }}
            .stat-card {{
                background: var(--card);
                padding: 30px;
                border-radius: 16px;
                box-shadow: 0 4px 6px rgba(0,0,0,0.07);
                text-align: center;
                transition: transform 0.2s;
            }}
            .stat-card:hover {{ transform: translateY(-4px); }}
            .stat-icon {{
                width: 60px;
                height: 60px;
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
                margin: 0 auto 16px;
                font-size: 28px;
            }}
            .stat-card:nth-child(1) .stat-icon {{ background: #e3f2fd; color: #1976d2; }}
            .stat-card:nth-child(2) .stat-icon {{ background: #fce4ec; color: #c2185b; }}
            .stat-card:nth-child(3) .stat-icon {{ background: #e8f5e9; color: #388e3c; }}
            .stat-card:nth-child(4) .stat-icon {{ background: #fff3e0; color: #f57c00; }}
            .stat-card:nth-child(5) .stat-icon {{ background: #f3e5f5; color: #7b1fa2; }}
            .stat-number {{ font-size: 2.5rem; font-weight: 700; color: var(--text); margin-bottom: 8px; }}
            .stat-label {{ color: var(--text-light); font-size: 0.95rem; text-transform: uppercase; letter-spacing: 0.5px; }}
            .section {{
                background: var(--card);
                padding: 30px;
                border-radius: 16px;
                box-shadow: 0 4px 6px rgba(0,0,0,0.07);
                margin-bottom: 30px;
            }}
            .section h2 {{
                font-size: 1.5rem;
                margin-bottom: 24px;
                padding-bottom: 12px;
                border-bottom: 2px solid var(--bg);
                display: flex;
                align-items: center;
                gap: 12px;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                margin-top: 20px;
            }}
            th, td {{
                padding: 16px;
                text-align: left;
                border-bottom: 1px solid #e0e0e0;
            }}
            th {{
                background: var(--primary);
                color: white;
                font-weight: 600;
                text-transform: uppercase;
                font-size: 0.85rem;
                letter-spacing: 0.5px;
            }}
            tr:hover {{ background: #f5f5f5; }}
            .badge {{
                display: inline-block;
                padding: 4px 12px;
                border-radius: 20px;
                font-size: 0.85rem;
                font-weight: 600;
            }}
            .badge-success {{ background: #e8f5e9; color: #2e7d32; }}
            .badge-info {{ background: #e3f2fd; color: #1976d2; }}
            .footer {{
                text-align: center;
                padding: 40px;
                color: var(--text-light);
                border-top: 1px solid #e0e0e0;
                margin-top: 40px;
            }}
            .cta-box {{
                background: linear-gradient(135deg, var(--accent) 0%, #0d47a1 100%);
                color: white;
                padding: 40px;
                border-radius: 16px;
                text-align: center;
                margin-top: 40px;
            }}
            .cta-box h3 {{ font-size: 1.75rem; margin-bottom: 16px; }}
            .cta-box a {{
                display: inline-block;
                background: white;
                color: var(--accent);
                padding: 12px 32px;
                border-radius: 30px;
                text-decoration: none;
                font-weight: 600;
                margin-top: 16px;
            }}
            .status-badge {{
                display: inline-block;
                padding: 4px 12px;
                border-radius: 20px;
                font-size: 0.75rem;
                background: {'#e8f5e9' if 'Upstash' in summary.get('storage_type', '') else '#fff3e0'};
                color: {'#2e7d32' if 'Upstash' in summary.get('storage_type', '') else '#f57c00'};
                margin-left: 12px;
            }}
            @media (max-width: 768px) {{
                .stats-grid {{ grid-template-columns: 1fr; }}
                header h1 {{ font-size: 1.75rem; }}
            }}
        </style>
    </head>
    <body>
        <header>
            <h1>📊 MNHC Health Platform Analytics</h1>
            <p>Real-time engagement metrics for pharmaceutical advertising partners</p>
        </header>
        
        <div class="container">
            <div style="text-align: center; margin-bottom: 30px; color: var(--text-light);">
                Storage: <span class="status-badge">{summary.get('storage_type', 'Unknown')}</span>
                | Last Updated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}
            </div>
            
            <div class="stats-grid">
                <div class="stat-card">
                    <div class="stat-icon">👁️</div>
                    <div class="stat-number">{summary.get('total_page_views', 0):,}</div>
                    <div class="stat-label">Total Page Views</div>
                </div>
                <div class="stat-card">
                    <div class="stat-icon">🧮</div>
                    <div class="stat-number">{summary.get('total_calculations', 0):,}</div>
                    <div class="stat-label">Claims Calculated</div>
                </div>
                <div class="stat-card">
                    <div class="stat-icon">📄</div>
                    <div class="stat-number">{summary.get('total_pdfs_generated', 0):,}</div>
                    <div class="stat-label">PDFs Generated</div>
                </div>
                <div class="stat-card">
                    <div class="stat-icon">🏥</div>
                    <div class="stat-number">{summary.get('unique_districts_active', 0)}</div>
                    <div class="stat-label">Active Districts</div>
                </div>
                <div class="stat-card">
                    <div class="stat-icon">💰</div>
                    <div class="stat-number">PKR {summary.get('total_platform_value', 0):,}</div>
                    <div class="stat-label">Total Claim Value</div>
                </div>
            </div>
            
            <div class="section">
                <h2>🏥 District-Level Engagement</h2>
                <table>
                    <tr>
                        <th>District</th>
                        <th style="text-align: center;">Page Views</th>
                        <th style="text-align: center;">Calculations</th>
                        <th style="text-align: center;">PDFs Generated</th>
                        <th style="text-align: right;">Est. Claim Value (PKR)</th>
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
                    <td style="text-align: center;">{stats.get('views', 0):,}</td>
                    <td style="text-align: center;">{stats.get('calculations', 0):,}</td>
                    <td style="text-align: center;">{stats.get('pdfs', 0):,}</td>
                    <td style="text-align: right;"><strong>PKR {stats.get('total_amount', 0):,}</strong></td>
                </tr>
            """
    
    html += f"""
                </table>
            </div>
            
            <div class="section">
                <h2>📈 Monthly Trends</h2>
                <table>
                    <tr>
                        <th>Month</th>
                        <th style="text-align: center;">Total Interactions</th>
                        <th style="text-align: right;">Total Claim Value</th>
                        <th>Top Districts</th>
                    </tr>
    """
    
    monthly = summary.get('monthly_trends', {})
    for month in sorted(monthly.keys(), reverse=True)[:6]:
        data = monthly[month]
        top_districts = sorted(data.get('districts', {}).items(), key=lambda x: x[1], reverse=True)[:3]
        top_dist_str = ', '.join([f"{d} ({c})" for d, c in top_districts])
        
        html += f"""
            <tr>
                <td><span class="badge badge-info">{month}</span></td>
                <td style="text-align: center;">{data.get('count', 0):,}</td>
                <td style="text-align: right;"><strong>PKR {data.get('total_amount', 0):,}</strong></td>
                <td>{top_dist_str}</td>
            </tr>
        """
    
    html += """
                </table>
            </div>
            
            <div class="cta-box">
                <h3>🎯 Advertise on MNHC Platform</h3>
                <p>Reach 3,000+ Health Managers across 36 districts of Punjab</p>
                <p style="margin-top: 10px; opacity: 0.9;">Premium ad placement available on calculator pages</p>
                <a href="mailto:smartbiopk@gmail.com?subject=MNHC Advertising Inquiry">Contact Us</a>
            </div>
            
            <div class="footer">
                <p><strong>MNHC Claim Portal</strong> | Powered by SmartBio Solutions</p>
                <p style="margin-top: 8px; font-size: 0.9rem;">
                    Privacy-compliant analytics | No personal health data collected
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

@app.route('/analytics/reset', methods=['POST'])
def reset_analytics():
    """Reset analytics data (protected - for admin use)"""
    # Simple protection - you should add proper auth in production
    secret = request.headers.get('X-Admin-Secret')
    if secret != os.environ.get('ADMIN_SECRET', 'your-secret-key'):
        return jsonify({'error': 'Unauthorized'}), 401
    
    if redis_client:
        try:
            redis_client.delete(ANALYTICS_KEY)
            return jsonify({'message': 'Analytics reset successful'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    return jsonify({'error': 'KV not available'}), 500

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
            'manager_name_hash': hashlib.sha256(data.get('manager_name', '').encode()).hexdigest()[:16]
        })

        # Return PDF
        pdf_buffer.seek(0)
        return send_file(pdf_buffer, as_attachment=True,
                        download_name=f"MNHC_Claim_{data.get('manager_name', 'User')}_{datetime.utcnow().strftime('%Y%m%d')}.pdf")

    except Exception as e:
        import traceback
        print(f"PDF Generation Error: {str(e)}")
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

# ---------- RUN ----------
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
