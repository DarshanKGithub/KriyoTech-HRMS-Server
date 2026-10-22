"""PDF and Email utilities for Payroll."""
import os
from io import BytesIO
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders


def generate_payslip_html(payslip_data: dict) -> str:
    """Generate HTML for payslip."""
    month_names = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    month_name = month_names[payslip_data['month'] - 1]
    
    components_html = ""
    if payslip_data.get('components'):
        for comp in payslip_data['components']:
            color = '#10b981' if comp['component_type'] == 'earning' else ('#ef4444' if comp['component_type'] == 'deduction' else '#f59e0b')
            components_html += f"""
            <tr>
                <td style="padding: 8px; border-bottom: 1px solid #e5e7eb;">{comp['component_name']}</td>
                <td style="padding: 8px; border-bottom: 1px solid #e5e7eb; text-align: right; color: {color}; font-weight: 500;">
                    ₹{comp['amount']:,.2f}
                </td>
            </tr>
            """
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{ font-family: Arial, sans-serif; color: #333; }}
            .container {{ max-width: 800px; margin: 0 auto; padding: 20px; }}
            .header {{ text-align: center; margin-bottom: 30px; border-bottom: 2px solid #4f4b9c; padding-bottom: 20px; }}
            .header h1 {{ margin: 0; color: #4f4b9c; font-size: 24px; }}
            .header p {{ margin: 5px 0; color: #666; font-size: 14px; }}
            .employee-info {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 30px; }}
            .info-box {{ background: #f9fafb; padding: 15px; border-radius: 5px; }}
            .info-box label {{ font-weight: bold; color: #4f4b9c; display: block; font-size: 12px; margin-bottom: 5px; }}
            .info-box value {{ font-size: 16px; }}
            .summary {{ display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 15px; margin-bottom: 30px; }}
            .summary-box {{ background: #f3f0ff; padding: 15px; border-radius: 5px; text-align: center; }}
            .summary-box label {{ font-weight: bold; color: #5b5f7a; display: block; font-size: 12px; margin-bottom: 5px; }}
            .summary-box value {{ font-size: 20px; font-weight: bold; color: #4f4b9c; }}
            .summary-box.deduction {{ background: #fee2e2; color: #991b1b; }}
            .summary-box.deduction value {{ color: #991b1b; }}
            .summary-box.tax {{ background: #fef3c7; }}
            .summary-box.tax value {{ color: #92400e; }}
            .summary-box.net {{ background: #dcfce7; }}
            .summary-box.net value {{ color: #166534; }}
            table {{ width: 100%; border-collapse: collapse; margin-bottom: 30px; }}
            th {{ background: #f9fafb; padding: 10px; text-align: left; font-weight: bold; border-bottom: 2px solid #e5e7eb; }}
            td {{ padding: 10px; border-bottom: 1px solid #e5e7eb; }}
            .footer {{ text-align: center; color: #999; font-size: 12px; margin-top: 40px; padding-top: 20px; border-top: 1px solid #e5e7eb; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>PAYSLIP</h1>
                <p>{month_name} {payslip_data['year']}</p>
            </div>
            
            <div class="employee-info">
                <div class="info-box">
                    <label>Employee ID</label>
                    <value>{payslip_data['employee_id']}</value>
                </div>
                <div class="info-box">
                    <label>Month</label>
                    <value>{month_name} {payslip_data['year']}</value>
                </div>
                <div class="info-box">
                    <label>Days Worked</label>
                    <value>{payslip_data['days_worked']}</value>
                </div>
                <div class="info-box">
                    <label>Days Absent</label>
                    <value>{payslip_data['days_absent']}</value>
                </div>
            </div>
            
            <div class="summary">
                <div class="summary-box">
                    <label>Gross Salary</label>
                    <value>₹{payslip_data['gross_salary']:,.2f}</value>
                </div>
                <div class="summary-box deduction">
                    <label>Deductions</label>
                    <value>₹{payslip_data['total_deductions']:,.2f}</value>
                </div>
                <div class="summary-box tax">
                    <label>Tax</label>
                    <value>₹{payslip_data['total_tax']:,.2f}</value>
                </div>
                <div class="summary-box net">
                    <label>Net Salary</label>
                    <value>₹{payslip_data['net_salary']:,.2f}</value>
                </div>
            </div>
            
            <table>
                <thead>
                    <tr>
                        <th>Component</th>
                        <th style="text-align: right;">Amount</th>
                    </tr>
                </thead>
                <tbody>
                    {components_html}
                </tbody>
            </table>
            
            <div class="footer">
                <p>Generated on {datetime.now().strftime('%d-%m-%Y %H:%M:%S')}</p>
                <p>This is a system-generated document.</p>
            </div>
        </div>
    </body>
    </html>
    """
    return html


def send_email(to_email: str, subject: str, body: str, attachment_path: str | None = None, attachment_name: str | None = None) -> bool:
    """Send email with optional attachment."""
    smtp_server = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
    smtp_port = int(os.getenv('SMTP_PORT', '587'))
    sender_email = os.getenv('SENDER_EMAIL')
    sender_password = os.getenv('SENDER_PASSWORD')
    
    if not sender_email or not sender_password:
        print(f"Warning: Email credentials not configured. Would send to {to_email}")
        return False
    
    try:
        message = MIMEMultipart()
        message['From'] = sender_email
        message['To'] = to_email
        message['Subject'] = subject
        
        message.attach(MIMEText(body, 'html'))
        
        if attachment_path and attachment_name:
            try:
                with open(attachment_path, 'rb') as attachment:
                    part = MIMEBase('application', 'octet-stream')
                    part.set_payload(attachment.read())
                    encoders.encode_base64(part)
                    part.add_header('Content-Disposition', f'attachment; filename= {attachment_name}')
                    message.attach(part)
            except Exception as e:
                print(f"Error attaching file: {e}")
        
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.send_message(message)
        
        return True
    except Exception as e:
        print(f"Error sending email: {e}")
        return False


def generate_payslip_pdf_bytes(payslip_data: dict) -> bytes:
    """Create a real, printable PDF. Never return HTML as application/pdf."""
    from io import BytesIO
    from xml.sax.saxutils import escape
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    output=BytesIO()
    doc=SimpleDocTemplate(output,pagesize=A4,rightMargin=42,leftMargin=42,topMargin=40,bottomMargin=40)
    styles=getSampleStyleSheet()
    rows=[Paragraph('KriyoHR | Payslip',styles['Title']),Paragraph('by KriyoTech Labs',styles['Normal']),Spacer(1,20)]
    rows.append(Paragraph(escape(str(payslip_data.get('employee_name','Employee'))),styles['Heading2']))
    rows.append(Paragraph(f"Period: {payslip_data['month']:02d}/{payslip_data['year']} | Status: {escape(str(payslip_data.get('status','draft')))}",styles['Normal']))
    rows.append(Paragraph(f"Attendance days: {payslip_data['days_worked']} | Unpaid days: {payslip_data['days_absent']}",styles['Normal']))
    rows.append(Spacer(1,20))
    data=[['Component','Type','Amount (INR)']]
    for item in payslip_data.get('components',[]):
        data.append([Paragraph(escape(str(item['component_name'])),styles['Normal']),item['component_type'],f"{float(item['amount']):,.2f}"])
    for label,key in [('Gross earnings','gross_salary'),('Deductions','total_deductions'),('Configured tax','total_tax'),('Net pay','net_salary')]:
        data.append([label,'',f"{float(payslip_data[key]):,.2f}"])
    table=Table(data,colWidths=[260,100,145],repeatRows=1)
    table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#183e32')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('ALIGN',(-1,1),(-1,-1),'RIGHT'),('PADDING',(0,0),(-1,-1),9),('LINEBELOW',(0,0),(-1,-1),.3,colors.HexColor('#dce5e0')),('BACKGROUND',(0,-1),(-1,-1),colors.HexColor('#e8f1e9'))]))
    rows.extend([table,Spacer(1,24),Paragraph('Earnings use the configured workweek, published holidays, recorded attendance and approved paid leave. This document does not confirm a bank transfer.',styles['Normal'])])
    doc.build(rows)
    value=output.getvalue()
    if not value.startswith(b'%PDF-'):
        raise RuntimeError('PDF generation failed')
    return value
