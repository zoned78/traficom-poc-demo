from flask import Flask, render_template, request, send_file
# Tuodaan kirjastot, mutta niitä käytetään vain jos asetus on päällä
from flask_mail import Mail, Message 
import xml.etree.ElementTree as ET
import zipfile
import io
import datetime
import uuid
import os

app = Flask(__name__)

# --- ASETUKSET ---

# OMINAISUUS: Sähköpostivahvistus (Feature Flag)
SEND_CONFIRMATION_EMAIL = False 

# SÄHKÖPOSTIPALVELIMEN ASETUKSET
app.config['MAIL_SERVER'] = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
app.config['MAIL_PORT'] = int(os.environ.get('MAIL_PORT', 587))
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get('MAIL_USERNAME')

mail = Mail(app)

# NAMESPACES
NS_BRIDGE = "http://eccairsportal.jrc.ec.europa.eu/ECCAIRS5_dataBridge.xsd"
NS_TYPES = "http://eccairsportal.jrc.ec.europa.eu/ECCAIRS5_dataTypes.xsd"

ET.register_namespace('', NS_BRIDGE)

def create_element(parent, tag_name, text_value):
    elem = ET.SubElement(parent, f"{{{NS_BRIDGE}}}{tag_name}")
    elem.text = str(text_value) if text_value else ""
    return elem

# ROUTES
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/sv')
def index_sv():
    return render_template('index_sv.html')

@app.route('/sme')
def index_sme():
    return render_template('index_sme.html')

@app.route('/generate', methods=['POST'])
def generate_report():
    # 1. HAETAAN DATA
    categories = request.form.getlist('category')
    event_types = request.form.getlist('event_type')
    
    data = {
        "headline": request.form.get('headline') or "Ilmoitus verkkolomakkeelta",
        "time": request.form.get('time'),
        "location": request.form.get('location') or "EFHK",
        "reg": request.form.get('reg') or "",
        "narrative": request.form.get('narrative') or "Ei kuvausta.",
        "contact": request.form.get('contact'),
        "severity": request.form.get('severity') or "300",
        "phase": request.form.get('phase'),
        "op_type": request.form.get('op_type'),
        "ac_category": request.form.get('ac_category'),
        "departure": request.form.get('departure'),
        "destination": request.form.get('destination')
    }

    if not data['time']:
        dt = datetime.datetime.now()
    else:
        dt = datetime.datetime.fromisoformat(data['time'])
    
    date_str = dt.strftime("%Y-%m-%d")
    time_str = dt.strftime("%H:%M:%S")

    # 2. XML RAKENNE
    root = ET.Element(f"{{{NS_BRIDGE}}}SET", {
        "Domain": "RIT",
        "TaxonomyName": "ECCAIRS Aviation",
        "TaxonomyVersion": "6.0.0.0",
        "Version": "1.0.0.0"
    })

    occurrence = ET.SubElement(root, f"{{{NS_BRIDGE}}}Occurrence")
    occ_attrs = ET.SubElement(occurrence, f"{{{NS_BRIDGE}}}ATTRIBUTES")
    
    create_element(occ_attrs, "Occurrence_Class", data['severity'])
    create_element(occ_attrs, "State_Area_Of_Occ", "81")
    create_element(occ_attrs, "Responsible_Entity", "2059")
    create_element(occ_attrs, "File_Number", f"WEB-{uuid.uuid4().hex[:8]}") 
    create_element(occ_attrs, "Location_Name", str(data['location']).upper())
    create_element(occ_attrs, "UTC_Date", date_str)
    create_element(occ_attrs, "UTC_Time", time_str)
    create_element(occ_attrs, "Headline", data['headline'])

    if categories:
        for cat_id in categories:
            create_element(occ_attrs, "Occurrence_Category", cat_id)
    else:
        create_element(occ_attrs, "Occurrence_Category", "98")

    entities = ET.SubElement(occurrence, f"{{{NS_BRIDGE}}}ENTITIES")

    # AIRCRAFT
    if (data['reg'] or data['phase'] or data['op_type'] or 
        data['departure'] or data['destination'] or data['ac_category']):
        
        ac_id = f"ID{uuid.uuid4().hex.upper()}"
        aircraft = ET.SubElement(entities, f"{{{NS_BRIDGE}}}Aircraft", {"ID": ac_id})
        ac_attrs = ET.SubElement(aircraft, f"{{{NS_BRIDGE}}}ATTRIBUTES")
        
        if data['reg']:
            reg_upper = str(data['reg']).upper()
            create_element(ac_attrs, "Call_Sign", reg_upper)
            create_element(ac_attrs, "Aircraft_Registration", reg_upper)
        else:
            create_element(ac_attrs, "Aircraft_Registration", "UNKNOWN")

        create_element(ac_attrs, "State_Of_Registry", "81")
        
        ac_cat_val = data['ac_category'] if data['ac_category'] else "7"
        create_element(ac_attrs, "Aircraft_Category", ac_cat_val)
        
        if data['phase']:
            create_element(ac_attrs, "Flight_Phase", data['phase'])
        if data['op_type']:
            create_element(ac_attrs, "Operation_Type", data['op_type'])
        if data['departure']:
            create_element(ac_attrs, "Last_Departure_Point", data['departure'])
        if data['destination']:
            create_element(ac_attrs, "Planned_Destination", data['destination'])

    # EVENTS
    if event_types:
        for ev_val in event_types:
            ev_id = f"ID{uuid.uuid4().hex.upper()}"
            event = ET.SubElement(entities, f"{{{NS_BRIDGE}}}Events", {"ID": ev_id})
            ev_attrs = ET.SubElement(event, f"{{{NS_BRIDGE}}}ATTRIBUTES")
            create_element(ev_attrs, "Event_Type", ev_val)

    # HISTORY
    hist_id = f"ID{uuid.uuid4().hex.upper()}"
    history = ET.SubElement(entities, f"{{{NS_BRIDGE}}}Reporting_History", {"ID": hist_id})
    hist_attrs = ET.SubElement(history, f"{{{NS_BRIDGE}}}ATTRIBUTES")
    
    create_element(hist_attrs, "Report_Identification", f"REP-{uuid.uuid4().hex[:6]}")
    create_element(hist_attrs, "Reporting_Entity", "6059")
    create_element(hist_attrs, "Reporting_Date", date_str)
    
    desc_elem = ET.SubElement(hist_attrs, f"{{{NS_BRIDGE}}}Reporter_S_Description")
    plain_text = ET.SubElement(desc_elem, f"{{{NS_TYPES}}}PlainText")
    plain_text.text = data['narrative']

    # --- NOTE (SÄHKÖPOSTI) ---
    # KORJATTU: Käytetään oikeita XSD-tageja: <Subject> ja <Note>
    if data['contact']:
        note_id = f"ID{uuid.uuid4().hex.upper()}"
        note = ET.SubElement(entities, f"{{{NS_BRIDGE}}}Note", {"ID": note_id})
        note_attrs = ET.SubElement(note, f"{{{NS_BRIDGE}}}ATTRIBUTES")
        
        # Attribute 608: XSD Tag = Subject
        create_element(note_attrs, "Subject", "Sähköposti")
        
        # Attribute 426: XSD Tag = Note (jonka sisällä PlainText)
        note_text_elem = ET.SubElement(note_attrs, f"{{{NS_BRIDGE}}}Note")
        plain_text_note = ET.SubElement(note_text_elem, f"{{{NS_TYPES}}}PlainText")
        plain_text_note.text = data['contact']

    # --- SÄHKÖPOSTIN LÄHETYS ---
    if SEND_CONFIRMATION_EMAIL and data['contact'] and app.config['MAIL_USERNAME']:
        try:
            msg = Message(
                subject="Vahvistus ilmoituksesta / Confirmation of Report",
                recipients=[data['contact']],
                body=f"""
Kiitos ilmoituksestasi! / Tack för din rapport!

Olemme vastaanottaneet seuraavat tiedot:
----------------------------------------
Otsikko: {data['headline']}
Aika: {data['time']}
Kuvaus: {data['narrative']}

Tämä on automaattinen vahvistusviesti.
                """
            )
            mail.send(msg)
        except Exception as e:
            print(f"Sähköpostivirhe: {str(e)}")

    # Zip ja lähetys
    xml_str = ET.tostring(root, encoding='utf-8', method='xml')
    memory_file = io.BytesIO()
    reg_clean = str(data['reg']).upper().replace(" ", "") if data['reg'] else "UNK"
    filename_base = f"report_{dt.strftime('%Y%m%d')}_{reg_clean}"
    
    with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zipf:
        zipf.writestr(f"{filename_base}.xml", xml_str)
    
    memory_file.seek(0)

    return send_file(
        memory_file,
        mimetype='application/zip',
        as_attachment=True,
        download_name=f"{filename_base}.e5x"
    )

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)