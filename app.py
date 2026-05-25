import discord
from discord import app_commands
from discord.ext import commands, tasks
import json
import os
import random
import math
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

USERS_FILE = "users.json"
STOCKS_FILE = "stocks.json"
CONFIG_FILE = "config.json"
EVENTS_FILE = "events.json"

STOCK_RESET_RANGES = {
    "삼성전자": (10000, 1268090), "현대자동차": (100000, 1975238), "닌텐도": (150000, 600000),
    "패러독스 인터랙티브": (1000, 300000), "애플": (20000, 1500000), "삼성 SDI": (100000, 5000000),
    "LG전자": (5000, 1246490), "SK 하이닉스": (100000, 2385092), "S-oil": (10000, 700000),
    "엔비디아": (30000, 200000), "구글": (200000, 950000), "메타": (20000, 3000000),
    "인텔": (10000, 1800000), "한화": (1000, 948593), "다이소": (1000, 5000),
    "맥도날드": (10000, 1000000), 
    "로블록스": (1000, 300000), 
    "카카오": (10, 50000), # 10원부터 시작하는 눈물의 카카오
    "스페이스X": (50000, 800000),
    "기아": (50000, 1200000),
}

def load_data(file_path, default_value):
    if not os.path.exists(file_path):
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(default_value, f, ensure_ascii=False, indent=4)
        return default_value
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return default_value

def save_data(file_path, data):
    temp_file = file_path + ".tmp"
    # 1. 먼저 임시 파일(.tmp)에 안전하게 쓰기
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    # 2. 쓰기가 완벽히 끝나면 원본 파일로 교체(Replace) - 원본 손상 방지
    os.replace(temp_file, file_path)

user_wallets = load_data(USERS_FILE, {})
stock_data = load_data(STOCKS_FILE, {})
config_data = load_data(CONFIG_FILE, {"update_interval_minutes": 30})

@bot.event
async def on_ready():
    print(f'봇이 성공적으로 로그인했습니다: {bot.user.name}')
    if not interest_loop.is_running(): interest_loop.start()
    if not stock_price_loop.is_running():
        current_minutes = config_data.get("update_interval_minutes", 30)
        stock_price_loop.change_interval(minutes=current_minutes)
        stock_price_loop.start()
    try:
        await bot.tree.sync()
    except Exception as e: print(e)

@tasks.loop(hours=24)
async def interest_loop():
    global user_wallets
    user_wallets = load_data(USERS_FILE, {})
    for user_id, info in user_wallets.items():
        if info.get("debt", 0) > 0:
            bank_type = info.get("bank", "None")
            rate = 0.03 if bank_type == "A" else (0.05 if bank_type == "B" else (0.07 if bank_type == "C" else 0))
            user_wallets[user_id]["debt"] += int(info["debt"] * rate)
    save_data(USERS_FILE, user_wallets)

@tasks.loop(minutes=30)
async def stock_price_loop():
    global stock_data
    stock_data = load_data(STOCKS_FILE, {})
    if not stock_data: return
    
    # 🕒 한국 시간 체크 (오후 7시 ~ 밤 12시 제한)
    kst = timezone(timedelta(hours=9))
    now_kst = datetime.now(kst)
    if not (19 <= now_kst.hour <= 23):
        return

    for name, info in stock_data.items():
        old_price = info["price"]
        
        # ⭐ [선물거래용] 주가 변동 직전의 진짜 가격을 기록해 둡니다.
        stock_data[name]["old_price_for_futures"] = old_price
        
        change_rate = random.uniform(-0.15, 0.15)
        calculated_price = old_price + int(old_price * change_rate)
        
        if name == "카카오":
            new_price = max(10, (calculated_price // 10) * 10)
        else:
            new_price = max(100, (calculated_price // 100) * 100)
        
        if name in STOCK_RESET_RANGES:
            min_p, max_p = STOCK_RESET_RANGES[name]
            if new_price > max_p:
                new_price = (max_p // 10) * 10 if name == "카카오" else (max_p // 100) * 100
            elif new_price < min_p:
                new_price = min_p
        
        if name == "다이소" and new_price > 7000: 
            new_price = 5000
            
        stock_data[name]["price"] = new_price
        stock_data[name]["rate"] = ((new_price - old_price) / old_price) * 100 if old_price > 0 else 0.0
        stock_data[name]["change"] = new_price - old_price
        
    save_data(STOCKS_FILE, stock_data)
    
    # 🎰 주가 변동이 끝난 직후 선물 거래 정산 함수를 호출합니다.
    await check_futures_results()

@bot.command(name="시간수정")
@commands.has_permissions(administrator=True)
async def change_stock_loop_time(ctx, minutes: int):
    if minutes <= 0: return
    try: await ctx.message.delete()
    except discord.Forbidden: pass
    config_data["update_interval_minutes"] = minutes
    save_data(CONFIG_FILE, config_data)
    stock_price_loop.change_interval(minutes=minutes)
    await ctx.send(f"⏰ 주가 변동 주기가 **{minutes}분**으로 변경되었습니다. (이 메시지는 잠시 후 사라집니다.)", delete_after=5)

@bot.command(name="주가수정")
@commands.has_permissions(administrator=True)
async def modify_stock_price(ctx, name: str, amount: int):
    try: await ctx.message.delete()
    except discord.Forbidden: pass
    global stock_data; stock_data = load_data(STOCKS_FILE, {})
    if name not in stock_data:
        await ctx.send(f"❌ '{name}'은(는) 존재하지 않는 기업입니다.", delete_after=5)
        return
    old_price = stock_data[name]["price"]; new_price = max(100, old_price + amount)
    stock_data[name]["price"] = new_price; stock_data[name]["change"] = new_price - old_price
    stock_data[name]["rate"] = ((new_price - old_price) / old_price) * 100 if old_price > 0 else 0.0
    save_data(STOCKS_FILE, stock_data)
    status_text = f"📈 {amount:,}원 상승" if amount > 0 else (f"📉 {abs(amount):,}원 하락" if amount < 0 else "⚪ 보합")
    await ctx.send(f"펌핑 완료 🛑 **{name}** 주가 강제 조정\n└ 이전가: `{old_price:,}원` ➡️ 변경가: `{new_price:,}원` ({status_text})", delete_after=5)

@bot.command(name="event")
@commands.has_permissions(administrator=True)  # 관리자 권한 필수
async def check_event(ctx, event_id: str = None):
    # json 파일 로드
    events_data = load_data(EVENTS_FILE, {})

    # 1. 뉴스 ID를 입력하지 않은 경우 (!event) -> 관리자 개인 DM으로 뉴스 ID 목록 발송
    if event_id is None:
        if not events_data:
            await ctx.send("📰 현재 `events.json`에 등록된 뉴스가 없습니다.")
            return

        embed = discord.Embed(
            title="🕵️ 관리자 전용 비밀 뉴스 ID 목록",
            description="조회하려는 뉴스의 ID를 확인하고 서버에서 `!event (뉴스ID)`를 입력하세요.\n*※ 이 메시지는 관리자님에게만 개인 DM으로 발송되었습니다.*",
            color=discord.Color.dark_purple()
        )
        
        for e_id, info in events_data.items():
            news_title = info.get("title", "제목 없음")
            embed.add_field(name=f"🆔 {e_id}", value=f"┗ 제목: {news_title}", inline=False)
        
        # 관리자 DM으로 목록 전송
        try:
            await ctx.author.send(embed=embed)
            # 유저들이 눈치채지 못하게 채널에 남는 안내 메시지는 3초 뒤 자동 삭제
            await ctx.send("🔒 뉴스 ID 목록을 개인 DM으로 안전하게 발송했습니다.", delete_after=3)
        except discord.Forbidden:
            await ctx.send("❌ DM 수신 설정이 차단되어 있어 목록을 보낼 수 없습니다. 설정을 확인해 주세요.")
        
        return

    # 2. 뉴스 ID를 입력한 경우 (!event 뉴스ID) -> 명령어 텍스트 삭제 및 20% 확률 조회
    if event_id not in events_data:
        await ctx.send(f"❌ `{event_id}`은(는) 존재하지 않는 뉴스 ID입니다.")
        return

    # 💡 관리자가 입력한 명령어 텍스트 즉시 삭제 (비밀 유지)
    try:
        await ctx.message.delete()
    except discord.Forbidden:
        pass  # 봇에게 '메시지 관리' 권한이 없을 경우 무시
    except discord.HTTPException:
        pass

    event_info = events_data[event_id]
    news_title = event_info.get("title", "제목 없음")
    news_text = event_info.get("text", "내용 없음")
    change_rate = event_info.get("change", "0")

    # 🎲 보내주신 코드의 20% 확률 시스템 유지
    is_analyzed = random.random() < 1

    if is_analyzed:
        try:
            rate_val = float(change_rate)
            if rate_val > 0:
                rate_str = f"📈 +{change_rate}% (상승 유도)"
            elif rate_val < 0:
                rate_str = f"📉 {change_rate}% (하락 유도)"
            else:
                rate_str = f"變 {change_rate}% (변동 없음)"
        except ValueError:
            rate_str = f"❓ {change_rate} (수치 분석 불가)"
    else:
        rate_str = f"❓ 수치 분석 불가 (정보 보안/예측 불허)"

    embed = discord.Embed(
        title=f"🕵️ 관리자 비밀 뉴스 조회 (ID: {event_id})",
        description=f"**제목: {news_title}**\n*조회 완료 후 관리자의 명령어는 자동으로 삭제되었습니다.*",
        color=discord.Color.dark_purple()
    )
    embed.add_field(name="💬 뉴스 헤드라인 내용", value=f"\"{news_text}\"", inline=False)
    embed.add_field(name="📊 예측 변동률 (보안)", value=rate_str, inline=False)
    embed.set_footer(text=f"요청자: {ctx.author.display_name} | 분석 성공률: 100%")

    await ctx.send(embed=embed)

@check_event.error
async def check_event_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ 권한이 없습니다.")

# 🛒 주식 구매 UI 핸들러
class StockBuySelect(discord.ui.Select):
    def __init__(self, stocks_data):
        options = [discord.SelectOption(label=name, description=f"현재 1주당 가격: {info['price']:,}원", value=name) for name, info in stocks_data.items()]
        super().__init__(placeholder="매수할 기업을 선택하세요...", min_values=1, max_values=1, options=options)
    async def callback(self, interaction: discord.Interaction):
        self.view.selected_stock = self.values[0]
        await interaction.response.edit_message(content=f"🏢 선택된 기업: **{self.view.selected_stock}**\n아래에서 구매할 주식 수량 버튼을 클릭하세요!", embed=None)

class StockBuyView(discord.ui.View):
    def __init__(self, stocks_data):
        super().__init__(timeout=60); self.add_item(StockBuySelect(stocks_data)); self.selected_stock = None
    @discord.ui.button(label="1주 구매", style=discord.ButtonStyle.secondary, row=1)
    async def buy_1(self, interaction: discord.Interaction, button: discord.ui.Button): await self.process_purchase(interaction, 1)
    @discord.ui.button(label="2주 구매", style=discord.ButtonStyle.secondary, row=1)
    async def buy_2(self, interaction: discord.Interaction, button: discord.ui.Button): await self.process_purchase(interaction, 2)
    @discord.ui.button(label="5주 구매", style=discord.ButtonStyle.secondary, row=1)
    async def buy_5(self, interaction: discord.Interaction, button: discord.ui.Button): await self.process_purchase(interaction, 5)
    @discord.ui.button(label="10주 구매", style=discord.ButtonStyle.primary, row=2)
    async def buy_10(self, interaction: discord.Interaction, button: discord.ui.Button): await self.process_purchase(interaction, 10)
    @discord.ui.button(label="20주 구매", style=discord.ButtonStyle.primary, row=2)
    async def buy_20(self, interaction: discord.Interaction, button: discord.ui.Button): await self.process_purchase(interaction, 20)

    async def process_purchase(self, interaction: discord.Interaction, amount: int):
        if not self.selected_stock: return await interaction.response.send_message("❌ 기업을 먼저 고르세요.", ephemeral=True)
        user_id = str(interaction.user.id); global user_wallets, stock_data
        user_wallets = load_data(USERS_FILE, {}); stock_data = load_data(STOCKS_FILE, {})
        if user_id not in user_wallets: return await interaction.response.send_message("❌ 가입 필요", ephemeral=True)
        current_price = stock_data[self.selected_stock]["price"]; total_cost = current_price * amount; user_money = user_wallets[user_id].get("money", 0)
        if user_money < total_cost: return await interaction.response.send_message("❌ 잔액 부족", ephemeral=True)
        if "stocks" not in user_wallets[user_id]: user_wallets[user_id]["stocks"] = {}
        user_wallets[user_id]["stocks"][self.selected_stock] = user_wallets[user_id]["stocks"].get(self.selected_stock, 0) + amount
        user_wallets[user_id]["money"] -= total_cost
        save_data(USERS_FILE, user_wallets)
        embed = discord.Embed(title="📥 주식 매수 체결 완료", color=discord.Color.blue())
        embed.add_field(name="🏢 종목명", value=self.selected_stock, inline=True)
        embed.add_field(name="📊 체결 수량", value=f"{amount} 주", inline=True)
        embed.add_field(name="💸 총 결제 금액", value=f"**{total_cost:,} 원**", inline=False)
        await interaction.response.edit_message(content=None, embed=embed, view=None)

@bot.tree.command(name="주식구매", description="상장된 주식을 선택하고 원하는 수량만큼 구매합니다. (나에게만 보임)")
async def buy_stock_command(interaction: discord.Interaction):
    current_stocks = load_data(STOCKS_FILE, {})
    if not current_stocks: return await interaction.response.send_message("❌ 상장된 기업이 없습니다.", ephemeral=True)
    await interaction.response.send_message(content="🛒 **가상 주식 매수 시스템**\n드롭다운에서 기업을 선택해 주세요!", view=StockBuyView(current_stocks), ephemeral=True)

# 📤 주식 매도 UI 핸들러
class StockSellSelect(discord.ui.Select):
    def __init__(self, stocks_data, user_owned_stocks):
        options = [discord.SelectOption(label=name, description=f"현재가: {info['price']:,}원 | 보유: {user_owned_stocks.get(name, 0):,}주", value=name) for name, info in stocks_data.items()]
        super().__init__(placeholder="매도(판매)할 기업을 선택하세요...", min_values=1, max_values=1, options=options)
    async def callback(self, interaction: discord.Interaction):
        self.view.selected_stock = self.values[0]
        await interaction.response.edit_message(content=f"🏢 선택된 매도 종목: **{self.view.selected_stock}**\n아래에서 시장에 판매할 주식 수량 버튼을 클릭하세요!", embed=None)

class StockSellView(discord.ui.View):
    def __init__(self, stocks_data, user_owned_stocks):
        super().__init__(timeout=60); self.add_item(StockSellSelect(stocks_data, user_owned_stocks)); self.selected_stock = None
    @discord.ui.button(label="1주 판매", style=discord.ButtonStyle.secondary, row=1)
    async def sell_1(self, interaction: discord.Interaction, button: discord.ui.Button): await self.process_sell(interaction, 1)
    @discord.ui.button(label="2주 판매", style=discord.ButtonStyle.secondary, row=1)
    async def sell_2(self, interaction: discord.Interaction, button: discord.ui.Button): await self.process_sell(interaction, 2)
    @discord.ui.button(label="5주 판매", style=discord.ButtonStyle.secondary, row=1)
    async def sell_5(self, interaction: discord.Interaction, button: discord.ui.Button): await self.process_sell(interaction, 5)
    @discord.ui.button(label="10주 판매", style=discord.ButtonStyle.danger, row=2)
    async def sell_10(self, interaction: discord.Interaction, button: discord.ui.Button): await self.process_sell(interaction, 10)
    @discord.ui.button(label="20주 판매", style=discord.ButtonStyle.danger, row=2)
    async def sell_20(self, interaction: discord.Interaction, button: discord.ui.Button): await self.process_sell(interaction, 20)

    async def process_sell(self, interaction: discord.Interaction, amount: int):
        if not self.selected_stock: return await interaction.response.send_message("❌ 기업을 먼저 고르세요.", ephemeral=True)
        user_id = str(interaction.user.id); global user_wallets, stock_data
        user_wallets = load_data(USERS_FILE, {}); stock_data = load_data(STOCKS_FILE, {})
        if user_id not in user_wallets: return await interaction.response.send_message("❌ 가입 필요", ephemeral=True)
        user_stocks = user_wallets[user_id].get("stocks", {}); owned_amount = user_stocks.get(self.selected_stock, 0)
        if owned_amount < amount: return await interaction.response.send_message("❌ 보유 주식 부족", ephemeral=True)
        current_price = stock_data[self.selected_stock]["price"]; total_earnings = current_price * amount
        user_wallets[user_id]["stocks"][self.selected_stock] = owned_amount - amount
        user_wallets[user_id]["money"] += total_earnings
        save_data(USERS_FILE, user_wallets)
        embed = discord.Embed(title="📤 주식 매도 체결 완료", color=discord.Color.red())
        embed.add_field(name="🏢 종목명", value=self.selected_stock, inline=True)
        embed.add_field(name="📊 매도 수량", value=f"{amount} 주", inline=True)
        embed.add_field(name="💰 총 정산 금액", value=f"**+{total_earnings:,} 원**", inline=False)
        await interaction.response.edit_message(content=None, embed=embed, view=None)

@bot.tree.command(name="주식매도", description="보유 중인 주식을 시장에 판매하여 현금화합니다. (나에게만 보임)")
async def sell_stock_command(interaction: discord.Interaction):
    user_id = str(interaction.user.id); current_stocks = load_data(STOCKS_FILE, {}); user_wallets = load_data(USERS_FILE, {})
    if user_id not in user_wallets: return await interaction.response.send_message("❌ 가입 필요", ephemeral=True)
    user_owned_stocks = user_wallets[user_id].get("stocks", {})
    await interaction.response.send_message(content="📤 **가상 주식 매도 시스템**\n판매할 주식을 선택해 주세요!", view=StockSellView(current_stocks, user_owned_stocks), ephemeral=True)

# 🏆 /랭킹 UI 핸들러 클래스들
class RankingSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="🥇 순자산 랭킹 (빚 포함)", description="현금 + 주식가치 - 빚 (진짜 내 재산 순위)", value="net_worth"),
            discord.SelectOption(label="🥈 실자산 랭킹 (빚 제외)", description="현금 + 주식가치 (외형 재산 순위)", value="gross_asset")
        ]
        super().__init__(placeholder="조회할 랭킹 종류를 선택하세요...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        ranking_type = self.values[0]
        user_wallets = load_data(USERS_FILE, {})
        stock_data = load_data(STOCKS_FILE, {})
        
        leaderboard = []

        for u_id, info in user_wallets.items():
            member = interaction.guild.get_member(int(u_id))
            if not member: continue

            cash = info.get("money", 0)
            debt = info.get("debt", 0)
            my_stocks = info.get("stocks", {})

            total_stock_value = 0
            for s_name, owned_amount in my_stocks.items():
                if owned_amount > 0:
                    current_unit_price = stock_data.get(s_name, {}).get("price", 0)
                    total_stock_value += (current_unit_price * owned_amount)

            if ranking_type == "net_worth":
                score = cash + total_stock_value - debt
            else:
                score = cash + total_stock_value

            leaderboard.append((member.display_name, score))

        leaderboard.sort(key=lambda x: x[1], reverse=True)

        title_text = "🥇 서버 순자산 랭킹 (빚 포함)" if ranking_type == "net_worth" else "🥈 서버 실자산 랭킹 (빚 제외)"
        color_theme = discord.Color.gold() if ranking_type == "net_worth" else discord.Color.light_gray()
        embed = discord.Embed(
            title=title_text,
            description="💰 금액은 비공개 처리되며, 순위와 닉네임만 표시됩니다.\n━━━━━━━━━━━━━━━━━━━━",
            color=color_theme
        )

        medals = ["👑 1위", "✨ 2위", "⭐ 3위", "🔹 4위", "🔹 5위"]
        for index, (name, score) in enumerate(leaderboard[:5]):
            embed.add_field(name=medals[index], value=f"**{name}**", inline=False)

        if not leaderboard:
            embed.description += "\n❌ 현재 순위에 표시할 활동 유저가 없습니다."

        await interaction.response.edit_message(embed=embed, view=self.view)

class RankingView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)
        self.add_item(RankingSelect())

@bot.tree.command(name="랭킹", description="서버 주식 부자들의 명예의 전당을 확인합니다. (나에게만 보임)")
async def ranking_command(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🏆 가상 주식 부자 명예의 전당",
        description="아래 드롭다운 메뉴를 선택하여 **순자산** 또는 **실자산** 랭킹을 확인해 보세요!",
        color=discord.Color.blue()
    )
    await interaction.response.send_message(embed=embed, view=RankingView(), ephemeral=True)

# 💳 /자산 명령어
@bot.tree.command(name="자산", description="내 소지금, 보유 중인 주식 현황, 빚 등을 모두 확인합니다. (나에게만 보임)")
async def show_my_assets(interaction: discord.Interaction):
    user_id = str(interaction.user.id); global user_wallets, stock_data
    user_wallets = load_data(USERS_FILE, {}); stock_data = load_data(STOCKS_FILE, {})
    if user_id not in user_wallets: return await interaction.response.send_message("❌ 가입 필요", ephemeral=True)
    user_info = user_wallets[user_id]; cash = user_info.get("money", 0); debt = user_info.get("debt", 0); my_stocks = user_info.get("stocks", {})
    total_stock_value = 0; stock_list_string = ""
    if my_stocks:
        for stock_name, owned_amount in my_stocks.items():
            if owned_amount <= 0: continue
            current_unit_price = stock_data.get(stock_name, {}).get("price", 0); sub_total_value = current_unit_price * owned_amount
            total_stock_value += sub_total_value; stock_list_string += f"🔹 **{stock_name}** : `{owned_amount:,}주` (총 {sub_total_value:,}원 상당)\n"
    stock_list_text = "```현재 보유 중인 주식이 없습니다.\n```" if not stock_list_string else stock_list_string
    net_worth = cash + total_stock_value - debt
    embed = discord.Embed(title=f"💳 {interaction.user.name}님의 자산 보고서", description=f"현재 시각 시세를 기준으로 측정된 실시간 자산 현황입니다.", color=discord.Color.purple())
    embed.set_thumbnail(url=interaction.user.display_avatar.url)
    embed.add_field(name="💰 보유 현금 (소지금)", value=f"`{cash:,} 원`", inline=True)
    embed.add_field(name="📉 남은 은행 빚", value=f"`{debt:,} 원`" if debt > 0 else "`0 원 (클린)`", inline=True)
    embed.add_field(name="📈 총 주식 평가액", value=f"`{total_stock_value:,} 원`", inline=True)
    embed.add_field(name="📋 상세 주식 보유 리스트", value=stock_list_text, inline=False)
    embed.add_field(name="📊 실질 순자산 (현금 + 주식 - 빚)", value=f"==> **{net_worth:,} 원**", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

class RepayModal(discord.ui.Modal, title="🏦 은행 빚 상환 창"):
    amount_input = discord.ui.TextInput(label="빚 갚기", placeholder="갚을 금액 숫자만 입력", min_length=1, max_length=15, required=True)
    async def on_submit(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id); global user_wallets; user_wallets = load_data(USERS_FILE, {})
        try: repay_amount = int(self.amount_input.value)
        except ValueError: return await interaction.response.send_message("❌ 숫자만 입력하세요.", ephemeral=True)
        current_money = user_wallets[user_id].get("money", 0); current_debt = user_wallets[user_id].get("debt", 0)
        if current_debt <= 0: return await interaction.response.send_message("❌ 빚이 없습니다.", ephemeral=True)
        if repay_amount > current_money: return await interaction.response.send_message("❌ 소지금 부족", ephemeral=True)
        if repay_amount > current_debt: repay_amount = current_debt
        user_wallets[user_id]["money"] -= repay_amount; user_wallets[user_id]["debt"] -= repay_amount
        if user_wallets[user_id]["debt"] == 0: user_wallets[user_id]["bank"] = "None"
        save_data(USERS_FILE, user_wallets)
        await interaction.response.send_message("🏦 상환 완료되었습니다.", ephemeral=True)

class BankSelect(discord.ui.Select):
    def __init__(self):
        options = [discord.SelectOption(label="A은행", description="100만원 대출 | 이자 3%", value="A"), discord.SelectOption(label="B은행", description="200만원 대출 | 이자 5%", value="B"), discord.SelectOption(label="C은행", description="300만원 대출 | 이자 7%", value="C")]
        super().__init__(placeholder="은행 선택...", min_values=1, max_values=1, options=options)
    async def callback(self, interaction: discord.Interaction):
        user_id = str(interaction.user.id); global user_wallets; user_wallets = load_data(USERS_FILE, {})
        if user_id not in user_wallets: return await interaction.response.send_message("❌ 가입 필요", ephemeral=True)
        if user_wallets[user_id].get("debt", 0) > 0: return await interaction.response.send_message("❌ 이미 대출중", ephemeral=True)
        selection = self.values[0]; loan = 1000000 if selection == "A" else (2000000 if selection == "B" else 3000000)
        user_wallets[user_id]["money"] += loan; user_wallets[user_id]["debt"] = loan; user_wallets[user_id]["bank"] = selection
        save_data(USERS_FILE, user_wallets)
        await interaction.response.send_message(f"🏦 {selection}은행 대출이 완료되었습니다.", ephemeral=True)

class BankView(discord.ui.View):
    def __init__(self): super().__init__(); self.add_item(BankSelect())
    @discord.ui.button(label="빚 갚기", style=discord.ButtonStyle.green, row=1)
    async def repay_button(self, interaction: discord.Interaction, button: discord.ui.Button): await interaction.response.send_modal(RepayModal())

class StockDescriptionSelect(discord.ui.Select):
    def __init__(self, stocks_data):
        options = [discord.SelectOption(label=name, description=f"현재가: {info['price']:,}원", value=name) for name, info in stocks_data.items()]
        super().__init__(placeholder="설명을 보고 싶은 주식을 선택하세요...", min_values=1, max_values=1, options=options)
    async def callback(self, interaction: discord.Interaction):
        stock_name = self.values[0]; current_stocks = load_data(STOCKS_FILE, {})
        if stock_name not in current_stocks: return
        embed = discord.Embed(title=f"🏢 기업 정보: {stock_name}", description=current_stocks[stock_name].get("description", "설명 없음"), color=discord.Color.blue())
        await interaction.response.send_message(embed=embed, ephemeral=True)

class StockDescriptionView(discord.ui.View):
    def __init__(self, stocks_data): super().__init__(); self.add_item(StockDescriptionSelect(stocks_data))

@bot.tree.command(name="주식초기화", description="모든 참가자의 자산을 초기화하고 주가를 랜덤으로 갱신합니다. (관리자 전용)")
@app_commands.checks.has_permissions(administrator=True)
async def reset_stock_game(interaction: discord.Interaction):
    global user_wallets, stock_data
    user_wallets = load_data(USERS_FILE, {})
    for user_id in user_wallets.keys(): user_wallets[user_id] = {"money": 500000, "debt": 0, "bank": "None", "stocks": {}, "last_attendance": ""}
    save_data(USERS_FILE, user_wallets)
    stock_data = load_data(STOCKS_FILE, {})
    for name, range_values in STOCK_RESET_RANGES.items():
        if name in stock_data:
            min_p, max_p = range_values
            stock_data[name]["price"] = random.randint(min_p // 100, max_p // 100) * 100
            stock_data[name]["rate"] = 0.0; stock_data[name]["change"] = 0
    save_data(STOCKS_FILE, stock_data)
    await interaction.response.send_message("🔄 주식 시장 대초기화가 완료되었습니다!")

@bot.tree.command(name="은행", description="은행에서 대출을 받거나 빚을 상환합니다.")
async def bank_command(interaction: discord.Interaction):
    user_id = str(interaction.user.id); user_wallets = load_data(USERS_FILE, {})
    if user_id not in user_wallets: return
    embed = discord.Embed(title="🏦 중앙 가상 은행", color=discord.Color.gold())
    embed.add_field(name="💰 소지금", value=f"{user_wallets[user_id].get('money', 0):,}원")
    embed.add_field(name="📉 남은 빚", value=f"{user_wallets[user_id].get('debt', 0):,}원")
    await interaction.response.send_message(embed=embed, view=BankView(), ephemeral=True)

@bot.tree.command(name="주식설명", description="특정 주식의 상세 설명을 확인합니다.")
async def stock_description_command(interaction: discord.Interaction):
    current_stocks = load_data(STOCKS_FILE, {})
    await interaction.response.send_message(embed=discord.Embed(title="📊 가상 기업 도감"), view=StockDescriptionView(current_stocks), ephemeral=True)

@bot.tree.command(name="주식시작", description="가상 주식 게임을 시작하고 초기 자금을 받습니다.")
async def start_game(interaction: discord.Interaction):
    user_id = str(interaction.user.id); global user_wallets; user_wallets = load_data(USERS_FILE, {})
    if user_id in user_wallets: return
    role = interaction.guild.get_role(1504759968837140491)
    if role: await interaction.user.add_roles(role)
    user_wallets[user_id] = {"money": 500000, "debt": 0, "bank": "None", "stocks": {}, "last_attendance": ""}
    save_data(USERS_FILE, user_wallets)
    await interaction.response.send_message("🎉 가입 완료! 500,000원이 지급되었습니다.")

@bot.tree.command(name="주가보기", description="현재 주식 시장의 주가를 확인합니다. (나에게만 보임)")
async def show_stocks(interaction: discord.Interaction):
    global stock_data; stock_data = load_data(STOCKS_FILE, {})
    embed = discord.Embed(title="📈 현재 주식 시장 시세표", description="현재 거래 가능한 가상 주식 목록입니다.\n━━━━━━━━━━━━━━━━━━━━━━━━", color=discord.Color.green())
    for name, info in stock_data.items():
        price = info.get("price", 0); rate = info.get("rate", 0.0); change = info.get("change", 0)
        if change > 0: box_content = f"현재가: {price:,}원\n+ 변동폭: 🔺 +{rate:.2f}% (+{int(change):,}원)"
        elif change < 0: box_content = f"현재가: {price:,}원\n- 변동폭: 🔻 {rate:.2f}% ({int(change):,}원)"
        else: box_content = f"현재가: {price:,}원\n  변동폭: ⚪ 0.00% (0원)"
        embed.add_field(name=f"🏢 {name}", value=f"```diff\n{box_content}\n```", inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)

# 🎰 [선물 거래] 유저 선택용 드롭다운 메뉴 및 뷰
class FuturesStockSelect(discord.ui.Select):
    def __init__(self, stocks_data):
        options = [discord.SelectOption(label=name, description=f"현재가: {info['price']:,}원", value=name) for name, info in stocks_data.items()]
        super().__init__(placeholder="선물 계약을 맺을 기업을 선택하세요...", min_values=1, max_values=1, options=options)
    async def callback(self, interaction: discord.Interaction):
        self.view.selected_stock = self.values[0]
        await interaction.response.edit_message(content=f"🏢 선택된 기업: **{self.view.selected_stock}**\n이제 아래에서 투자 방향(롱/숏)과 레버리지 배율을 설정하세요!", embed=None)

class FuturesView(discord.ui.View):
    def __init__(self, stocks_data, user_money):
        super().__init__(timeout=60)
        self.add_item(FuturesStockSelect(stocks_data))
        self.selected_stock = None
        self.user_money = user_money
        self.position = None  # "LONG" 또는 "SHORT"
        self.leverage = 1

    @discord.ui.button(label="📈 LONG (오른다)", style=discord.ButtonStyle.success, row=1)
    async def set_long(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.position = "LONG"
        await interaction.response.send_message("방향이 **📈 LONG (상승)**으로 설정되었습니다.", ephemeral=True)

    @discord.ui.button(label="📉 SHORT (떨어진다)", style=discord.ButtonStyle.danger, row=1)
    async def set_short(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.position = "SHORT"
        await interaction.response.send_message("방향이 **📉 SHORT (하락)**으로 설정되었습니다.", ephemeral=True)

    @discord.ui.button(label="🚀 배율: 1배", style=discord.ButtonStyle.secondary, row=2)
    async def lev_1(self, interaction: discord.Interaction, button: discord.ui.Button): self.leverage = 1; await interaction.response.send_message("레버리지가 **1배**로 설정되었습니다.", ephemeral=True)
    @discord.ui.button(label="🔥 배율: 3배", style=discord.ButtonStyle.secondary, row=2)
    async def lev_3(self, interaction: discord.Interaction, button: discord.ui.Button): self.leverage = 3; await interaction.response.send_message("레버리지가 **3배(고위험)**로 설정되었습니다.", ephemeral=True)
    @discord.ui.button(label="💀 배율: 5배", style=discord.ButtonStyle.secondary, row=2)
    async def lev_5(self, interaction: discord.Interaction, button: discord.ui.Button): self.leverage = 5; await interaction.response.send_message("레버리지가 **5배(지옥길)**로 설정되었습니다.", ephemeral=True)

class FuturesBetModal(discord.ui.Modal, title="💰 선물 계약 투자금 입력"):
    def __init__(self, view):
        super().__init__()
        self.view = view
        self.money_input = discord.ui.TextInput(label="투자할 현금 액수", placeholder="숫자만 입력 (예: 50000)", min_length=1, max_length=15, required=True)
        self.add_item(self.money_input)

    async def on_submit(self, interaction: discord.Interaction):
        if not self.view.selected_stock or not self.view.position:
            return await interaction.response.send_message("❌ 종목 선택 및 롱/숏 방향 설정을 먼저 완료해 주세요.", ephemeral=True)
        
        try:
            bet_amount = int(self.money_input.value)
        except ValueError:
            return await interaction.response.send_message("❌ 숫자만 입력 가능합니다.", ephemeral=True)

        if bet_amount <= 0:
            return await interaction.response.send_message("❌ 최소 1원 이상 투자해야 합니다.", ephemeral=True)
        if bet_amount > self.view.user_money:
            return await interaction.response.send_message("❌ 보유하신 소지금이 부족합니다.", ephemeral=True)

        user_id = str(interaction.user.id)
        global user_wallets
        user_wallets = load_data(USERS_FILE, {})

        user_wallets[user_id]["money"] -= bet_amount
        
        if "futures" not in user_wallets[user_id]:
            user_wallets[user_id]["futures"] = []
            
        contract = {
            "stock_name": self.view.selected_stock,
            "position": self.view.position,
            "leverage": self.view.leverage,
            "bet_money": bet_amount
        }
        user_wallets[user_id]["futures"].append(contract)
        save_data(USERS_FILE, user_wallets)

        embed = discord.Embed(title="🎲 선물 계약 체결 완료 (대기 중)", color=discord.Color.dark_orange())
        embed.description = f"다음 주가 변동 주기(30분 간격)에 결과가 정산됩니다."
        embed.add_field(name="🏢 종목", value=self.view.selected_stock, inline=True)
        embed.add_field(name="📊 포지션", value="📈 LONG" if self.view.position == "LONG" else "📉 SHORT", inline=True)
        embed.add_field(name="🔥 레버리지", value=f"{self.view.leverage}배", inline=True)
        embed.add_field(name="💸 투자금", value=f"{bet_amount:,}원", inline=False)
        
        await interaction.response.edit_message(content=None, embed=embed, view=None)

@bot.tree.command(name="도박", description="주가의 상승/하락에 배팅하는 레버리지 선물 거래를 진행합니다. (나에게만 보임)")
async def futures_command(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    user_wallets = load_data(USERS_FILE, {})
    current_stocks = load_data(STOCKS_FILE, {})
    
    if user_id not in user_wallets:
        return await interaction.response.send_message("❌ 가입이 필요합니다.", ephemeral=True)
    if not current_stocks:
        return await interaction.response.send_message("❌ 상장된 기업이 없습니다.", ephemeral=True)
        
    user_money = user_wallets[user_id].get("money", 0)
    view = FuturesView(current_stocks, user_money)
    
    confirm_button = discord.ui.Button(label="💳 투자금 입력 및 계약 완료", style=discord.ButtonStyle.primary, row=3)
    async def confirm_callback(interact):
        await interact.response.send_modal(FuturesBetModal(view))
    confirm_button.callback = confirm_callback
    view.add_item(confirm_button)

    embed = discord.Embed(
        title="📉 가상 주식 마진/선물 거래소 📈",
        description="⚠️ **주의**: 예측 실패 시 원금이 통째로 청산(소각)당할 수 있는 위험한 투자입니다.\n\n"
                    "1️⃣ 드롭다운에서 기업을 고르세요.\n"
                    "2️⃣ 롱(오른다) 또는 숏(떨어진다) 버튼을 누르세요.\n"
                    "3️⃣ 배율을 선택하고 최종 [계약 완료] 버튼을 누르세요.",
        color=discord.Color.dark_red()
    )
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

# ⚙️ 주가 변동 시 선물 계약 자동 정산 엔진 함수 (완성본)
async def check_futures_results():
    global user_wallets
    user_wallets = load_data(USERS_FILE, {})
    stock_data = load_data(STOCKS_FILE, {})
    
    for user_id, info in list(user_wallets.items()):
        contracts = info.get("futures", [])
        if not contracts:
            continue
            
        retained_contracts = []
        total_payout = 0
        summary_messages = []

        for c in contracts:
            s_name = c["stock_name"]
            pos = c["position"]
            lev = c["leverage"]
            bet = c["bet_money"]
            
            old_p = stock_data.get(s_name, {}).get("old_price_for_futures", 0)
            new_p = stock_data.get(s_name, {}).get("price", 0)
            
            if old_p == 0 or old_p == new_p:
                retained_contracts.append(c)
                continue
                
            raw_rate = ((new_p - old_p) / old_p)
            
            if pos == "LONG":
                earning_rate = raw_rate * lev
            else:
                earning_rate = -raw_rate * lev
                
            if earning_rate <= -1.0:
                summary_messages.append(f"💀 **{s_name}** ({pos} {lev}배) ➡️ 주가 반대 급변으로 **[청산]**되어 `{bet:,}원`이 전액 소각되었습니다.")
            else:
                payout = int(bet + (bet * earning_rate))
                total_payout += payout
                profit = payout - bet
                sign = "🟢 +" if profit >= 0 else "🔴 "
                summary_messages.append(f"💰 **{s_name}** ({pos} {lev}배) ➡️ 정산 금액: `{payout:,}원` (수익: {sign}{profit:,}원)")

        user_wallets[user_id]["money"] += total_payout
        user_wallets[user_id]["futures"] = retained_contracts
        save_data(USERS_FILE, user_wallets)
        
        if summary_messages:
            try:
                user = await bot.fetch_user(int(user_id))
                embed = discord.Embed(title="🎰 가상 주식 선물 거래 정산 리포트", color=discord.Color.orange())
                embed.description = "\n".join(summary_messages)
                await user.send(embed=embed)
            except discord.Forbidden:
                pass

# 📅 [신규 기능] /출석체크 기능 추가
@bot.tree.command(name="출석", description="하루에 한 번 출석하여 무작위 주식 투자 지원금을 받습니다.")
async def daily_attendance(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    global user_wallets
    user_wallets = load_data(USERS_FILE, {})
    
    if user_id not in user_wallets:
        return await interaction.response.send_message("❌ `/주식시작`을 먼저 진행해 주세요.", ephemeral=True)
        
    # 한국 시간 기준 오늘 날짜 구하기
    kst = timezone(timedelta(hours=9))
    today_str = datetime.now(kst).strftime("%Y-%m-%d")
    
    last_date = user_wallets[user_id].get("last_attendance", "")
    if last_date == today_str:
        return await interaction.response.send_message("❌ 오늘은 이미 출석체크를 완료하셨습니다! 내일 다시 참여해 주세요.", ephemeral=True)
        
    # 30,000원 ~ 60,000원 사이 무작위 보상 지급
    reward = random.randint(30000, 60000)
    user_wallets[user_id]["money"] += reward
    user_wallets[user_id]["last_attendance"] = today_str
    save_data(USERS_FILE, user_wallets)
    
    embed = discord.Embed(title="📆 일일 출석체크 완료!", color=discord.Color.green())
    embed.description = f"오늘의 주식 보조금이 지갑으로 입금되었습니다."
    embed.add_field(name="💵 지급 금액", value=f"`+{reward:,} 원`", inline=True)
    embed.add_field(name="💰 현재 잔고", value=f"`{user_wallets[user_id]['money']:,} 원`", inline=True)
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="뉴스", description="[관리자 전용] 랜덤으로 2개의 뉴스를 발생시키고 주가에 즉시 반영합니다.")
async def trigger_random_news(interaction: discord.Interaction):
    # 1. 관리자 권한 체크
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ 이 명령어는 서버 관리자만 사용할 수 있습니다.", ephemeral=True)
        return

    # 2. 파일 데이터 로드
    events_data = load_data(EVENTS_FILE, {})
    stocks_data = load_data(STOCKS_FILE, {})

    # 등록된 뉴스가 2개 미만인 경우 예외 처리
    if len(events_data) < 2:
        await interaction.response.send_message("❌ `events.json`에 등록된 뉴스가 최소 2개 이상이어야 합니다.", ephemeral=True)
        return

    # 3. 전체 뉴스 중 랜덤으로 2개 선택 (중복 없이)
    selected_ids = random.sample(list(events_data.keys()), 2)

    # 뉴스 결과를 담을 임베드 생성
    embed = discord.Embed(
        title="🚨 [긴급 속보] 주식 시장 주요 뉴스 발행",
        description="관리자에 의해 새로운 뉴스가 발생하여 시장 주가에 즉시 반영되었습니다.",
        color=discord.Color.red()
    )

    # 4. 선택된 2개의 뉴스를 순회하며 주가 반영 및 임ベ드 추가
    for event_id in selected_ids:
        event_info = events_data[event_id]
        news_title = event_info.get("title", "제목 없음")
        news_text = event_info.get("text", "내용 없음")
        change_rate = event_info.get("change", "0")

        # 뉴스 ID 앞부분을 추출하여 실제 stocks.json의 기업 명칭과 매칭
        # (알려주신 맵핑 규칙 적용)
        prefix = event_id.split('.')[0].lower()
        
        if "apple" in prefix:
            target_company = "애플"
        elif "samsung" in prefix:
            target_company = "삼성전자"
        elif "hanhwa" in prefix:
            target_company = "한화"
        else:
            # 지정된 3개 기업 외에 다른 이름이 들어올 경우를 대비한 자동 매칭 예외처리
            target_company = None
            for stock_name in stocks_data.keys():
                if prefix in stock_name.lower() or stock_name.lower() in prefix:
                    target_company = stock_name
                    break

        # stocks.json에 해당 기업이 존재하는지 확인 후 주가 변동 적용
        if target_company and target_company in stocks_data:
            try:
                rate = float(change_rate) / 100.0
                current_price = stocks_data[target_company]["price"]
                
                # 새로운 주가 계산 (소수점 버림)
                new_price = math.floor(current_price * (1 + rate))
                stocks_data[target_company]["price"] = new_price
                
                # 부호 및 화살표 표시
                arrow = f"📈 +{change_rate}%" if rate > 0 else f"📉 {change_rate}%"
                
                # 임베드에 뉴스 정보 추가
                embed.add_field(
                    name=f"📌 {news_title}",
                    value=f"{news_text}\n\n🏢 **영향 기업:** {target_company}\n📊 **주가 변동:** {current_price:,}원 ➡️ **{new_price:,}원** ({arrow})",
                    inline=False
                )
            except ValueError:
                print(f"❌ 뉴스 수치 변환 오류 (ID: {event_id})")
        else:
            # 기업 매칭에 실패한 경우 뉴스는 띄우되 주가는 바꾸지 않음
            embed.add_field(
                name=f"📌 {news_title} (시장 영향 없음)",
                value=f"{news_text}",
                inline=False
            )

    # 5. 변동된 주가 데이터를 `stocks.json`에 즉시 저장!
    save_data(STOCKS_FILE, stocks_data)

    # 6. 전 서버 유저들이 볼 수 있게 속보 전송 (ephemeral=False)
    await interaction.response.send_message(embed=embed, ephemeral=False)

bot.run(os.getenv("DISCORD_TOKEN"))
