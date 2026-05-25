import discord
from discord import app_commands
from discord.ext import commands, tasks
import json
import os
import random
import math
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dotenv import load_dotenv

# 💡 절대 경로 지정을 통해 .env 파일을 찾지 못하는 버그를 방지합니다.
env_path = Path(__file__).parent / '.env'
load_dotenv(dotenv_path=env_path)

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
    "엔비디아": (30000, 2000000), "구글": (50000, 2500000), "마이크로소프트": (60000, 3000000),
    "테슬라": (20000, 1800000), "아마존": (30000, 1900000), "메타": (40000, 2200000),
    "넷플릭스": (35000, 2100000), "TSMC": (25000, 1600000), "ASML": (80000, 4500000),
    "도요타": (15000, 1100000), "소니": (10000, 950000), "네이버": (30000, 800000),
    "카카오": (10, 50000), "스페이스X": (50000, 800000)
}

market_status = {
    "is_open": False,
    "open_time": "09:00",
    "close_time": "22:30"
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
    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    os.replace(temp_file, file_path)

user_wallets = load_data(USERS_FILE, {})
stock_market = load_data(STOCKS_FILE, {})
config_data = load_data(CONFIG_FILE, {"news_channel_id": None})
events_pool = load_data(EVENTS_FILE, [])

def get_korea_time():
    return datetime.now(timezone.utc) + timedelta(hours=9)

def is_market_open_now():
    if not market_status["is_open"]:
        return False
    try:
        now_dt = get_korea_time()
        now_str = now_dt.strftime("%Y-%m-%d")
        open_dt = datetime.strptime(f"{now_str} {market_status['open_time']}", "%Y-%m-%d %H:%M")
        close_dt = datetime.strptime(f"{now_str} {market_status['close_time']}", "%Y-%m-%d %H:%M")
        return open_dt <= now_dt.replace(tzinfo=None) <= close_dt
    except Exception:
        return market_status["is_open"]

@bot.event
async def on_ready():
    print(f"✅ 로그인 성공: {bot.user.name}")
    try:
        synced = await bot.tree.sync()
        print(f"🔄 {len(synced)}개의 슬래시 명령어 동기화 완료.")
    except Exception as e:
        print(f"❌ 명령어 동기화 실패: {e}")
    if not update_stocks.is_running():
        update_stocks.start()

# 🔄 30초마다 주가를 변동시키는 루프 함수
@tasks.loop(seconds=30)
async def update_stocks():
    global stock_market
    if not is_market_open_now() or not stock_market:
        return

    news_channel = None
    if config_data.get("news_channel_id"):
        news_channel = bot.get_channel(config_data["news_channel_id"])

    # 5% 확률로 전체 시장 이벤트 발생
    event_triggered = random.random() < 0.05
    current_event = None
    if event_triggered and events_pool:
        current_event = random.choice(events_pool)
        if news_channel:
            embed = discord.Embed(
                title=f"🚨 [긴급 속보] {current_event['title']}",
                description=current_event['description'],
                color=discord.Color.red() if current_event['effect'] < 0 else discord.Color.blue()
            )
            await news_channel.send(embed=embed)

    for stock_name, stock_info in stock_market.items():
        current_price = stock_info["price"]
        start_price = stock_info.get("start_price", current_price)

        # 기본 주가 변동 연산
        change_percent = random.uniform(-4.5, 4.5)
        
        # 소형주 추가 변동성
        if current_price < 5000:
            change_percent += random.uniform(-2.0, 2.0)

        # 추세 반영
        trend = stock_info.get("trend", 0)
        change_percent += trend
        if random.random() < 0.15:
            stock_info["trend"] = random.uniform(-1.5, 1.5)

        price_change = int(current_price * (change_percent / 100))
        current_price += price_change

        # 💡 [버그 수정 1] 일반 변동 시 정수 오버플로우 및 음수 주가 방지 (최소 10원 ~ 최대 20억 원 제한)
        current_price = max(10, min(current_price, 2000000000))

        # 이벤트 반영
        if current_event and current_event.get("target") == stock_name:
            event_effect = current_event["effect"]
            event_change = int(current_price * (event_effect / 100))
            current_price += event_change
            
            # 💡 [버그 수정 2] 이벤트 변동 시 정수 오버플로우 방지 (최소 10원 ~ 최대 20억 원 제한)
            current_price = max(10, min(current_price, 2000000000))

        rate = ((current_price - start_price) / start_price) * 100
        stock_info["price"] = current_price
        stock_info["rate"] = round(rate, 2)
        stock_info["change"] = current_price - start_price

    save_data(STOCKS_FILE, stock_market)

@bot.tree.command(name="주식시작", description="주식 게임에 가입하고 투자 자금을 받습니다.")
async def start_game(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    if user_id in user_wallets:
        await interaction.response.send_message("❌ 이미 주식 게임에 가입되어 있습니다.", ephemeral=True)
        return

    # 💡 [역할 관리 권한 부족 예외 처리 보완]
    role = interaction.guild.get_role(1504759968837140491)
    if role:
        try:
            await interaction.user.add_roles(role)
        except discord.Forbidden:
            print("⚠️ 경고: 봇의 역할 순서가 지급할 역할보다 낮아 역할을 지급하지 못했습니다.")
            # 역할을 못 주더라도 가입 프로세스는 계속 진행되도록 처리하거나 안내창을 띄웁니다.

    user_wallets[user_id] = {"money": 500000, "debt": 0, "bank": "None", "stocks": {}, "last_attendance": ""}
    save_data(USERS_FILE, user_wallets)
    await interaction.response.send_message("🎉 가입 완료! 초기 자본 500,000원이 지급되었습니다.")

@bot.tree.command(name="주가보기", description="현재 시장의 모든 주식 시세를 확인합니다.")
async def 내시세(interaction: discord.Interaction):
    if not stock_market:
        await interaction.response.send_message("📊 현재 시장에 등록된 기업이 없습니다. 먼저 `/주식초기화`를 진행해 주세요.", ephemeral=True)
        return

    embed = discord.Embed(title="📊 실시간 주식 시장 시세판", color=discord.Color.blue())
    for stock_name, info in stock_market.items():
        price = info["price"]
        rate = info["rate"]
        change = info["change"]
        
        sign = "🔺" if change > 0 else "🔻" if change < 0 else "🔹"
        change_str = f"{sign} {abs(change):,}" if change != 0 else "0"
        
        embed.add_field(
            name=f"🏢 {stock_name}",
            value=f"**현재가:** {price:,}원\n**전일대비:** {change_str} ({rate:+.2f}%)",
            inline=True
        )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="주식구매", description="지정한 기업의 주식을 매수합니다.")
@app_commands.describe(기업명="구매할 기업 이름", 수량="구매할 주식 수량 (1 이상의 정수)")
async def buy_stock(interaction: discord.Interaction, 기업명: str, 수량: int):
    if not is_market_open_now():
        await interaction.response.send_message("🔒 현재 주식 시장이 닫혀 있습니다.", ephemeral=True)
        return
    if 수량 <= 0:
        await interaction.response.send_message("❌ 수량은 1주 이상이어야 합니다.", ephemeral=True)
        return

    user_id = str(interaction.user.id)
    if user_id not in user_wallets:
        await interaction.response.send_message("❌ 먼저 `/주식시작` 명령어로 게임에 가입해 주세요.", ephemeral=True)
        return
    if 기업명 not in stock_market:
        await interaction.response.send_message("❌ 존재하지 않는 기업입니다.", ephemeral=True)
        return

    stock_price = stock_market[기업명]["price"]
    total_cost = stock_price * 수량

    if user_wallets[user_id]["money"] < total_cost:
        await interaction.response.send_message("❌ 잔액이 부족합니다.", ephemeral=True)
        return

    user_wallets[user_id]["money"] -= total_cost
    user_stocks = user_wallets[user_id]["stocks"]
    
    if 기업명 not in user_stocks:
        user_stocks[기업명] = {"amount": 0, "avg_price": 0}
        
    current_amount = user_stocks[기업명]["amount"]
    current_avg = user_stocks[기업명]["avg_price"]
    
    new_amount = current_amount + 수량
    new_avg = int(((current_avg * current_amount) + total_cost) / new_amount)
    
    user_stocks[기업명]["amount"] = new_amount
    user_stocks[기업명]["avg_price"] = new_avg

    save_data(USERS_FILE, user_wallets)
    await interaction.response.send_message(f"🛒 **{기업명}** 주식 {수량}주를 {total_cost:,}원에 매수했습니다.")

@bot.tree.command(name="주식판매", description="보유 중인 주식을 매도합니다.")
@app_commands.describe(기업명="판매할 기업 이름", 수량="판매할 주식 수량 (1 이상의 정수)")
async def sell_stock(interaction: discord.Interaction, 기업명: str, 수량: int):
    if not is_market_open_now():
        await interaction.response.send_message("🔒 현재 주식 시장이 닫혀 있습니다.", ephemeral=True)
        return
    if 수량 <= 0:
        await interaction.response.send_message("❌ 수량은 1주 이상이어야 합니다.", ephemeral=True)
        return

    user_id = str(interaction.user.id)
    if user_id not in user_wallets or 기업명 not in user_wallets[user_id]["stocks"]:
        await interaction.response.send_message("❌ 해당 주식을 보유하고 있지 않습니다.", ephemeral=True)
        return

    owned_amount = user_wallets[user_id]["stocks"][기업명]["amount"]
    if owned_amount < 수량:
        await interaction.response.send_message(f"❌ 보유 주식이 부족합니다. (현재 보유: {owned_amount}주)", ephemeral=True)
        return

    stock_price = stock_market[기업명]["price"]
    total_revenue = stock_price * 수량

    user_wallets[user_id]["money"] += total_revenue
    user_wallets[user_id]["stocks"][기업명]["amount"] -= 수량

    if user_wallets[user_id]["stocks"][기업명]["amount"] == 0:
        del user_wallets[user_id]["stocks"][기업명]

    save_data(USERS_FILE, user_wallets)
    await interaction.response.send_message(f"💰 **{기업명}** 주식 {수량}주를 {total_revenue:,}원에 매도했습니다.")

@bot.tree.command(name="지갑", description="내 자산 상태와 보유 주식 현황을 보여줍니다.")
async def show_wallet(interaction: discord.Interaction):
    user_id = str(interaction.user.id)
    if user_id not in user_wallets:
        await interaction.response.send_message("❌ 먼저 `/주식시작` 명령어로 게임에 가입해 주세요.", ephemeral=True)
        return

    wallet = user_wallets[user_id]
    cash = wallet["money"]
    total_stock_eval = 0

    embed = discord.Embed(title=f"💳 {interaction.user.display_name}님의 자산 현황판", color=discord.Color.green())
    embed.add_field(name="💵 보유 현금", value=f"{cash:,}원", inline=False)

    stock_list_str = ""
    for stock_name, stock_data in wallet["stocks"].items():
        amount = stock_data["amount"]
        avg_price = stock_data["avg_price"]
        current_price = stock_market[stock_name]["price"] if stock_name in stock_market else avg_price
        
        eval_price = current_price * amount
        total_stock_eval += eval_price
        
        profit = eval_price - (avg_price * amount)
        profit_rate = (profit / (avg_price * amount)) * 100 if avg_price > 0 else 0
        
        stock_list_str += f"**{stock_name}**: {amount}주 보유\n  └ 평단가: {avg_price:,}원 | 현재가: {current_price:,}원\n  └ 평가금액: {eval_price:,}원 ({profit_rate:+.2f}%)\n\n"

    if not stock_list_str:
        stock_list_str = "*현재 보유 중인 주식이 없습니다.*"

    embed.add_field(name="📈 보유 주식 상세 목록", value=stock_list_str, inline=False)
    embed.add_field(name="💰 총 자산 (현금+주식)", value=f"**{cash + total_stock_eval:,}원**", inline=False)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="주식초기화", description="[관리자] 모든 주가 및 유저 정보를 초기 상태로 리셋합니다.")
@app_commands.checks.has_permissions(administrator=True)
async def reset_all(interaction: discord.Interaction):
    global stock_market, user_wallets
    stock_market = {}
    for name, (min_p, max_p) in STOCK_RESET_RANGES.items():
        initial_price = random.randint(min_p, max_p)
        stock_market[name] = {
            "price": initial_price,
            "start_price": initial_price,
            "rate": 0.0,
            "change": 0,
            "trend": random.uniform(-1.0, 1.0)
        }
    user_wallets = {}
    save_data(STOCKS_FILE, stock_market)
    save_data(USERS_FILE, user_wallets)
    await interaction.response.send_message("🔄 [시스템] 모든 데이터베이스가 성공적으로 포맷 및 초기화되었습니다.")

@bot.tree.command(name="시장개장", description="[관리자] 지정된 시간 범위 동안 주식 거래를 승인합니다.")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(시작시간="예: 09:00", 종료시간="예: 22:30")
async def open_market(interaction: discord.Interaction, 시작시간: str, 종료시간: str):
    try:
        now_date = get_korea_time().strftime("%Y-%m-%d")
        full_open_time = datetime.strptime(f"{now_date} {시작시간}", "%Y-%m-%d %H:%M")
        full_close_time = datetime.strptime(f"{now_date} {종료시간}", "%Y-%m-%d %H:%M")
        
        if full_close_time <= full_open_time:
            await interaction.response.send_message("❌ 종료 시간은 시작 시간보다 늦어야 합니다.", ephemeral=True)
            return

        global market_status
        market_status["is_open"] = True
        market_status["open_time"] = 시작시간
        market_status["close_time"] = 종료시간

        embed = discord.Embed(
            title="🔔 [주식 시장 강제 개장 통보]",
            description="관리자의 권한으로 주식 시장이 임시 개장되었습니다!",
            color=discord.Color.green()
        )
        embed.add_field(name="🔓 시장 상태", value="**🟢 거래 가능 (OPEN)**", inline=True)
        embed.add_field(name="⏰ 운영 기간", value=f"**{시작시간}** ~ **{종료시간}** (당일 기준)", inline=True)
        embed.set_footer(text="※ 지정된 운영 시간 외에는 거래 기능이 제한됩니다.")

        await interaction.response.send_message(embed=embed, ephemeral=False)

    except ValueError:
        await interaction.response.send_message(
            "❌ 시간 형식이 올바르지 않습니다.\n**HH:MM** 형태로 입력해 주세요! (예: `09:30`, `17:00`)", 
            ephemeral=True
        )

# 봇 실행
bot.run(DISCORD_TOKEN)
