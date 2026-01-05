import os
import json
import psycopg2
from flask import Flask, render_template, request, jsonify
from psycopg2.extras import RealDictCursor
from datetime import datetime
import pytz
from dotenv import load_dotenv

# --- NEW AI LIBRARY (google-genai) ---
from google import genai
from google.genai import types

# Load environment variables
load_dotenv()

# Configure the New Gemini Client
client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))

app = Flask(__name__)

# Load questions
with open('final_hr_questions.json', 'r') as f:
    SURVEY_DATA = json.load(f)

def get_db_connection():
    # 1. Try to get the URL from the environment (Render/Production)
    db_url = os.environ.get('DATABASE_URL')
    
    # 2. Fallback for Local Testing (If .env fails)
    if not db_url:
        # REPLACE THIS WITH YOUR ACTUAL CONNECTION STRING IF NEEDED
        pass 
        
    conn = psycopg2.connect(db_url)
    return conn

def get_ist_time():
    """Returns current time in Indian Standard Time"""
    utc_now = datetime.now(pytz.utc)
    ist_tz = pytz.timezone('Asia/Kolkata')
    return utc_now.astimezone(ist_tz)

@app.route('/')
def index():
    return render_template('survey.html', survey_data=SURVEY_DATA)

@app.route('/submit', methods=['POST'])
def submit():
    form_data = request.form.to_dict()
    respondent_name = form_data.pop('respondent_name', 'Anonymous') or 'Anonymous'
    
    processed_answers = {}
    for key, value in form_data.items():
        try:
            processed_answers[key] = int(value)
        except ValueError:
            processed_answers[key] = value
    
    ist_now = get_ist_time()

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO survey_responses (respondent_name, answers, submitted_at) VALUES (%s, %s, %s)",
            (respondent_name, json.dumps(processed_answers), ist_now)
        )
        conn.commit()
        cur.close()
        conn.close()
        return render_template('survey.html', survey_data=SURVEY_DATA, success=True)
    except Exception as e:
        return f"Database Error: {e}"

@app.route('/admin')
def admin():
    if request.args.get('key') != 'mysecretadminpassword':
        return "Access Denied."

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM survey_responses ORDER BY submitted_at DESC")
    rows = cur.fetchall()
    cur.close()
    conn.close()

    ist_tz = pytz.timezone('Asia/Kolkata')
    processed_rows = []
    
    for row in rows:
        # 1. Convert Time to IST
        utc_time = row['submitted_at']
        if utc_time:
            if utc_time.tzinfo is None:
                utc_time = pytz.utc.localize(utc_time)
            row['submitted_at'] = utc_time.astimezone(ist_tz)

        # 2. Parse Answers
        answers = row['answers']
        cat_totals = {k: [] for k in SURVEY_DATA.keys()}
        
        for key, val in answers.items():
            if isinstance(val, int) and '_' in key:
                category = key.rsplit('_', 1)[0]
                if category in cat_totals:
                    cat_totals[category].append(val)
        
        # 3. Calculate Normalized Stats (MATCHING REPORT LOGIC EXACTLY)
        cat_averages = {}
        sum_of_category_averages = 0
        valid_categories_count = 0

        for cat, scores in cat_totals.items():
            if scores:
                avg = sum(scores) / len(scores)
                cat_averages[cat] = round(avg, 2)
                # Accumulate for Overall Score
                sum_of_category_averages += avg
                valid_categories_count += 1
            else:
                cat_averages[cat] = 0
        
        # 4. Calculate Overall Score (Normalized by Category)
        if valid_categories_count > 0:
            overall = round(sum_of_category_averages / valid_categories_count, 2)
        else:
            overall = 0
        
        # 5. Determine Strength/Weakness
        active_cats = {k:v for k,v in cat_averages.items() if v > 0}
        if active_cats:
            sorted_cats = sorted(active_cats.items(), key=lambda x: x[1], reverse=True)
            strength = sorted_cats[0]
            weakness = sorted_cats[-1]
        else:
            strength = ("N/A", 0)
            weakness = ("N/A", 0)

        row_dict = dict(row)
        row_dict['stats'] = {
            'averages': cat_averages,
            'strength': strength,
            'weakness': weakness,
            'overall': overall,
            'categories_list': list(cat_averages.keys()),
            'scores_list': list(cat_averages.values())
        }
        processed_rows.append(row_dict)

    return render_template('admin.html', responses=processed_rows, survey_data=SURVEY_DATA)

@app.route('/report')
def report():
    # SECURITY: Require secret key
    if request.args.get('key') != 'mysecretadminpassword':
        return "Access Denied."

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT answers FROM survey_responses")
    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        return "No data available to generate report."

    # --- CALCULATION ENGINE (NORMALIZED) ---
    
    # 1. Initialize storage
    category_scores = {category: [] for category in SURVEY_DATA.keys()}
    
    total_responses = len(rows)
    
    # 2. Collect all raw scores into their categories
    for row in rows:
        answers = row['answers']
        for key, value in answers.items():
            if not isinstance(value, int): continue

            # Parse key (e.g. "Creativity_1") -> "Creativity"
            if '_' in key:
                category_part = key.rsplit('_', 1)[0]
                if category_part in category_scores:
                    category_scores[category_part].append(value)

    # 3. Calculate Normalized Category Averages
    final_averages = {}
    valid_categories_count = 0
    sum_of_category_averages = 0

    for cat, scores in category_scores.items():
        if scores:
            # Average of questions in this category
            avg = sum(scores) / len(scores)
            final_averages[cat] = round(avg, 2)
            
            # Add to total for Overall Score calculation
            sum_of_category_averages += avg
            valid_categories_count += 1
        else:
            final_averages[cat] = 0

    # 4. Calculate Overall Engagement Score (NORMALIZED)
    if valid_categories_count > 0:
        overall_score = round(sum_of_category_averages / valid_categories_count, 2)
    else:
        overall_score = 0

    # 5. Find Strongest and Weakest Areas
    active_cats = {k:v for k,v in final_averages.items() if v > 0}
    sorted_cats = sorted(active_cats.items(), key=lambda x: x[1], reverse=True)
    
    strongest = sorted_cats[0] if sorted_cats else ("None", 0)
    weakest = sorted_cats[-1] if sorted_cats else ("None", 0)

    # IST Timestamp
    ist_now = get_ist_time()

    return render_template('report.html', 
                           averages=final_averages, 
                           total=total_responses,
                           overall=overall_score,
                           strongest=strongest,
                           weakest=weakest,
                           timestamp=ist_now.strftime('%Y-%m-%d %I:%M %p'))

# --- NEW ROUTE: AGGREGATE ORGANIZATION ANALYSIS ---
@app.route('/analyze_aggregate')
def analyze_aggregate():
    # 1. Fetch ALL Data
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT answers FROM survey_responses")
    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        return jsonify({"error": "No data available"}), 404

    # 2. Calculate Averages (Same logic as Report Route)
    category_scores = {category: [] for category in SURVEY_DATA.keys()}
    
    for row in rows:
        answers = row['answers']
        for key, value in answers.items():
            if not isinstance(value, int): continue
            if '_' in key:
                category_part = key.rsplit('_', 1)[0]
                if category_part in category_scores:
                    category_scores[category_part].append(value)

    final_averages = {}
    for cat, scores in category_scores.items():
        if scores:
            avg = sum(scores) / len(scores)
            final_averages[cat] = round(avg, 2)
        else:
            final_averages[cat] = 0

    # 3. Construct Prompt for the Organization
    # We send the category averages to the AI
    prompt_data = "\n".join([f"{cat}: {score}/5.0" for cat, score in final_averages.items()])

    system_prompt = f"""
    You are an expert Organizational Development Consultant and HR Strategist.
    You are analyzing the AGGREGATED survey results for the entire company.
    
    COMPANY WIDE SCORES (0-5 Scale):
    {prompt_data}
    
    INSTRUCTIONS:
    - Return ONLY raw HTML. Do not use Markdown backticks.
    - Tone: Strategic, executive-level, and objective.
    - Use <h3> for headers.
    
    REQUIRED OUTPUT FORMAT:
    
    <h3>Organizational Health Summary</h3>
    <p>(Provide a high-level narrative about the company culture. Is it high-performing? Toxic? Disconnected?)</p>
    
    <h3>Cultural Drivers</h3>
    <div style="display: flex; gap: 20px;">
        <div style="flex: 1;">
            <h4 style="color:#28a745; margin-bottom:5px;">Systemic Strengths</h4>
            <ul>
                <li>(Analyze the highest scoring categories. What does the company do right?)</li>
            </ul>
        </div>
        <div style="flex: 1;">
            <h4 style="color:#d9534f; margin-bottom:5px;">Systemic Weaknesses</h4>
            <ul>
                <li>(Analyze the lowest scoring categories. What are the root causes?)</li>
            </ul>
        </div>
    </div>
    
    <h3>Strategic Recommendations</h3>
    <p><strong>Top 3 Priorities for Leadership:</strong></p>
    <ul>
        <li><strong>[Priority 1]:</strong> (Actionable advice based on the data)</li>
        <li><strong>[Priority 2]:</strong> (Actionable advice)</li>
        <li><strong>[Priority 3]:</strong> (Actionable advice)</li>
    </ul>
    """

    # 4. Call Gemini
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash-lite',
            contents=system_prompt
        )
        return jsonify({"analysis": response.text})
    except Exception as e:
        print(f"Gemini API Error: {e}")
        return jsonify({"error": str(e)}), 500

# --- AI ANALYSIS ROUTE (Correct Model & Prompt) ---
@app.route('/analyze_response/<int:response_id>')
def analyze_response(response_id):
    # 1. Fetch Data
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute("SELECT * FROM survey_responses WHERE id = %s", (response_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()

    if not row:
        return jsonify({"error": "Response not found"}), 404

    # 2. Construct the text prompt
    answers = row['answers']
    prompt_data = ""
    
    for key, val in answers.items():
        if '_' in key and isinstance(val, int):
            parts = key.rsplit('_', 1)
            category = parts[0]
            index = int(parts[1]) - 1 
            
            try:
                question_text = SURVEY_DATA[category][index]
                prompt_data += f"[{category}] {question_text}: {val}/5\n"
            except:
                continue

    # 3. The HR Analyst System Prompt
    system_prompt = f"""
    You are an expert Organizational Psychologist and Senior HR Analyst.
    Analyze the following employee survey data to create a psychological profile.
    
    EMPLOYEE NAME: {row['respondent_name']}
    
    SURVEY DATA:
    {prompt_data}
    
    INSTRUCTIONS:
    - Return ONLY raw HTML. Do not use Markdown backticks (```html).
    - Tone: Professional, insightful, and direct.
    - formatting: Use <h3> for main headers. Use <strong> for emphasis.
    
    REQUIRED OUTPUT FORMAT:
    
    <h3>Executive Summary</h3>
    <p>(Provide a cohesive narrative summary of the employee's state of mind, connecting their highest satisfaction areas with their deepest frustrations.)</p>
    
    <h3>Psychological Drivers</h3>
    <p><strong>Motivations:</strong></p>
    <ul>
        <li><strong>[Motivation Name]:</strong> (Analyze high scores here. Explain WHY this drives them.)</li>
        <li><strong>[Motivation Name]:</strong> (Analyze high scores here.)</li>
    </ul>
    
    <p><strong>Frustrations:</strong></p>
    <ul>
        <li><strong>[Frustration Name]:</strong> (Analyze low scores here. Explain the psychological impact, e.g., anxiety, stagnation.)</li>
        <li><strong>[Frustration Name]:</strong> (Analyze low scores here.)</li>
    </ul>
    
    <h3>Risk Analysis</h3>
    <ul>
        <li><strong style="color:#d9534f">[Risk Category]:</strong> (Identify red flags, especially in Ethics, Leadership, or Safety. Explain the business risk.)</li>
    </ul>

    <h3>Action Plan</h3>
    <p><strong>Questions for 1-on-1 Meeting:</strong></p>
    <ul>
        <li>"Question 1..."</li>
        <li>"Question 2..."</li>
        <li>"Question 3..."</li>
    </ul>
    
    <p><strong>Organizational Improvements:</strong></p>
    <ul>
        <li>(Provide 2-3 specific systemic changes the company should make to address the root causes of this employee's dissatisfaction.)</li>
    </ul>
    """

    # 4. Call Gemini (Using Correct Model Name)
    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash-lite', # Corrected model name
            contents=system_prompt
        )
        return jsonify({"analysis": response.text})
    except Exception as e:
        print(f"Gemini API Error: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)