# -*- coding: utf-8 -*-
"""
Campus Women Safety Bot - Complete Production Version
For reporting abuse and harassment anonymously
"""

import os
import sqlite3
import logging
import asyncio
import json
import threading
import time
import urllib.request
from datetime import datetime
from typing import Dict, List, Optional, Any

# Telegram imports
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, ContextTypes, 
    MessageHandler, filters, CallbackQueryHandler
)
from telegram.constants import ParseMode
from telegram.request import HTTPXRequest

# ==================== KEEP ALIVE SYSTEM ====================

def keep_bot_awake():
    """Keeps the bot alive by pinging it every 5 minutes"""
    token = TOKEN
    url = f"https://api.telegram.org/bot{token}/getMe"
    while True:
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status == 200:
                    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ✅ Bot is alive")
        except Exception as e:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] ❌ Keep-alive error: {e}")
        time.sleep(300)

# Optional Google Sheets support
try:
    import gspread
    from oauth2client.service_account import ServiceAccountCredentials
    GOOGLE_SHEETS_AVAILABLE = True
except ImportError:
    GOOGLE_SHEETS_AVAILABLE = False

# ==================== CONFIGURATION ====================

TOKEN = "8071197561:AAEKEyG6Aib-oFlMAH2V57Pvum_hGQ99uRw"
ADMIN_ID = 6044463378

# Bot configuration
BOT_CONFIG = {
    "connect_timeout": 35.0,
    "read_timeout": 35.0,
    "write_timeout": 35.0,
    "pool_timeout": 35.0,
    "poll_interval": 2.0,
    "max_retries": 5,
    "retry_delay": 10,
}

GOOGLE_SHEETS_ENABLED = False
GOOGLE_SHEETS_CREDENTIALS_FILE = "credentials.json"
GOOGLE_SHEETS_NAME = "Campus Women Safety Reports"
DB_FILE = "campus_safety_reports.db"

EMERGENCY_CONTACTS = {
    "campus_security": "0911-123456",
    "women_support": "0911-789012",
    "counseling": "0911-345678",
}

# ==================== LOGGING SETUP ====================

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== DATABASE CLASS ====================

class Database:
    """Database handler for all operations"""
    
    def __init__(self, db_file: str = DB_FILE):
        self.db_file = db_file
        self.init_tables()
    
    def get_connection(self):
        return sqlite3.connect(self.db_file)
    
    def init_tables(self):
        """Initialize all database tables"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        # Reports table - using username instead of user_id as primary identifier
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_number INTEGER UNIQUE,
                username TEXT,
                user_id INTEGER,
                first_name TEXT,
                year TEXT,
                message TEXT,
                has_media BOOLEAN DEFAULT 0,
                media_type TEXT,
                media_file_id TEXT,
                replied BOOLEAN DEFAULT 0,
                reply_text TEXT,
                reply_date TEXT,
                viewed BOOLEAN DEFAULT 0,
                created_at TEXT
            )
        ''')
        
        # Admins table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS admins (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE,
                username TEXT,
                role TEXT DEFAULT 'admin',
                added_at TEXT
            )
        ''')
        
        # Add main admin
        cursor.execute('''
            INSERT OR IGNORE INTO admins (user_id, username, role, added_at)
            VALUES (?, NULL, 'super_admin', ?)
        ''', (ADMIN_ID, datetime.now().isoformat()))
        
        # Statistics table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS stats (
                key TEXT PRIMARY KEY,
                value INTEGER DEFAULT 0,
                updated_at TEXT
            )
        ''')
        
        # Initialize stats
        for stat in ['total_reports', 'total_replies', 'total_media', 'total_deleted']:
            cursor.execute('''
                INSERT OR IGNORE INTO stats (key, value, updated_at)
                VALUES (?, 0, ?)
            ''', (stat, datetime.now().isoformat()))
        
        conn.commit()
        conn.close()
        logger.info("✅ Database initialized")
    
    def save_report(self, report_data: Dict) -> int:
        """Save a report and return report number"""
        conn = self.get_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT COALESCE(MAX(report_number), 0) + 1 FROM reports")
        report_number = cursor.fetchone()[0]
        
        cursor.execute('''
            INSERT INTO reports (
                report_number, username, user_id, first_name, year, message,
                has_media, media_type, media_file_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            report_number, 
            report_data.get('username', 'unknown'),
            report_data['user_id'], 
            report_data.get('first_name'),
            report_data['year'], 
            report_data['message'],
            report_data.get('has_media', 0), 
            report_data.get('media_type'),
            report_data.get('media_file_id'), 
            datetime.now().isoformat()
        ))
        
        cursor.execute('''
            UPDATE stats SET value = value + 1, updated_at = ?
            WHERE key = 'total_reports'
        ''', (datetime.now().isoformat(),))
        
        if report_data.get('has_media'):
            cursor.execute('''
                UPDATE stats SET value = value + 1, updated_at = ?
                WHERE key = 'total_media'
            ''', (datetime.now().isoformat(),))
        
        conn.commit()
        conn.close()
        return report_number
    
    def get_all_reports(self, limit: int = None) -> List[Dict]:
        """Get all reports, optionally with limit"""
        conn = self.get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        query = "SELECT * FROM reports ORDER BY report_number DESC"
        if limit:
            query += f" LIMIT {limit}"
        
        cursor.execute(query)
        results = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return results
    
    def get_report(self, report_number: int) -> Optional[Dict]:
        """Get a single report by number"""
        conn = self.get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM reports WHERE report_number = ?", (report_number,))
        result = cursor.fetchone()
        conn.close()
        return dict(result) if result else None
    
    def get_reports_by_username(self, username: str) -> List[Dict]:
        """Get all reports by a specific username"""
        conn = self.get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM reports WHERE username = ? ORDER BY report_number DESC", (username,))
        results = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return results
    
    def delete_report(self, report_number: int) -> bool:
        """Delete a single report by number"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM reports WHERE report_number = ?", (report_number,))
        deleted = cursor.rowcount > 0
        
        if deleted:
            cursor.execute('''
                UPDATE stats SET value = value + 1, updated_at = ?
                WHERE key = 'total_deleted'
            ''', (datetime.now().isoformat(),))
        
        conn.commit()
        conn.close()
        return deleted
    
    def delete_user_reports(self, username: str) -> int:
        """Delete all reports by a specific username"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM reports WHERE username = ?", (username,))
        deleted_count = cursor.rowcount
        
        if deleted_count > 0:
            # Update stats for each deleted report
            for _ in range(deleted_count):
                cursor.execute('''
                    UPDATE stats SET value = value + 1, updated_at = ?
                    WHERE key = 'total_deleted'
                ''', (datetime.now().isoformat(),))
        
        conn.commit()
        conn.close()
        return deleted_count
    
    def mark_replied(self, report_number: int, reply_text: str):
        """Mark report as replied"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE reports SET replied = 1, reply_text = ?, reply_date = ?
            WHERE report_number = ?
        ''', (reply_text, datetime.now().isoformat(), report_number))
        
        cursor.execute('''
            UPDATE stats SET value = value + 1, updated_at = ?
            WHERE key = 'total_replies'
        ''', (datetime.now().isoformat(),))
        
        conn.commit()
        conn.close()
    
    def mark_viewed(self, report_number: int):
        """Mark report as viewed by admin"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE reports SET viewed = 1 WHERE report_number = ?", (report_number,))
        conn.commit()
        conn.close()
    
    def get_unviewed_count(self) -> int:
        """Get count of unviewed reports"""
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM reports WHERE viewed = 0")
        count = cursor.fetchone()[0]
        conn.close()
        return count
    
    def get_stats(self) -> Dict:
        """Get all statistics"""
        conn = self.get_connection()
        cursor = cursor = conn.cursor()
        cursor.execute("SELECT key, value FROM stats")
        stats = dict(cursor.fetchall())
        
        cursor.execute("SELECT COUNT(*) FROM reports WHERE replied = 1")
        stats['replied'] = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM reports WHERE replied = 0")
        stats['pending'] = cursor.fetchone()[0]
        
        cursor.execute("SELECT year, COUNT(*) FROM reports GROUP BY year")
        stats['by_year'] = dict(cursor.fetchall())
        
        cursor.execute("SELECT username, COUNT(*) FROM reports GROUP BY username ORDER BY COUNT(*) DESC LIMIT 10")
        stats['top_users'] = [dict(row) for row in cursor.fetchall()]
        
        conn.close()
        return stats
    
    def search_reports(self, keyword: str) -> List[Dict]:
        """Search reports by keyword"""
        conn = self.get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM reports 
            WHERE message LIKE ? OR year LIKE ? OR username LIKE ?
            ORDER BY report_number DESC
        ''', (f'%{keyword}%', f'%{keyword}%', f'%{keyword}%'))
        results = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return results
    
    def export_to_csv(self, filename: str = None):
        """Export all reports to CSV"""
        import csv
        if not filename:
            filename = f"reports_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        reports = self.get_all_reports()
        if not reports:
            return None
        
        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = ['report_number', 'username', 'user_id', 'first_name', 'year', 
                         'message', 'has_media', 'media_type', 'replied', 
                         'reply_text', 'created_at']
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            for report in reports:
                writer.writerow({k: report.get(k, '') for k in fieldnames})
        
        return filename

# Initialize database
db = Database()

# ==================== BOT HANDLERS ====================

user_states = {}
pending_replies = {}

YEARS = ["remdial", "1st year", "2nd year", "3rd year", "4th year", "5th year", "6th year"]

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

def get_year_keyboard():
    """Create year selection keyboard"""
    keyboard = [
        [f"📚 {YEARS[0]}", f"📚 {YEARS[1]}", f"📚 {YEARS[2]}"],
        [f"📚 {YEARS[3]}", f"📚 {YEARS[4]}", f"📚 {YEARS[5]}"],
        [f"📚 {YEARS[6]}"]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main message handler"""
    user_id = update.effective_user.id
    text = update.message.text
    user = update.effective_user
    
    if user_id == ADMIN_ID and user_id in pending_replies:
        await handle_admin_reply(update, context)
        return
    
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
    
    if user_id in user_states and user_states[user_id].get("awaiting_report"):
        await save_user_report(update, context)
        return
    
    await update.message.reply_text(
        "እባክሽ መጀመሪያ አመትሽን ከታች ካሉት ቁልፎች ምረጪ 👇\n\n"
        "ቁልፎቹን ካላየሽ /start በመጻፍ ጀምሪ።",
        reply_markup=get_year_keyboard()
    )

async def save_user_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save user's report to database"""
    user_id = update.effective_user.id
    user = update.effective_user
    username = user.username or f"user_{user_id}"  # Use username if available
    year = user_states[user_id]["year"]
    
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
    
    report_data = {
        'user_id': user_id,
        'username': username,
        'first_name': user.first_name,
        'year': year,
        'message': message_text,
        'has_media': 1 if has_media else 0,
        'media_type': media_type,
        'media_file_id': media_file_id,
    }
    
    report_number = db.save_report(report_data)
    
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
    await notify_admin(context, report_number, year, message_text, username, has_media, media_type, media_file_id)
    
    del user_states[user_id]
    
    await update.message.reply_text(
        "🌸 *ሌላ ሪፖርት ማቅረብ ትፈልጊያለሽ?* 🌸\n\n"
        "ዝቅ ያለሽ ነገር ቢኖር ነጻነትሽን ጠብቀሽ መግለጽ ትችያለሽ።\n\n"
        "*አንቺ ጠንካራ ነሽ!* 💪",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=get_year_keyboard()
    )
    
    await asyncio.sleep(2)
    
    final_thank_you = """
🌟 *በጣም በጣም እናመሰግናለን!* 🌟

ለመጋራት ያሳየሽው ድፍረት ለሌሎች ምሳሌ ነው።

✨ *ለውጥ የሚመጣው በአንቺ በመሰሉ ጀግኖች ነው* ✨

ቀንሽ በረከት! 🙏
"""
    
    await update.message.reply_text(final_thank_you, parse_mode=ParseMode.MARKDOWN)

async def notify_admin(context: ContextTypes.DEFAULT_TYPE, report_number: int, year: str, 
                       message: str, username: str, has_media: bool, media_type: str, media_file_id: str):
    """Notify admin about new report"""
    admin_msg = f"""
🔴 *አዲስ ሪፖርት #{report_number}* 🔴

👤 *የተጠቃሚ ስም:* @{username}
📚 *ዓመት:* {year}
💬 *መልዕክት:* {message[:200]}...
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
        
        if has_media and media_file_id:
            if media_type == "photo":
                await context.bot.send_photo(chat_id=ADMIN_ID, photo=media_file_id)
            elif media_type == "video":
                await context.bot.send_video(chat_id=ADMIN_ID, video=media_file_id)
            elif media_type == "voice":
                await context.bot.send_voice(chat_id=ADMIN_ID, voice=media_file_id)
    except Exception as e:
        logger.error(f"Error notifying admin: {e}")

async def handle_admin_reply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle admin's reply to a report"""
    admin_id = update.effective_user.id
    report_number = pending_replies[admin_id]
    
    reply_text = update.message.text
    if not reply_text:
        await update.message.reply_text("❌ እባክህ ጽሁፍ ላክ።")
        return
    
    report = db.get_report(report_number)
    if not report:
        await update.message.reply_text(f"❌ ሪፖርት #{report_number} አልተገኘም።")
        del pending_replies[admin_id]
        return
    
    try:
        await context.bot.send_message(
            chat_id=report['user_id'],
            text=f"📢 *ምላሽ ከአስተዳዳሪ*\n\n{reply_text}\n\n💜 ድምጽሽ ይሰማል።",
            parse_mode=ParseMode.MARKDOWN
        )
        
        db.mark_replied(report_number, reply_text)
        await update.message.reply_text(f"✅ ምላሽ ለሪፖርት #{report_number} ተልኳል!")
        
    except Exception as e:
        await update.message.reply_text(f"❌ ምላሽ መላክ አልቻለም: {str(e)}")
    
    del pending_replies[admin_id]

# ==================== NEW DELETE COMMANDS ====================

async def delete_report_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        report = db.get_report(report_number)
        
        if not report:
            await update.message.reply_text(f"❌ ሪፖርት #{report_number} አልተገኘም።")
            return
        
        # Confirm before deletion
        confirm_keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ አዎ ሰርዝ", callback_data=f"confirm_del_{report_number}"),
                InlineKeyboardButton("❌ አይ ተወው", callback_data="cancel_del")
            ]
        ])
        
        await update.message.reply_text(
            f"⚠️ *ማስጠንቀቂያ:* ሪፖርት #{report_number} ን መሰረዝ ትፈልጋለህ?\n\n"
            f"👤 ተጠቃሚ: @{report['username']}\n"
            f"📝 መልዕክት: {report['message'][:100]}...\n\n"
            f"ይህ እርምጃ ሊቀለበስ አይችልም!",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=confirm_keyboard
        )
        
    except ValueError:
        await update.message.reply_text("❌ የሪፖርት ቁጥር ትክክል አይደለም።")

async def delete_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete all reports by a user: /deleteuser @username"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ አይፈቀድም።")
        return
    
    if not context.args:
        await update.message.reply_text(
            "❌ አጠቃቀም: `/deleteuser @username`\n"
            "ለምሳሌ: `/deleteuser @john_doe`\n\n"
            "ይህ በዚህ ተጠቃሚ የቀረቡትን ሁሉንም ሪፖርቶች ይሰርዛል!",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    username = context.args[0].replace('@', '')  # Remove @ if present
    user_reports = db.get_reports_by_username(username)
    
    if not user_reports:
        await update.message.reply_text(f"❌ @{username} ምንም ሪፖርት አላቀረበም።")
        return
    
    report_count = len(user_reports)
    
    # Show recent reports by this user
    reports_text = ""
    for r in user_reports[:5]:
        reports_text += f"   #{r['report_number']}: {r['message'][:50]}...\n"
    
    if report_count > 5:
        reports_text += f"   ... እና {report_count - 5} ተጨማሪ ሪፖርቶች\n"
    
    confirm_keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ አዎ ሁሉንም ሰርዝ", callback_data=f"confirm_deluser_{username}"),
            InlineKeyboardButton("❌ አይ ተወው", callback_data="cancel_del")
        ]
    ])
    
    await update.message.reply_text(
        f"⚠️ *ማስጠንቀቂያ:* የ@{username} ሁሉንም ሪፖርቶች መሰረዝ ትፈልጋለህ?\n\n"
        f"📊 *ጠቅላላ ሪፖርቶች:* {report_count}\n\n"
        f"📝 *የቅርብ ጊዜ ሪፖርቶች:*\n{reports_text}\n\n"
        f"ይህ እርምጃ ሊቀለበስ አይችልም!",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=confirm_keyboard
    )

async def confirm_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle delete confirmation"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data.startswith("confirm_del_"):
        report_number = int(data.split("_")[2])
        if db.delete_report(report_number):
            await query.edit_message_text(f"✅ ሪፖርት #{report_number} በስኬት ተሰርዟል!")
        else:
            await query.edit_message_text(f"❌ ሪፖርት #{report_number} መሰረዝ አልተቻለም።")
    
    elif data.startswith("confirm_deluser_"):
        username = data.split("_")[2]
        deleted_count = db.delete_user_reports(username)
        if deleted_count > 0:
            await query.edit_message_text(
                f"✅ የ@{username} {deleted_count} ሪፖርቶች በስኬት ተሰርዘዋል!"
            )
        else:
            await query.edit_message_text(f"❌ የ@{username} ሪፖርቶች መሰረዝ አልተቻለም።")
    
    elif data == "cancel_del":
        await query.edit_message_text("✅ ስረዛ ተሰርዟል።")

# ==================== ADMIN COMMANDS ====================

async def reports_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View all reports (admin only)"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ አይፈቀድም።")
        return
    
    reports = db.get_all_reports(limit=20)
    
    if not reports:
        await update.message.reply_text("📭 ምንም ሪፖርት የለም።")
        return
    
    for report in reports:
        db.mark_viewed(report['report_number'])
    
    text = "📊 *የቅርብ ጊዜ ሪፖርቶች*\n\n"
    for report in reports[:10]:
        text += f"🔹 *#{report['report_number']}* | 👤 @{report['username']}\n"
        text += f"   📚 {report['year']} | 💬 {report['message'][:50]}...\n"
        text += f"   ✅ ምላሽ: {'አለ' if report['replied'] else 'የለም'}\n"
        text += f"   📅 {report['created_at'][:10]}\n\n"
    
    text += f"\n📌 ጠቅላላ: {len(reports)} ሪፖርቶች"
    
    keyboard = [
        [InlineKeyboardButton(f"ለ#{r['report_number']} ምላሽ ስጥ", callback_data=f"reply_{r['report_number']}")] for r in reports[:5]
    ]
    keyboard.append([InlineKeyboardButton("🗑️ ሰርዝ", callback_data="show_delete_options")])
    keyboard.append([InlineKeyboardButton("📊 ስታቲስቲክስ", callback_data="stats")])
    keyboard.append([InlineKeyboardButton("📥 ሁሉንም አውርድ", callback_data="export")])
    
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
            "ለምሳሌ: `/reply 1 እናመሰግናለን`",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    try:
        report_number = int(context.args[0])
        reply_text = ' '.join(context.args[1:])
        
        report = db.get_report(report_number)
        if not report:
            await update.message.reply_text(f"❌ ሪፖርት #{report_number} አልተገኘም።")
            return
        
        await context.bot.send_message(
            chat_id=report['user_id'],
            text=f"📢 *ምላሽ ከአስተዳዳሪ*\n\n{reply_text}\n\n💜 ድምጽሽ ይሰማል።",
            parse_mode=ParseMode.MARKDOWN
        )
        
        db.mark_replied(report_number, reply_text)
        await update.message.reply_text(f"✅ ምላሽ ለሪፖርት #{report_number} ተልኳል!")
        
    except ValueError:
        await update.message.reply_text("❌ የሪፖርት ቁጥር ትክክል አይደለም።")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View statistics (admin only)"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ አይፈቀድም።")
        return
    
    stats = db.get_stats()
    
    text = f"""
📊 *የቦት ስታቲስቲክስ* 📊

📝 *ጠቅላላ ሪፖርቶች:* {stats.get('total_reports', 0)}
✅ *ምላሽ የተሰጣቸው:* {stats.get('replied', 0)}
⏳ *ምላሽ ያልተሰጣቸው:* {stats.get('pending', 0)}
📎 *ሚዲያ ያላቸው:* {stats.get('total_media', 0)}
🗑️ *የተሰረዙ:* {stats.get('total_deleted', 0)}
👁️ *ያልታዩ:* {db.get_unviewed_count()}

📚 *ሪፖርቶች በዓመት:*
"""
    for year, count in stats.get('by_year', {}).items():
        text += f"   • {year}: {count}\n"
    
    if stats.get('top_users'):
        text += f"\n👥 *ከፍተኛ ሪፖርት አድራጊዎች:*\n"
        for user in stats['top_users'][:5]:
            text += f"   • @{user['username']}: {user['COUNT(*)']} ሪፖርቶች\n"
    
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def export_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Export reports to CSV (admin only)"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ አይፈቀድም።")
        return
    
    await update.message.reply_text("📥 ሪፖርቶችን በማውረድ ላይ...")
    
    filename = db.export_to_csv()
    if filename:
        with open(filename, 'rb') as f:
            await update.message.reply_document(
                document=f,
                filename=filename,
                caption="📊 የሪፖርቶች ውጤት"
            )
        os.remove(filename)
    else:
        await update.message.reply_text("ምንም ሪፖርት የለም።")

async def search_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Search reports: /search keyword"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ አይፈቀድም።")
        return
    
    if not context.args:
        await update.message.reply_text("አጠቃቀም: `/search ቁልፍ ቃል`", parse_mode=ParseMode.MARKDOWN)
        return
    
    keyword = ' '.join(context.args)
    results = db.search_reports(keyword)
    
    if not results:
        await update.message.reply_text(f"'{keyword}' የሚል ምንም ሪፖርት አልተገኘም።")
        return
    
    text = f"🔍 *'{keyword}' የሚል ፍለጋ ውጤት:*\n\n"
    for r in results[:10]:
        text += f"#{r['report_number']} | @{r['username']} | {r['year']}\n"
        text += f"   💬 {r['message'][:50]}...\n\n"
    
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

async def view_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """View single report: /view 1"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ አይፈቀድም።")
        return
    
    if not context.args:
        await update.message.reply_text("አጠቃቀም: `/view ሪፖርት_ቁጥር`", parse_mode=ParseMode.MARKDOWN)
        return
    
    try:
        report_number = int(context.args[0])
        report = db.get_report(report_number)
        
        if not report:
            await update.message.reply_text(f"ሪፖርት #{report_number} አልተገኘም።")
            return
        
        text = f"""
📋 *ሪፖርት #{report['report_number']}*

👤 *ተጠቃሚ:* @{report['username']}
📚 *ዓመት:* {report['year']}
💬 *መልዕክት:* {report['message']}
📎 *ሚዲያ:* {'አለ' if report['has_media'] else 'የለም'}
✅ *ምላሽ:* {'አለ' if report['replied'] else 'የለም'}
📅 *ቀን:* {report['created_at'][:19]}

{'📝 *ምላሽ:* ' + report['reply_text'] if report['reply_text'] else ''}
"""
        await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)
        
    except ValueError:
        await update.message.reply_text("የሪፖርት ቁጥር ትክክል አይደለም።")

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Broadcast message to all users (admin only)"""
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ አይፈቀድም።")
        return
    
    if not context.args:
        await update.message.reply_text(
            "አጠቃቀም: `/broadcast መልዕክት`\n"
            "ይህ መልዕክት ሪፖርት ላደረጉ ሁሉ ይላካል።",
            parse_mode=ParseMode.MARKDOWN
        )
        return
    
    message = ' '.join(context.args)
    reports = db.get_all_reports()
    unique_users = set((r['user_id'], r['username']) for r in reports)
    
    if not unique_users:
        await update.message.reply_text("ምንም ተጠቃሚ የለም።")
        return
    
    sent = 0
    failed = 0
    
    await update.message.reply_text(f"📢 ለ {len(unique_users)} ተጠቃሚዎች በማሰራጨት ላይ...")
    
    for user_id, username in unique_users:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"📢 *አስታወቂያ*\n\n{message}\n\n_ይህ አስፈላጊ መረጃ ነው።_",
                parse_mode=ParseMode.MARKDOWN
            )
            sent += 1
            await asyncio.sleep(0.1)
        except:
            failed += 1
    
    await update.message.reply_text(f"✅ ማሰራጨት ተጠናቋል!\nየደረሰባቸው: {sent}\nያልደረሰባቸው: {failed}")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help command"""
    is_admin = update.effective_user.id == ADMIN_ID
    
    if is_admin:
        help_text = """
📚 *የአስተዳዳሪ ትዕዛዞች*

📋 *የሪፖርት አያያዝ:*
/reports - ሁሉንም ሪፖርቶች ለማየት
/reply [ቁጥር] [መልዕክት] - ለሪፖርት ምላሽ ለመስጠት
/view [ቁጥር] - ሙሉ ሪፖርት ለማየት
/search [ቃል] - ሪፖርቶችን ለመፈለግ

🗑️ *ማስወገጃ ትዕዛዞች:*
/delete [ቁጥር] - አንድ ሪፖርት ለመሰረዝ
/deleteuser [@username] - የአንድ ተጠቃሚ ሁሉንም ሪፖርቶች ለመሰረዝ

📊 *ስታቲስቲክስ:*
/stats - ስታቲስቲክስ ለማየት
/export - ወደ CSV ለማውረድ
/broadcast [መልዕክት] - ለሁሉም ተጠቃሚዎች መልዕክት ለመላክ

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
        stats = db.get_stats()
        text = f"📊 ጠቅላላ ሪፖርቶች: {stats.get('total_reports', 0)}\n"
        text += f"✅ ምላሽ የተሰጣቸው: {stats.get('replied', 0)}\n"
        text += f"⏳ ምላሽ ያልተሰጣቸው: {stats.get('pending', 0)}\n"
        text += f"🗑️ የተሰረዙ: {stats.get('total_deleted', 0)}"
        await query.edit_message_text(text)
    
    elif data == "export":
        filename = db.export_to_csv()
        if filename:
            with open(filename, 'rb') as f:
                await context.bot.send_document(
                    chat_id=admin_id,
                    document=f,
                    filename=filename
                )
            os.remove(filename)
    
    elif data == "show_delete_options":
        keyboard = [
            [InlineKeyboardButton("🗑️ አንድ ሪፖርት ሰርዝ", callback_data="delete_one")],
            [InlineKeyboardButton("👤 የተጠቃሚ ታሪክ ሰርዝ", callback_data="delete_user")],
            [InlineKeyboardButton("◀️ ተመለስ", callback_data="back_to_reports")]
        ]
        await query.edit_message_text(
            "🗑️ *ማስወገጃ አማራጮች*\n\n"
            "የምትፈልገውን አማራጭ ምረጥ:",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif data == "delete_one":
        await query.edit_message_text(
            "📝 የምትሰርዘውን ሪፖርት ቁጥር ጻፍ:\n\n"
            "ትዕዛዝ ተጠቀም: `/delete ቁጥር`",
            parse_mode=ParseMode.MARKDOWN
        )
    
    elif data == "delete_user":
        await query.edit_message_text(
            "👤 የምትሰርዘውን ተጠቃሚ ስም ጻፍ:\n\n"
            "ትዕዛዝ ተጠቀም: `/deleteuser @username`",
            parse_mode=ParseMode.MARKDOWN
        )
    
    elif data == "back_to_reports":
        reports = db.get_all_reports(limit=20)
        text = "📊 *የቅርብ ጊዜ ሪፖርቶች*\n\n"
        for report in reports[:10]:
            text += f"🔹 *#{report['report_number']}* | 👤 @{report['username']}\n"
            text += f"   💬 {report['message'][:50]}...\n"
        
        keyboard = [
            [InlineKeyboardButton(f"ለ#{r['report_number']} ምላሽ ስጥ", callback_data=f"reply_{r['report_number']}")] for r in reports[:5]
        ]
        keyboard.append([InlineKeyboardButton("🗑️ ሰርዝ", callback_data="show_delete_options")])
        keyboard.append([InlineKeyboardButton("📊 ስታቲስቲክስ", callback_data="stats")])
        keyboard.append([InlineKeyboardButton("📥 ሁሉንም አውርድ", callback_data="export")])
        
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel pending reply"""
    user_id = update.effective_user.id
    if user_id in pending_replies:
        del pending_replies[user_id]
        await update.message.reply_text("✅ ምላሽ ተሰርዟል።")
    else:
        await update.message.reply_text("ምንም በመጠባበቅ ላይ ያለ ምላሽ የለም።")

# ==================== MAIN FUNCTION ====================

def main():
    """Main function to run the bot"""
    
    print("🤖 የካምፓስ ሴቶች ደህንነት ቦት እየጀመረ ነው...")
    
    keep_alive_thread = threading.Thread(target=keep_bot_awake, daemon=True)
    keep_alive_thread.start()
    print("🔄 ኪፕ-አላይቭ ሲስተም ተጀምሯል")
    
    application = Application.builder().token(TOKEN).build()
    
    # Command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("reports", reports_command))
    application.add_handler(CommandHandler("reply", reply_command))
    application.add_handler(CommandHandler("view", view_command))
    application.add_handler(CommandHandler("search", search_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("export", export_command))
    application.add_handler(CommandHandler("broadcast", broadcast_command))
    application.add_handler(CommandHandler("cancel", cancel_command))
    
    # NEW DELETE COMMANDS
    application.add_handler(CommandHandler("delete", delete_report_command))
    application.add_handler(CommandHandler("deleteuser", delete_user_command))
    
    # Message handlers
    application.add_handler(MessageHandler(
        filters.TEXT | filters.PHOTO | filters.VIDEO | filters.VOICE | filters.Document.ALL,
        handle_message
    ))
    
    # Callback handler
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(CallbackQueryHandler(confirm_delete, pattern="^(confirm_del_|confirm_deluser_|cancel_del)"))
    
    print(f"✅ ቦት እየሰራ ነው!")
    print(f"📊 የውሂብ ጎታ: {DB_FILE}")
    print(f"👤 የአስተዳዳሪ መታወቂያ: {ADMIN_ID}")
    print(f"📅 የተጀመረው በ: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)
    print("ቦትን ለማቆም Ctrl+C ን ተጫን\n")
    
    try:
        application.run_polling(
            poll_interval=1.0,
            drop_pending_updates=True,
        )
    except KeyboardInterrupt:
        print("\n👋 ቦት ቆሟል")
    except Exception as e:
        print(f"\n❌ ቦት ተሰበረ: {e}")
        print("ከ10 ሰከንድ በኋላ እንደገና እየጀመረ...")
        time.sleep(10)
        main()

if __name__ == "__main__":
    print("""
    ╔════════════════════════════════════════╗
    ║   የካምፓስ ሴቶች ደህንነት ቦት v3.0     ║
    ║   ስም-አልባ ሪፖርት አሰራር               ║
    ╚════════════════════════════════════════╝
    """)
    
    main()