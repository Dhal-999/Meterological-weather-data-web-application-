from flask import Flask, render_template, request, send_file, session, redirect, url_for
import pandas as pd
import io
from datetime import datetime
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from io import BytesIO
import zipfile
import socket
import webbrowser
from threading import Timer

app = Flask(__name__)
app.secret_key = 'supersecretkey'

APP_VERSION = "v1.2"
DEVELOPER = {
    "team": "MET Grp-3",
    "organization": "DRDO"
}

@app.route('/', methods=['GET', 'POST'])
def index(): 
    result = []
    error = None
    filenames = session.get("filenames", [])
    df_map = {}
    metadata_map = {}

    if 'csv_data' in session:
        for fname, csv_str in session['csv_data'].items():
            df_map[fname] = pd.read_csv(io.StringIO(csv_str))

    if request.method == 'POST':
        remove_filename = request.form.get("remove_file")
        if remove_filename:
            filenames = [f for f in filenames if f != remove_filename]
            if 'csv_data' in session and remove_filename in session['csv_data']:
                del session['csv_data'][remove_filename]
            session['filenames'] = filenames
            return redirect(url_for("index"))

        uploaded_files = request.files.getlist('files')
        if uploaded_files and any(file.filename != '' for file in uploaded_files):
            if 'csv_data' not in session:
                session['csv_data'] = {}
            for file in uploaded_files:
                if file.filename != '':
                    df = pd.read_csv(file)
                    session['csv_data'][file.filename] = df.to_csv(index=False)
                    df_map[file.filename] = df
                    if file.filename not in filenames:
                        filenames.append(file.filename)
            session['filenames'] = filenames
            session['last_updated'] = datetime.now().strftime('%d %B %Y, %I:%M %p')

        for fname, df in df_map.items():
            metadata_map[fname] = {
                "rows": df.shape[0],
                "columns": list(df.columns)
            }

        step_input = request.form.get('altitude', '')
        if not df_map:
            error = "Please upload at least one CSV file."
        else:
            try:
                step = float(step_input.strip())
                if step <= 0:
                    raise ValueError("Step must be a positive number.")

                results = []
                for fname, df in df_map.items():
                    if 'Altitude_m' not in df.columns:
                        raise ValueError(f"File '{fname}' missing 'Altitude_m' column.")

                    altitudes = df['Altitude_m'].dropna().unique()
                    max_alt = altitudes.max()
                    step_points = np.arange(0, max_alt + 1, step)

                    for alt in step_points:
                        idx = (df['Altitude_m'] - alt).abs().idxmin()
                        closest_row = df.loc[idx]
                        matched_altitude = closest_row['Altitude_m']
                        altitude_diff = matched_altitude - alt

                        row = {
                            'Dataset': fname,
                            'Input_Altitude': alt,
                            'Matched_Altitude_m': matched_altitude,
                            'Altitude_Diff_m': altitude_diff,
                            'Temperature_K': closest_row.get('Temperature_K', 'N/A'),
                            'Pressure_hPa': closest_row.get('Pressure_hPa', 'N/A'),
                            'Humidity_percent': closest_row.get('Humidity_percent', 'N/A'),
                            'WindSpeed_knots': closest_row.get('WindSpeed_knots', 'N/A'),
                            'WindDirection_deg': closest_row.get('WindDirection_deg', 'N/A')
                        }
                        results.append(row)

                result = results
                session['result'] = pd.DataFrame(result).to_csv(index=False)
            except Exception as e:
                error = f"Error processing input: {str(e)}"

    return render_template('index.html',
                           result=result,
                           error=error,
                           filenames=filenames,
                           metadata_map=metadata_map,
                           last_updated=session.get("last_updated"),
                           app_version=APP_VERSION,
                           developer=DEVELOPER)

@app.route('/download_csv')
def download_csv():
    if 'result' not in session:
        return "No data to download. Please submit form first.", 400
    csv_buffer = io.BytesIO(session['result'].encode('utf-8'))
    return send_file(csv_buffer, mimetype='text/csv', as_attachment=True, download_name='result.csv')


@app.route('/download_all')
def download_all():
    if 'result' not in session:
        return "No data to download. Please submit form first.", 400

    df = pd.read_csv(io.StringIO(session['result']))
    zip_buffer = BytesIO()

    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zipf:
        # Add CSV to ZIP
        csv_bytes = df.to_csv(index=False).encode('utf-8')
        zipf.writestr("result.csv", csv_bytes)

        # Generate PDF with plots
        pdf_buffer = BytesIO()
        with PdfPages(pdf_buffer) as pdf:
            x = df["Input_Altitude"]
            graphs = [
                ('Temperature_K', 'Temperature (K)'),
                ('Pressure_hPa', 'Pressure (hPa)'),
                ('Humidity_percent', 'Humidity (%)'),
                ('WindSpeed_knots', 'Wind Speed (knots)'),
                ('WindDirection_deg', 'Wind Direction (°)'),
                ('Matched_Altitude_m', 'Matched Altitude (m)')
            ]
            for col, title in graphs:
                if col in df.columns:
                    plt.figure(figsize=(10, 5))
                    plt.plot(x, df[col], marker='o')
                    plt.title(title)
                    plt.xlabel("Input Altitude (m)")
                    plt.ylabel(title)
                    plt.grid(True)
                    pdf.savefig()
                    plt.close()
        pdf_buffer.seek(0)
        zipf.writestr("graphs.pdf", pdf_buffer.read())

    zip_buffer.seek(0)
    return send_file(zip_buffer, mimetype='application/zip',
                     as_attachment=True, download_name='graphs_and_csv.zip')

@app.route('/clear')
def clear_session():
    """Clears the entire session, removing all uploaded files and results."""
    session.clear()
    return redirect(url_for('index'))

def find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]

def open_browser(port):
    webbrowser.open_new(f"http://127.0.0.1:{port}")

if __name__ == '__main__':
    port = find_free_port()
    Timer(1, open_browser, args=(port,)).start()
    app.run(host="127.0.0.1", port=port, debug=False)