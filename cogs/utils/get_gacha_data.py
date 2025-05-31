import requests
import json
from pathlib import Path
import sqlite3
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
import datetime
import pytz


pwd = Path(__file__).parent.parent
DB_PATH = pwd / "../gacha_data/gacha_data.db"
IMAGE_DIR = pwd / "../gacha_data/images"
UTC_PLUS_9 = pytz.timezone('Etc/GMT-9')


def initialize_database():
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    
    cur.execute("""
    CREATE TABLE IF NOT EXISTS students_list (
        id INTEGER PRIMARY KEY, name_jp TEXT, name_tw TEXT, name_en TEXT,
        star_grade INTEGER, is_limited INTEGER, in_global INTEGER
    )""")
    cur.execute("DROP TABLE IF EXISTS current_banner_jp")
    cur.execute("""
    CREATE TABLE current_banner_jp (
        type TEXT,
        rateup_id INTEGER 
    )""")
    
    cur.execute("DROP TABLE IF EXISTS current_banner_gl") 
    cur.execute("""
    CREATE TABLE current_banner_gl (
        type TEXT,
        rateup_id INTEGER
    )""")
    con.commit()
    con.close()


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


def process_student_data(region_data, region_key_for_students_dict, students_dict):
    student_iterable = []
    if isinstance(region_data, dict):
        student_iterable = region_data.values()
    elif isinstance(region_data, list):
        student_iterable = region_data
    else:
        print(f"警告：{region_key_for_students_dict} 學生資料格式無法識別 ({type(region_data)})，跳過處理。")
        return

    for char in student_iterable:
        if not isinstance(char, dict): continue
        char_id = char.get("Id")
        if not char_id: continue

        if region_key_for_students_dict == "char_jp":
            students_dict[char_id] = {
                "id": char_id, "name_jp": char.get("Name"), "name_tw": None, "name_en": None,
                "star_grade": char.get("StarGrade"), "is_limited": char.get("IsLimited"),
                "in_global": 1 if isinstance(char.get("IsReleased"), list) and len(char.get("IsReleased")) > 1 and char.get("IsReleased")[1] else 0
            }
        elif char_id in students_dict:
            if region_key_for_students_dict == "char_tw":
                students_dict[char_id]["name_tw"] = char.get("Name")
            elif region_key_for_students_dict == "char_en":
                students_dict[char_id]["name_en"] = char.get("Name")

# --- 主要更新函式 ---
def update():
    print("<<<<< 開始更新轉蛋資料 >>>>>")
    initialize_database() # 每次更新都確保資料表結構是最新的

    api_urls = {
        "char_jp": "https://schaledb.com/data/jp/students.min.json",
        "char_tw": "https://schaledb.com/data/tw/students.min.json",
        "char_en": "https://schaledb.com/data/en/students.min.json",
        "banner_jp": "https://raw.githubusercontent.com/electricgoat/ba-data/refs/heads/jp/DB/ShopRecruitExcelTable.json", 
        "banner_gl": "https://raw.githubusercontent.com/electricgoat/ba-data/refs/heads/global/Excel/ShopRecruitExcelTable.json" 
    }
    
    api_data = {}
    api_data_fetch_success = True
    essential_keys = ["char_jp", "banner_jp", "banner_gl"] 

    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_url = {executor.submit(fetch_url, url): key for key, url in api_urls.items()}
        for future in tqdm(as_completed(future_to_url), total=len(api_urls), desc="獲取 API 資料"):
            key = future_to_url[future]
            data = future.result()
            api_data[key] = data
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

    now_utc9 = datetime.datetime.now(UTC_PLUS_9)
    VALID_BANNER_TYPES = ["PickupGacha", "NormalGacha", "LimitedGacha", "FesGacha"]
    def process_banner_data(raw_banner_json_data, banner_table_name):
        if not isinstance(raw_banner_json_data, dict):
            print(f"警告：{banner_table_name} 的卡池資料格式非預期的字典，跳過處理。實際類型: {type(raw_banner_json_data)}")
            return
        
        banner_list = raw_banner_json_data.get("DataList")
        if not isinstance(banner_list, list):
            print(f"警告：{banner_table_name} 的卡池資料中 'DataList' 格式非預期的列表，跳過處理。實際類型: {type(banner_list)}")
            return
            
        active_banners_to_insert = []
        for banner_item in banner_list:
            if not isinstance(banner_item, dict): continue
            
            is_legacy = banner_item.get("IsLegacy", True)
            if is_legacy:
                continue

            category_type = banner_item.get("CategoryType")
            if category_type not in VALID_BANNER_TYPES:
                continue

            try:
                sale_from_str = banner_item.get("SalePeriodFrom")
                sale_to_str = banner_item.get("SalePeriodTo")

                if not sale_from_str or not sale_to_str: continue

                sale_from = UTC_PLUS_9.localize(datetime.datetime.strptime(sale_from_str, "%Y-%m-%d %H:%M:%S"))
                sale_to = UTC_PLUS_9.localize(datetime.datetime.strptime(sale_to_str, "%Y-%m-%d %H:%M:%S"))
                
                if sale_from <= now_utc9 <= sale_to:
                    info_char_ids = banner_item.get("InfoCharacterId", [])
                    
                    rateup_id = None # 預設為 None
                    if category_type != "NormalGacha" and info_char_ids: 
                        rateup_id = info_char_ids[0] 
                    
                    active_banners_to_insert.append((category_type, rateup_id))
            except ValueError as ve:
                print(f"解析卡池時間失敗: {banner_item.get('Id')}, From: {sale_from_str}, To: {sale_to_str}. 錯誤: {ve}")
            except Exception as e:
                print(f"處理卡池 {banner_item.get('Id')} 時發生未知錯誤: {e}")

        cur.execute(f"DELETE FROM {banner_table_name}") # 先清空
        if active_banners_to_insert:
            cur.executemany(f"INSERT INTO {banner_table_name} (type, rateup_id) VALUES (?, ?)", active_banners_to_insert)
            print(f"在 {banner_table_name} 中找到並寫入 {len(active_banners_to_insert)} 個活躍卡池。")
        else:
            print(f"在 {banner_table_name} 中沒有找到當前活躍的卡池。")

    process_banner_data(api_data.get("banner_jp"), "current_banner_jp")
    process_banner_data(api_data.get("banner_gl"), "current_banner_gl")

    con.commit()
    con.close()
    print("卡池資料庫更新完成。")
    print(">>>>> 轉蛋資料更新結束 >>>>>")