import csv
import io
import logging
import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode

import database as db

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

ITEMS_PER_PAGE = 10


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _category_emoji(category: str | None) -> str:
    return db.CATEGORY_EMOJI.get(category, "") if category else ""


def build_teams_keyboard(
    teams: list[dict], page: int, prefix: str, back_callback: str = "back_to_teams"
) -> InlineKeyboardMarkup:
    """
    teams: list of dicts with 'name' and optional 'category'.
    Button label shows category emoji prefix; callback data uses team name only.
    """
    start = page * ITEMS_PER_PAGE
    end = start + ITEMS_PER_PAGE
    page_teams = teams[start:end]
    total_pages = max(1, (len(teams) + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE)

    def make_btn(t: dict) -> InlineKeyboardButton:
        emoji = _category_emoji(t.get("category"))
        label = f"{emoji} {t['name']}".strip() if emoji else t["name"]
        return InlineKeyboardButton(label, callback_data=f"{prefix}:{t['name']}")

    buttons = []
    for i in range(0, len(page_teams), 2):
        row = [make_btn(page_teams[i])]
        if i + 1 < len(page_teams):
            row.append(make_btn(page_teams[i + 1]))
        buttons.append(row)

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"{prefix}_page:{page - 1}"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton("Next ➡️", callback_data=f"{prefix}_page:{page + 1}"))
    if nav_row:
        buttons.append(nav_row)

    buttons.append([InlineKeyboardButton("❌ Close", callback_data="close")])
    return InlineKeyboardMarkup(buttons)


def format_counters_text(canonical: str, counters: list[dict], category: str | None = None) -> str:
    cat_line = ""
    if category:
        emoji = _category_emoji(category)
        cat_line = f"\n📂 Category: {emoji} {category}"
    if not counters:
        return f"🔍 No counters found for <b>{canonical}</b>.{cat_line}"
    lines = []
    for c in counters:
        line = f"  • <b>{c['name']}</b>"
        if c.get("punchup"):
            line += f" 👊 <i>{c['punchup']}</i>"
        if c.get("note"):
            line += f" — <i>{c['note']}</i>"
        lines.append(line)
    return f"⚔️ Counters for <b>{canonical}</b>:{cat_line}\n\n" + "\n".join(lines)


def _parse_quoted_args(raw_args: list[str]) -> list[str]:
    """Parse command arguments, respecting quoted strings for multi-word names."""
    joined = " ".join(raw_args)
    result = []
    current = []
    in_quote = False
    quote_char = None

    for char in joined:
        if in_quote:
            if char == quote_char:
                in_quote = False
                if current:
                    result.append("".join(current))
                    current = []
            else:
                current.append(char)
        else:
            if char in ('"', "'"):
                in_quote = True
                quote_char = char
            elif char == " ":
                if current:
                    result.append("".join(current))
                    current = []
            else:
                current.append(char)

    if current:
        result.append("".join(current))

    return result


# ---------------------------------------------------------------------------
# Commands — public
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    admin = db.is_admin(user.id)
    cats = ", ".join(db.VALID_CATEGORIES)
    text = (
        f"👋 Welcome, <b>{user.first_name}</b>!\n\n"
        "⚔️ <b>Marvel Strike Force — Counter Database</b>\n\n"
        "<b>Commands:</b>\n"
        "/counter <code>TEAM</code> — Who counters this team?\n"
        "/where <code>TEAM</code> — What teams does this team counter?\n"
        "/teams — List all teams alphabetically\n"
        "/listteams — Browse teams with inline buttons\n"
        f"/category <code>CATEGORY</code> — Teams by category ({cats})\n"
        "/stats — Database statistics\n"
        "/myid — Show your Telegram user ID\n"
    )
    if admin:
        text += (
            "\n<b>Admin commands:</b>\n"
            "/addteam <code>TEAM</code> — Create a team\n"
            "/delteam <code>TEAM</code> — Delete a team + all its counters\n"
            "/addcounter <code>TEAM COUNTER [note]</code> — Add a counter\n"
            "/delcounter <code>TEAM COUNTER</code> — Remove a counter\n"
            "/setcategory <code>TEAM CATEGORY</code> — Assign a category\n"
            "/importcsv — Import counters from a CSV file\n"
            "/resetdatabase — ⚠️ Delete all teams and counters\n"
            "/addadmin <code>USER_ID</code> — Grant admin rights\n"
            "/removeadmin <code>USER_ID</code> — Revoke admin rights\n"
            "/backup — Download the database file\n"
        )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def myid_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"🪪 Your Telegram user ID is: <code>{user.id}</code>\n\n"
        "Admins can grant you admin rights with /addadmin.",
        parse_mode=ParseMode.HTML,
    )


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    s = db.get_stats()
    cat_lines = ""
    if s["by_category"]:
        lines = []
        for cat in db.VALID_CATEGORIES:
            if cat in s["by_category"]:
                emoji = _category_emoji(cat)
                lines.append(f"  {emoji} {cat}: {s['by_category'][cat]}")
        cat_lines = "\n<b>Teams per category:</b>\n" + "\n".join(lines)

    text = (
        "📊 <b>Database Stats</b>\n\n"
        f"👥 Teams: <b>{s['teams']}</b>\n"
        f"⚔️ Counter entries: <b>{s['counters']}</b>\n"
        f"🔑 Admins: <b>{s['admins']}</b>"
        + ("\n" + cat_lines if cat_lines else "")
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def teams_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    teams = db.list_all_teams_full()
    if not teams:
        await update.message.reply_text("No teams in the database yet.")
        return

    lines = []
    for t in teams:
        emoji = _category_emoji(t["category"])
        cat_str = f" [{emoji} {t['category']}]" if t["category"] else ""
        lines.append(f"• <b>{t['name']}</b>{cat_str}")

    total = len(teams)
    text = f"📋 <b>All Teams</b> ({total} total)\n\n" + "\n".join(lines)

    # Telegram message limit is 4096 chars; split if needed
    if len(text) <= 4096:
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)
    else:
        chunks = []
        chunk_lines = []
        chunk_len = 0
        header = f"📋 <b>All Teams</b> ({total} total)\n\n"
        for line in lines:
            if chunk_len + len(line) + 1 > 3900:
                chunks.append(header + "\n".join(chunk_lines))
                chunk_lines = []
                chunk_len = 0
                header = ""
            chunk_lines.append(line)
            chunk_len += len(line) + 1
        if chunk_lines:
            chunks.append(header + "\n".join(chunk_lines))
        for chunk in chunks:
            await update.message.reply_text(chunk, parse_mode=ParseMode.HTML)


async def category_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        cats = "\n".join(
            f"  {_category_emoji(c)} /category {c}" for c in db.VALID_CATEGORIES
        )
        await update.message.reply_text(
            f"Usage: /category <code>CATEGORY</code>\n\nAvailable categories:\n{cats}",
            parse_mode=ParseMode.HTML,
        )
        return

    raw = " ".join(context.args)
    # Case-insensitive match
    category = next((c for c in db.VALID_CATEGORIES if c.lower() == raw.lower()), None)
    if not category:
        cats = ", ".join(db.VALID_CATEGORIES)
        await update.message.reply_text(
            f"❌ Unknown category <b>{raw}</b>.\nValid categories: {cats}",
            parse_mode=ParseMode.HTML,
        )
        return

    teams = db.list_teams_by_category(category)
    emoji = _category_emoji(category)
    if not teams:
        await update.message.reply_text(
            f"{emoji} No teams assigned to <b>{category}</b> yet.",
            parse_mode=ParseMode.HTML,
        )
        return

    keyboard = build_teams_keyboard(teams, 0, "team")
    total = len(teams)
    text = f"{emoji} <b>{category}</b> — {total} team(s)\nSelect a team to see its counters:"
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


async def counter_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Usage: /counter <code>TEAM_NAME</code>\nExample: /counter Hydra",
            parse_mode=ParseMode.HTML,
        )
        return

    team_name = " ".join(context.args)

    # Exact match first
    canonical = db.get_team_canonical_name(team_name)
    if canonical:
        row = db.get_team_row(canonical)
        counters = db.get_counters_for_team(canonical)
        text = format_counters_text(canonical, counters, row["category"] if row else None)
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Close", callback_data="close")]])
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
        return

    # Partial search fallback
    matches = db.search_teams(team_name)
    if not matches:
        await update.message.reply_text(
            f"❌ No team matching <b>{team_name}</b> found.",
            parse_mode=ParseMode.HTML,
        )
        return

    if len(matches) == 1:
        canonical = matches[0]
        row = db.get_team_row(canonical)
        counters = db.get_counters_for_team(canonical)
        text = format_counters_text(canonical, counters, row["category"] if row else None)
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Close", callback_data="close")]])
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
        return

    # Multiple matches — let user pick
    match_dicts = [{"name": m, "category": None} for m in matches]
    keyboard = build_teams_keyboard(match_dicts, 0, "team")
    await update.message.reply_text(
        f"🔍 Found <b>{len(matches)}</b> teams matching <i>{team_name}</i>. Pick one:",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


def _format_where_text(canonical: str, results: list[dict]) -> str:
    if not results:
        return f"🔍 <b>{canonical}</b> doesn't counter any team in the database yet."
    lines = []
    for r in results:
        line = f"  • <b>{r['name']}</b>"
        if r.get("punchup"):
            line += f" 👊 <i>{r['punchup']}</i>"
        if r.get("note"):
            line += f" — <i>{r['note']}</i>"
        lines.append(line)
    return f"🎯 <b>{canonical}</b> counters these teams:\n\n" + "\n".join(lines)


async def where_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Usage: /where <code>TEAM_NAME</code>\n"
            "Returns all teams that can be countered by the given team.\n"
            "Example: /where Asgardians",
            parse_mode=ParseMode.HTML,
        )
        return

    team_name = " ".join(context.args)

    # Exact match first
    canonical = db.get_team_canonical_name(team_name)
    if canonical:
        results = db.get_teams_countered_by(canonical)
        text = _format_where_text(canonical, results)
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Close", callback_data="close")]])
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
        return

    # Partial search fallback (search all teams, not just those with counters)
    matches = db.search_all_teams(team_name)
    if not matches:
        await update.message.reply_text(
            f"❌ No team matching <b>{team_name}</b> found.",
            parse_mode=ParseMode.HTML,
        )
        return

    if len(matches) == 1:
        canonical = matches[0]
        results = db.get_teams_countered_by(canonical)
        text = _format_where_text(canonical, results)
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Close", callback_data="close")]])
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
        return

    # Multiple matches — let user pick
    match_dicts = [{"name": m, "category": None} for m in matches]
    keyboard = build_teams_keyboard(match_dicts, 0, "where_team")
    await update.message.reply_text(
        f"🔍 Found <b>{len(matches)}</b> teams matching <i>{team_name}</i>. Pick one:",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def listteams_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    teams = db.list_all_teams()
    if not teams:
        await update.message.reply_text("No teams in the database yet.")
        return

    keyboard = build_teams_keyboard(teams, 0, "team")
    total = len(teams)
    text = f"📋 <b>All Teams</b> ({total} total)\nSelect a team to see its counters:"
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)


# ---------------------------------------------------------------------------
# Commands — admin only
# ---------------------------------------------------------------------------

async def addteam_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db.is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 Only admins can add teams.")
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: /addteam <code>TEAM_NAME</code>\n"
            'Example: /addteam "Sinister Six"',
            parse_mode=ParseMode.HTML,
        )
        return

    args = _parse_quoted_args(context.args)
    team_name = args[0]
    success, msg = db.add_team(team_name)
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def delteam_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db.is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 Only admins can delete teams.")
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: /delteam <code>TEAM_NAME</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    args = _parse_quoted_args(context.args)
    team_name = args[0]
    canonical = db.get_team_canonical_name(team_name)
    if not canonical:
        await update.message.reply_text(
            f"❌ Team not found: <b>{team_name}</b>", parse_mode=ParseMode.HTML
        )
        return

    # Count how many counters will be removed
    counters = db.get_counters_for_team(canonical)
    counter_count = len(counters)

    # Store pending delete in user_data for confirmation
    context.user_data["pending_delteam"] = canonical

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Yes, delete", callback_data="delteam_confirm"),
            InlineKeyboardButton("❌ Cancel", callback_data="delteam_cancel"),
        ]
    ])
    await update.message.reply_text(
        f"⚠️ Are you sure you want to delete <b>{canonical}</b>?\n"
        f"This will also remove <b>{counter_count}</b> counter entry(ies) linked to this team.",
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )


async def setcategory_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db.is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 Only admins can set categories.")
        return

    if len(context.args) < 2:
        cats = ", ".join(db.VALID_CATEGORIES)
        await update.message.reply_text(
            f"Usage: /setcategory <code>TEAM_NAME</code> <code>CATEGORY</code>\n"
            f"Categories: {cats}\n\n"
            'Example: /setcategory "Dark Hunters" War',
            parse_mode=ParseMode.HTML,
        )
        return

    args = _parse_quoted_args(context.args)
    if len(args) < 2:
        await update.message.reply_text("Please provide both TEAM_NAME and CATEGORY.")
        return

    team_name = args[0]
    category = args[1]
    success, msg = db.set_category(team_name, category)
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def addcounter_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db.is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 Only admins can add counters.")
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: /addcounter <code>TEAM</code> <code>COUNTER_TEAM</code> [<code>note</code>]\n"
            "Example: /addcounter Hydra Asgardians\n"
            'Example with note: /addcounter Hydra Asgardians "Strong AoE"\n\n'
            "Use quotes for team names with spaces:\n"
            '/addcounter "Sinister Six" "Wakanda Forever" "Speed advantage"',
            parse_mode=ParseMode.HTML,
        )
        return

    args = _parse_quoted_args(context.args)
    if len(args) < 2:
        await update.message.reply_text("Please provide both TEAM_NAME and COUNTER_TEAM.")
        return

    note = args[2] if len(args) >= 3 else None
    success, msg = db.add_counter(args[0], args[1], note)
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def delcounter_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db.is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 Only admins can remove counters.")
        return

    if len(context.args) < 2:
        await update.message.reply_text(
            "Usage: /delcounter <code>TEAM</code> <code>COUNTER_TEAM</code>\n"
            "Example: /delcounter Hydra Asgardians",
            parse_mode=ParseMode.HTML,
        )
        return

    args = _parse_quoted_args(context.args)
    if len(args) < 2:
        await update.message.reply_text("Please provide both TEAM_NAME and COUNTER_TEAM.")
        return

    success, msg = db.del_counter(args[0], args[1])
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def addadmin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db.is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 Only admins can add other admins.")
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: /addadmin <code>USER_ID</code>\n"
            "Tip: Users can find their ID with /myid",
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ USER_ID must be a number.")
        return

    db.add_admin(target_id)
    await update.message.reply_text(
        f"✅ User <code>{target_id}</code> is now an admin.",
        parse_mode=ParseMode.HTML,
    )


async def removeadmin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db.is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 Only admins can remove admins.")
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: /removeadmin <code>USER_ID</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ USER_ID must be a number.")
        return

    if target_id == update.effective_user.id:
        await update.message.reply_text("⚠️ You cannot remove yourself as admin.")
        return

    removed = db.remove_admin(target_id)
    if removed:
        await update.message.reply_text(
            f"🗑️ User <code>{target_id}</code> is no longer an admin.",
            parse_mode=ParseMode.HTML,
        )
    else:
        await update.message.reply_text(
            f"❌ User <code>{target_id}</code> was not an admin.",
            parse_mode=ParseMode.HTML,
        )


async def importcsv_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db.is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 Only admins can import CSV files.")
        return

    context.user_data["awaiting_csv"] = True
    await update.message.reply_text(
        "📂 <b>CSV Import</b>\n\n"
        "Send me a CSV file with these columns:\n"
        "<code>Team,Counter,PunchUp,Note</code>\n\n"
        "• <b>Team</b> — team being countered\n"
        "• <b>Counter</b> — team that counters it\n"
        "• <b>PunchUp</b> — optional punch-up note\n"
        "• <b>Note</b> — optional general note\n\n"
        "Teams are created automatically if they don't exist.\n"
        "Duplicate counters are skipped.\n\n"
        "Upload the file now, or send /cancel to abort.",
        parse_mode=ParseMode.HTML,
    )


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("awaiting_csv", None)
    context.user_data.pop("awaiting_reset", None)
    await update.message.reply_text("❌ Operation cancelled.")


async def resetdatabase_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db.is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 Only admins can reset the database.")
        return

    context.user_data["awaiting_reset"] = True
    await update.message.reply_text(
        "⚠️ <b>WARNING: This will permanently delete:</b>\n"
        "  • All teams\n"
        "  • All counters\n"
        "  • All notes and punch-up data\n\n"
        "Admin accounts will be preserved.\n\n"
        "To confirm, type exactly:\n"
        "<code>CONFIRM RESET</code>\n\n"
        "Or send /cancel to abort.",
        parse_mode=ParseMode.HTML,
    )


async def _run_smart_search(update: Update, query: str) -> None:
    """Execute the shared counter/where search logic for a given query string."""
    close_btn = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Close", callback_data="close")]])

    # 1. Exact team match → show counters + what it counters
    canonical = db.get_team_canonical_name(query)
    if canonical:
        row = db.get_team_row(canonical)

        counters = db.get_counters_for_team(canonical)
        counter_text = format_counters_text(
            canonical,
            counters,
            row["category"] if row else None
        )

        targets = db.get_teams_countered_by(canonical)
        where_text = _format_where_text(canonical, targets)

        reply = f"{counter_text}\n\n{'─' * 20}\n\n{where_text}"

        await update.message.reply_text(
            reply,
            parse_mode=ParseMode.HTML,
            reply_markup=close_btn
        )
        return

    

    # 2. Partial match among teams that have counters → /counter logic
    counter_matches = db.search_teams(query)
    if counter_matches:
        if len(counter_matches) == 1:
            canonical = counter_matches[0]
            row = db.get_team_row(canonical)
            counters = db.get_counters_for_team(canonical)
            reply = format_counters_text(canonical, counters, row["category"] if row else None)
            await update.message.reply_text(reply, parse_mode=ParseMode.HTML, reply_markup=close_btn)
        else:
            match_dicts = [{"name": m, "category": None} for m in counter_matches]
            keyboard = build_teams_keyboard(match_dicts, 0, "team")
            await update.message.reply_text(
                f"⚔️ Found <b>{len(counter_matches)}</b> teams matching <i>{query}</i>.\n"
                "Select one to see who counters it:",
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
        return

    # 3. Partial match across all teams → /where logic (reverse lookup)
    where_matches = db.search_all_teams(query)
    if where_matches:
        if len(where_matches) == 1:
            canonical = where_matches[0]
            results = db.get_teams_countered_by(canonical)
            reply = _format_where_text(canonical, results)
            await update.message.reply_text(reply, parse_mode=ParseMode.HTML, reply_markup=close_btn)
        else:
            match_dicts = [{"name": m, "category": None} for m in where_matches]
            keyboard = build_teams_keyboard(match_dicts, 0, "where_team")
            await update.message.reply_text(
                f"🔍 Found <b>{len(where_matches)}</b> teams matching <i>{query}</i>.\n"
                "Select one to see what it counters:",
                parse_mode=ParseMode.HTML,
                reply_markup=keyboard,
            )
        return

    # 4. Nothing found — silent (no spam for unrelated chat)


def _extract_mention_query(message, bot_username: str) -> str | None:
    raw = message.text or ""
    bot_tag = f"@{bot_username}".lower()

    if bot_tag not in raw.lower():
        return None

    query = raw.replace(bot_tag, "").strip()

    return query if query else None


async def handle_text_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message:
        return

    raw_text = (message.text or message.caption or "").strip()
chat_type = message.chat.type  # "private", "group", "supergroup", "channel"

# --- FIX: remove bot mention in groups ---
if chat_type in ("group", "supergroup"):
    bot_username = context.bot.username
    raw_text = raw_text.replace(f"@{bot_username}", "").strip()

    # --- Reset confirmation flow: always takes priority ---
    if context.user_data.get("awaiting_reset"):
        if not db.is_admin(update.effective_user.id):
            context.user_data.pop("awaiting_reset", None)
            return

        if raw_text != "CONFIRM RESET":
            await message.reply_text(
                "❌ Confirmation text did not match.\n"
                "Type <code>CONFIRM RESET</code> exactly, or /cancel to abort.",
                parse_mode=ParseMode.HTML,
            )
            return

        context.user_data.pop("awaiting_reset", None)
        result = db.reset_database()
        await message.reply_text(
            f"✅ <b>Database reset complete.</b>\n\n"
            f"🗑️ Teams deleted: <b>{result['teams_deleted']}</b>\n"
            f"🗑️ Counters deleted: <b>{result['counters_deleted']}</b>\n\n"
            "Admin accounts were preserved.",
            parse_mode=ParseMode.HTML,
        )
        return

    # --- Determine search query based on chat type ---
    if chat_type == "private":
        # Private chat: search everything automatically
        query = raw_text
    else:
        # Group/supergroup: only respond when bot is explicitly mentioned
        bot_username = context.bot.username
        query = _extract_mention_query(message, bot_username)
        if query is None:
            return  # Not mentioned — stay silent

    if not query or len(query) < 3:
        return

    await _run_smart_search(update, query)


async def handle_csv_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    if not db.is_admin(user.id):
        return

    if not context.user_data.get("awaiting_csv"):
        return

    doc = update.message.document
    if not doc:
        return

    filename = doc.file_name or ""
    if not filename.lower().endswith(".csv"):
        await update.message.reply_text(
            "⚠️ Please upload a <b>.csv</b> file.",
            parse_mode=ParseMode.HTML,
        )
        return

    context.user_data.pop("awaiting_csv", None)

    processing_msg = await update.message.reply_text("⏳ Processing CSV...")

    try:
        tg_file = await doc.get_file()
        file_bytes = await tg_file.download_as_bytearray()
        text = file_bytes.decode("utf-8-sig")  # handles BOM from Excel exports

        reader = csv.DictReader(io.StringIO(text))

        # Normalise header names (strip whitespace)
        raw_rows = list(reader)
        if not raw_rows:
            await processing_msg.edit_text("❌ The CSV file is empty.")
            return

        # Check required columns exist
        first = raw_rows[0]
        normalised_keys = {k.strip(): k for k in first.keys()}
        required = {"Team", "Counter"}
        missing = required - set(normalised_keys.keys())
        if missing:
            await processing_msg.edit_text(
                f"❌ Missing required columns: <b>{', '.join(missing)}</b>\n\n"
                "Expected header: <code>Team,Counter,PunchUp,Note</code>",
                parse_mode=ParseMode.HTML,
            )
            return

        # Strip whitespace from all keys
        cleaned_rows = [
            {k.strip(): (v.strip() if v else v) for k, v in row.items()}
            for row in raw_rows
        ]

        result = db.import_csv_data(cleaned_rows)

        await processing_msg.edit_text(
            f"✅ <b>Import complete!</b>\n\n"
            f"👥 Teams created: <b>{result['teams_created']}</b>\n"
            f"⚔️ Counters created: <b>{result['counters_added']}</b>\n"
            f"✏️ Counters updated: <b>{result['counters_updated']}</b>\n"
            f"⏭️ Skipped (invalid rows): <b>{result['skipped']}</b>",
            parse_mode=ParseMode.HTML,
        )

    except UnicodeDecodeError:
        await processing_msg.edit_text(
            "❌ Could not read the file. Make sure it is saved as UTF-8."
        )
    except Exception as e:
        logger.exception("CSV import error")
        await processing_msg.edit_text(f"❌ Import failed: {e}")


async def backup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not db.is_admin(update.effective_user.id):
        await update.message.reply_text("🚫 Only admins can download the backup.")
        return

    if not os.path.exists(db.DB_PATH):
        await update.message.reply_text("❌ Database file not found.")
        return

    await update.message.reply_document(
        document=open(db.DB_PATH, "rb"),
        filename="msf_counters.db",
        caption="📦 MSF Counter Database backup",
    )


# ---------------------------------------------------------------------------
# Inline keyboard callbacks
# ---------------------------------------------------------------------------

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "close":
        await query.delete_message()
        return

    # --- delteam confirmation ---
    if data == "delteam_confirm":
        if not db.is_admin(query.from_user.id):
            await query.edit_message_text("🚫 Only admins can delete teams.")
            return
        team_name = context.user_data.get("pending_delteam")
        if not team_name:
            await query.edit_message_text("⚠️ No pending delete. Please run /delteam again.")
            return
        context.user_data.pop("pending_delteam", None)
        success, msg = db.del_team(team_name)
        await query.edit_message_text(msg, parse_mode=ParseMode.HTML)
        return

    if data == "delteam_cancel":
        context.user_data.pop("pending_delteam", None)
        await query.edit_message_text("❌ Deletion cancelled.")
        return

    # --- listteams pagination ---
    if data.startswith("team_page:"):
        page = int(data.split(":")[1])
        teams = db.list_all_teams()
        keyboard = build_teams_keyboard(teams, page, "team")
        total = len(teams)
        text = f"📋 <b>All Teams</b> ({total} total)\nSelect a team to see its counters:"
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
        return

    # --- team detail view ---
    if data.startswith("team:"):
        team_name = data[len("team:"):]
        canonical = db.get_team_canonical_name(team_name)
        if not canonical:
            await query.edit_message_text(
                f"❌ Team <b>{team_name}</b> not found.", parse_mode=ParseMode.HTML
            )
            return

        row = db.get_team_row(canonical)
        counters = db.get_counters_for_team(canonical)
        text = format_counters_text(canonical, counters, row["category"] if row else None)

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("⬅️ Back to Teams", callback_data="back_to_teams")],
            [InlineKeyboardButton("❌ Close", callback_data="close")],
        ])
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
        return

    if data == "back_to_teams":
        teams = db.list_all_teams()
        keyboard = build_teams_keyboard(teams, 0, "team")
        total = len(teams)
        text = f"📋 <b>All Teams</b> ({total} total)\nSelect a team to see its counters:"
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
        return

    # --- /where team picker ---
    if data.startswith("where_team:"):
        team_name = data[len("where_team:"):]
        canonical = db.get_team_canonical_name(team_name)
        if not canonical:
            await query.edit_message_text(
                f"❌ Team <b>{team_name}</b> not found.", parse_mode=ParseMode.HTML
            )
            return
        results = db.get_teams_countered_by(canonical)
        text = _format_where_text(canonical, results)
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("❌ Close", callback_data="close")]])
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=keyboard)
        return


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN environment variable is not set.")

    db.init_db()

    first_admin = os.environ.get("BOT_ADMIN_ID")
    if first_admin:
        try:
            db.add_admin(int(first_admin))
            logger.info(f"Added initial admin: {first_admin}")
        except ValueError:
            logger.warning("BOT_ADMIN_ID is not a valid integer, skipping.")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("myid", myid_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("teams", teams_command))
    app.add_handler(CommandHandler("category", category_command))
    app.add_handler(CommandHandler("counter", counter_command))
    app.add_handler(CommandHandler("where", where_command))
    app.add_handler(CommandHandler("listteams", listteams_command))
    app.add_handler(CommandHandler("addteam", addteam_command))
    app.add_handler(CommandHandler("delteam", delteam_command))
    app.add_handler(CommandHandler("setcategory", setcategory_command))
    app.add_handler(CommandHandler("addcounter", addcounter_command))
    app.add_handler(CommandHandler("delcounter", delcounter_command))
    app.add_handler(CommandHandler("importcsv", importcsv_command))
    app.add_handler(CommandHandler("resetdatabase", resetdatabase_command))
    app.add_handler(CommandHandler("cancel", cancel_command))
    app.add_handler(CommandHandler("addadmin", addadmin_command))
    app.add_handler(CommandHandler("removeadmin", removeadmin_command))
    app.add_handler(CommandHandler("backup", backup_command))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_csv_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_messages))
    app.add_handler(CallbackQueryHandler(button_callback))

    logger.info("MSF Counter Bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
