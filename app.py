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

app = Flask(__name__)

# Capping Configuration
CAPS = {
    'opd': 1100,
    'anc': 200,
    'pnc': 50,
    'del': 30,
    'tb': 30,
    'epi': 200,
    'nut': 250,
    'ppfp': 20,
    'short': 60,
    'long': 30
}

RATES = {
    'opd': 400,
    'anc': 600,
    'pnc': 200,
    'del': 6500,
    'tb': 200,
    'epi': 100,
    'nut': 200,
    'ppfp': 300,
    'short': 150,
    'long': 400
}

# Simulated Ad Database
ADS_DB = {
    'Faisalabad': {'text': 'Advertise Here - Reach 3000+ Health Managers contact smartbiopk@gmail.com', 'link': '#'},
    'Lahore': {'text': 'Advertise Here - Reach 3000+ Health Managers smartbiopk@gmail.com', 'link': '#'},
    'default': {'text': 'Advertise Here - Reach 3000+ Health Managers smartbiopk@gmail.com', 'link': '/advertise'}
}

def format_date_ddmmyyyy(date_str):
    """Convert YYYY-MM-DD to DD/MM/YYYY format"""
    if not date_str or date_str == '':
        return ''
    try:
        # Parse the date (HTML date inputs come as YYYY-MM-DD)
        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
        # Return as DD/MM/YYYY
        return date_obj.strftime('%d/%m/%Y')
    except:
        # If already in different format or invalid, return as-is
        return date_str

@app.route('/')
def index():
    district = request.args.get('district', 'default')
    ad = ADS_DB.get(district, ADS_DB['default'])

    # Complete list of all 36 districts of Punjab, Pakistan
    districts = [
        'Attock', 'Bahawalnagar', 'Bahawalpur', 'Bhakkar', 'Chakwal', 'Chiniot',
        'Dera Ghazi Khan', 'Faisalabad', 'Gujranwala', 'Gujrat', 'Hafizabad',
        'Jhang', 'Jhelum', 'Kasur', 'Khanewal', 'Khushab', 'Lahore', 'Layyah',
        'Lodhran', 'Mandi Bahauddin', 'Mianwali', 'Multan', 'Muzaffargarh',
        'Nankana Sahib', 'Narowal', 'Okara', 'Pakpattan', 'Rahim Yar Khan',
        'Rajanpur', 'Rawalpindi', 'Sahiwal', 'Sargodha', 'Sheikhupura',
        'Sialkot', 'Toba Tek Singh', 'Vehari'
    ]

    return render_template('index.html', ad=ad, districts=districts, selected_district=district)

@app.route('/calculate', methods=['POST'])
def calculate():
    """AJAX endpoint for real-time calculation"""
    data = request.json
    results = {}
    total = 25000

    for key, rate in RATES.items():
        val = int(data.get(key, 0) or 0)
        cap = CAPS[key]
        actual = min(val, cap)
        amount = actual * rate
        total += amount
        results[key] = {
            'amount': amount,
            'capped': val > cap,
            'entered': val,
            'cap': cap
        }

    results['total'] = total
    return jsonify(results)

@app.route('/generate_pdf', methods=['POST'])
def generate_pdf():
    temp_sig_path = None
    try:
        data = request.form

        # Process signature
        signature_data = data.get('signature', '')
        if signature_data and ',' in signature_data:
            try:
                img_data = base64.b64decode(signature_data.split(',')[1])
                sig_image = Image.open(io.BytesIO(img_data))
                temp_sig_path = f"temp_sig_{datetime.now().strftime('%Y%m%d%H%M%S')}.png"
                sig_image.save(temp_sig_path)
            except Exception as e:
                print(f"Signature error: {e}")
                temp_sig_path = None

        # Generate PDF in memory
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

        # Format dates to DD/MM/YYYY
        period_start = format_date_ddmmyyyy(data.get('period_start', ''))
        period_end = format_date_ddmmyyyy(data.get('period_end', ''))
        claim_date = format_date_ddmmyyyy(data.get('date', ''))

        # Certification - 12pt
        cert_style = ParagraphStyle('Cert', parent=styles['Normal'],
                                  fontSize=12, leading=16, spaceAfter=12)
        cert = f"""It is certified that the following healthcare services have been provided at Mariam Nawaz Health Clinic <b>{data.get('clinic_name', '')}</b> under the supervision of the undersigned Health Manager during the period <b>{period_start}</b> to <b>{period_end}</b>."""
        elements.append(Paragraph(cert, cert_style))

        # Calculate values with capping
        values = {}
        total = 25000
        for key in RATES:
            val = int(data.get(key, 0) or 0)
            actual = min(val, CAPS[key])
            values[key] = actual * RATES[key]
            total += values[key]

        # Table
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

        table = Table(table_data,
                     colWidths=[1.3*cm, 8.5*cm, 2.4*cm, 2.8*cm, 3.5*cm],
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

        # Declaration - 12pt
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

        info_table = Table(info_data,
                          colWidths=[4.5*cm, 7*cm, 2.5*cm, 5*cm],
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

        # Add Signature if exists
        if temp_sig_path and os.path.exists(temp_sig_path):
            elements.append(Spacer(1, 0.4*cm))
            elements.append(RLImage(temp_sig_path, width=6*cm, height=1.5*cm))

        # Build PDF in memory
        doc.build(elements)

        # Send PDF as response
        pdf_buffer.seek(0)
        return send_file(pdf_buffer, as_attachment=True,
                       download_name=f"MNHC_Claim_{data.get('manager_name', 'User')}.pdf")

    except Exception as e:
        # Clean up on error
        try:
            if temp_sig_path and os.path.exists(temp_sig_path):
                os.remove(temp_sig_path)
        except:
            pass
        return str(e), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
