from pathlib import Path
import sqlite3

pwd = Path(__file__).parent
DB_PATH = pwd / "../../gacha_data/gacha_data.db"

def get_character_pools(server: str) -> dict:
    """從資料庫獲取指定伺服器的所有角色卡池。"""
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    pools = {
        "R": [], "SR": [], "SSR": [], "Limited": [], "Fes": []
    }
    
    # 查詢條件
    server_condition = "WHERE in_global = 1" if server == "global" else ""

    # 獲取所有學生
    cur.execute(f"SELECT id, name_jp, name_en, star_grade, is_limited FROM students_list {server_condition}")
    all_students = cur.fetchall()
    
    # 根據星級和是否限定進行分類
    for char in all_students:
        name = char["name_en"] if server == "global" else char["name_jp"]
        char_info = {"id": char["id"], "name": name}

        if char["star_grade"] == 1:
            pools["R"].append(char_info)
        elif char["star_grade"] == 2:
            pools["SR"].append(char_info)
        elif char["star_grade"] == 3:
            if char["is_limited"] == 1:
                # 這裡假設 Fes 池的角色也在 is_limited 中，後續會從 banner 資訊中區分
                 pools["Limited"].append(char_info)
            else:
                pools["SSR"].append(char_info)

    con.close()
    return pools

def get_current_banners(server: str) -> list:
    """從資料庫獲取指定伺服器的當前卡池資訊。"""
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    table_name = f"current_banner_{'gl' if server == 'global' else 'jp'}"
    name_column = "name_en" if server == "global" else "name_jp"
    
    # 使用 JOIN 查詢來直接獲取角色名稱和星級
    query = f"""
        SELECT
            b.type,
            s1.id as rateup_1_id,
            s1.{name_column} as rateup_1_name,
            s1.star_grade as rateup_1_rarity,
            s2.id as rateup_2_id,
            s2.{name_column} as rateup_2_name,
            s2.star_grade as rateup_2_rarity
        FROM {table_name} b
        LEFT JOIN students_list s1 ON b.rateup_1 = s1.id
        LEFT JOIN students_list s2 ON b.rateup_2 = s2.id
    """
    cur.execute(query)
    
    banners = []
    for row in cur.fetchall():
        banner_info = {
            "gachaType": row["type"],
            "rateups": []
        }
        if row["rateup_1_id"]:
            banner_info["rateups"].append({
                "id": row["rateup_1_id"],
                "name": row["rateup_1_name"],
                "rarity": "SR" if row["rateup_1_rarity"] == 2 else "SSR"
            })
        if row["rateup_2_id"]:
            banner_info["rateups"].append({
                "id": row["rateup_2_id"],
                "name": row["rateup_2_name"],
                "rarity": "SR" if row["rateup_2_rarity"] == 2 else "SSR"
            })
        banners.append(banner_info)
        
    con.close()
    return banners