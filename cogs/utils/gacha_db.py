# cogs/utils/gacha_db.py

from pathlib import Path
import sqlite3
import datetime 
import pytz     
pwd = Path(__file__).parent
DB_PATH = pwd / "../../gacha_data/gacha_data.db" # 確保路徑是正確的

TARGET_TIMEZONE_FOR_PULL_TIME = pytz.timezone('Asia/Taipei')

def get_character_pools(server: str) -> dict:
    """從資料庫獲取指定伺服器的所有角色卡池。"""
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    pools = {
        "R": [], "SR": [], "SSR": [], # 常駐
        "Limited_Normal": [],       # 普通限定 (is_limited == 1)
        "Limited_Fes": []           # Fes 限定 (is_limited == 3)
    }
    
    server_condition = "WHERE in_global = 1" if server == "global" else ""
    

    cur.execute(f"SELECT id, name_jp, name_tw, star_grade, is_limited FROM students_list {server_condition}")
    all_students = cur.fetchall()
    
    for char in all_students:
        name = char["name_tw"] if server == "global" else char["name_jp"]
        char_info = {"id": char["id"], "name": name}

        if char["star_grade"] == 1 and char["is_limited"] == 0:  
            pools["R"].append(char_info)
        elif char["star_grade"] == 2 and char["is_limited"] == 0:  
            pools["SR"].append(char_info)
        elif char["star_grade"] == 3:
            if char["is_limited"] == 0:
                pools["SSR"].append(char_info)
            elif char["is_limited"] == 1: # 限定角色
                pools["Limited_Normal"].append(char_info)
            elif char["is_limited"] == 3: # Fes角色
                pools["Limited_Fes"].append(char_info)
    con.close()
    return pools

def get_current_banners(server: str) -> list:
    """從資料庫獲取指定伺服器的當前卡池資訊。"""
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    table_name = f"current_banner_{'gl' if server == 'global' else 'jp'}"
    name_column = "name_tw" if server == "global" else "name_jp"
    

    query = f"""
        SELECT
            b.type,
            s_rateup.id as rateup_char_id,          
            s_rateup.{name_column} as rateup_char_name, 
            s_rateup.star_grade as rateup_char_rarity,
            s_rateup.is_limited as rateup_char_is_limited
        FROM {table_name} b
        LEFT JOIN students_list s_rateup ON b.rateup_id = s_rateup.id 
    """
    cur.execute(query)
    
    banners = []
    for row in cur.fetchall():
        banner_info = {
            "gachaType": row["type"],
            "rateups": []
        }
        if row["rateup_char_id"]: 
            banner_info["rateups"].append({
                "id": row["rateup_char_id"],
                "name": row["rateup_char_name"],
                "rarity": "SR" if row["rateup_char_rarity"] == 2 else "SSR",
                "is_limited_type": row["rateup_char_is_limited"] # 0 = 常駐, 1 = 普通限定, 3 = Fes 限定
            })
        banners.append(banner_info)
        
    con.close()
    return banners

def record_pulls(user_id: int, server: str, banner_name: str, pull_results: list):
    """將抽卡結果記錄到資料庫。"""
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    
    records_to_insert = []
    current_time_with_tz = datetime.datetime.now(TARGET_TIMEZONE_FOR_PULL_TIME)
    formatted_pull_time = current_time_with_tz.strftime('%Y-%m-%d %H:%M:%S')
    for result in pull_results:
        clean_rarity = result["rarity"].split('_')[-1]
        
        if "id" not in result or "name" not in result:
            continue

        records_to_insert.append((
            user_id,
            result["id"],
            result["name"],
            clean_rarity,
            banner_name,
            server,
            formatted_pull_time
        ))
    
    if records_to_insert:
        cur.executemany(
            "INSERT INTO gacha_history (user_id, char_id, char_name, rarity, banner_name, server, pull_time) VALUES (?, ?, ?, ?, ?, ?, ?)",
            records_to_insert
        )
        con.commit()
    
    con.close()

# --- 修改後的函式 ---
def get_user_history_for_banner(user_id: int, banner_name: str) -> list:
    """從資料庫獲取指定用戶在特定卡池的抽卡歷史記錄。"""
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    
    cur.execute(
        "SELECT * FROM gacha_history WHERE user_id = ? AND banner_name = ? ORDER BY pull_time DESC",
        (user_id, banner_name)
    )
    history = cur.fetchall()
    
    con.close()
    return history
# --- 修改結束 ---