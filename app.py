from flask import Flask, render_template, request, send_file
import xml.etree.ElementTree as ET
import zipfile
import io
import datetime
import uuid
import os

app = Flask(__name__)

# NAMESPACES
NS_BRIDGE = "http://eccairsportal.jrc.ec.europa.eu/ECCAIRS5_dataBridge.xsd"
NS_TYPES = "http://eccairsportal.jrc.ec.europa.eu/ECCAIRS5_dataTypes.xsd"

ET.register_namespace('', NS_BRIDGE)

# --- MAPPING: Lomakkeen koodi -> ECCAIRS Value ID ---
# Lähde: E2 Occurrence entity 15052025 (5).xlsx (Attribute ID 430)
CATEGORY_MAPPING = {
    "AMAN": "1",          # Abrupt maneuvre
    "ARC": "2",           # Abnormal runway contact
    "CFIT": "3",          # Controlled flight into or toward terrain
    "EVAC": "4",          # Evacuation
    "F-NI": "5",          # Fire/smoke (non-impact)
    "F-POST": "6",        # Fire/smoke (post-impact)
    "FUEL": "7",          # Fuel related
    "RAMP": "8",          # Ground Handling
    "GCOL": "9",          # Ground Collision
    "ICE": "10",          # Icing
    "LALT": "11",         # Low altitude operations
    "LOC-G": "12",        # Loss of control - ground
    "LOC-I": "13",        # Loss of control - inflight
    "AIRPROX": "14",      # MAC: Airprox/ACAS alert/loss of separation (Value ID 14)
    "MAC": "14",          # Alias samalle (jos lomakkeella käytetään tätä)
    "RE": "15",           # Runway excursion
    "SCF-NP": "18",       # System/component failure [non-powerplant]
    "SCF-PP": "19",       # System/component failure [powerplant]
    "SEC": "20",          # Security related
    "TURB": "21",         # Turbulence encounter
    "USOS": "22",         # Undershoot/overshoot
    "WSTRW": "23",        # Windshear or thunderstorm
    "ADRM": "24",         # Aerodrome
    "ATM": "25",          # ATM/CNS
    "CABIN": "26",        # Cabin safety events
    "WILD": "27",         # Collision Wildlife
    "RI": "28",           # Runway incursion
    "BIRD": "29",         # Birdstrike
    "OTHR": "98",         # Other
    "UNK": "99",          # Unknown or undetermined
    "UIMC": "100",        # Unintended flight in IMC
    "EXTL": "101",        # External load related occurrences
    "CTOL": "102",        # Collision with obstacle(s) during take-off and landing
    "LOLI": "103",        # Loss of lifting conditions en-route
    "GTOW": "104",        # Glider towing related events
    "MED": "105",         # Medical
    "NAV": "106",         # Navigation error
    
    # Apukoodit lomaketta varten
    "UAS": "98"           # Droonit menevät yleensä OTHR (98) tai MAC (14) alle.
}

def create_element(parent, tag_name, text_value):
    elem = ET.SubElement(parent, f"{{{NS_BRIDGE}}}{tag_name}")
    elem.text = str(text_value) if text_value else ""
    return elem

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/generate', methods=['POST'])
def generate_report():
    data = {
        "headline": request.form.get('headline') or "Ilmoitus verkkolomakkeelta",
        "time": request.form.get('time'),
        "location": request.form.get('location') or "EFHK",
        "reg": request.form.get('reg') or "",
        "category": request.form.get('category'),
        "narrative": request.form.get('narrative') or "Ei kuvausta.",
        "contact": request.form.get('contact'),
        "severity": request.form.get('severity') or "300",
        "phase": request.form.get('phase'),
        "event_type": request.form.get('event_type')
    }

    if not data['time']:
        dt = datetime.datetime.now()
    else:
        dt = datetime.datetime.fromisoformat(data['time'])
    
    date_str = dt.strftime("%Y-%m-%d")
    time_str = dt.strftime("%H:%M:%S")

    # XML Setup
    root = ET.Element(f"{{{NS_BRIDGE}}}SET", {
        "Domain": "RIT",
        "TaxonomyName": "ECCAIRS Aviation",
        "TaxonomyVersion": "6.0.0.0",
        "Version": "1.0.0.0"
    })

    # Occurrence
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

    # CATEGORY (Tämä käyttää nyt kattavaa listaa)
    category_id = CATEGORY_MAPPING.get(data['category'], "98")
    create_element(occ_attrs, "Occurrence_Category", category_id)

    # Entities
    entities = ET.SubElement(occurrence, f"{{{NS_BRIDGE}}}ENTITIES")

    # Aircraft
    if data['reg'] or data['phase']:
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
        create_element(ac_attrs, "Aircraft_Category", "17")
        
        if data['phase']:
            create_element(ac_attrs, "Flight_Phase", data['phase'])

    # Events
    if data['event_type']:
        ev_id = f"ID{uuid.uuid4().hex.upper()}"
        event = ET.SubElement(entities, f"{{{NS_BRIDGE}}}Events", {"ID": ev_id})
        ev_attrs = ET.SubElement(event, f"{{{NS_BRIDGE}}}ATTRIBUTES")
        create_element(ev_attrs, "Event_Type", data['event_type'])

    # Reporting History
    hist_id = f"ID{uuid.uuid4().hex.upper()}"
    history = ET.SubElement(entities, f"{{{NS_BRIDGE}}}Reporting_History", {"ID": hist_id})
    hist_attrs = ET.SubElement(history, f"{{{NS_BRIDGE}}}ATTRIBUTES")
    
    create_element(hist_attrs, "Report_Identification", f"REP-{uuid.uuid4().hex[:6]}")
    create_element(hist_attrs, "Reporting_Entity", "6059")
    create_element(hist_attrs, "Reporting_Date", date_str)
    
    desc_elem = ET.SubElement(hist_attrs, f"{{{NS_BRIDGE}}}Reporter_S_Description")
    plain_text = ET.SubElement(desc_elem, f"{{{NS_TYPES}}}PlainText")
    plain_text.text = data['narrative']

    # Packaging
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