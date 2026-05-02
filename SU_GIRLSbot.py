# -*- coding: utf-8 -*-
"""
Campus Women Safety Bot - Supabase Version for Vercel Webhook
All features preserved - exactly as you love it!
"""

import os
import logging
import asyncio
from datetime import datetime
from typing import Dict, List, Optional, Any

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler
from telegram.constants import ParseMode

from supabase import create_client, Client

# ==================== LOGGING ====================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== CONFIGURATION ====================
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "6044463378"))

# Supabase Configuration
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

if not TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN not set!")
if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set!")

# Initialize Supabase
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Emergency contacts (UPDATE THESE!)
EMERGENCY_CONTACTS = {
    "campus_security": "0911-123456",
    "women_support": "0911-789012",
    "counseling": "0911-345678",
}

# Year options
YEARS = ["remdial", "1st year", "2nd year", "3rd year", "4th year", "5th year", "6th year"]

# Store temporary states (in memory - OK for serverless)
user_states = {}
pending_replies = {}

# ==================== SUPABASE DATABASE FUNCTIONS ====================

def get_next_report_number() -> int:
    """Get next available report number"""
    try:
        result = supabase.table('reports').select('report_number').order('report_number', desc=True).limit(1).execute()
        if result.data and len(result.data) > 0:
            return result.data[0]['report_number'] + 1
    except Exception as e:
        logger.error(f"Error getting next report number: {e}")
    return 1

def save_report(report_data: Dict) -> int:
    """Save a report and return report number"""
    report_number = get_next_report_number()
    
    data = {
        'report_number': report_number,
        'username': report_data.get('username', 'unknown'),
        'user_id': report_data['user_id'],
        'first_name': report_data.get('first_name'),
        'year': report_data['year'],
        'message': report_data['message'],
        'has_media': report_data.get('has_media', False),
        'media_type': report_data.get('media_type'),
        'media_file_id': report_data.get('media_file_id'),
        'created_at': datetime.now().isoformat()
    }
    
    try:
        supabase.table('reports').insert(data).execute()
        
        # Update total reports count
        stats_result = supabase.table('stats').select('value').eq('key', 'total_reports').execute()
        if stats_result.data:
            new_value = stats_result.data[0]['value'] + 1
            supabase.table('stats').update({'value': new_value, 'updated_at': datetime.now().isoformat()}).eq('key', 'total_reports').execute()
        else:
            supabase.table('stats').insert({'key': 'total_reports', 'value': 1}).execute()
        
        if report_data.get('has_media'):
            media_result = supabase.table('stats').select('value').eq('key', 'total_media').execute()
            if media_result.data:
                supabase.table('stats').update({'value': media_result.data[0]['value'] + 1}).eq('key', 'total_media').execute()
            else:
                supabase.table('stats').insert({'key': 'total_media', 'value': 1}).execute()
                
    except Exception as e:
        logger.error(f"Error saving report: {e}")
    
    return report_number

def get_all_reports(limit: int = 50) -> List[Dict]:
    """Get all reports"""
    try:
        result = supabase.table('reports').select('*').order('report_number', desc=True).limit(limit).execute()
        return result.data if result.data else []
    except Exception as e:
        logger.error(f"Error getting reports: {e}")
        return []

def get_report(report_number: int) -> Optional[Dict]:
    """Get a single report"""
    try:
        result = supabase.table('reports').select('*').eq('report_number', report_number).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        logger.error(f"Error getting report: {e}")
        return None

def get_reports_by_username(username: str) -> List[Dict]:
    """Get reports by username"""
    try:
        result = supabase.table('reports').select('*').eq('username', username).order('report_number', desc=True).execute()
        return result.data if result.data else []
    except Exception as e:
        logger.error(f"Error getting user reports: {e}")
        return []

def delete_report(report_number: int) -> bool:
    """Delete a report"""
    try:
        result = supabase.table('reports').delete().eq('report_number', report_number).execute()
        deleted = len(result.data) > 0 if result.data else False
        
        if deleted:
            stats_result = supabase.table('stats').select('value').eq('key', 'total_deleted').execute()
            if stats_result.data:
                supabase.table('stats').update({'value': stats_result.data[0]['value'] + 1}).eq('key', 'total_deleted').execute()
            else:
                supabase.table('stats').insert({'key': 'total_deleted', 'value': 1}).execute()
        
        return deleted
    except Exception as e:
        logger.error(f"Error deleting report: {e}")
        return False

def delete_user_reports(username: str) -> int:
    """Delete all reports by a user"""
    try:
        result = supabase.table('reports').delete().eq('username', username).execute()
        deleted_count = len(result.data) if result.data else 0
        
        if deleted_count > 0:
            stats_result = supabase.table('stats').select('value').eq('key', 'total_deleted').execute()
            if stats_result.data:
                supabase.table('stats').update({'value': stats_result.data[0]['value'] + deleted_count}).eq('key', 'total_deleted').execute()
        
        return deleted_count
    except Exception as e:
        logger.error(f"Error deleting user reports: {e}")
        return 0

def mark_replied(report_number: int, reply_text: str):
    """Mark report as replied"""
    try:
        supabase.table('reports').update({
            'replied': True,
            'reply_text': reply_text,
            'reply_date': datetime.now().isoformat()
        }).eq('report_number', report_number).execute()
        
        stats_result = supabase.table('stats').select('value').eq('key', 'total_replies').execute()
        if stats_result.data:
            supabase.table('stats').update({'value': stats_result.data[0]['value'] + 1}).eq('key', 'total_replies').execute()
    except Exception as e:
        logger.error(f"Error marking replied: {e}")

def mark_viewed(report_number: int):
    """Mark report as viewed"""
    try:
        supabase.table('reports').update({'viewed': True}).eq('report_number', report_number).execute()
    except Exception as e:
        logger.error(f"Error marking viewed: {e}")

def get_unviewed_count() -> int:
    """Get unviewed reports count"""
    try:
        result = supabase.table('reports').select('id', count='exact').eq('viewed', False).execute()
        return result.count if result.count else 0
    except Exception as e:
        logger.error(f"Error getting unviewed count: {e}")
        return 0

def get_stats() -> Dict:
    """Get statistics"""
    stats = {
        'total_reports': 0,
        'replied': 0,
        'pending': 0,
        'total_media': 0,
        'total_deleted': 0,
        'by_year': {},
        'top_users': []
    }
    
    try:
        # Get from stats table
        result = supabase.table('stats').select('key', 'value').execute()
        if result.data:
            for row in result.data:
                stats[row['key']] = row['value']
        
        # Get replied count
        replied_result = supabase.table('reports').select('id', count='exact').eq('replied', True).execute()
        stats['replied'] = replied_result.count if replied_result.count else 0
        
        # Get pending count
        pending_result = supabase.table('reports').select('id', count='exact').eq('replied', False).execute()
        stats['pending'] = pending_result.count if pending_result.count else 0
        
        # Get total reports
        total_result = supabase.table('reports').select('id', count='exact').execute()
        stats['total_reports'] = total_result.count if total_result.count else 0
        
        # Group by year
        year_result = supabase.table('reports').select('year').execute()
        if year_result.data:
            for row in year_result.data:
                year = row['year']
                stats['by_year'][year] = stats['by_year'].get(year, 0) + 1
        
        # Top users
        user_result = supabase.table('reports').select('username').execute()
        if user_result.data:
            user_counts = {}
            for row in user_result.data:
                username = row['username']
                user_counts[username] = user_counts.get(username, 0) + 1
            top = sorted(user_counts.items(), key=lambda x: x[1], reverse=True)[:10]
            stats['top_users'] = [{'username': k, 'count': v} for k, v in top]
            
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
    
    return stats

def search_reports(keyword: str) -> List[Dict]:
    """Search reports"""
    try:
        result = supabase.table('reports').select('*').or_(
            f'message.ilike.%{keyword}%,year.ilike.%{keyword}%,username.ilike.%{keyword}%'
        ).order('report_number', desc=True).limit(50).execute()
        return result.data if result.data else []
    except Exception as e:
        logger.error(f"Error searching reports: {e}")
        return []

def init_tables():
    """Create tables if they don't exist"""
    try:
        # Check if reports table exists
        supabase.table('reports').select('id').limit(1).execute()
    except Exception:
        logger.info("Please create tables in Supabase SQL editor")
        # Tables don't exist - user needs to create them manually

# ==================== BOT HANDLERS ====================

def get_year_keyboard():
    """Create year selection keyboard"""
    keyboard = [
        [f"📚 {YEARS[0]}", f"📚 {YEARS[1]}", f"📚 {YEARS[2]}"],
        [f"📚 {YEARS[3]}", f"📚 {YEARS[4]}", f"📚 {YEARS[5]}"],
        [f"📚 {YEARS[6]}"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command handler"""
    welcome_text = """
🌸 *እንኳን ደህና መጣሽ ወደ ካምፓስ ሴቶች ደህንነት ቦት* 🌸

ይህ ቦት ሴቶች በደህና ስሜታቸውን እንዲገልጹ ተዘጋጅቷል።

✨ *ድምጽሽ አስፈላጊ ነው* ✨

📌 *አሰራር:*
1. አመትሽን ምረጪ
2. ስለደረሰብሽ ችግር ጻፊ ወይም ሚዲያ ላኪ
3. ሪፖርትሽ ደርሶናል የሚል ማረጋገጫ ታገኛለሽ
4. አስተዳዳሪ ምላሽ ይሰጣል

🔒 *ማንነትሽ ሙሉ በሙሉ ተጠብቆ ይቆያል*

/help በመጻፍ ተጨማሪ መረጃ ማግኘት ትችያለሽ
"""
    
    await update.message.reply_text(
        welcome_text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_year_keyboard()
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main message handler"""
    user_id = update.effective_user.id
    text = update.message.text
    
    # Handle admin reply mode
    if user_id == ADMIN_ID and user_id in pending_replies:
        await handle_admin_reply(update, context)
        return
    
    # Handle year selection
    clean_text = text.replace("📚 ", "") if text else ""
    
    if clean_text in YEARS:
        user_states[user_id] = {"year": clean_text, "awaiting_report": True}
        await update.message.reply_text(
            f"✅ *ዓመት {clean_text} መርጠሻል* ✅\n\n"
            "አሁን በነጻነት ስለደረሰብሽ ችግር መግለጽ ትችያለሽ።\n\n"
            "መላክ የምትችለው:\n"
            "✏️ ጽሁፍ\n"
            "📷 ፎቶ\n"
            "🎥 ቪዲዮ\n"
            "🎤 የድምጽ መልዕክት\n\n"
            "*ማንነትሽ ሙሉ በሙሉ እንደሚጠበቅ እናስታውሻለን* 🔒",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=ReplyKeyboardRemove()
        )
        return
    
    # Handle report submission
    if user_id in user_states and user_states[user_id].get("awaiting_report"):
        await save_user_report(update, context)
        return
    
    # Default response
    await update.message.reply_text(
        "እባክሽ መጀመሪያ አመትሽን ከታች ካሉት ቁልፎች ምረጪ 👇\n\n"
        "ቁልፎቹን ካላየሽ /start በመጻፍ ጀምሪ።",
        reply_markup=get_year_keyboard()
    )

async def save_user_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save user's report to database"""
    user_id = update.effective_user.id
    user = update.effective_user
    username = user.username or f"user_{user_id}"
    year = user_states[user_id]["year"]
    
    # Extract message and media
    message_text = ""
    has_media = False
    media_type = None
    media_file_id = None
    
    if update.message.text:
        message_text = update.message.text
    elif update.message.caption:
        message_text = update.message.caption
    elif update.message.photo:
        message_text = update.message.caption or "📷 ፎቶ ተልኳል"
        has_media = True
        media_type = "photo"
        media_file_id = update.message.photo[-1].file_id
    elif update.message.video:
        message_text = update.message.caption or "🎥 ቪዲዮ ተልኳል"
        has_media = True
        media_type = "video"
        media_file_id = update.message.video.file_id
    elif update.message.voice:
        message_text = "🎤 የድምጽ መልዕክት"
        has_media = True
        media_type = "voice"
        media_file_id = update.message.voice.file_id
    elif update.message.document:
        message_text = update.message.caption or f"📄 ፋይል ተልኳል"
        has_media = True
        media_type = "document"
        media_file_id = update.message.document.file_id
    else:
        await update.message.reply_text("❌ እባክሽ ጽሁፍ፣ ፎቶ፣ ቪዲዮ ወይም ድምጽ ላኪ።")
        return
    
    # Save to database
    report_data = {
        'user_id': user_id,
        'username': username,
        'first_name': user.first_name,
        'year': year,
        'message': message_text,
        'has_media': has_media,
        'media_type': media_type,
        'media_file_id': media_file_id,
    }
    
    report_number = save_report(report_data)
    
    # ========== CONFIRMATION MESSAGE ==========
    confirmation = f"""
✅ *ሪፖርት #{report_number} በስኬት ደርሶናል* ✅

*እናመሰግናለን ቆንጆ!* 💜

ድፍረትሽ እና ቆራጥነትሽ ሌሎች ሴቶችን ያበረታታል።

━━━━━━━━━━━━━━━━━━━━━
📞 *የካምፓስ ድጋፍ ስልኮች*
━━━━━━━━━━━━━━━━━━━━━

🏢 *የሴቶች ጉዳይ ጽህፈት ቤት*
   📞 `{EMERGENCY_CONTACTS['women_support']}`

🛡️ *የካምፓስ ጥበቃ (ሴኩሪቲ)*
   📞 `{EMERGENCY_CONTACTS['campus_security']}`

💬 *የምክር አገልግሎት (ካውንሰሊንግ)*
   📞 `{EMERGENCY_CONTACTS['counseling']}`

━━━━━━━━━━━━━━━━━━━━━

📌 *ቀጣይ እርምጃዎች:*
• አስተዳዳሪዎቻችን ሪፖርቱን ገምግመው ምላሽ ይሰጣሉ
• ማንነትሽ ሙሉ በሙሉ ተጠብቆ ይቆያል 🔒

*አንቺ ብቻሽ አይደለሽም! አብረን እንገኛለን* 🌸
"""
    
    await update.message.reply_text(confirmation, parse_mode=ParseMode.MARKDOWN)
    
    # Notify admin
    admin_msg = f"""
🔴 *አዲስ ሪፖርት #{report_number}* 🔴

👤 *የተጠቃሚ ስም:* @{username}
📚 *ዓመት:* {year}
💬 *መልዕክት:* {message_text[:200]}...
📎 *ሚዲያ:* {'አለ (' + media_type + ')' if has_media else 'የለም'}

💡 *ምላሽ ለመስጠት:* /reply {report_number} [መልዕክት]
🗑️ *ለመሰረዝ:* /delete {report_number}
👤 *የተጠቃሚ ታሪክ ለመሰረዝ:* /deleteuser @{username}
"""
    
    try:
        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=admin_msg,
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Forward media if any
        if has_media and media_file_id:
            if media_type == "photo":
                await context.bot.send_photo(chat_id=ADMIN_ID, photo=media_file_id)
            elif media_type == "video":
                await context.bot.send_video(chat_id=ADMIN_ID, video=media_file_id)
            elif media_type == "voice":
                await context.bot.send_voice(chat_id=ADMIN_ID, voice=media_file_id)
    except Exception as e:
        logger.error(f"Error notifying admin: {e}")
    
    # Clear user state
    del user_states[user_id]
    
    # Ask for another report
    await update.message.reply_text(
        "🌸 *ሌላ ሪፖርት ማቅረብ ትፈልጊያለሽ?* 🌸\n\n"
        "ዝቅ ያለሽ ነገር ቢኖር ነጻነትሽን ጠብቀሽ መግለጽ ትችያለሽ።\n\n"
        "*አንቺ ጠንካራ ነሽ!* 💪",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_year_keyboard()
    )
    
    # Final thank you
    await asyncio.sleep(2)
    
    final_thank_you = """
🌟 *በጣም በጣም እናመሰግናለን!* 🌟

ለመጋራት ያሳየሽው ድፍረት ለሌሎች ምሳሌ ነው።

✨ *ለውጥ የሚመጣው በአንቺ በመሰሉ ጀግኖች ነው* ✨

ቀንሽ በረከት! 🙏
"""
    
    await update.message.reply_text(final_thank_you, parse_mode=ParseMode.MARKDOWN)

async def handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle admin's reply to a report"""
    admin_id = update.effective_user.id
    report_number = pending_replies[admin_id]
    
    reply_text = update.message.text
    if not reply_text:
        await update.message.reply_text("❌ እባክህ ጽሁፍ ላክ።")
        return
    
    # Get the report
    report = get_report(report_number)
    if not report:
        await update.message.reply_text(f"❌ ሪፖርት #{report_number} አልተገኘም።")
        del pending_replies[admin_id]
        return
    
    # Send anonymous reply to user
    try:
        reply_message = f"""
📢 *ምላሽ ከአስተዳዳሪ*

ውድ ተማሪ፣

{reply_text}

💜 *ይህ ሚስጥራዊ ምላሽ ነው*
ተጨማሪ እርዳታ ከፈለጌ እንደገና ሪፖርት ማድረግ ትችያለሽ።

*ድምጽሽ ይሰማል* 🌸
"""
        await context.bot.send_message(
            chat_id=report['user_id'],
            text=reply_message,
            parse_mode=ParseMode.MARKDOWN
        )
        
        # Mark as replied in database
        mark_replied(report_number, reply_text)
        
        await update.message.reply_text(f"✅ ምላሽ ለሪፖርት #{report_number} ተልኳል!")
        
    except Exception as e:
        await update.message.reply_text(f"❌ ምላሽ መላክ አልቻለም: {str(e)}")
    
    del pending_replies[admin_id]

# ==================== ADMIN COMMANDS ====================

async def reports_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View all reports (admin only)"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ አይፈቀድም።")
        return
    
    reports = get_all_reports(limit=20)
    
    if not reports:
        await update.message.reply_text("📭 ምንም ሪፖርት የለም።")
        return
    
    # Mark as viewed
    for report in reports:
        mark_viewed(report['report_number'])
    
    text = "📊 *የቅርብ ጊዜ ሪፖርቶች*\n\n"
    for report in reports[:10]:
        text += f"🔹 *#{report['report_number']}* | 👤 @{report['username']}\n"
        text += f"   📚 {report['year']} | 💬 {report['message'][:50]}...\n"
        text += f"   ✅ ምላሽ: {'አለ' if report['replied'] else 'የለም'}\n"
        text += f"   📅 {report['created_at'][:10] if report['created_at'] else 'Unknown'}\n\n"
    
    text += f"\n📌 ጠቅላላ: {len(reports)} ሪፖርቶች"
    
    keyboard = [
        [InlineKeyboardButton(f"ለ#{r['report_number']} ምላሽ ስጥ", callback_data=f"reply_{r['report_number']}")] for r in reports[:5]
    ]
    keyboard.append([InlineKeyboardButton("📊 ስታቲስቲክስ", callback_data="stats")])
    
    await update.message.reply_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def reply_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reply to a report: /reply 1 Hello"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ አይፈቀድም።")
        return
    
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(
            "❌ አጠቃቀም: `/reply [ቁጥር] [መልዕክት]`\n"
            "ለምሳሌ: `/reply 1 እናመሰግናለን ስለጋራሽ`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    try:
        report_number = int(context.args[0])
        reply_text = ' '.join(context.args[1:])
        
        report = get_report(report_number)
        if not report:
            await update.message.reply_text(f"❌ ሪፖርት #{report_number} አልተገኘም።")
            return
        
        # Send reply
        await context.bot.send_message(
            chat_id=report['user_id'],
            text=f"📢 *ምላሽ ከአስተዳዳሪ*\n\n{reply_text}\n\n💜 ድምጽሽ ይሰማል።",
            parse_mode=ParseMode.MARKDOWN
        )
        
        mark_replied(report_number, reply_text)
        await update.message.reply_text(f"✅ ምላሽ ለሪፖርት #{report_number} ተልኳል!")
        
    except ValueError:
        await update.message.reply_text("❌ የሪፖርት ቁጥር ትክክል አይደለም።")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View statistics (admin only)"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ አይፈቀድም።")
        return
    
    stats = get_stats()
    
    text = f"""
📊 *የቦት ስታቲስቲክስ* 📊

📝 *ጠቅላላ ሪፖርቶች:* {stats.get('total_reports', 0)}
✅ *ምላሽ የተሰጣቸው:* {stats.get('replied', 0)}
⏳ *ምላሽ ያልተሰጣቸው:* {stats.get('pending', 0)}
📎 *ሚዲያ ያላቸው:* {stats.get('total_media', 0)}
🗑️ *የተሰረዙ:* {stats.get('total_deleted', 0)}

📚 *ሪፖርቶች በዓመት:*
"""
    for year, count in stats.get('by_year', {}).items():
        text += f"   • {year}: {count}\n"
    
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def delete_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete a single report: /delete 123"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ አይፈቀድም።")
        return
    
    if not context.args:
        await update.message.reply_text(
            "❌ አጠቃቀም: `/delete ሪፖርት_ቁጥር`\n"
            "ለምሳሌ: `/delete 5`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    try:
        report_number = int(context.args[0])
        if delete_report(report_number):
            await update.message.reply_text(f"✅ ሪፖርት #{report_number} ተሰርዟል!")
        else:
            await update.message.reply_text(f"❌ ሪፖርት #{report_number} አልተገኘም።")
    except ValueError:
        await update.message.reply_text("❌ የሪፖርት ቁጥር ትክክል አይደለም።")

async def deleteuser_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete all reports by a user: /deleteuser @username"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ አይፈቀድም።")
        return
    
    if not context.args:
        await update.message.reply_text(
            "❌ አጠቃቀም: `/deleteuser @username`\n"
            "ለምሳሌ: `/deleteuser @john_doe`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    username = context.args[0].replace('@', '')
    count = delete_user_reports(username)
    await update.message.reply_text(f"✅ {count} ሪፖርቶች ለ@{username} ተሰርዘዋል!")

async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Search reports: /search keyword"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ አይፈቀድም።")
        return
    
    if not context.args:
        await update.message.reply_text("አጠቃቀም: `/search ቁልፍ ቃል`", parse_mode=ParseMode.MARKDOWN)
        return
    
    keyword = ' '.join(context.args)
    results = search_reports(keyword)
    
    if not results:
        await update.message.reply_text(f"'{keyword}' የሚል ምንም ሪፖርት አልተገኘም።")
        return
    
    text = f"🔍 *'{keyword}' የሚል ፍለጋ ውጤት:*\n\n"
    for r in results[:10]:
        text += f"#{r['report_number']} | @{r['username']} | {r['year']}\n"
        text += f"   💬 {r['message'][:50]}...\n\n"
    
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help command"""
    is_admin = update.effective_user.id == ADMIN_ID
    
    if is_admin:
        help_text = """
📚 *የአስተዳዳሪ ትዕዛዞች*

/reports - ሁሉንም ሪፖርቶች ለማየት
/reply [ቁጥር] [መልዕክት] - ለሪፖርት ምላሽ ለመስጠት
/delete [ቁጥር] - አንድ ሪፖርት ለመሰረዝ
/deleteuser [@username] - የአንድ ተጠቃሚ ሁሉንም ሪፖርቶች ለመሰረዝ
/search [ቃል] - ሪፖርቶችን ለመፈለግ
/stats - ስታቲስቲክስ ለማየት
/help - ይህን እርዳታ ለማየት

💡 *ፈጣን ምላሽ:* በ /reports ውስጥ ቁልፎችን ተጠቀም
"""
    else:
        help_text = """
🌸 *የተጠቃሚ መመሪያ* 🌸

1. አመትሽን ምረጪ
2. ስለደረሰብሽ ችግር ጻፊ ወይም ሚዲያ ላኪ
3. ሪፖርትሽ ደርሶናል የሚል ማረጋገጫ ታገኛለሽ
4. አስተዳዳሪ ምላሽ ይሰጣል

🔒 *ማንነትሽ ሙሉ በሙሉ ተጠብቆ ይቆያል*
🆘 *የአስቸኳይ ጊዜ ስልኮች በሪፖርት ማጠናቀቂያ ላይ ይታያሉ*

/start በመጻፍ መጀመር ትችያለሽ
"""
    
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button presses"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    admin_id = update.effective_user.id
    
    if admin_id != ADMIN_ID:
        await query.edit_message_text("⛔ አይፈቀድም።")
        return
    
    if data.startswith("reply_"):
        report_number = int(data.split("_")[1])
        pending_replies[admin_id] = report_number
        await query.edit_message_text(
            f"📝 *ለሪፖርት #{report_number} ምላሽ በመስጠት ላይ*\n\n"
            "ምላሽህን ላክ (ጽሁፍ ብቻ):\n"
            "ለመሰረዝ /cancel በላይ",
            parse_mode=ParseMode.MARKDOWN
        )
    
    elif data == "stats":
        stats = get_stats()
        text = f"📊 ጠቅላላ ሪፖርቶች: {stats.get('total_reports', 0)}\n"
        text += f"✅ ምላሽ የተሰጣቸው: {stats.get('replied', 0)}\n"
        text += f"⏳ ምላሽ ያልተሰጣቸው: {stats.get('pending', 0)}"
        await query.edit_message_text(text)

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel pending reply"""
    user_id = update.effective_user.id
    if user_id in pending_replies:
        del pending_replies[user_id]
        await update.message.reply_text("✅ ምላሽ ተሰርዟል።")
    else:
        await update.message.reply_text("ምንም በመጠባበቅ ላይ ያለ ምላሽ የለም።")

# ==================== WEBHOOK APPLICATION ====================

def create_app():
    """Create Flask application for Vercel webhook"""
    from flask import Flask, request as flask_request, jsonify
    
    flask_app = Flask(__name__)
    
    @flask_app.route('/', methods=['POST', 'GET'])
    def webhook():
        if flask_request.method == 'GET':
            return jsonify({"status": "Bot is running", "message": "Send POST requests for Telegram webhook"})
        
        try:
            # Initialize application
            application = Application.builder().token(TOKEN).build()
            
            # Add handlers
            application.add_handler(CommandHandler("start", start))
            application.add_handler(CommandHandler("help", help_command))
            application.add_handler(CommandHandler("reports", reports_command))
            application.add_handler(CommandHandler("reply", reply_command))
            application.add_handler(CommandHandler("delete", delete_command))
            application.add_handler(CommandHandler("deleteuser", deleteuser_command))
            application.add_handler(CommandHandler("search", search_command))
            application.add_handler(CommandHandler("stats", stats_command))
            application.add_handler(CommandHandler("cancel", cancel_command))
            application.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.VIDEO | filters.VOICE | filters.Document.ALL, handle_message))
            application.add_handler(CallbackQueryHandler(button_callback))
            
            # Process update
            update = Update.de_json(flask_request.get_json(force=True), application.bot)
            application.process_update(update)
            
            return jsonify({"status": "ok"})
        except Exception as e:
            logger.error(f"Webhook error: {e}")
            return jsonify({"status": "error", "message": str(e)}), 500
    
    return flask_app

# For local testing
if __name__ == "__main__":
    app = create_app()
    app.run(port=8080)

# For Vercel
app = create_app()