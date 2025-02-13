import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, InputMediaVideo
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, CallbackContext, CallbackQueryHandler
import urllib.parse
from pymongo import MongoClient
from datetime import datetime, timedelta
import requests

# Bot Configuration
BOT_TOKEN = "7559089435:AAFT3aJ4AGB2JaVbftJlkJ71CjsmWtxDGBw"
MONGO_URI = "mongodb+srv://ak:ak@cluster0.ftsd9.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
CHANNEL_ID = "-1002285272169"
FORCE_SUBS1 = "-1002106690102"
FORCE_SUBS2 = "-1002488211847"
VERIFICATION_REQUIRED = True

# Admin IDs
admin_ids = [5706788169, 5706788169]

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# MongoDB connection
try:
    client = MongoClient(MONGO_URI)
    db = client['terabox_bot']
    users_collection = db['users']
    verification_logs = db['verification_logs']  # Collection for verification tracking
    logger.info("Successfully connected to MongoDB!")
except Exception as e:
    logger.error(f"Error connecting to MongoDB: {e}")
    raise

def shorten_url_link(url):
    """
    Shorten URL using RgLinks.com API
    """
    try:
        api_url = 'https://rglinks.com/api'
        api_key = 'cedfe548e9b4ac8d706ea4e23b86e13a1eaaaa9c'
        
        params = {
            'api': api_key,
            'url': url,
            'format': 'json'
        }
        
        response = requests.get(api_url, params=params)
        
        if response.status_code == 200:
            try:
                data = response.json()
                if data.get('status') == 'success' and 'shortenedUrl' in data:
                    shortened_url = data['shortenedUrl'].replace('\\', '')
                    logger.info(f"Successfully shortened URL: {shortened_url}")
                    return shortened_url
                else:
                    logger.error(f"RgLinks API error: {data}")
                    return url
            except ValueError as e:
                logger.error(f"Failed to parse RgLinks API response: {e}")
                return url
        else:
            logger.error(f"RgLinks API request failed with status code: {response.status_code}")
            return url
            
    except Exception as e:
        logger.error(f"Error in URL shortening: {e}")
        return url

async def check_subscription(user_id: int, bot) -> bool:
    """
    Check if user has subscribed to both required channels
    """
    try:
        member1 = await bot.get_chat_member(chat_id=FORCE_SUBS1, user_id=user_id)
        member2 = await bot.get_chat_member(chat_id=FORCE_SUBS2, user_id=user_id)
        return all(member.status in ['creator', 'administrator', 'member'] 
                  for member in [member1, member2])
    except Exception as e:
        logger.error(f"Error checking subscription: {e}")
        return False

async def create_invite_link(chat_id: int, bot) -> str:
    """
    Create invite link for a channel
    """
    try:
        invite_link = await bot.create_chat_invite_link(chat_id=chat_id)
        return invite_link.invite_link
    except Exception as e:
        logger.error(f"Error creating invite link: {e}")
        return None

async def check_verification(user_id: int) -> bool:
    """
    Check if user is verified and within 24-hour window
    """
    user = users_collection.find_one({"user_id": user_id})
    if user and user.get("verified_until", datetime.min) > datetime.now():
        return True
    return False

async def get_token(user_id: int, bot_username: str) -> str:
    """
    Generate verification token and create shortened verification link
    """
    try:
        token = os.urandom(16).hex()
        
        users_collection.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "token": token,
                    "verified_until": datetime.min,
                    "token_generated_at": datetime.now()
                }
            },
            upsert=True
        )
        
        telegram_verification_link = f"https://telegram.me/{bot_username}?start={token}"
        shortened_link = shorten_url_link(telegram_verification_link)
        
        logger.info(f"Generated verification token for user {user_id}: {token}")
        logger.info(f"Shortened verification link: {shortened_link}")
        
        return shortened_link
        
    except Exception as e:
        logger.error(f"Error in token generation and link shortening: {e}")
        return telegram_verification_link

async def log_verification(user_id: int, username: str, full_name: str):
    """
    Log user verification with timestamp
    """
    try:
        verification_logs.insert_one({
            "user_id": user_id,
            "username": username,
            "full_name": full_name,
            "verified_at": datetime.now()
        })
    except Exception as e:
        logger.error(f"Error logging verification: {e}")

async def get_daily_verifications() -> dict:
    """
    Get verification statistics for the current day (12 AM to 12 AM)
    """
    try:
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow_start = today_start + timedelta(days=1)
        
        daily_verifications = verification_logs.count_documents({
            "verified_at": {
                "$gte": today_start,
                "$lt": tomorrow_start
            }
        })
        
        unique_users = len(set(log['user_id'] for log in verification_logs.find({
            "verified_at": {
                "$gte": today_start,
                "$lt": tomorrow_start
            }
        })))
        
        return {
            "total_verifications": daily_verifications,
            "unique_users": unique_users,
            "start_time": today_start,
            "end_time": tomorrow_start
        }
    except Exception as e:
        logger.error(f"Error getting daily verifications: {e}")
        return None

async def verified_command(update: Update, context: CallbackContext) -> None:
    """
    Handle /verified command to show daily verification statistics
    """
    if update.effective_user.id in admin_ids:
        stats = await get_daily_verifications()
        if stats:
            message = (
                f"📊 **Daily Verification Statistics**\n\n"
                f"🕐 Period: {stats['start_time'].strftime('%Y-%m-%d %H:%M')} to {stats['end_time'].strftime('%Y-%m-%d %H:%M')}\n\n"
                f"✅ Total Verifications: {stats['total_verifications']}\n"
                f"👥 Unique Users: {stats['unique_users']}\n"
            )
            await update.message.reply_text(message, parse_mode='Markdown')
        else:
            await update.message.reply_text("❌ Error fetching verification statistics.")
    else:
        await update.message.reply_text("⚠️ You don't have permission to use this command.")

async def prompt_subscription(update: Update, bot) -> None:
    """
    Prompt user to subscribe to required channels
    """
    invite_link1 = await create_invite_link(FORCE_SUBS1, bot)
    invite_link2 = await create_invite_link(FORCE_SUBS2, bot)

    if not invite_link1 or not invite_link2:
        await update.message.reply_text("❌ Error generating invite links. Please try again later.")
        return

    buttons = [
        [InlineKeyboardButton("Join Channel 1", url=invite_link1)],
        [InlineKeyboardButton("Join Channel 2", url=invite_link2)],
        [InlineKeyboardButton("✅ Done", callback_data="check_subscription")]
    ]
    reply_markup = InlineKeyboardMarkup(buttons)
    
    await update.message.reply_text(
        "🚨 **Join Our Channels to Use the Bot!** 🚨\n\n"
        "You must join the following channels to use this bot:\n"
        f"1. [Channel 1]({invite_link1})\n"
        f"2. [Channel 2]({invite_link2})\n\n"
        "After joining, click the '✅ Done' button below.",
        reply_markup=reply_markup,
        parse_mode='Markdown'
    )

async def check_subscription_callback(update: Update, context: CallbackContext) -> None:
    """
    Handle subscription verification callback
    """
    query = update.callback_query
    user = query.from_user
    
    if await check_subscription(user.id, context.bot):
        await query.answer("✅ Subscription verified successfully!")
        photo_url = 'https://ik.imagekit.io/dvnhxw9vq/unnamed.png?updatedAt=1735280750258'
        
        users_collection.update_one(
            {"user_id": user.id},
            {"$set": {"username": user.username, "full_name": user.full_name}},
            upsert=True
        )
        
        message = (
            f"New user verified:\n"
            f"Name: {user.full_name}\n"
            f"Username: @{user.username}\n"
            f"User ID: {user.id}"
        )
        await context.bot.send_message(chat_id=CHANNEL_ID, text=message)
        
        await query.message.edit_text(
            "✅ **Verification Successful!**\n\n"
            "You have successfully joined all required channels.\n"
            "Now you can use the bot!\n\n"
            "📝 **How to use:**\n"
            "Simply send any TeraBox link, and I'll convert it into a streaming link for you.\n\n"
            "🔹 Send your TeraBox link now to get started!\n"
            "🔹 Make sure to stay subscribed to our channels for updates.",
            parse_mode='Markdown'
        )
        
        await context.bot.send_photo(
            chat_id=user.id,
            photo=photo_url,
            caption=(
                "👋 **Welcome to TeraBox Online Player!** 🌟\n\n"
                "I'm ready to help you stream your TeraBox videos!\n\n"
                "✨ **What can I do for you?**\n"
                "- Send me any TeraBox link\n"
                "- I'll give you direct streaming links without ads\n"
                "- Enjoy uninterrupted streaming experience\n\n"
                "🔑 **Ready to start?**\n"
                "Just paste your TeraBox link below! 👇\n\n"
                "Thank you for choosing TeraBox Online Player! ❤️"
            ),
            parse_mode='Markdown'
        )
    else:
        await query.answer("❌ You need to join both channels first!", show_alert=True)

async def start(update: Update, context: CallbackContext) -> None:
    """
    Handle /start command
    """
    logger.info("Received /start command")
    user = update.effective_user

    if not await check_subscription(user.id, context.bot):
        await prompt_subscription(update, context.bot)
        return

    if context.args:
        text = update.message.text
        if text.startswith("/start terabox-"):
            await handle_terabox_link(update, context)
            return
        token = context.args[0]
        user_data = users_collection.find_one({"user_id": user.id, "token": token})

        if user_data:
            users_collection.update_one(
                {"user_id": user.id},
                {"$set": {"verified_until": datetime.now() + timedelta(days=1)}},
                upsert=True
            )
            await log_verification(user.id, user.username, user.full_name)
            await update.message.reply_text(
                "✅ **Verification Successful!**\n\n"
                "You can now use the bot for the next 24 hours without any ads or restrictions.",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text(
                "❌ **Invalid Token!**\n\n"
                "Please try verifying again.",
                parse_mode='Markdown'
            )
        return

    users_collection.update_one(
        {"user_id": user.id},
        {"$set": {"username": user.username, "full_name": user.full_name}},
        upsert=True
    )
    
    message = (
        f"New user started the bot:\n"
        f"Name: {user.full_name}\n"
        f"Username: @{user.username}\n"
        f"User ID: {user.id}"
    )
    await context.bot.send_message(chat_id=CHANNEL_ID, text=message)
    
    photo_url = 'https://ik.imagekit.io/dvnhxw9vq/unnamed.png?updatedAt=1735280750258'
    await update.message.reply_photo(
        photo=photo_url,
        caption=(
            "👋 **Welcome to TeraBox Online Player!** 🌟\n\n"
            "I'm here to help you stream your TeraBox videos!\n\n"
            "✨ **What can I do for you?**\n"
            "- Send me any TeraBox link\n"
            "- I'll give you direct streaming links without ads\n"
            "- Enjoy uninterrupted streaming experience\n\n"
            "🔑 **Ready to start?**\n"
            "Just paste your TeraBox link below! 👇\n\n"
            "Thank you for choosing TeraBox Online Player! ❤️"
        ),
        parse_mode='Markdown'
    )

async def handle_link(update: Update, context: CallbackContext) -> None:
    """
    Handle incoming TeraBox links
    """
    user = update.effective_user
    
    if user.id not in admin_ids:
        if VERIFICATION_REQUIRED and not await check_verification(user.id):
            verification_link = await get_token(user.id, context.bot.username)
            
            btn = [
                [InlineKeyboardButton("🔑 Verify Now", url=verification_link)],
                [InlineKeyboardButton("📝 How To Verify", url="https://t.me/TutorialsNG/5")]
            ]
            
            await update.message.reply_text(
                text=(
                    "🚨 <b>Verification Required!</b>\n\n"
                    "<b>⏰ Duration: 24 hours</b>\n\n"
                    "Please verify your access to continue using the bot.\n\n"
                    "<b>🔑 Why Verify?</b>\n"
                    "• Access premium features\n"
                    "• Ad-free experience\n"
                    "• 24 hours uninterrupted access\n\n"
                    "<b>👉 Click the 'Verify Now' button below</b>\n\n"
                    "❤️ Thank you for your support!"
                ),
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup(btn)
            )
            return

    if update.message.text.startswith('http://') or update.message.text.startswith('https://'):
        original_link = update.message.text
        parsed_link = urllib.parse.quote(original_link, safe='')
        modified_link = f"https://terabox-player-one.vercel.app/?url=https://www.terabox.tech/play.html?url={parsed_link}"
        modified_url = f"https://terabox-player-one.vercel.app/?url=https://www.terabox.tech/play.html?url={parsed_link}"
        link_parts = original_link.split('/')
        link_id = link_parts[-1]
        sharelink = f"https://t.me/share/url?url=https://t.me/TeraBox_Video_Player_Robot?start=terabox-{link_id}"

        button = [
            [InlineKeyboardButton("🌐Stream Server 1🌐", url=modified_link)],
            [InlineKeyboardButton("🌐Stream Server 2🌐", url=modified_url)],
            [InlineKeyboardButton("◀Share▶", url=sharelink)]
        ]
        reply_markup = InlineKeyboardMarkup(button)

        user_message = (
            f"User message:\n"
            f"Name: {update.effective_user.full_name}\n"
            f"Username: @{update.effective_user.username}\n"
            f"User ID: {update.effective_user.id}\n"
            f"Message: {original_link}"
        )
        await context.bot.send_message(chat_id=CHANNEL_ID, text=user_message)

        await update.message.reply_text(
            f"👇👇 YOUR VIDEO LINK IS READY, USE THESE SERVERS 👇👇\n\n♥ 👇Your Stream Link👇 ♥\n",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text("Please send Me Only TeraBox Link.")

async def handle_terabox_link(update: Update, context: CallbackContext) -> None:
    """
    Handle TeraBox links from shared messages
    """
    text = update.message.text
    user = update.effective_user
    
    if user.id not in admin_ids:
        if VERIFICATION_REQUIRED and not await check_verification(user.id):
            verification_link = await get_token(user.id, context.bot.username)
            btn = [
                [InlineKeyboardButton("🔑 Verify Now", url=verification_link)],
                [InlineKeyboardButton("📝 How To Verify", url="https://t.me/TutorialsNG/5")]
            ]
            await update.message.reply_text(
                text=(
                    "🚨 <b>Verification Required!</b>\n\n"
                    "<b>⏰ Duration: 24 hours</b>\n\n"
                    "Please verify your access to continue using the bot.\n\n"
                    "<b>🔑 Why Verify?</b>\n"
                    "• Access premium features\n"
                    "• Ad-free experience\n"
                    "• 24 hours uninterrupted access\n\n"
                    "<b>👉 Click the 'Verify Now' button below</b>\n\n"
                    "❤️ Thank you for your support!"
                ),
                parse_mode='HTML',
                reply_markup=InlineKeyboardMarkup(btn)
            )
            return
               
    if text.startswith("/start terabox-"):
        link_text = text.replace("/start terabox-", "")
        link = f"https://terabox.com/s/{link_text}"
        linkb = f"https://terafileshare.com/s/{link_text}"
        slink = f"https://terabox-player-one.vercel.app/?url=https://www.terabox.tech/play.html?url={link}"
        slinkb = f"https://terabox-player-one.vercel.app/?url=https://www.terabox.tech/play.html?url={linkb}"
        share = f"https://t.me/share/url?url=https://t.me/TeraBox_Video_Player_Robot?start=terabox-{link_text}"

        button = [
            [InlineKeyboardButton("🌐Stream Server 1🌐", url=slink)],
            [InlineKeyboardButton("🌐Stream Server 2🌐", url=slinkb)],
            [InlineKeyboardButton("◀Share▶", url=share)]
        ]
        reply_markup = InlineKeyboardMarkup(button)

        await update.message.reply_text(
            f"👇👇 YOUR VIDEO LINK IS READY, USE THESE SERVERS 👇👇\n\n♥ 👇Your Stream Link👇 ♥\n",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )

async def broadcast(update: Update, context: CallbackContext) -> None:
    """
    Broadcast message to all users
    """
    if update.effective_user.id in admin_ids:
        message = update.message.reply_to_message
        if message:
            all_users = users_collection.find({}, {"user_id": 1})
            total_users = users_collection.count_documents({})
            sent_count = 0
            block_count = 0
            fail_count = 0

            for user_data in all_users:
                user_id = user_data['user_id']
                try:
                    if message.photo:
                        await context.bot.send_photo(
                            chat_id=user_id, 
                            photo=message.photo[-1].file_id, 
                            caption=message.caption
                        )
                    elif message.video:
                        await context.bot.send_video(
                            chat_id=user_id, 
                            video=message.video.file_id, 
                            caption=message.caption
                        )
                    else:
                        await context.bot.send_message(
                            chat_id=user_id, 
                            text=message.text
                        )
                    sent_count += 1
                except Exception as e:
                    if 'blocked' in str(e):
                        block_count += 1
                    else:
                        fail_count += 1

            await update.message.reply_text(
                f"Broadcast completed!\n\n"
                f"Total users: {total_users}\n"
                f"Messages sent: {sent_count}\n"
                f"Users blocked the bot: {block_count}\n"
                f"Failed to send messages: {fail_count}"
            )
        else:
            await update.message.reply_text(
                "Please reply to a message with /broadcast to send it to all users."
            )
    else:
        await update.message.reply_text("You Have No Rights To Use My Commands")

async def stats(update: Update, context: CallbackContext) -> None:
    """
    Show bot statistics
    """
    if update.effective_user.id in admin_ids:
        try:
            total_users = users_collection.count_documents({})
            db_stats = db.command("dbstats")
            used_storage_mb = db_stats['dataSize'] / (1024 ** 2)

            if 'fsTotalSize' in db_stats:
                total_storage_mb = db_stats['fsTotalSize'] / (1024 ** 2)
                free_storage_mb = total_storage_mb - used_storage_mb
            else:
                total_storage_mb = 512  # Default value
                free_storage_mb = total_storage_mb - used_storage_mb

            message = (
                f"📊 **Bot Statistics**\n\n"
                f"👥 **Total Users:** {total_users}\n"
                f"💾 **MongoDB Used Storage:** {used_storage_mb:.2f} MB\n"
                f"🆓 **MongoDB Free Storage:** {free_storage_mb:.2f} MB\n"
            )
            await update.message.reply_text(message, parse_mode='Markdown')
        except Exception as e:
            logger.error(f"Error fetching stats: {e}")
            await update.message.reply_text("❌ An error occurred while fetching stats.")
    else:
        await update.message.reply_text("You Have No Rights To Use My Commands")

def main() -> None:
    """
    Start the bot
    """
    # Initialize the bot
    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_handler(CommandHandler("verified", verified_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_link))
    application.add_handler(CallbackQueryHandler(check_subscription_callback, pattern="^check_subscription$"))

    # Start the bot
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
