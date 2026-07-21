import logging
import os
import re
import tempfile
import httpx

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BOT_TOKEN       = os.environ.get("TELEGRAM_BOT_TOKEN")
RAPIDAPI_KEY    = os.environ.get("RAPIDAPI_KEY")
RAPIDAPI_HOST   = "instagram-downloader-scraper-reels-igtv-posts-stories.p.rapidapi.com"

INSTAGRAM_URL_RE = re.compile(
    r"(https?://(?:www\.)?instagram\.com/(?:reel|p|tv)/[A-Za-z0-9_\-]+/?[^\s]*)"
)

MAX_TELEGRAM_SIZE = 50 * 1024 * 1024

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Salut ! Envoie-moi un lien Instagram (reel, post vidéo...) "
        "et je te renvoie la vidéo directement ici."
    )


async def get_video_url(instagram_url: str) -> str | None:
    """Appelle l'API RapidAPI et retourne l'URL de téléchargement de la vidéo."""
    headers = {
        "x-rapidapi-key": RAPIDAPI_KEY,
        "x-rapidapi-host": RAPIDAPI_HOST,
    }
    params = {"url": instagram_url}

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"https://{RAPIDAPI_HOST}/scraper",
            headers=headers,
            params=params,
        )
        resp.raise_for_status()
        data = resp.json()
        logger.info("API response: %s", data)

    # Structure réelle: {'data': [{'media': 'url_video', 'thumb': '...', 'isVideo': True}]}
    items = data.get("data") or []
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                v = item.get("media") or item.get("video_url") or item.get("url")
                if v and item.get("isVideo"):
                    return v
        # Fallback : premier media trouvé
        for item in items:
            if isinstance(item, dict):
                v = item.get("media") or item.get("url")
                if v:
                    return v
    return None


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message_text = update.message.text or ""
    match = INSTAGRAM_URL_RE.search(message_text)

    if not match:
        await update.message.reply_text(
            "Je ne vois pas de lien Instagram valide. "
            "Envoie un lien du type https://www.instagram.com/reel/..."
        )
        return

    url = match.group(1)
    status_msg = await update.message.reply_text("⏳ Récupération du lien...")
    await update.message.chat.send_action(ChatAction.UPLOAD_VIDEO)

    try:
        video_url = await get_video_url(url)
    except Exception as exc:
        logger.exception("Erreur API pour %s", url)
        await status_msg.edit_text("❌ Erreur lors de la récupération de la vidéo. Réessaie.")
        return

    if not video_url:
        await status_msg.edit_text(
            "❌ Impossible de trouver la vidéo. Vérifie que le lien est public."
        )
        return

    await status_msg.edit_text("⬇️ Téléchargement en cours...")

    try:
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            resp = await client.get(video_url)
            resp.raise_for_status()
            video_bytes = resp.content
    except Exception as exc:
        logger.exception("Erreur téléchargement vidéo %s", video_url)
        await status_msg.edit_text("❌ Impossible de télécharger la vidéo.")
        return

    if len(video_bytes) > MAX_TELEGRAM_SIZE:
        await status_msg.edit_text("❌ La vidéo dépasse 50 Mo, Telegram ne me permet pas de l'envoyer.")
        return

    await status_msg.edit_text("📤 Envoi...")
    await update.message.reply_video(video=video_bytes, supports_streaming=True)
    await status_msg.delete()


def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError("Variable TELEGRAM_BOT_TOKEN non définie.")
    if not RAPIDAPI_KEY:
        raise RuntimeError("Variable RAPIDAPI_KEY non définie.")

    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot démarré, en attente de messages...")
    application.run_polling()


if __name__ == "__main__":
    main()
