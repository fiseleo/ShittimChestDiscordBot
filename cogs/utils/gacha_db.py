from pathlib import Path
import sqlite3

pwd = Path(__file__).parent
DB_PATH = pwd / "../../gacha_data/gacha_data.db" # 確保路徑是正確的

def get_character_pools(server: str) -> dict:
    """從資料庫獲取指定伺服器的所有角色卡池。"""
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    pools = {
        "R": [], "SR": [], "SSR": [], "Limited": [], "Fes": []
    }
    
    server_condition = "WHERE in_global = 1" if server == "global" else ""
    

    cur.execute(f"SELECT id, name_jp, name_tw, star_grade, is_limited FROM students_list {server_condition}")
    all_students = cur.fetchall()
    
    for char in all_students:
        name = char["name_tw"] if server == "global" else char["name_jp"]
        char_info = {"id": char["id"], "name": name}

        if char["star_grade"] == 1 and char["is_limited"] == 0:  # R級角色且非限定
            pools["R"].append(char_info)
        elif char["star_grade"] == 2 and char["is_limited"] == 0:  # SR級角色且非限定
            pools["SR"].append(char_info)
        elif char["star_grade"] == 3:
            if char["is_limited"] == 0:
                pools["SSR"].append(char_info)
            elif char["is_limited"] == 1: # 限定角色
                pools["Limited"].append(char_info)
            elif char["is_limited"] == 3: # Fes角色
                pools["Fes"].append(char_info)
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
            s_rateup.id as rateup_char_id,          -- 修改: 單一 rateup ID
            s_rateup.{name_column} as rateup_char_name, -- 修改: 單一 rateup 名稱
            s_rateup.star_grade as rateup_char_rarity  -- 修改: 單一 rateup 稀有度
        FROM {table_name} b
        LEFT JOIN students_list s_rateup ON b.rateup_id = s_rateup.id -- 修改: JOIN 條件
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
                "rarity": "SR" if row["rateup_char_rarity"] == 2 else "SSR"
            })
        banners.append(banner_info)
        
    con.close()
    return banners