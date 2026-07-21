import logging
import os
import re
import tempfile
import uuid

import yt_dlp
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
# Récupère le token depuis une variable d'environnement (plus sûr que de le
# mettre en dur dans le code). Voir le README pour comment la définir.
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

INSTAGRAM_URL_RE = re.compile(
    r"(https?://(?:www\.)?instagram\.com/(?:reel|p|tv)/[A-Za-z0-9_\-]+/?[^\s]*)"
)

# Telegram limite l'envoi de fichiers via bot à 50 Mo
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


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message_text = update.message.text or ""
    match = INSTAGRAM_URL_RE.search(message_text)

    if not match:
        await update.message.reply_text(
            "Je ne vois pas de lien Instagram valide dans ton message. "
            "Envoie un lien du type https://www.instagram.com/reel/..."
        )
        return

    url = match.group(1)
    status_msg = await update.message.reply_text("Téléchargement en cours...")
    await update.message.chat.send_action(ChatAction.UPLOAD_VIDEO)

    with tempfile.TemporaryDirectory() as tmp_dir:
        output_template = os.path.join(tmp_dir, f"{uuid.uuid4()}.%(ext)s")
        ydl_opts = {
            "outtmpl": output_template,
            "format": (
                "best[height>width][ext=mp4]"
                "/bestvideo[height>width]+bestaudio"
                "/best[ext=mp4]/best"
            ),
            "merge_output_format": "mp4",
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
        }

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
        except Exception as exc:
            logger.exception("Échec du téléchargement pour %s", url)
            await status_msg.edit_text(
                "Impossible de télécharger cette vidéo. "
                "Vérifie que le lien est correct et que le contenu est public."
            )
            return

        if not os.path.exists(filename):
            await status_msg.edit_text("Le fichier téléchargé est introuvable, réessaie.")
            return

        size = os.path.getsize(filename)
        if size > MAX_TELEGRAM_SIZE:
            await status_msg.edit_text(
                "La vidéo dépasse 50 Mo, Telegram ne me permet pas de l'envoyer via le bot."
            )
            return

        await status_msg.edit_text("Envoi de la vidéo...")
        with open(filename, "rb") as video_file:
            await update.message.reply_video(
                video=video_file,
                supports_streaming=True,
                width=info.get("width"),
                height=info.get("height"),
                duration=int(info.get("duration") or 0) or None,
            )

        await status_msg.delete()


def main() -> None:
    if not BOT_TOKEN:
        raise RuntimeError(
            "La variable d'environnement TELEGRAM_BOT_TOKEN n'est pas définie."
        )

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot démarré, en attente de messages...")
    application.run_polling()


if __name__ == "__main__":
    main()
