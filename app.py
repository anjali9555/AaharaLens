import os
import json
import base64
import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from datetime import datetime, date, timedelta

# Page Configuration
st.set_page_config(
    page_title="AaharaLens | AI Nutrition Intelligence",
    page_icon="🥗",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Backend Endpoint Configuration
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

# ================= CUSTOM SAAS STYLING =================
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');

    html, body, [class*="css"] {
        font-family: 'Plus Jakarta Sans', sans-serif;
    }

    .main-header {
        background: linear-gradient(135deg, #0F2027 0%, #203A43 50%, #2C5364 100%);
        padding: 24px 32px;
        border-radius: 16px;
        color: white;
        margin-bottom: 24px;
        box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.1), 0 8px 10px -6px rgba(0, 0, 0, 0.1);
    }

    .nutrition-card {
        background: #ffffff;
        border: 1px solid #E2E8F0;
        border-radius: 14px;
        padding: 20px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
        margin-bottom: 16px;
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }

    .nutrition-card:hover {
        transform: translateY(-2px);
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.08);
    }

    .macro-pill {
        display: inline-block;
        padding: 6px 14px;
        border-radius: 20px;
        font-size: 13px;
        font-weight: 700;
        margin-right: 8px;
        margin-bottom: 8px;
    }
    .pill-protein { background-color: #EBF8FF; color: #2B6CB0; border: 1px solid #BEE3F8; }
    .pill-carbs { background-color: #FEFCBF; color: #B7791F; border: 1px solid #FAF089; }
    .pill-fat { background-color: #FED7D7; color: #C53030; border: 1px solid #FEB2B2; }
    .pill-fiber { background-color: #C6F6D5; color: #22543D; border: 1px solid #9AE6B4; }
    .pill-score { background-color: #E9D8FD; color: #553C9A; border: 1px solid #D6BCFA; }

    .stButton>button {
        border-radius: 10px;
        font-weight: 600;
        height: 44px;
        transition: all 0.2s ease;
    }

    .source-badge {
        font-size: 11px;
        padding: 3px 8px;
        border-radius: 6px;
        background-color: #EDF2F7;
        color: #4A5568;
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)

# ================= SESSION STATE INITIALIZATION =================
if "auth_token" not in st.session_state:
    st.session_state.auth_token = None
if "current_user" not in st.session_state:
    st.session_state.current_user = None
if "chat_messages" not in st.session_state:
    st.session_state.chat_messages = []
if "chat_conv_id" not in st.session_state:
    st.session_state.chat_conv_id = f"conv_{int(datetime.now().timestamp())}"

# ================= API CLIENT HELPER =================
def api_request(method: str, endpoint: str, data=None, files=None, params=None):
    headers = {}
    if st.session_state.auth_token:
        headers["Authorization"] = f"Bearer {st.session_state.auth_token}"

    url = f"{BACKEND_URL}{endpoint}"
    try:
        if method.upper() == "GET":
            return requests.get(url, headers=headers, params=params, timeout=25)
        elif method.upper() == "POST":
            if files:
                return requests.post(url, headers=headers, data=data, files=files, params=params, timeout=40)
            return requests.post(url, headers=headers, json=data, params=params, timeout=30)
        elif method.upper() == "PUT":
            return requests.put(url, headers=headers, json=data, timeout=25)
        elif method.upper() == "DELETE":
            return requests.delete(url, headers=headers, timeout=20)
    except requests.exceptions.ConnectionError:
        st.error("⚠️ Backend server is offline. Please launch FastAPI (`uvicorn src.main:app --port 8000`).")
        return None
    except requests.exceptions.Timeout:
        st.error("⏱️ Request timed out. External AI provider or database took too long to respond.")
        return None
    except Exception as e:
        st.error(f"Network error: {str(e)}")
        return None

# ================= SIDEBAR NAVIGATION =================
with st.sidebar:
    st.markdown("""
        <div style="background: linear-gradient(135deg, #059669 0%, #047857 100%); padding: 18px; border-radius: 12px; color: white; text-align: center; margin-bottom: 12px;">
            <div style="font-size: 32px; line-height: 1.2;">🥗</div>
            <div style="font-weight: 800; font-size: 20px; letter-spacing: -0.5px;">AaharaLens</div>
            <div style="font-size: 11px; opacity: 0.9; margin-top: 4px;">Multimodal AI Nutrition Intelligence</div>
        </div>
    """, unsafe_allow_html=True)
    st.divider()

    if st.session_state.current_user:
        st.success(f"👤 Logged in: **{st.session_state.current_user.get('full_name', 'User')}**")
        if st.button("🚪 Logout", use_container_width=True):
            st.session_state.auth_token = None
            st.session_state.current_user = None
            st.rerun()
    else:
        st.info("💡 Guest Mode. Login to save meals & targets.")

    st.markdown("### Navigation")
    menu = st.radio(
        "Go to",
        [
            "📊 Dashboard & Meal Log",
            "🔍 Multimodal Food Analysis",
            "🏷️ Food Label Scanner",
            "🥗 AI Meal Planner",
            "⚖️ Compare & Substitute",
            "👨‍🍳 Leftover Recipe Generator",
            "💬 AI Nutritionist (RAG)",
            "📈 Weekly Analytics",
            "⚙️ User Profile & Targets",
            "🔐 Account / Login"
        ],
        label_visibility="collapsed"
    )

    st.divider()
    # Check Backend Health
    try:
        h_resp = requests.get(f"{BACKEND_URL}/health", timeout=1.5)
        if h_resp and h_resp.status_code == 200:
            info = h_resp.json()
            st.caption(f"🟢 **API Status:** Connected")
            st.caption(f"🧠 **Model:** `{info.get('groq_model', 'qwen/qwen3.8-27b')}`")
        else:
            st.caption("🔴 **API Status:** Backend Disconnected")
    except Exception:
        st.caption("🔴 **API Status:** Backend Offline")

# ================= TAB 1: DASHBOARD & MEAL LOG =================
if menu == "📊 Dashboard & Meal Log":
    st.markdown("""
    <div class="main-header">
        <h1 style="margin:0; font-size: 28px; font-weight:800;">📊 Daily Nutrition Dashboard</h1>
        <p style="margin:4px 0 0 0; opacity: 0.9;">Real-time macronutrient adherence, calorie budgeting, and intelligent meal recommendations.</p>
    </div>
    """, unsafe_allow_html=True)

    col_date, col_action = st.columns([3, 1])
    with col_date:
        selected_date = st.date_input("Select Date", value=date.today())
    date_str = selected_date.strftime("%Y-%m-%d")

    dash_resp = api_request("GET", f"/api/v1/meals/dashboard/{date_str}")

    if dash_resp and dash_resp.status_code == 200:
        dash = dash_resp.json()

        # Metric Cards
        m1, m2, m3, m4, m5 = st.columns(5)
        c_cal = dash["consumed_calories"]
        t_cal = dash["target_calories"]
        r_cal = dash["remaining_calories"]

        m1.metric("Calories", f"{c_cal:.0f} kcal", f"Target: {t_cal:.0f} ({r_cal:.0f} left)")
        m2.metric("Protein", f"{dash['consumed_protein']:.1f}g", f"Target: {dash['target_protein']:.0f}g")
        m3.metric("Carbohydrates", f"{dash['consumed_carbs']:.1f}g", f"Target: {dash['target_carbs']:.0f}g")
        m4.metric("Total Fat", f"{dash['consumed_fat']:.1f}g", f"Target: {dash['target_fat']:.0f}g")
        m5.metric("Dietary Fiber", f"{dash['consumed_fiber']:.1f}g", f"Target: {dash['target_fiber']:.0f}g")

        # Visual Calorie & Macro Progress
        st.markdown("#### Calorie Budget Progress")
        pct = min(1.0, max(0.0, c_cal / max(1.0, t_cal)))
        st.progress(pct, text=f"{dash['calorie_adherence_percent']}% of daily calorie target reached")

        # AI Next Meal Decision Engine Callout
        if dash.get("ai_meal_decision"):
            st.info(f"🤖 **AI Meal Decision Engine:** {dash['ai_meal_decision']}")

        st.divider()

        # Meal Diary Section
        st.subheader("Today's Logged Meals")
        meals_by_type = dash.get("meals_by_type", {})

        t_col1, t_col2 = st.columns([2, 1])
        with t_col1:
            for m_type in ["breakfast", "lunch", "dinner", "snacks"]:
                items = meals_by_type.get(m_type, [])
                st.markdown(f"##### {m_type.capitalize()} ({len(items)} items)")
                if not items:
                    st.caption("No foods logged yet for this meal slot.")
                else:
                    for item in items:
                        with st.expander(f"🍽️ {item['food_name']} — {item['serving_size']} ({item['calories']:.0f} kcal)"):
                            c1, c2, c3, c4 = st.columns(4)
                            c1.caption(f"**Protein:** {item['protein']}g")
                            c2.caption(f"**Carbs:** {item['carbohydrates']}g")
                            c3.caption(f"**Fat:** {item['fat']}g")
                            c4.caption(f"**Fiber:** {item['fiber']}g")
                            if st.button("🗑️ Remove", key=f"del_{item['id']}"):
                                del_res = api_request("DELETE", f"/api/v1/meals/{item['id']}")
                                if del_res and del_res.status_code == 200:
                                    st.success(f"Removed {item['food_name']}")
                                    st.rerun()

        with t_col2:
            st.markdown("##### Macro Distribution")
            macro_df = pd.DataFrame({
                "Macro": ["Protein", "Carbs", "Fat"],
                "Grams": [dash["consumed_protein"], dash["consumed_carbs"], dash["consumed_fat"]]
            })
            if macro_df["Grams"].sum() > 0:
                fig = px.pie(macro_df, names="Macro", values="Grams", hole=0.5,
                             color="Macro",
                             color_discrete_map={"Protein": "#3182CE", "Carbs": "#D69E2E", "Fat": "#E53E3E"})
                fig.update_layout(margin=dict(t=10, b=10, l=10, r=10), height=250)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.caption("Log meals to view macronutrient breakdown.")

    st.divider()
    # Quick Log Food
    with st.expander("➕ Log a Food Directly to Daily Diary"):
        with st.form("quick_log_form"):
            ql_col1, ql_col2, ql_col3 = st.columns(3)
            with ql_col1:
                meal_type_input = st.selectbox("Meal Category", ["breakfast", "lunch", "dinner", "snacks"])
                food_name_input = st.text_input("Food Name", placeholder="e.g. 2 Rotis with Dal Tadka")
            with ql_col2:
                serving_input = st.text_input("Serving / Quantity", value="1 serving")
                cals_input = st.number_input("Calories (kcal)", min_value=0.0, value=250.0, step=10.0)
            with ql_col3:
                prot_input = st.number_input("Protein (g)", min_value=0.0, value=10.0, step=1.0)
                carbs_input = st.number_input("Carbs (g)", min_value=0.0, value=35.0, step=1.0)
                fat_input = st.number_input("Fat (g)", min_value=0.0, value=6.0, step=1.0)
                fiber_input = st.number_input("Fiber (g)", min_value=0.0, value=4.0, step=0.5)

            if st.form_submit_button("Log Meal to Diary", type="primary"):
                if food_name_input.strip():
                    log_data = {
                        "date": date_str,
                        "meal_type": meal_type_input,
                        "food_name": food_name_input,
                        "serving_size": serving_input,
                        "serving_weight_g": 100.0,
                        "calories": cals_input,
                        "protein": prot_input,
                        "carbohydrates": carbs_input,
                        "fat": fat_input,
                        "fiber": fiber_input
                    }
                    res = api_request("POST", "/api/v1/meals", data=log_data)
                    if res and res.status_code == 201:
                        st.success(f"Logged {food_name_input} successfully!")
                        st.rerun()

# ================= TAB 2: MULTIMODAL FOOD ANALYSIS =================
elif menu == "🔍 Multimodal Food Analysis":
    st.markdown("""
    <div class="main-header">
        <h1 style="margin:0; font-size: 28px; font-weight:800;">🔍 Multimodal AI Food Analysis</h1>
        <p style="margin:4px 0 0 0; opacity: 0.9;">Analyze meals via text, image upload, or live camera. AI identifies ingredients and computes verified macros without hallucinating numbers.</p>
    </div>
    """, unsafe_allow_html=True)

    input_mode = st.radio("Choose Input Mode", ["✍️ Text Description", "📸 Upload Meal Photo", "📷 Live Camera Capture"], horizontal=True)

    analysis_result = None

    if input_mode == "✍️ Text Description":
        st.markdown("##### Enter Food Item or Complete Meal Description")
        food_query = st.text_input("Food Query", placeholder="e.g. 2 wheat rotis, 1 bowl dal tadka, and 100g paneer tikka")
        portion_hint = st.text_input("Portion / Serving Size Hint (Optional)", placeholder="e.g. Medium serving")

        if st.button("Analyze Nutrition", type="primary"):
            if food_query:
                with st.spinner("AI parsing ingredients and computing verified ICMR & USDA macros..."):
                    resp = api_request("POST", "/api/v1/food/analyze-text", data={"food_query": food_query, "portion_hint": portion_hint})
                    if resp and resp.status_code == 200:
                        analysis_result = resp.json()

    elif input_mode in ["📸 Upload Meal Photo", "📷 Live Camera Capture"]:
        if input_mode == "📸 Upload Meal Photo":
            uploaded_file = st.file_uploader("Upload Plate/Bowl Image", type=["jpg", "jpeg", "png", "webp"])
        else:
            uploaded_file = st.camera_input("Capture Food Image from Camera")

        if uploaded_file is not None:
            col_img, col_btn = st.columns([1, 1])
            with col_img:
                st.image(uploaded_file, caption="Selected Food Photo", use_container_width=True)
            with col_btn:
                portion_hint = st.text_input("Custom Portion Clarification (Optional)", placeholder="e.g. 1 plate, half bowl")
                if st.button("Detect Food & Compute Nutrition", type="primary"):
                    with st.spinner("Vision AI recognizing dishes, portion cues & verified nutrition..."):
                        files = {"file": (uploaded_file.name or "capture.jpg", uploaded_file.getvalue(), uploaded_file.type)}
                        data = {"portion_hint": portion_hint} if portion_hint else {}
                        resp = api_request("POST", "/api/v1/food/analyze-image", files=files, data=data)
                        if resp and resp.status_code == 200:
                            analysis_result = resp.json()

    # Display Analysis Results
    if analysis_result:
        st.success(f"Analysis Complete: {analysis_result.get('query_or_source', 'Food Item')}")
        st.caption(f"ℹ️ {analysis_result.get('meal_summary', '')}")

        # Total Macro Card
        st.markdown("### Total Nutritional Breakdown")
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Calories", f"{analysis_result['total_calories']} kcal")
        c2.metric("Protein", f"{analysis_result['total_protein']}g")
        c3.metric("Carbohydrates", f"{analysis_result['total_carbohydrates']}g")
        c4.metric("Total Fat", f"{analysis_result['total_fat']}g")
        c5.metric("Fiber", f"{analysis_result['total_fiber']}g")

        # Health score badge
        st.markdown(f"**Health Score:** <span class='macro-pill pill-score'>{analysis_result.get('overall_health_score', 8)} / 10</span>", unsafe_allow_html=True)

        st.markdown("#### Detected Dishes & Verified Ingredients")
        for idx, item in enumerate(analysis_result.get("detected_items", [])):
            with st.container():
                st.markdown(f"""
                <div class="nutrition-card">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <h4 style="margin: 0;">🍲 {item['food_name']}</h4>
                        <span class="source-badge">Verified: {item.get('source', 'ICMR / IFCT')}</span>
                    </div>
                    <p style="margin: 4px 0 12px 0; font-size: 13px; color: #4A5568;">
                        Portion: <b>{item['serving_size']}</b> | Confidence: <b>{item.get('confidence_level', 'High')}</b>
                    </p>
                    <div>
                        <span class="macro-pill pill-protein">Protein: {item['protein']}g</span>
                        <span class="macro-pill pill-carbs">Carbs: {item['carbohydrates']}g</span>
                        <span class="macro-pill pill-fat">Fat: {item['total_fat']}g</span>
                        <span class="macro-pill pill-fiber">Fiber: {item['dietary_fiber']}g</span>
                        <span class="macro-pill pill-score">Health: {item['health_score']}/10</span>
                    </div>
                    <p style="margin-top: 8px; font-size: 13px;"><b>Ingredients:</b> {', '.join(item.get('detected_ingredients', []))}</p>
                    <p style="margin-top: 4px; font-size: 13px; color: #2D3748;">💡 <i>{item.get('suggested_pairing', '')}</i></p>
                </div>
                """, unsafe_allow_html=True)

        # User Review & Confirmation before Logging to Diary
        if st.session_state.auth_token:
            st.markdown("---")
            st.markdown("##### 📝 Review & Confirm Meal Logging")
            col_target_meal, col_log_btn = st.columns([1, 2])
            with col_target_meal:
                selected_meal_type = st.selectbox("Select Meal Category", ["breakfast", "lunch", "dinner", "snack"], index=1)
            with col_log_btn:
                st.write("") # spacing
                st.write("")
                if st.button("✅ Confirm & Log Meal to Diary", type="primary", use_container_width=True):
                    logged_count = 0
                    for it in analysis_result.get("detected_items", []):
                        r = api_request("POST", "/api/v1/meals", data={
                            "date": date.today().strftime("%Y-%m-%d"),
                            "meal_type": selected_meal_type,
                            "food_name": it["food_name"],
                            "serving_size": it["serving_size"],
                            "serving_weight_g": it["serving_weight_g"],
                            "calories": it["calories"],
                            "protein": it["protein"],
                            "carbohydrates": it["carbohydrates"],
                            "fat": it["total_fat"],
                            "fiber": it["dietary_fiber"]
                        })
                        if r and r.status_code == 201:
                            logged_count += 1
                    if logged_count > 0:
                        st.success(f"Successfully logged {logged_count} item(s) to {selected_meal_type.title()}!")
                        st.rerun()

        st.caption(f"🔒 {analysis_result.get('disclaimer', '')}")

# ================= TAB 3: FOOD LABEL SCANNER =================
elif menu == "🏷️ Food Label Scanner":
    st.markdown("""
    <div class="main-header">
        <h1 style="margin:0; font-size: 28px; font-weight:800;">🏷️ Packaged Food Nutrition Label Scanner</h1>
        <p style="margin:4px 0 0 0; opacity: 0.9;">Upload packaged food nutrition facts panels. Vision AI parses exact values, detects hidden sugars, and flags sodium & trans-fat risks.</p>
    </div>
    """, unsafe_allow_html=True)

    label_file = st.file_uploader("Upload Nutrition Facts Label Image", type=["jpg", "jpeg", "png", "webp"])
    if label_file:
        st.image(label_file, caption="Nutrition Facts Panel", width=350)
        if st.button("Scan Label", type="primary"):
            with st.spinner("Extracting nutrition facts and checking health flags..."):
                files = {"file": (label_file.name, label_file.getvalue(), label_file.type)}
                resp = api_request("POST", "/api/v1/food/scan-label", files=files)
                if resp and resp.status_code == 200:
                    data = resp.json()
                    st.subheader(f"Product: {data['product_name']}")
                    st.caption(f"Serving Size: {data['serving_size']}")

                    lc1, lc2, lc3, lc4, lc5 = st.columns(5)
                    lc1.metric("Calories", f"{data['calories']} kcal")
                    lc2.metric("Protein", f"{data['protein']}g")
                    lc3.metric("Carbs", f"{data['carbohydrates']}g")
                    lc4.metric("Fat", f"{data['total_fat']}g")
                    lc5.metric("Sugars", f"{data['sugars']}g")

                    st.markdown(f"**Health Rating:** {data['health_rating_score']} / 10")
                    st.info(f"**Nutritionist Verdict:** {data['nutritionist_verdict']}")

                    if data.get("flags"):
                        st.warning("⚠️ **Flags & Health Warnings:** " + "; ".join(data["flags"]))
                    if data.get("allergens"):
                        st.error("🚨 **Allergen Alerts:** " + ", ".join(data["allergens"]))

# ================= TAB 4: AI MEAL PLANNER =================
elif menu == "🥗 AI Meal Planner":
    st.markdown("""
    <div class="main-header">
        <h1 style="margin:0; font-size: 28px; font-weight:800;">🥗 AI Personalized Meal Planner</h1>
        <p style="margin:4px 0 0 0; opacity: 0.9;">Generate balanced Indian & international meal plans tailored to your calorie targets, dietary preference, and budget.</p>
    </div>
    """, unsafe_allow_html=True)

    with st.form("plan_config_form"):
        p_c1, p_c2, p_c3 = st.columns(3)
        with p_c1:
            duration = st.slider("Plan Duration", 1, 7, 3, help="Number of days to plan")
            cuisine = st.selectbox("Cuisine Focus", ["Indian (North & South)", "Mediterranean", "High-Protein Global"])
        with p_c2:
            diet = st.selectbox("Dietary Preference", ["vegetarian", "non-vegetarian", "vegan", "eggetarian"])
            budget = st.checkbox("Budget-Friendly Ingredients", value=True)
        with p_c3:
            custom_cals = st.number_input("Target Daily Calories", min_value=1200.0, max_value=4000.0, value=2000.0, step=100.0)
            allergy_text = st.text_input("Allergies to strictly avoid", placeholder="e.g. Peanuts, Gluten")

        generate_btn = st.form_submit_button("Generate Personalized Meal Plan", type="primary")

    if generate_btn:
        allergies = [a.strip() for a in allergy_text.split(",") if a.strip()]
        req_data = {
            "duration_days": duration,
            "custom_calories": custom_cals,
            "dietary_preference": diet,
            "focus_cuisine": cuisine,
            "allergies": allergies,
            "budget_friendly": budget
        }
        with st.spinner("AI crafting evidence-based meal plan with full macro calculations & grocery list..."):
            p_res = api_request("POST", "/api/v1/planner/generate", data=req_data)
            if p_res and p_res.status_code == 200:
                plan = p_res.json()
                st.session_state.active_meal_plan = plan
                st.success("Meal plan successfully generated!")

    if "active_meal_plan" in st.session_state:
        plan = st.session_state.active_meal_plan
        st.subheader("Your Generated Plan")
        st.caption(f"Nutritionist Notes: {plan.get('nutritionist_notes', '')}")

        for day in plan.get("daily_plans", []):
            with st.expander(f"📅 {day['day_name']} — Total: {day['total_calories']:.0f} kcal (Protein: {day['total_protein']:.1f}g)", expanded=True):
                for m_slot in ["breakfast", "lunch", "dinner", "snack"]:
                    meal = day[m_slot]
                    st.markdown(f"**{m_slot.capitalize()}:** {meal['dish_name']} ({meal['portion_size']}) — `{meal['calories']:.0f} kcal` | Protein: `{meal['protein_g']}g`")
                    st.caption(f"Why: {meal['why_recommended']} | Affordable substitute: *{meal.get('affordable_substitute', 'N/A')}*")

        st.divider()
        st.subheader("🛒 Consolidated Grocery Shopping List")
        g_list = plan.get("grocery_shopping_list", {})
        gc1, gc2, gc3, gc4 = st.columns(4)
        with gc1:
            st.markdown("🥬 **Produce**")
            for item in g_list.get("produce", []): st.write(f"- {item}")
        with gc2:
            st.markdown("🌾 **Grains & Staples**")
            for item in g_list.get("grains_and_staples", []): st.write(f"- {item}")
        with gc3:
            st.markdown("🧀 **Proteins & Dairy**")
            for item in g_list.get("proteins_and_dairy", []): st.write(f"- {item}")
        with gc4:
            st.markdown("🧂 **Pantry & Spices**")
            for item in g_list.get("pantry_and_spices", []): st.write(f"- {item}")

# ================= TAB 5: COMPARE & SUBSTITUTE =================
elif menu == "⚖️ Compare & Substitute":
    st.markdown("""
    <div class="main-header">
        <h1 style="margin:0; font-size: 28px; font-weight:800;">⚖️ Food Comparison & Smart Substitutions</h1>
        <p style="margin:4px 0 0 0; opacity: 0.9;">Compare two foods head-to-head or find evidence-based healthy swaps based on verified nutritional metrics.</p>
    </div>
    """, unsafe_allow_html=True)

    choice = st.radio("Choose Feature", ["Head-to-Head Comparison", "Smart Healthier Substitution"], horizontal=True)

    if choice == "Head-to-Head Comparison":
        cmp_c1, cmp_c2 = st.columns(2)
        with cmp_c1:
            food_1 = st.text_input("Food Item A", value="Paneer")
        with cmp_c2:
            food_2 = st.text_input("Food Item B", value="Tofu")

        if st.button("Compare Foods", type="primary"):
            with st.spinner("Analyzing verified metrics..."):
                resp = api_request("POST", "/api/v1/food/compare", data={"food_a": food_1, "food_b": food_2})
                if resp and resp.status_code == 200:
                    c_data = resp.json()
                    st.info(f"💡 {c_data['comparison_summary']}")

                    col_a, col_b = st.columns(2)
                    with col_a:
                        fa = c_data["food_a"]
                        st.markdown(f"### {fa['food_name']}")
                        st.metric("Calories", f"{fa['calories']} kcal")
                        st.metric("Protein", f"{fa['protein']}g")
                        st.metric("Carbs", f"{fa['carbohydrates']}g")
                        st.metric("Fat", f"{fa['total_fat']}g")
                    with col_b:
                        fb = c_data["food_b"]
                        st.markdown(f"### {fb['food_name']}")
                        st.metric("Calories", f"{fb['calories']} kcal")
                        st.metric("Protein", f"{fb['protein']}g")
                        st.metric("Carbs", f"{fb['carbohydrates']}g")
                        st.metric("Fat", f"{fb['total_fat']}g")

                    st.success(f"🏆 Winner for Weight Loss: **{c_data['winner_for_weight_loss']}**")
                    st.success(f"💪 Winner for Muscle Gain: **{c_data['winner_for_muscle_gain']}**")

    else:
        orig_food = st.text_input("Food to Substitute", value="White Rice")
        sub_reason = st.selectbox("Dietary Goal", ["Lower Carbohydrates / Diabetes-Friendly", "Higher Protein", "Lower Saturated Fat", "Gluten-Free Alternative"])
        if st.button("Find Healthier Alternatives", type="primary"):
            with st.spinner("Generating smart functional substitutes..."):
                resp = api_request("POST", "/api/v1/food/substitute", data={"food_name": orig_food, "goal_or_reason": sub_reason})
                if resp and resp.status_code == 200:
                    s_data = resp.json()
                    for sub in s_data.get("substitutions", []):
                        st.markdown(f"""
                        <div class="nutrition-card">
                            <h4 style="margin:0; color:#2B6CB0;">✨ {sub['substitute_name']}</h4>
                            <p style="margin:4px 0 8px 0; font-size:14px;">{sub['why_it_works']}</p>
                            <div>
                                <span class="macro-pill pill-protein">Protein: {sub['protein']}g</span>
                                <span class="macro-pill pill-carbs">Carbs: {sub['carbs']}g</span>
                                <span class="macro-pill pill-fat">Fat: {sub['fat']}g</span>
                            </div>
                            <p style="margin-top:8px; font-size:13px; color:#4A5568;"><b>Culinary Tip:</b> {sub['culinary_tips']}</p>
                        </div>
                        """, unsafe_allow_html=True)

# ================= TAB 6: LEFTOVER RECIPE GENERATOR =================
elif menu == "👨‍🍳 Leftover Recipe Generator":
    st.markdown("""
    <div class="main-header">
        <h1 style="margin:0; font-size: 28px; font-weight:800;">👨‍🍳 Leftover Ingredient Recipe Generator</h1>
        <p style="margin:4px 0 0 0; opacity: 0.9;">Tell the AI what ingredients you have in your fridge, and get delicious, nutritious recipes with calculated macros.</p>
    </div>
    """, unsafe_allow_html=True)

    ingredients_input = st.text_area("Available Ingredients (comma-separated)", placeholder="e.g. Paneer, Bell pepper, Onion, Tomatoes, Rolled oats, Eggs")
    rc1, rc2 = st.columns(2)
    with rc1:
        diet_pref = st.selectbox("Diet Preference", ["vegetarian", "non-vegetarian", "vegan"])
    with rc2:
        goal_pref = st.selectbox("Goal", ["High-Protein", "Low-Calorie", "Quick 15-Minute Meal"])

    if st.button("Generate Chef Recipes", type="primary"):
        if ingredients_input.strip():
            items = [i.strip() for i in ingredients_input.split(",") if i.strip()]
            with st.spinner("Generating nutritious chef-inspired recipes..."):
                resp = api_request("POST", "/api/v1/food/recipe-generator", data={
                    "ingredients": items,
                    "dietary_preference": diet_pref,
                    "fitness_goal": goal_pref
                })
                if resp and resp.status_code == 200:
                    r_data = resp.json()
                    for r in r_data.get("recipes", []):
                        with st.container():
                            st.markdown(f"""
                            <div class="nutrition-card">
                                <h3 style="margin:0;">🍳 {r['title']}</h3>
                                <p style="color:#718096; font-size:13px;">Prep Time: {r['prep_time']} | Health Benefit: {r['health_benefit']}</p>
                                <div>
                                    <span class="macro-pill pill-protein">{r['protein_g']}g Protein</span>
                                    <span class="macro-pill pill-carbs">{r['carbs_g']}g Carbs</span>
                                    <span class="macro-pill pill-fat">{r['fat_g']}g Fat</span>
                                    <span class="macro-pill pill-fiber">{r['fiber_g']}g Fiber</span>
                                </div>
                                <h5 style="margin-top:12px; margin-bottom:4px;">Instructions:</h5>
                                <ol style="padding-left: 20px;">
                                    {"".join(f"<li>{step}</li>" for step in r['instructions'])}
                                </ol>
                            </div>
                            """, unsafe_allow_html=True)

# ================= TAB 7: AI NUTRITIONIST CHATBOT (RAG) =================
elif menu == "💬 AI Nutritionist (RAG)":
    st.markdown("""
    <div class="main-header">
        <h1 style="margin:0; font-size: 28px; font-weight:800;">💬 Clinical Nutrition AI Assistant</h1>
        <p style="margin:4px 0 0 0; opacity: 0.9;">Grounded in peer-reviewed clinical nutrition science & Indian Food Composition Tables. Ask any question about foods, habits, and macros.</p>
    </div>
    """, unsafe_allow_html=True)

    use_user_context = st.checkbox("Include my personalized daily meal history & targets in context", value=True)

    with st.expander("ℹ️ Advanced Hybrid RAG & Vector Engine Status"):
        rag_stat_resp = api_request("GET", "/api/v1/chat/status")
        if rag_stat_resp and rag_stat_resp.status_code == 200:
            s_data = rag_stat_resp.json()
            c_r1, c_r2, c_r3 = st.columns(3)
            c_r1.metric("Retrieval Mode", s_data.get("rag_mode", "Hybrid"))
            c_r2.metric("Embedding Model", "BGE-small-en-v1.5 (384d)")
            c_r3.metric("Vector Database", f"Qdrant ({s_data.get('qdrant_mode', 'local')})")
            st.caption(f"Indexed Chunks: `{s_data.get('bm25_chunks_indexed', 13)}` | Collection Status: `{s_data.get('collection_info', {}).get('status', 'Ready')}`")
        else:
            st.caption("⚡ Hybrid RAG active (FastEmbed BGE ONNX + Qdrant Local + BM25 Lexical)")

    # Display chat history
    for msg in st.session_state.chat_messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("sources"):
                st.caption(f"📚 Sources: {', '.join(msg['sources'])}")

    user_input = st.chat_input("Ask a nutrition question (e.g. Compare paneer and tofu, or analyze my daily eating habits)...")
    if user_input:
        st.session_state.chat_messages.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)

        with st.chat_message("assistant"):
            with st.spinner("Searching persistent knowledge base..."):
                c_resp = api_request("POST", "/api/v1/chat", data={
                    "message": user_input,
                    "conversation_id": st.session_state.chat_conv_id,
                    "include_user_context": use_user_context
                })
                if c_resp and c_resp.status_code == 200:
                    ans_data = c_resp.json()
                    st.markdown(ans_data["answer"])
                    if ans_data.get("sources"):
                        st.caption(f"📚 Grounded in: {', '.join(ans_data['sources'])}")

                    st.session_state.chat_messages.append({
                        "role": "assistant",
                        "content": ans_data["answer"],
                        "sources": ans_data.get("sources", [])
                    })

                    # Follow-up pills
                    if ans_data.get("suggested_followups"):
                        st.markdown("**Suggested follow-ups:**")
                        cols = st.columns(len(ans_data["suggested_followups"]))
                        for i, q in enumerate(ans_data["suggested_followups"]):
                            if cols[i].button(q, key=f"fu_{len(st.session_state.chat_messages)}_{i}"):
                                st.session_state.chat_messages.append({"role": "user", "content": q})
                                st.rerun()

# ================= TAB 8: WEEKLY ANALYTICS =================
elif menu == "📈 Weekly Analytics":
    st.markdown("""
    <div class="main-header">
        <h1 style="margin:0; font-size: 28px; font-weight:800;">📈 7-Day Nutritional Intelligence Report</h1>
        <p style="margin:4px 0 0 0; opacity: 0.9;">Macro distributions, average daily intake trends, top consumed foods, and AI-driven clinical improvements.</p>
    </div>
    """, unsafe_allow_html=True)

    w_resp = api_request("GET", "/api/v1/meals/weekly-report")
    if w_resp and w_resp.status_code == 200:
        w_data = w_resp.json()

        st.info(f"📅 **Analysis Window:** {w_data['start_date']} to {w_data['end_date']} | Status: {w_data['progress_status']}")

        w1, w2, w3, w4 = st.columns(4)
        w1.metric("Average Daily Calories", f"{w_data['average_daily_calories']:.0f} kcal")
        w2.metric("Average Daily Protein", f"{w_data['average_daily_protein']:.1f}g")
        w3.metric("Average Daily Carbs", f"{w_data['average_daily_carbs']:.1f}g")
        w4.metric("Average Daily Fat", f"{w_data['average_daily_fat']:.1f}g")

        st.divider()

        wc1, wc2 = st.columns([1, 1])
        with wc1:
            st.markdown("#### Weekly Macronutrient Distribution")
            split = w_data.get("macro_distribution", {})
            w_fig = px.pie(
                values=[split.get("protein_percent", 20), split.get("carbs_percent", 55), split.get("fat_percent", 25)],
                names=["Protein %", "Carbohydrates %", "Fat %"],
                hole=0.45,
                color_discrete_sequence=["#3182CE", "#D69E2E", "#E53E3E"]
            )
            st.plotly_chart(w_fig, use_container_width=True)

        with wc2:
            st.markdown("#### Most Frequently Consumed Foods")
            freqs = w_data.get("most_frequent_foods", [])
            if freqs:
                f_df = pd.DataFrame(freqs)
                b_fig = px.bar(f_df, x="frequency", y="food", orientation="h", color="frequency", color_continuous_scale="Blues")
                b_fig.update_layout(yaxis={'categoryorder':'total ascending'}, margin=dict(t=10, b=10, l=10, r=10))
                st.plotly_chart(b_fig, use_container_width=True)
            else:
                st.caption("No foods logged in this 7-day period.")

        st.divider()
        st.subheader("Clinical Insights & Actionable AI Tips")

        ic1, ic2 = st.columns(2)
        with ic1:
            st.markdown("##### 💪 Strengths Identified")
            for s in w_data.get("strengths", []): st.write(f"✅ {s}")
        with ic2:
            st.markdown("##### 🎯 Areas for Improvement")
            for imp in w_data.get("areas_for_improvement", []): st.write(f"⚠️ {imp}")

        st.markdown("##### 🚀 Personalized Next Steps")
        for tip in w_data.get("actionable_ai_recommendations", []):
            st.write(f"💡 {tip}")

# ================= TAB 9: USER PROFILE & TARGETS =================
elif menu == "⚙️ User Profile & Targets":
    st.markdown("""
    <div class="main-header">
        <h1 style="margin:0; font-size: 28px; font-weight:800;">⚙️ Personalized Profile & Target Formulation</h1>
        <p style="margin:4px 0 0 0; opacity: 0.9;">Configure biometrics, activity level, and dietary preferences to calculate clinical BMR & TDEE targets.</p>
    </div>
    """, unsafe_allow_html=True)

    prof_resp = api_request("GET", "/api/v1/profile")
    current_prof = {}
    if prof_resp and prof_resp.status_code == 200:
        current_prof = prof_resp.json()

    p_data = current_prof.get("profile", {})
    t_data = current_prof.get("targets", {})

    with st.form("profile_form"):
        pf_c1, pf_c2, pf_c3 = st.columns(3)
        with pf_c1:
            age = st.number_input("Age (years)", min_value=12, max_value=110, value=p_data.get("age", 25))
            gender = st.selectbox("Biological Sex", ["male", "female", "other"], index=0 if p_data.get("gender") == "male" else 1)
            height = st.number_input("Height (cm)", min_value=80.0, max_value=250.0, value=float(p_data.get("height_cm", 172.0)))
        with pf_c2:
            weight = st.number_input("Weight (kg)", min_value=30.0, max_value=250.0, value=float(p_data.get("weight_kg", 68.0)))
            activity = st.selectbox(
                "Activity Level",
                ["sedentary", "light", "moderate", "active", "very_active"],
                index=["sedentary", "light", "moderate", "active", "very_active"].index(p_data.get("activity_level", "moderate"))
            )
            diet_pref = st.selectbox(
                "Dietary Preference",
                ["vegetarian", "non-vegetarian", "vegan", "eggetarian"],
                index=["vegetarian", "non-vegetarian", "vegan", "eggetarian"].index(p_data.get("dietary_preference", "vegetarian"))
            )
        with pf_c3:
            goal = st.selectbox(
                "Fitness & Body Composition Goal",
                ["weight_loss", "mild_weight_loss", "maintenance", "mild_muscle_gain", "muscle_gain"],
                index=["weight_loss", "mild_weight_loss", "maintenance", "mild_muscle_gain", "muscle_gain"].index(p_data.get("fitness_goal", "maintenance"))
            )
            allergies_str = st.text_input("Allergies (comma-separated)", value=", ".join(p_data.get("allergies", [])))
            custom_cal = st.number_input("Custom Calorie Target (Optional, 0 for auto)", min_value=0.0, max_value=5000.0, value=float(p_data.get("custom_calorie_target") or 0.0))

        if st.form_submit_button("Recalculate & Save Profile", type="primary"):
            al_list = [a.strip() for a in allergies_str.split(",") if a.strip()]
            payload = {
                "age": age,
                "gender": gender,
                "height_cm": height,
                "weight_kg": weight,
                "activity_level": activity,
                "dietary_preference": diet_pref,
                "fitness_goal": goal,
                "allergies": al_list,
                "dietary_restrictions": [],
                "preferred_cuisine": ["Indian"],
                "custom_calorie_target": custom_cal if custom_cal > 500 else None
            }
            save_res = api_request("PUT", "/api/v1/profile", data=payload)
            if save_res and save_res.status_code == 200:
                st.success("Profile & targets successfully recalculated!")
                st.rerun()

    if t_data:
        st.subheader("Your Clinical Nutrition Targets")
        st.caption(f"Calculated via: {t_data.get('formula_used', 'Mifflin-St Jeor Clinical Formula')}")
        tc1, tc2, tc3, tc4, tc5 = st.columns(5)
        tc1.metric("Basal Metabolic Rate (BMR)", f"{t_data.get('bmr', 0):.0f} kcal")
        tc2.metric("TDEE Expenditure", f"{t_data.get('tdee', 0):.0f} kcal")
        tc3.metric("Target Daily Calories", f"{t_data.get('target_calories', 0):.0f} kcal")
        tc4.metric("Protein Target", f"{t_data.get('target_protein_g', 0):.0f}g")
        tc5.metric("Water Target", f"{t_data.get('target_water_liters', 0):.1f} L")
        st.caption(f"🔒 {t_data.get('disclaimer', '')}")

# ================= TAB 10: ACCOUNT & LOGIN =================
elif menu == "🔐 Account / Login":
    st.markdown("""
    <div class="main-header">
        <h1 style="margin:0; font-size: 28px; font-weight:800;">🔐 Account Management & Security</h1>
        <p style="margin:4px 0 0 0; opacity: 0.9;">Secure authentication, data privacy, and session control.</p>
    </div>
    """, unsafe_allow_html=True)

    auth_tab1, auth_tab2 = st.tabs(["Sign In", "Create New Account"])

    with auth_tab1:
        with st.form("login_form"):
            l_ident = st.text_input("Username or Email")
            l_pwd = st.text_input("Password", type="password")
            if st.form_submit_button("Sign In", type="primary"):
                if l_ident and l_pwd:
                    res = api_request("POST", "/api/v1/auth/login", data={"username_or_email": l_ident, "password": l_pwd})
                    if res and res.status_code == 200:
                        data = res.json()
                        st.session_state.auth_token = data["access_token"]
                        st.session_state.current_user = data["user"]
                        st.success(f"Welcome back, {data['user']['full_name']}!")
                        st.rerun()
                    else:
                        st.error("Invalid credentials. Please verify your username and password.")

    with auth_tab2:
        with st.form("register_form"):
            r_name = st.text_input("Full Name")
            r_user = st.text_input("Username")
            r_email = st.text_input("Email Address")
            r_pwd = st.text_input("Password (min 6 characters)", type="password")
            if st.form_submit_button("Register Account", type="primary"):
                if r_name and r_user and r_email and r_pwd:
                    reg_res = api_request("POST", "/api/v1/auth/register", data={
                        "full_name": r_name,
                        "username": r_user,
                        "email": r_email,
                        "password": r_pwd
                    })
                    if reg_res and reg_res.status_code == 201:
                        data = reg_res.json()
                        st.session_state.auth_token = data["access_token"]
                        st.session_state.current_user = data["user"]
                        st.success("Account created successfully!")
                        st.rerun()
                    else:
                        st.error("Registration failed. Email or username may already be in use.")
