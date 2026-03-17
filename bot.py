import os
import logging
import re
import threading
import urllib.request
import urllib.parse
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from groq import Groq

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
GROQ_API_KEY = os.environ["GROQ_API_KEY"]
GMAIL_FROM = os.environ["GMAIL_FROM"]
SENDGRID_API_KEY = os.environ["SENDGRID_API_KEY"]
ALLOWED_USER_ID = int(os.environ["ALLOWED_USER_ID"])
PORT = int(os.environ.get("PORT", 8080))

FIRMA = """Nassim Hid
Mail: nassimhidfilm@gmail.com
Teléfono: 3855771291
Instagram: @nass_hid"""

SYSTEM_PROMPT = """Sos Nassim Hid, un profesional creativo de grabación, edición y creación de contenido audiovisual.
Cuando te llegue una solicitud de mail, redactá un mail de prospección personalizado.

Reglas de redacción:
- Idioma: español
- Tono: creativo y distinto, humano y único, NO corporativo
- Mencioná el nombre del contacto naturalmente
- Usá los datos del contacto como CONTEXTO para personalizar, no los copies literalmente
- Esparcí los detalles a lo largo del mensaje de forma orgánica y natural
- Incluí un halago sutil casi al pasar, relacionado con su rubro
- Dejá claro que este no es un mail masivo
- Hablá del servicio (grabación, edición, creación de contenido) de forma concisa y atractiva
- Terminá con un CTA amigable, sin presionar
- NO incluyas la firma, esa se agrega automáticamente

Formato de respuesta EXACTO (sin texto adicional):
ASUNTO: [asunto aquí]
CUERPO:
[cuerpo del mail aquí, terminando con "Nassim"]"""

groq_client = Groq(api_key=GROQ_API_KEY)


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot activo")

    def log_message(self, format, *args):
        pass


def run_health_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    server.serve_forever()


def enviar_sendgrid(destinatario, asunto, cuerpo):
    cuerpo_completo = cuerpo + "\n\n--\n" + FIRMA
    payload = json.dumps({
        "personalizations": [{"to": [{"email": destinatario}]}],
        "from": {"email": GMAIL_FROM, "name": "Nassim Hid"},
        "subject": asunto,
        "content": [{"type": "text/plain", "value": cuerpo_completo}]
    }).encode()

    req = urllib.request.Request(
        "https://api.sendgrid.com/v3/mail/send",
        data=payload,
        headers={
            "Authorization": f"Bearer {SENDGRID_API_KEY}",
            "Content-Type": "application/json"
        },
        method="POST"
    )
    with urllib.request.urlopen(req) as resp:
        return resp.status


def generar_mail(nombre, email, empresa, rubro, notas, tono="creativo"):
    prompt = f"""Redactá un mail de prospección con estos datos:
- Nombre: {nombre}
- Email: {email}
- Empresa: {empresa or 'no especificada'}
- Rubro: {rubro or 'no especificado'}
- Notas: {notas or 'ninguna'}
- Tono solicitado: {tono}"""

    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=1000,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ]
    )
    return response.choices[0].message.content


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
    await update.message.reply_text("""¡Hola Nassim! Listo para enviar mails.

Usá esta plantilla:

NOMBRE: [nombre completo]
MAIL: [email del contacto]
EMPRESA: [empresa, opcional]
RUBRO: [rubro o industria]
NOTAS: [detalles para personalizar]
TONO: [creativo / formal, opcional]""")


async def manejar_mensaje(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ALLOWED_USER_ID:
        return

    texto = update.message.text

    if texto.lower() in ["sí", "si", "enviar", "mandar", "ok", "dale"]:
        if "mail_pendiente" in context.user_data:
            pendiente = context.user_data["mail_pendiente"]
            try:
                await update.message.reply_text("Enviando...")
                enviar_sendgrid(pendiente["email"], pendiente["asunto"], pendiente["cuerpo"])
                await update.message.reply_text(f"Mail enviado a {pendiente['nombre']} ({pendiente['email']})")
                context.user_data.pop("mail_pendiente")
            except Exception as e:
                await update.message.reply_text(f"Error al enviar: {str(e)}")
        else:
            await update.message.reply_text("No hay ningún mail pendiente.")
        return

    if texto.lower() in ["no", "cancelar"]:
        context.user_data.pop("mail_pendiente", None)
        await update.message.reply_text("Cancelado.")
        return

    campos = parsear_plantilla(texto)
    if not campos.get("NOMBRE") or not campos.get("MAIL"):
        await update.message.reply_text("Necesito al menos NOMBRE y MAIL.")
        return

    await update.message.reply_text(f"Generando mail para {campos['NOMBRE']}...")

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
        context.user_data["mail_pendiente"] = {
            "nombre": campos["NOMBRE"],
            "email": campos["MAIL"],
            "asunto": asunto,
            "cuerpo": cuerpo
        }
        await update.message.reply_text(f"""Borrador listo:

De: {GMAIL_FROM}
Para: {campos['MAIL']}
Asunto: {asunto}

{cuerpo}

--
{FIRMA}

---
Respondé SI para enviar o NO para cancelar.""")
    except Exception as e:
        await update.message.reply_text(f"Error generando el mail: {str(e)}")


def main():
    hilo = threading.Thread(target=run_health_server, daemon=True)
    hilo.start()
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, manejar_mensaje))
    logger.info("Bot corriendo...")
    app.run_polling()


if __name__ == "__main__":
    main()
