import discord
from discord.ext import commands
from discord import app_commands
from pathlib import Path
import random
import math
import PIL.Image
import PIL.ImageChops
from .utils import gacha_db # 使用我們更新後的 gacha_db

ASSETS_DIR = Path(__file__).parent.parent / "assets"
IMAGE_DIR = Path(__file__).parent.parent / "gacha_data" / "images"

try:
    MASK = PIL.Image.open(ASSETS_DIR / "mask.png")
    BORDER = PIL.Image.open(ASSETS_DIR / "border.png")
    STAR_1 = PIL.Image.open(ASSETS_DIR / "star.png")
    STAR_2 = PIL.Image.open(ASSETS_DIR / "two_star.png")
    STAR_3 = PIL.Image.open(ASSETS_DIR / "three_star.png")
    PURPLE_GLOW = PIL.Image.open(ASSETS_DIR / "purple_glow.png")
    YELLOW_GLOW = PIL.Image.open(ASSETS_DIR / "yellow_glow.png")
    PICKUP_ICON = PIL.Image.open(ASSETS_DIR / "pickup.png")
except FileNotFoundError as e:
    raise FileNotFoundError(f"缺少核心素材圖片，請檢查 assets 資料夾: {e}")

class Gacha(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.load_data_from_db()

    def load_data_from_db(self):
        print("正在從資料庫載入轉蛋資料...")
        self.pools_gl = gacha_db.get_character_pools("global")
        self.banners_gl = gacha_db.get_current_banners("global")
        
        self.pools_jp = gacha_db.get_character_pools("japan")
        self.banners_jp = gacha_db.get_current_banners("japan")
        print("轉蛋資料載入完成。")

    def pull_logic(self, server: str, choice: int, last_pull: bool):
        pools_source = self.pools_gl if server == "global" else self.pools_jp
        all_banners_for_server = self.banners_gl if server == "global" else self.banners_jp
        
        # 深拷貝基礎卡池
        pool_r = pools_source["R"].copy()
        pool_sr = pools_source["SR"].copy()
        pool_ssr_permanent = pools_source["SSR"].copy() # 常駐三星
        pool_limited_normal = pools_source["Limited_Normal"].copy() # 普通限定
        pool_limited_fes = pools_source["Limited_Fes"].copy() # Fes 限定

        current_pickup_char = None # 當前卡池的 Pick Up 角色 (字典)
        
        # 預設權重: R, SR, SSR_常駐, SSR_PickUp, SSR_Limited_Normal_Other, SSR_Limited_Fes_PickUp, SSR_Limited_Fes_Other
        # 索引:     0,  1,  2,         3,            4,                        5,                         6
        weights = [78.5, 18.5, 3.0, 0, 0, 0, 0] 
        result_categories = ["R", "SR", "SSR_Perm", "SSR_PickUp", "SSR_Lim_Norm_Other", "SSR_Fes_PickUp", "SSR_Fes_Other"]
        
        gacha_type = "NormalGacha"

        if choice > -1 and choice < len(all_banners_for_server):
            selected_banner = all_banners_for_server[choice]
            gacha_type = selected_banner["gachaType"]
            
            if selected_banner.get("rateups") and selected_banner["rateups"]:
                current_pickup_char = selected_banner["rateups"][0] # 只取第一個 pick up
                
                # 從相應卡池中移除 UP 角，避免重複計算機率
                if current_pickup_char["rarity"] == "SR":
                    pool_sr = [char for char in pool_sr if char["id"] != current_pickup_char["id"]]
                else: # SSR Pick Up
                    if gacha_type == "FesGacha": # current_pickup_char["is_limited_type"] == 3
                        pool_limited_fes = [char for char in pool_limited_fes if char["id"] != current_pickup_char["id"]]
                    elif gacha_type == "LimitedGacha": # current_pickup_char["is_limited_type"] == 1
                        pool_limited_normal = [char for char in pool_limited_normal if char["id"] != current_pickup_char["id"]]
                    else: # PickupGacha (常駐UP) current_pickup_char["is_limited_type"] == 0
                        pool_ssr_permanent = [char for char in pool_ssr_permanent if char["id"] != current_pickup_char["id"]]
            
            # --- 權重調整 ---
            if gacha_type == "PickupGacha": # 常駐 UP
                if current_pickup_char and current_pickup_char["rarity"] == "SSR":
                    weights[2] -= 0.7  # 常駐SSR機率降低
                    weights[3] += 0.7  # Pickup SSR 機率增加
                # SR UP 暫不改變總SR機率，僅提高特定SR出率 (這部分需細化，目前簡化)
            
            elif gacha_type == "LimitedGacha": # 普通限定 UP
                # 總三星率 3%
                weights[3] = 0.7 # 當期 UP 的限定 SSR (current_pickup_char)
                
                # 「同期其他 UP 的限定 SSR」: 機率與常駐 SSR 一樣
                # 需要找出所有當前活躍的 LimitedGacha 的 UP 角 (除了自己)
                concurrent_limited_up_others_ids = []
                for b_idx, b_info in enumerate(all_banners_for_server):
                    if b_idx == choice: continue # 跳過自己
                    if b_info["gachaType"] == "LimitedGacha" and b_info.get("rateups") and b_info["rateups"]:
                        # 假設 rateup 的 is_limited_type 都是 1
                        concurrent_limited_up_others_ids.append(b_info["rateups"][0]["id"])
                
                pool_concurrent_limited_others = [
                    char for char in pool_limited_normal 
                    if char["id"] in concurrent_limited_up_others_ids and (not current_pickup_char or char["id"] != current_pickup_char["id"])
                ]

                num_permanent_ssr = len(pool_ssr_permanent)
                num_concurrent_limited_others = len(pool_concurrent_limited_others)
                total_off_banner_pool_size = num_permanent_ssr + num_concurrent_limited_others
                if total_off_banner_pool_size > 0:
                    weights[2] = (num_permanent_ssr / total_off_banner_pool_size) * 2.3
                    weights[4] = (num_concurrent_limited_others / total_off_banner_pool_size) * 2.3
                    #print(f"調整後權重 - SSR_Perm: {weights[2]}, SSR_Lim_Norm_Other: {weights[4]} (總大小: {total_off_banner_pool_size})")
                else: # 單 UP 角
                    weights[2] = 2.3
                    weights[4] = 0

                
            elif gacha_type == "FesGacha":
                # 總三星率 6%
                weights[5] = 0.7  # 當期 UP 的 Fes SSR (current_pickup_char)
                # 其他 Fes 限定角均分 0.9%
                num_other_fes = len(pool_limited_fes) # pool_limited_fes 此時已移除了UP角
                if num_other_fes > 0:
                    # weights[6] (SSR_Fes_Other) 總共佔 0.9%
                    # 這裡的 weights[6] 應該是總機率，選擇時再均分
                    weights[6] = 0.9 
                else:
                    weights[6] = 0
                # 常駐三星均分剩餘 4.4% (6 - 0.7 - 0.9)
                weights[2] = 4.4 

        # 十連保底 SR
        if last_pull:
            r_weight = weights[0]
            weights[0] = 0
            weights[1] += r_weight # 簡化：R的機率全給SR

        # 權重正規化 (確保總和為100)
        active_weights = [w for w in weights if w > 0]
        if active_weights:
            current_total_weight = sum(active_weights)
            if abs(current_total_weight - 100.0) > 1e-5 : # 允許微小誤差
                if current_total_weight > 0: # 避免除以零
                    factor = 100.0 / current_total_weight
                    weights = [w * factor for w in weights]
                else: # 理論上不應發生，所有權重為0
                    weights[0] = 100.0 # 強制設為 R
        else: # 所有權重都為0，強制設為 R
             weights[0] = 100.0

        # 抽卡
        try:
            valid_categories_weights = {cat: weights[i] for i, cat in enumerate(result_categories) if weights[i] > 0}
            if not valid_categories_weights:
                raise IndexError("No valid categories with positive weights.")

            chosen_category = random.choices(
                list(valid_categories_weights.keys()), 
                list(valid_categories_weights.values())
            )[0]
            
            pulled_char_info = {} # 存放抽出的角色原始資訊 (id, name)

            if chosen_category == "R" and pool_r:
                pulled_char_info = random.choice(pool_r)
            elif chosen_category == "SR" and pool_sr:
                pulled_char_info = random.choice(pool_sr)
            elif chosen_category == "SSR_Perm" and pool_ssr_permanent:
                pulled_char_info = random.choice(pool_ssr_permanent)
            elif chosen_category == "SSR_PickUp" and current_pickup_char and current_pickup_char["rarity"] == "SSR" and gacha_type != "FesGacha" and gacha_type != "LimitedGacha": #常駐UP
                pulled_char_info = current_pickup_char
            elif chosen_category == "SSR_PickUp" and current_pickup_char and current_pickup_char["rarity"] == "SSR" and gacha_type == "LimitedGacha": #限定UP
                pulled_char_info = current_pickup_char
            elif chosen_category == "SSR_Lim_Norm_Other" and pool_concurrent_limited_others: # 同期其他限定UP
                pulled_char_info = random.choice(pool_concurrent_limited_others)
            elif chosen_category == "SSR_Fes_PickUp" and current_pickup_char and gacha_type == "FesGacha":
                pulled_char_info = current_pickup_char
            elif chosen_category == "SSR_Fes_Other" and pool_limited_fes:
                pulled_char_info = random.choice(pool_limited_fes)
            
            # Fallback
            if not pulled_char_info:
                 if pool_r:
                    pulled_char_info = random.choice(pool_r)
                    chosen_category = "R" # 更新抽出的類別
                 else:
                    return {"id": 0, "name": "資料錯誤", "rarity": "Error", "server": server}

            final_rarity_display = chosen_category # 用於顯示的稀有度類別
            if "PickUp" in chosen_category or "PickUp" in final_rarity_display: # 讓圖片顯示 pickup
                 final_rarity_display = "Pickup_" + ("SR" if pulled_char_info.get("rarity")=="SR" else "SSR") if "PickUp" in chosen_category else chosen_category
            elif "Fes_PickUp" in chosen_category :
                 final_rarity_display = "Pickup_Fes"
            elif "Fes_Other" in chosen_category:
                 final_rarity_display = "SSR" # Fes其他角色當作普通SSR顯示，但它是限定
            elif "SSR" in chosen_category: # SSR_Perm or SSR_Lim_Norm_Other
                 final_rarity_display = "SSR"


            return {
                "id": pulled_char_info["id"],
                "name": pulled_char_info["name"],
                "rarity": final_rarity_display, # 用於 create_single_image 判斷
                "server": server
            }
        except IndexError as e:
            print(f"抽卡錯誤 (IndexError): {e}, Weights: {weights}")
            if pool_r: fallback = random.choice(pool_r); return {"id": fallback["id"], "name": fallback["name"], "rarity": "R", "server": server}
            return {"id": 0, "name": "抽卡機大故障", "rarity": "Error", "server": server}
        except Exception as e:
            print(f"抽卡時發生未知錯誤: {e}")
            if pool_r: fallback = random.choice(pool_r); return {"id": fallback["id"], "name": fallback["name"], "rarity": "R", "server": server}
            return {"id": 0, "name": "系統維護中", "rarity": "Error", "server": server}

    def create_single_image(self, result: dict):
        # ... (此函式邏輯根據 result["rarity"] 判斷 PICKUP_ICON，基本不變) ...
        base_char_image = PIL.Image.new("RGBA", (160, 160), (0, 0, 0, 0))
        try:
            char_img_path = IMAGE_DIR / f"{result['id']}.png"
            with PIL.Image.open(char_img_path) as char_pil_img:
                char_pil_img = char_pil_img.convert("RGBA")
                char_pil_img = PIL.ImageChops.multiply(char_pil_img, MASK)
                base_char_image.alpha_composite(char_pil_img, (20, 20))
        except FileNotFoundError:
            print(f"警告：找不到學生圖片 {result['id']}.png for {result['name']}")
        except Exception as e:
            print(f"載入學生圖片 {result['id']}.png 時發生錯誤: {e}")

        rarity_display = result["rarity"] # pull_logic 返回的詳細稀有度
        
        is_pickup = "Pickup" in rarity_display # 例如 "Pickup_SR", "Pickup_SSR", "Pickup_Fes"

        if rarity_display == "R":
            base_char_image.alpha_composite(BORDER)
            base_char_image.alpha_composite(STAR_1)
        elif rarity_display == "SR" or rarity_display == "Pickup_SR":
            base_char_image.alpha_composite(YELLOW_GLOW)
            base_char_image.alpha_composite(BORDER)
            base_char_image.alpha_composite(STAR_2)
            if is_pickup:
                base_char_image.alpha_composite(PICKUP_ICON)
        elif rarity_display in ("SSR", "Pickup_SSR", "Pickup_Fes", "SSR_Lim_Norm_Other", "SSR_Fes_Other"): # 所有三星都用紫色光
            base_char_image.alpha_composite(PURPLE_GLOW)
            base_char_image.alpha_composite(BORDER)
            base_char_image.alpha_composite(STAR_3)
            if is_pickup: # Pickup_SSR 或 Pickup_Fes
                base_char_image.alpha_composite(PICKUP_ICON)
        elif rarity_display == "Error":
             pass
        return base_char_image
        
    # ... generate_gacha_image, 斜線指令 gacha, GachaDropdown, GachaButton, GachaView 保持不變 ...
    # 注意：GachaDropdown 的 label 可能需要調整以更好地區分卡池類型和UP角。

    def generate_gacha_image(self, results: list):
        char_images = [self.create_single_image(res) for res in results]
        image_count = len(char_images)
        cols = 5
        rows = math.ceil(image_count / cols)
        img_width, img_height = 120, 140 
        padding = 10 

        if image_count > 1:
            canvas_width = cols * img_width + padding * 2
            canvas_height = rows * img_height + padding * 2
            base_image = PIL.Image.new("RGBA", (canvas_width, canvas_height), (194, 229, 245, 255))
            for i, img in enumerate(char_images):
                x_offset = padding + (i % cols * img_width) + (img_width - 160) // 2
                y_offset = padding + (i // cols * img_height) + (img_height - 160) // 2
                base_image.alpha_composite(img, (x_offset, y_offset))
        elif image_count == 1 :
            base_image = PIL.Image.new("RGBA", (200, 200), (194, 229, 245, 255))
            base_image.alpha_composite(char_images[0], ( (200-160)//2, (200-160)//2) )
        else: 
            base_image = PIL.Image.new("RGBA", (200,200), (194,229,245,255))
        base_image.save("result.png")

    @app_commands.command(name="gacha", description="模擬抽卡")
    @app_commands.describe(mode="選擇一次招募的數量")
    @app_commands.choices(mode=[
        app_commands.Choice(name="單抽", value="single"),
        app_commands.Choice(name="十抽", value="ten")
    ])
    async def gacha(self, interaction: discord.Interaction, mode: app_commands.Choice[str]):
        view = GachaView(cog=self, mode=mode.value)
        await interaction.response.send_message("請選擇您要進行招募的卡池：", view=view, ephemeral=True)

class GachaDropdown(discord.ui.Select):
    def __init__(self, cog: Gacha, mode: str):
        self.cog = cog
        self.mode = mode
        
        options = []
        # 國際服卡池
        for i, banner in enumerate(self.cog.banners_gl):
            banner_name = self._get_banner_display_name(banner)
            options.append(discord.SelectOption(
                label=f"國際服：{banner_name}",
                value=f"global_{i}",
                description=banner["gachaType"]
            ))

        # 日服卡池
        for i, banner in enumerate(self.cog.banners_jp):
            banner_name = self._get_banner_display_name(banner)
            options.append(discord.SelectOption(
                label=f"日服：{banner_name}",
                value=f"japan_{i}",
                description=banner["gachaType"]
            ))

        if not options:
            options = [discord.SelectOption(label="暫無卡池", value="no_banner", disabled=True)]

        super().__init__(placeholder="選擇卡池", options=options)

    def _get_banner_display_name(self, banner):
        """根據卡池資訊生成顯示名稱"""
        if banner["gachaType"] == "NormalGacha":
            return "常駐招募"
        elif banner["rateups"]:
            pickup_names = [rateup["name"] for rateup in banner["rateups"]]
            return " & ".join(pickup_names[:2])  # 最多顯示兩個pickup角色名
        else:
            return "特殊招募"

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "no_banner":
            await interaction.response.send_message("目前沒有可用的卡池資訊。", ephemeral=True)
            return

        await interaction.response.defer()
        
        server_str, choice_str = self.values[0].split("_")
        choice = int(choice_str)

        if self.mode == "single":
            results = [self.cog.pull_logic(server_str, choice, False)]
        else:  # ten
            results = [self.cog.pull_logic(server_str, choice, i == 9) for i in range(10)]
        
        self.cog.generate_gacha_image(results)
        
        # 生成embed
        banner_display_name = self._get_banner_display_name(
            (self.cog.banners_gl if server_str == "global" else self.cog.banners_jp)[choice]
        )
        
        embed = discord.Embed(
            title=f"老師，這是您的招募結果！",
            description=f"**伺服器：** {'國際服' if server_str == 'global' else '日服'}\n**卡池：** {banner_display_name}",
            color=discord.Color.blue()
        )
        
        
        try:
            file = discord.File("result.png", filename="result.png")
            embed.set_image(url="attachment://result.png")
            view = GachaView(cog=self.cog, mode=self.mode, server=server_str, choice=choice, is_button=True)
            await interaction.followup.send(content=interaction.user.mention, file=file, embed=embed, view=view)
        except FileNotFoundError:
            await interaction.followup.send(content=f"{interaction.user.mention} 抱歉，生成結果圖片時發生錯誤。", embed=embed)
        except Exception as e:
            print(f"傳送抽卡結果時發生錯誤: {e}")
            await interaction.followup.send(content=f"{interaction.user.mention} 抱歉，處理您的請求時發生了未預期的錯誤。", embed=embed)


class GachaButton(discord.ui.Button):
    def __init__(self, cog: Gacha, mode: str, server: str, choice: int):
        super().__init__(label="再抽一次！", style=discord.ButtonStyle.primary)
        self.cog = cog
        self.mode = mode
        self.server = server
        self.choice = choice

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer()
        
        if self.mode == "single":
            results = [self.cog.pull_logic(self.server, self.choice, False)]
        else:  # ten
            results = [self.cog.pull_logic(self.server, self.choice, i == 9) for i in range(10)]
            
        self.cog.generate_gacha_image(results)

        

        current_banner_list = self.cog.banners_gl if self.server == "global" else self.cog.banners_jp
        banner = current_banner_list[self.choice]
        
        banner_display_name = "常駐招募"
        if banner["gachaType"] != "NormalGacha" and banner["rateups"]:
            pickup_names = [rateup["name"] for rateup in banner["rateups"]]
            banner_display_name = " & ".join(pickup_names[:2])

        embed = discord.Embed(
            title=f"老師，這是您的招募結果！",
            description=f"**伺服器：** {'國際服' if self.server == 'global' else '日服'}\n**卡池：** {banner_display_name}",
            color=discord.Color.blue()
        )
        
        

        try:
            file = discord.File("result.png", filename="result.png")
            embed.set_image(url="attachment://result.png")
            view = GachaView(cog=self.cog, mode=self.mode, server=self.server, choice=self.choice, is_button=True)
            await interaction.followup.send(content=interaction.user.mention, file=file, embed=embed, view=view)


        except FileNotFoundError:
            await interaction.followup.send(content=f"{interaction.user.mention} 抱歉，生成結果圖片時發生錯誤。", embed=embed)
        except Exception as e:
            print(f"傳送抽卡結果時發生錯誤: {e}")
            await interaction.followup.send(content=f"{interaction.user.mention} 抱歉，處理您的請求時發生了未預期的錯誤。", embed=embed)


class GachaView(discord.ui.View):
    def __init__(self, cog: Gacha, mode: str, server: str = "global", choice: int = -1, is_button: bool = False):
        super().__init__(timeout=300) 
        self.cog = cog
        if is_button:
            self.add_item(GachaButton(self.cog, mode, server, choice))
        else:
            self.add_item(GachaDropdown(self.cog, mode))


async def setup(bot: commands.Bot):
    await bot.add_cog(Gacha(bot))
    print("Improved Gacha cog has been loaded with enhanced pull logic.")