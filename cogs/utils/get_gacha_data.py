import requests
import json
from pathlib import Path
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm

# --- 全域設定 ---
pwd = Path(__file__).parent.parent
DB_PATH = pwd / "../gacha_data/gacha_data.db"
IMAGE_DIR = pwd / "../gacha_data/images"

# --- 資料庫初始化 ---
def initialize_database():
    """確保資料庫檔案和所有需要的資料表都已建立。"""
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS students_list (
        id INTEGER PRIMARY KEY, name_jp TEXT, name_tw TEXT, name_en TEXT,
        star_grade INTEGER, is_limited INTEGER, in_global INTEGER
    )""")
    cur.execute("CREATE TABLE IF NOT EXISTS current_banner_jp (type TEXT, rateup_1 INTEGER, rateup_2 INTEGER)")
    cur.execute("CREATE TABLE IF NOT EXISTS current_banner_gl (type TEXT, rateup_1 INTEGER, rateup_2 INTEGER)")
    con.commit()
    con.close()

# --- 並行下載輔助函式 ---
def fetch_url(url, is_json=True):
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        return response.json() if is_json else response.content
    except requests.exceptions.JSONDecodeError as e:
        print(f"JSON 解碼失敗: {url}, 狀態碼: {response.status_code}, 回應內容前200字元: {response.text[:200]}, 錯誤: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"下載失敗: {url}, 錯誤: {e}")
        return None

def download_and_save_image(student_id, save_path):
    url = f"https://schaledb.com/images/student/icon/{student_id}.webp"
    image_data = fetch_url(url, is_json=False)
    if image_data:
        with open(save_path, "wb") as f: f.write(image_data)
        return True
    return False

# --- 學生資料處理輔助函式 ---
def process_student_data(region_data, region_key_for_students_dict, students_dict):
    """
    處理來自特定區域的學生資料並整合到 students_dict 中。
    region_data: 從 API 獲取的原始學生資料。
    region_key_for_students_dict: 'char_jp', 'char_tw', 或 'char_en'，用於決定如何更新 students_dict。
    students_dict: 要更新的主要學生資料字典。
    """
    student_iterable = []
    if isinstance(region_data, dict): # 如果 API 回傳的是字典
        student_iterable = region_data.values()
        # print(f"處理 {region_key_for_students_dict}：資料是字典，遍歷其 values。")
    elif isinstance(region_data, list): # 如果 API 回傳的是列表
        student_iterable = region_data
        # print(f"處理 {region_key_for_students_dict}：資料是列表，直接遍歷。")
    else:
        print(f"警告：{region_key_for_students_dict} 學生資料格式無法識別 ({type(region_data)})，跳過處理。")
        return

    for char in student_iterable:
        if not isinstance(char, dict): # 確保迭代的每個元素都是字典
            # print(f"警告：在 {region_key_for_students_dict} 學生資料中發現非字典項目: {type(char)}，跳過。")
            continue 
        
        char_id = char.get("Id")
        if not char_id: 
            # print(f"警告：在 {region_key_for_students_dict} 學生資料中發現無 ID 項目，跳過: {char}")
            continue

        if region_key_for_students_dict == "char_jp": # 主資料來源 (日服)
            students_dict[char_id] = {
                "id": char_id, 
                "name_jp": char.get("Name"), 
                "name_tw": None, 
                "name_en": None,
                "star_grade": char.get("StarGrade"), 
                "is_limited": char.get("IsLimited"),
                # 確保 IsReleased 存在且是至少有2個元素的列表
                "in_global": 1 if isinstance(char.get("IsReleased"), list) and len(char.get("IsReleased")) > 1 and char.get("IsReleased")[1] else 0
            }
        elif char_id in students_dict: # 更新其他語言的名稱
            if region_key_for_students_dict == "char_tw":
                students_dict[char_id]["name_tw"] = char.get("Name")
            elif region_key_for_students_dict == "char_en":
                students_dict[char_id]["name_en"] = char.get("Name")

# --- 主要更新函式 ---
def update():
    print("<<<<< 開始更新轉蛋資料 >>>>>")
    initialize_database()

    api_urls = {
        "char_jp": "https://schaledb.com/data/jp/students.min.json",
        "char_tw": "https://schaledb.com/data/tw/students.min.json",
        "char_en": "https://schaledb.com/data/en/students.min.json",
        "banner_jp": "https://api.ennead.cc/buruaka/banner?region=japan",
        "banner_gl": "https://api.ennead.cc/buruaka/banner?region=global"
    }
    
    api_data = {}
    api_data_fetch_success = True
    essential_keys = ["char_jp", "banner_jp", "banner_gl"] # 定義必要的 API 資料

    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_url = {executor.submit(fetch_url, url): key for key, url in api_urls.items()}
        for future in tqdm(as_completed(future_to_url), total=len(api_urls), desc="獲取 API 資料"):
            key = future_to_url[future]
            data = future.result()
            api_data[key] = data # 儲存獲取到的資料，即使是 None
            if data is None and key in essential_keys:
                print(f"無法獲取必要的 API 資料: {key}。")
                api_data_fetch_success = False
    
    if not api_data_fetch_success:
        print("由於一個或多個必要的 API 資料獲取失敗，更新程序已中止。")
        return

    students = {}
    process_student_data(api_data.get("char_jp"), "char_jp", students)
    process_student_data(api_data.get("char_tw"), "char_tw", students)
    process_student_data(api_data.get("char_en"), "char_en", students)
    
    if not students:
        print("沒有有效的學生資料被整合，更新程序中止。")
        return

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    student_rows = [tuple(s.values()) for s in students.values()]
    cur.executemany("INSERT OR REPLACE INTO students_list VALUES (?, ?, ?, ?, ?, ?, ?)", student_rows)
    con.commit()
    print(f"學生資料庫更新/寫入 {len(student_rows)} 筆記錄。")

    image_download_tasks = [(sid, IMAGE_DIR / f"{sid}.png") for sid in students if not (IMAGE_DIR / f"{sid}.png").exists()]
    if image_download_tasks:
        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_id = {executor.submit(download_and_save_image, *task): task[0] for task in image_download_tasks}
            for future in tqdm(as_completed(future_to_id), total=len(image_download_tasks), desc="下載學生頭像"):
                if not future.result():
                    print(f"下載學生 {future_to_id[future]} 的圖片時失敗。")
    else:
        print("所有學生頭像均已存在，無需下載。")

    name_jp_to_id = {s["name_jp"]: s["id"] for s in students.values() if s["name_jp"]}
    name_en_to_id = {s["name_en"]: s["id"] for s in students.values() if s["name_en"]}
    
    cur.execute("DELETE FROM current_banner_jp")
    jp_banners_to_insert = []
    for banner in api_data.get("banner_jp", {}).get("current", []): # 使用 .get 避免 banner_jp 為 None 時出錯
        rateups = banner.get("rateups", [])
        if rateups:
            rateup_ids = [name_jp_to_id.get(name) for name in rateups if name_jp_to_id.get(name)]
            if rateup_ids:
                 jp_banners_to_insert.append((banner.get("gachaType"), rateup_ids[0], rateup_ids[1] if len(rateup_ids) > 1 else None))
    if jp_banners_to_insert: cur.executemany("INSERT INTO current_banner_jp VALUES (?, ?, ?)", jp_banners_to_insert)

    cur.execute("DELETE FROM current_banner_gl")
    gl_banners_to_insert = []
    for banner in api_data.get("banner_gl", {}).get("current", []): # 使用 .get 避免 banner_gl 為 None 時出錯
        rateups = banner.get("rateups", [])
        if rateups:
            rateup_ids = [name_en_to_id.get(name) for name in rateups if name_en_to_id.get(name)]
            if rateup_ids:
                gl_banners_to_insert.append((banner.get("gachaType"), rateup_ids[0], rateup_ids[1] if len(rateup_ids) > 1 else None))
    if gl_banners_to_insert: cur.executemany("INSERT INTO current_banner_gl VALUES (?, ?, ?)", gl_banners_to_insert)

    con.commit()
    con.close()
    print("卡池資料庫更新完成。")
    print(">>>>> 轉蛋資料更新結束 >>>>>")