import smtplib
from email.message import EmailMessage
import discord
from discord.ext import commands, tasks
import os
import json
from datetime import datetime, timezone, time as dtime

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.guilds = True
intents.dm_messages = True
intents.members = True

bot = commands.Bot(command_prefix="/", intents=intents)

user_states = {}
questions = [
    "What did you understand from the book that you read?",
    "What did you learn that you can do in your life?",
    "Send a proof with the name of the book (upload file/photo).",
    "(Optional) Do you want to add the name of the book? If not, type NO."
]
proof_requests = {
    0: "Submit your photo please.",
    1: "Submit your video please.",
    2: "Submit your photo please."
}

channel_id_restrict = 1392159500437553172
category_id_commands = 1390938040431677611

# Ensure folders exist
os.makedirs("submissions", exist_ok=True)
os.makedirs("jokers", exist_ok=True)
os.makedirs("wallets", exist_ok=True)

@bot.event
async def on_ready():
    print(f"✅ Bot is ready as {bot.user}")
    apply_daily_scores.start()
    monthly_reset.start()
    send_weekly_email.start()  # ← MOVE IT HERE


@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    if message.content.startswith("/") or message.channel.id != channel_id_restrict:
        await bot.process_commands(message)
        return

    user_id = str(message.author.id)
    today = datetime.utcnow().strftime("%Y-%m-%d")
    filepath = f"submissions/{today}_{user_id}.json"

    if user_id in user_states and user_states[user_id].get("confirmation_pending"):
        answer = message.content.strip().lower()
        if answer == "yes":
            os.remove(filepath)
            del user_states[user_id]
        elif answer == "no":
            await message.channel.send("❌ Submission cancelled. Keeping previous one.")
            del user_states[user_id]
            return
        else:
            await message.channel.send("Please answer with 'yes' or 'no'.")
            return

    if user_id not in user_states:
        if os.path.exists(filepath):
            user_states[user_id] = {
                "confirmation_pending": True,
                "start_time": today,
                "username": message.author.display_name
            }
            await message.channel.send("🔁 You’ve already submitted today. Do you want to replace the previous submission? (yes/no)")
            return

        user_states[user_id] = {
            "step": 0,
            "answers": {},
            "proof_path": None,
            "start_time": today,
            "username": message.author.display_name
        }
        await message.channel.send(questions[0])
        return

    state = user_states[user_id]
    step = state.get("step", 0)

    if step == 2:  # Expecting proof file
        if message.attachments:
            proof_url = message.attachments[0].url
            state["proof_path"] = proof_url
            state["step"] += 1
        else:
            await message.channel.send("⚠️ Please upload your proof (image or file) for the book.")
            return
    else:
        state["answers"][f"q{step}"] = message.content.strip()
        state["step"] += 1

    if state["step"] < len(questions):
        await message.channel.send(questions[state["step"]])
    else:
        score = 0  # You can define custom logic later if needed

        await message.channel.send("✅ Thanks for submitting! Your score for today is: 0 Jokers")

        submission_data = {
            "user": state["username"],
            "answers": state["answers"],
            "proof": state["proof_path"],
            "score": score
        }
        with open(filepath, "w") as f:
            json.dump(submission_data, f, indent=2)

        del user_states[user_id]

def update_joker(user_id: str, delta: float):
    filepath = f"jokers/{user_id}.json"
    current = 0
    if os.path.exists(filepath):
        with open(filepath, "r") as f:
            current = json.load(f).get("jokers", 0)
    current += delta
    with open(filepath, "w") as f:
        json.dump({"jokers": current}, f)

def update_wallet(user_id: str, delta: float):
    filepath = f"wallets/{user_id}.json"
    balance = 0
    if os.path.exists(filepath):
        with open(filepath, "r") as f:
            balance = json.load(f).get("wallet", 0)
    balance += delta
    with open(filepath, "w") as f:
        json.dump({"wallet": round(balance, 2)}, f)

def is_admin(member: discord.Member):
    return member.guild_permissions.manage_messages

@bot.command(name="view_submissions")
@commands.cooldown(1, 5, commands.BucketType.user)
async def view_submissions(ctx, date: str = None):
    if ctx.channel.category_id != category_id_commands:
        return
    if date is None:
        date = datetime.utcnow().strftime("%Y-%m-%d")
    found = False
    for file in os.listdir("submissions"):
        if file.startswith(date):
            with open(f"submissions/{file}", "r") as f:
                data = json.load(f)
                msg = f"📅 Submission from {data['user']}:\n"
                for k, v in data['answers'].items():
                    msg += f"**{k}**: {v}\n"
                for k, v in data.get("proof", {}).items():
                    msg += f"📎 Proof ({k}): {v}\n"
                await ctx.send(msg)
                found = True
    if not found:
        await ctx.send(f"No submissions found for {date}.")

@bot.command(name="add_joker")
@commands.has_permissions(manage_messages=True)
@commands.cooldown(1, 5, commands.BucketType.user)
async def add_joker(ctx, user: discord.User, amount: float):
    if ctx.channel.category_id != category_id_commands:
        return
    update_joker(str(user.id), amount)
    await ctx.send(f"✅ Added {amount} Jokers to {user.display_name}.")

@bot.command(name="remove_joker")
@commands.has_permissions(manage_messages=True)
@commands.cooldown(1, 5, commands.BucketType.user)
async def remove_joker(ctx, user: discord.User, amount: float):
    if ctx.channel.category_id != category_id_commands:
        return
    update_joker(str(user.id), -amount)
    await ctx.send(f"✅ Removed {amount} Jokers from {user.display_name}.")

@bot.command(name="jokers")
@commands.cooldown(1, 5, commands.BucketType.user)
async def jokers(ctx, user: discord.User = None):
    if ctx.channel.category_id != category_id_commands:
        return
    if user and user != ctx.author and not is_admin(ctx.author):
        await ctx.send("❌ You don’t have permission to check other users’ Jokers.")
        return
    if user is None:
        user = ctx.author
    filepath = f"jokers/{user.id}.json"
    jokers = 0
    if os.path.exists(filepath):
        with open(filepath, "r") as f:
            jokers = json.load(f).get("jokers", 0)
    await ctx.send(f"🃏 {user.display_name} has {jokers} Jokers.")

@bot.command(name="wallet")
@commands.cooldown(1, 5, commands.BucketType.user)
async def wallet(ctx, user: discord.User = None):
    if ctx.channel.category_id != category_id_commands:
        return
    if user and user != ctx.author and not is_admin(ctx.author):
        await ctx.send("❌ You don’t have permission to check another user’s wallet.")
        return
    if user is None:
        user = ctx.author
    filepath = f"wallets/{user.id}.json"
    balance = 0.0
    if os.path.exists(filepath):
        with open(filepath, "r") as f:
            balance = json.load(f).get("wallet", 0.0)
    await ctx.send(f"💰 {user.display_name}'s wallet: €{balance:.2f}")

@bot.command(name="add_money")
@commands.has_permissions(manage_messages=True)
@commands.cooldown(1, 5, commands.BucketType.user)
async def add_money(ctx, user: discord.User, amount: float):
    update_wallet(str(user.id), amount)
    await ctx.send(f"💶 Added {amount}€ to {user.display_name}'s wallet.")

@bot.command(name="remove_money")
@commands.has_permissions(manage_messages=True)
@commands.cooldown(1, 5, commands.BucketType.user)
async def remove_money(ctx, user: discord.User, amount: float):
    update_wallet(str(user.id), -amount)
    await ctx.send(f"💸 Removed {amount}€ from {user.display_name}'s wallet.")


import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

@bot.command(name="test_email")
async def test_email(ctx):
    sender_email = os.getenv("EMAIL_ADDRESS")
    sender_password = os.getenv("EMAIL_PASSWORD")
    recipients = ["ala.hergli20@gmail.com", "medazizhergli2006@gmail.com"]

    message = MIMEMultipart()
    message["From"] = sender_email
    message["To"] = ", ".join(recipients)
    message["Subject"] = "✅ Test Email from Discord Bot"

    body = "This is a test email to confirm your Railway SMTP setup works."
    message.attach(MIMEText(body, "plain"))

    try:
        server = smtplib.SMTP(os.getenv("SMTP_SERVER"), int(os.getenv("SMTP_PORT")))
        server.starttls()
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, recipients, message.as_string())
        server.quit()
        await ctx.send("✅ Test email sent successfully.")
    except Exception as e:
        await ctx.send(f"❌ Failed to send email: {e}")


@tasks.loop(time=dtime(hour=23, minute=59, tzinfo=timezone.utc))
async def apply_daily_scores():
    today = datetime.utcnow().strftime("%Y-%m-%d")
    users_with_submission = set()
    for file in os.listdir("submissions"):
        if file.startswith(today):
            with open(f"submissions/{file}", "r") as f:
                data = json.load(f)
                user_id = file.split("_")[1].split(".")[0]
                users_with_submission.add(user_id)
                update_joker(user_id, data.get("score", 0))
    if datetime.utcnow().weekday() != 5:  # Not Saturday
        for filename in os.listdir("jokers"):
            user_id = filename.replace(".json", "")
            if user_id not in users_with_submission:
                update_joker(user_id, -1)


@tasks.loop(time=dtime(hour=0, minute=1, tzinfo=timezone.utc))
async def monthly_reset():
    if datetime.utcnow().day != 1:
        return
    for filename in os.listdir("jokers"):
        user_id = filename.replace(".json", "")
        with open(f"jokers/{filename}", "r") as f:
            jokers = json.load(f).get("jokers", 0)
        bonus = jokers * 5 if jokers >= 0 else jokers * 15
        if jokers >= 0:
            bonus += 50
        update_wallet(user_id, bonus)
        update_joker(user_id, -jokers)
        if not os.path.exists(f"wallets/{user_id}.json"):
            update_wallet(user_id, 0)
        if not is_admin(ctx.guild.get_member(int(user_id))):
            update_joker(user_id, 5)


@tasks.loop(time=dtime(hour=0, minute=0, tzinfo=timezone.utc))
async def send_weekly_email():
    if datetime.utcnow().weekday() != 6:  # Sunday
        return

    summary = ""
    for filename in os.listdir("jokers"):
        user_id = filename.replace(".json", "")
        jokers = 0
        wallet = 0.0
        if os.path.exists(f"jokers/{user_id}.json"):
            with open(f"jokers/{user_id}.json", "r") as f:
                jokers = json.load(f).get("jokers", 0)
        if os.path.exists(f"wallets/{user_id}.json"):
            with open(f"wallets/{user_id}.json", "r") as f:
                wallet = json.load(f).get("wallet", 0.0)
        
        summary += f"👤 User ID: {user_id}\n"
        summary += f"  - Jokers: {jokers}\n"
        summary += f"  - Wallet: €{wallet:.2f}\n\n"

    msg = EmailMessage()
    msg["Subject"] = "📊 Weekly CheckBot Stats"
    msg["From"] = os.getenv("EMAIL_ADDRESS")
    msg["To"] = "ala.hergli20@gmail.com, medazizhergli2006@gmail.com"
    msg.set_content(summary)

    try:
        with smtplib.SMTP(os.getenv("SMTP_SERVER"), int(os.getenv("SMTP_PORT"))) as smtp:
            smtp.starttls()
            smtp.login(os.getenv("EMAIL_ADDRESS"), os.getenv("EMAIL_PASSWORD"))
            smtp.send_message(msg)
        print("✅ Weekly email sent.")
    except Exception as e:
        print(f"❌ Failed to send email: {e}")


import os
bot.run(os.getenv("DISCORD_TOKEN"))

