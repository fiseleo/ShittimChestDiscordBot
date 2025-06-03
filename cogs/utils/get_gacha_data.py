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
SIMULATED_TIME_UTC9 = None

def initialize_database():
    """初始化資料庫和資料夾，僅建立表結構，不刪除核心資料。"""
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
    cur.execute("CREATE TABLE current_banner_jp (type TEXT, rateup_id INTEGER)")
    
    cur.execute("DROP TABLE IF EXISTS current_banner_gl") 
    cur.execute("CREATE TABLE current_banner_gl (type TEXT, rateup_id INTEGER)")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS gacha_history (
        id INTEGER PRIMARY KEY,
        user_id INTEGER NOT NULL,
        char_id INTEGER NOT NULL,
        char_name TEXT NOT NULL,
        rarity TEXT NOT NULL,
        banner_name TEXT NOT NULL,
        server TEXT NOT NULL,
        pull_time TEXT NOT NULL
    )""")

    con.commit()
    con.close()

def set_simulated_time(year=None, month=None, day=None, hour=0, minute=0, second=0):
    global SIMULATED_TIME_UTC9
    if year and month and day:
        try:
            SIMULATED_TIME_UTC9 = UTC_PLUS_9.localize(datetime.datetime(year, month, day, hour, minute, second))
            print(f"模擬時間已設定為 (UTC+9): {SIMULATED_TIME_UTC9.strftime('%Y-%m-%d %H:%M:%S')}")
            return True, SIMULATED_TIME_UTC9
        except Exception as e:
            print(f"設定模擬時間失敗: {e}")
            SIMULATED_TIME_UTC9 = None 
            return False, None
    else:
        SIMULATED_TIME_UTC9 = None
        print("模擬時間已清除，將使用實際當前時間。")
        return True, None

def fetch_url(url, is_json=True):
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        return response.json() if is_json else response.content
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

def process_student_data(region_data, region_key, students_dict):
    student_iterable = region_data.values() if isinstance(region_data, dict) else region_data
    for char in student_iterable:
        if not isinstance(char, dict): continue
        char_id = char.get("Id")
        if not char_id: continue
        if region_key == "char_jp":
            students_dict[char_id] = {"id": char_id, "name_jp": char.get("Name"), "name_tw": None, "name_en": None, "star_grade": char.get("StarGrade"), "is_limited": char.get("IsLimited"), "in_global": 1 if isinstance(char.get("IsReleased"), list) and len(char.get("IsReleased")) > 1 and char.get("IsReleased")[1] else 0}
        elif char_id in students_dict:
            if region_key == "char_tw": students_dict[char_id]["name_tw"] = char.get("Name")
            elif region_key == "char_en": students_dict[char_id]["name_en"] = char.get("Name")

def update():
    print("<<<<< 開始更新轉蛋資料 >>>>>")

    def get_banners_from_db(cur, table_name):
        try:
            cur.execute(f"SELECT type, rateup_id FROM {table_name}")
            return {tuple(row) for row in cur.fetchall()}
        except sqlite3.OperationalError:
            return set()

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    
    old_jp_banners = get_banners_from_db(cur, "current_banner_jp")
    old_gl_banners = get_banners_from_db(cur, "current_banner_gl")
    con.close() # 暫時關閉，initialize_database 會自己處理連線

    initialize_database() # 這會清空 banner 表，建立其他不存在的表

    api_urls = {"char_jp": "https://schaledb.com/data/jp/students.min.json", 
                "char_tw": "https://schaledb.com/data/tw/students.min.json", "char_en": "https://schaledb.com/data/en/students.min.json", 
                "banner_jp": "https://raw.githubusercontent.com/electricgoat/ba-data/refs/heads/jp/DB/ShopRecruitExcelTable.json", 
                "banner_gl": "https://raw.githubusercontent.com/electricgoat/ba-data/refs/heads/global/Excel/ShopRecruitExcelTable.json"}
    api_data = {}

    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_url = {executor.submit(fetch_url, url): key for key, url in api_urls.items()}
        for future in as_completed(future_to_url):
            api_data[future_to_url[future]] = future.result()
    if not all(api_data.get(k) for k in ["char_jp", "banner_jp", "banner_gl"]):
        print("一個或多個必要的 API 資料獲取失敗，更新中止。")
        return

    students = {}
    process_student_data(api_data.get("char_jp"), "char_jp", students)
    process_student_data(api_data.get("char_tw"), "char_tw", students)
    process_student_data(api_data.get("char_en"), "char_en", students)
    image_tasks = [(sid, IMAGE_DIR / f"{sid}.png") for sid in students if not (IMAGE_DIR / f"{sid}.png").exists()]
    if image_tasks:
        with ThreadPoolExecutor(max_workers=10) as executor:
            list(tqdm(executor.map(lambda p: download_and_save_image(*p), image_tasks), total=len(image_tasks), desc="下載學生頭像"))

    current_time = SIMULATED_TIME_UTC9 if SIMULATED_TIME_UTC9 else datetime.datetime.now(UTC_PLUS_9)
    VALID_BANNER_TYPES = ["PickupGacha", "NormalGacha", "LimitedGacha", "FesGacha"]

    def process_new_banners(data):
        if not data or not isinstance(data.get("DataList"), list): return []
        active_banners = []
        for banner in data["DataList"]:
            if banner.get("IsLegacy") or banner.get("CategoryType") not in VALID_BANNER_TYPES: continue
            try:
                start, end = datetime.datetime.strptime(banner["SalePeriodFrom"], "%Y-%m-%d %H:%M:%S"), datetime.datetime.strptime(banner["SalePeriodTo"], "%Y-%m-%d %H:%M:%S")
                if UTC_PLUS_9.localize(start) <= current_time <= UTC_PLUS_9.localize(end):
                    rateup_id = banner.get("InfoCharacterId", [None])[0] if banner["CategoryType"] != "NormalGacha" else None
                    active_banners.append((banner["CategoryType"], rateup_id))
            except (ValueError, KeyError): continue
        return active_banners

    new_jp_banners_list = process_new_banners(api_data.get("banner_jp"))
    new_gl_banners_list = process_new_banners(api_data.get("banner_gl"))
    
    new_jp_banners_set = set(new_jp_banners_list)
    new_gl_banners_set = set(new_gl_banners_list)

    con = sqlite3.connect(DB_PATH) # 重新連線
    cur = con.cursor()

    history_cleared_jp = False
    history_cleared_gl = False

    #Fix for issue  清空抽卡記錄

    if old_jp_banners != new_jp_banners_set:
        print("偵測到日服卡池變更，正在清空日服伺服器的抽卡記錄...") 
        cur.execute("DELETE FROM gacha_history WHERE server = ?", ('japan',)) #
        history_cleared_jp = True
    else:
        print("日服卡池沒有變更，抽卡記錄不需要清空。")

    if old_gl_banners != new_gl_banners_set:
        print("偵測到國際服卡池變更，正在清空國際服伺服器的抽卡記錄...") 
        cur.execute("DELETE FROM gacha_history WHERE server = ?", ('global',))
        history_cleared_gl = True
    else:
        print("國際服卡池沒有變更，抽卡記錄不需要清空。")

    if not history_cleared_jp and not history_cleared_gl:
        print("沒有偵測到卡池變更，抽卡記錄不需要清空。")
    

    cur.executemany("INSERT OR REPLACE INTO students_list VALUES (?, ?, ?, ?, ?, ?, ?)", [tuple(s.values()) for s in students.values()])
    if new_jp_banners_list:
        cur.executemany("INSERT INTO current_banner_jp (type, rateup_id) VALUES (?, ?)", new_jp_banners_list)
    if new_gl_banners_list:
        cur.executemany("INSERT INTO current_banner_gl (type, rateup_id) VALUES (?, ?)", new_gl_banners_list)
    
    cur.execute("DELETE FROM students_list WHERE id = ?", (10099,))
    con.commit()
    con.close()
    
    print(">>>>> 轉蛋資料更新結束 >>>>>")

# --- 新增函式：檢查資料庫是否有足夠資料 ---
def is_database_data_sufficient() -> bool:
    """檢查資料庫是否已經有學生資料。"""
    if not DB_PATH.exists():
        return False # 資料庫檔案不存在，肯定沒資料

    con = None
    try:
        con = sqlite3.connect(DB_PATH)
        cur = con.cursor()
        # 檢查 students_list 是否有資料
        cur.execute("SELECT COUNT(id) FROM students_list")
        count = cur.fetchone()[0]
        return count > 0 # 如果大於0，代表有資料
    except sqlite3.OperationalError:
        # 例如 students_list 表格還不存在
        return False
    except Exception as e:
        print(f"檢查資料庫資料時發生錯誤: {e}")
        return False # 出錯時，保守起見認為需要更新
    finally:
        if con:
            con.close()
# --- 新增函式結束 ---