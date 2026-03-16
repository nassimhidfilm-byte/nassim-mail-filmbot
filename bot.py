import os
import logging
import re
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from anthropic import Anthropic
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
GMAIL_USER = os.environ["GMAIL_USER"]        # nassimhidfilm@gmail.com
GMAIL_PASSWORD = os.environ["GMAIL_PASSWORD"] # App password de Gmail
ALLOWED_USER_ID = int(os.environ["ALLOWED_USER_ID"])  # Tu Telegram user ID

FIRMA = """
Nassim Hid
Mail: nassimhidfilm@gmail.com
Teléfono: 3855771291
Instagram: @nass_hid
"""

SYSTEM_PROMPT = """Sos Nassim Hid, un profesional creativo de grabación, edición y creación de contenido audiovisual.
Cuando te llegue una solicitud de mail, redactá un mail de prospección personalizado.

Reglas de redacción:
- Idioma: español
- Tono: creativo y distinto, humano y único, NO corporativo
- Mencioná el nombre del contacto naturalmente
- Usá los datos del contacto como CONTEXTO para personalizar, no los copies literalmente
- Esparcí los detalles a lo largo del mensaje de forma orgánica
- Incluí un halago sutil casi al pasar, relacionado con su rubro
- Dejá claro que este no es un mail masivo
- Hablá del servicio (grabación, edición, creación de contenido) de forma concisa y atractiva
- Terminá con un CTA amigable, sin presionar
- NO incluyas la firma, esa se agrega automáticamente

Formato de respuesta EXACTO:
ASUNTO: [asunto aquí]
CUERPO:
[cuerpo del mail aquí, terminando con "Nassim"]"""

client = Anthropic(api_key=ANTHROPIC_API_KEY)


def generar_mail(nombre, email, empresa, rubro, notas, tono="creativo"):
    prompt = f"""Redactá un mail de prospección con estos datos:
- Nombre: {nombre}
- Email: {email}
- Empresa: {empresa or 'no especificada'}
- Rubro: {rubro or 'no especificado'}
- Notas: {notas or 'ninguna'}
- Tono solicitado: {tono}"""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text


def enviar_gmail(destinatario, asunto, cuerpo):
    msg = MIMEMultipart()
    msg["From"] = GMAIL_USER
    msg["To"] = destinatario
    msg["Subject"] = asunto

    cuerpo_completo = cuerpo + "\n\n--\n" + FIRMA.strip()
    msg.attach(MIMEText(cuerpo_completo, "plain", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_USER, GMAIL_PASSWORD)
        server.sendmail(GMAIL_USER, destinatario, msg.as_string())


def parsear_mail(texto):
    asunto = ""
    cuerpo = ""

    asunto_match = re.search(r"ASUNTO:\s*(.+)", texto)
    if asunto_match:
        asunto = asunto_match.group(1).strip()

    cuerpo_match = re.search(r"CUERPO:\s*\n([\s\S]+)", texto)
    if cuerpo_match:
        cuerpo = cuerpo_match.group(1).strip()

    return asunto, cuerpo


def parsear_plantilla(texto):
    """
    Parsea el mensaje de Telegram con el formato de plantilla.
    Formato esperado:
    NOMBRE: Juan Pérez
    MAIL: juan@empresa.com
    EMPRESA: Empresa SA (opcional)
    RUBRO: Fitness
    NOTAS: Tiene un gym en Tucumán, entrena jugadores de fútbol
    TONO: formal (opcional, default: creativo)
    """
    campos = {}
    patron = r"(NOMBRE|MAIL|EMPRESA|RUBRO|NOTAS|TONO):\s*(.+)"
    for match in re.finditer(patron, texto, re.IGNORECASE):
        clave = match.group(1).upper()
        valor = match.group(2).strip()
        campos[clave] = valor
    return campos


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return

    plantilla = """¡Hola Nassim! 👋 Listo para enviar mails.

Usá esta plantilla para cada contacto:

NOMBRE: [nombre completo]
MAIL: [email del contacto]
EMPRESA: [empresa, opcional]
RUBRO: [rubro o industria]
NOTAS: [detalles para personalizar]
TONO: [creativo / formal, opcional]

Te genero el mail y te lo muestro antes de enviarlo."""

    await update.message.reply_text(plantilla)


async def ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return

    texto = """📋 Comandos disponibles:

/start — Muestra la plantilla
/ayuda — Esta ayuda

Para enviar un mail, mandame un mensaje con el formato:
NOMBRE: Juan
MAIL: juan@gym.com
RUBRO: Fitness
NOTAS: tiene un gym en Tucumán

Te voy a mostrar el borrador y preguntarte si lo enviás."""

    await update.message.reply_text(texto)


async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return

    texto = update.message.text

    # Si el usuario confirma envío
    if texto.lower() in ["sí", "si", "enviar", "mandar", "ok", "dale"]:
        if "mail_pendiente" in context.user_data:
            pendiente = context.user_data["mail_pendiente"]
            try:
                await update.message.reply_text("Enviando... ✉️")
                enviar_gmail(
                    pendiente["email"],
                    pendiente["asunto"],
                    pendiente["cuerpo"]
                )
                await update.message.reply_text(
                    f"✅ Mail enviado a {pendiente['nombre']} ({pendiente['email']})"
                )
                context.user_data.pop("mail_pendiente")
            except Exception as e:
                await update.message.reply_text(f"❌ Error al enviar: {str(e)}")
        else:
            await update.message.reply_text("No hay ningún mail pendiente. Mandame los datos del contacto.")
        return

    # Si el usuario cancela
    if texto.lower() in ["no", "cancelar", "cancel"]:
        context.user_data.pop("mail_pendiente", None)
        await update.message.reply_text("Cancelado. Mandame los datos de otro contacto cuando quieras.")
        return

    # Parsear plantilla
    campos = parsear_plantilla(texto)

    if not campos.get("NOMBRE") or not campos.get("MAIL"):
        await update.message.reply_text(
            "Necesito al menos NOMBRE y MAIL. Usá el formato:\n\nNOMBRE: Juan\nMAIL: juan@empresa.com\nRUBRO: Fitness\nNOTAS: ..."
        )
        return

    await update.message.reply_text(f"Generando mail para {campos['NOMBRE']}... ✍️")

    try:
        mail_generado = generar_mail(
            nombre=campos.get("NOMBRE"),
            email=campos.get("MAIL"),
            empresa=campos.get("EMPRESA", ""),
            rubro=campos.get("RUBRO", ""),
            notas=campos.get("NOTAS", ""),
            tono=campos.get("TONO", "creativo")
        )

        asunto, cuerpo = parsear_mail(mail_generado)

        # Guardar en memoria para confirmar
        context.user_data["mail_pendiente"] = {
            "nombre": campos["NOMBRE"],
            "email": campos["MAIL"],
            "asunto": asunto,
            "cuerpo": cuerpo
        }

        preview = f"""📧 Borrador listo:

De: nassimhidfilm@gmail.com
Para: {campos['MAIL']}
Asunto: {asunto}

{cuerpo}

--
{FIRMA.strip()}

---
¿Lo enviamos? Respondé SÍ para enviar o NO para cancelar."""

        await update.message.reply_text(preview)

    except Exception as e:
        await update.message.reply_text(f"❌ Error generando el mail: {str(e)}")


def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ayuda", ayuda))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje))
    logger.info("Bot corriendo...")
    app.run_polling()


if __name__ == "__main__":
    main()
